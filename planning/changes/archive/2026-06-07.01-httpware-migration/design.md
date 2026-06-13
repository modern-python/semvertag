---
status: shipped
date: 2026-06-07
slug: httpware-migration
supersedes: null
superseded_by: null
pr: null
outcome: shipped (#2)
---

# httpware migration — design spec

**Date:** 2026-06-07
**Status:** Approved, ready for implementation planning
**Topic slug:** `httpware-migration`

## Goal

Port semvertag's provider HTTP stack from a hand-rolled retrying transport + decoder wrapper onto [`httpware`](https://github.com/modern-python/httpware) 0.8+, the sibling `modern-python` client framework. Result: semvertag deletes ~600 lines of HTTP plumbing it doesn't need to own, gains a maintained middleware-chain client, and keeps its operator-action exit-code semantics.

Semvertag is pre-1.0; breaking behavior changes are explicitly allowed when the new behavior is the better solution.

## Current state (what gets removed)

Three modules carry the HTTP layer today:

- **`semvertag/_transport.py`** — `RetryingTransport(httpx2.BaseTransport)` with 3 attempts, 1 s base full-jitter backoff, 30 s per-request wall cap, Retry-After parsing (numeric + HTTP date), retries on `{408, 429, 500, 502, 503, 504}` and `{ConnectError, ReadTimeout, WriteTimeout, RemoteProtocolError}`.
- **`semvertag/providers/_http.py`** — `HttpClient` dataclass wrapping `httpx2.Client` with three jobs: pydantic decoding via `request(..., schema=T)` / `request_many(..., schema=T)`, raw `httpx2.Response` access via `request_raw`, and auth-header injection via a callable.
- **`semvertag/providers/gitlab.py`** — `GitLabProvider` uses `HttpClient` for project lookup, latest commit, paginated tag list (link-header walking via `request_raw`), and tag creation (with 400-body inspection for the "already exists" fragment).

`semvertag/ioc.py` wires a `TransportsGroup` that builds `RetryingTransport`, then a `ProvidersGroup.gitlab_provider` that constructs `httpx2.Client(transport=transport, base_url=..., timeout=...)`, wraps it in `HttpClient`, and binds a finalizer to close the underlying client.

Tests (1204 lines touching HTTP):

- `tests/unit/test_transport_retry.py` — 403 lines pinning every `RetryingTransport` behavior.
- `tests/unit/test_http_client.py` — 186 lines pinning `HttpClient` decoding + status-translator wiring.
- `tests/integration/test_gitlab_provider.py` — 615 lines using `httpx2.MockTransport` to drive `GitLabProvider` end-to-end.

## Target shape

```
semvertag/
├── _transport.py        ← DELETED
├── providers/
│   ├── _http.py         ← DELETED
│   ├── _errors.py       ← NEW: translate httpware StatusError → semvertag domain errors
│   └── gitlab.py        ← holds httpware.Client directly; uses _errors.translate_gitlab()
└── ioc.py               ← builds httpware.Client with Retry middleware; TransportsGroup deleted
```

`GitLabProvider` holds a `httpware.Client` field directly (renamed from `http: HttpClient` to keep the call-site shape `self.http.<verb>(...)` familiar). Typed reads use `self.http.get(url, response_model=...)`. Pagination + 400-body inspection use `self.http.send(self.http.build_request(...))` returning the raw `httpx2.Response`. Each provider method wraps its httpware calls in one `try/except httpware.StatusError`, calling `_errors.translate_gitlab(exc, project_id=self.project_id)` for the GitLab-specific message taxonomy.

`HttpClient`'s three jobs are absorbed into httpware:

| Old `HttpClient` job | New home |
|---|---|
| Pydantic decoding (`schema=T`) | httpware's `response_model=` |
| Raw response access (`request_raw`) | httpware's `send()` / `client.get()` without `response_model` |
| Auth header injection (callable) | `headers={"PRIVATE-TOKEN": token}` at client construction (the header is a constant for the client's lifetime — no per-request callable needed) |

## Retry middleware: one knob, otherwise httpware defaults

```python
httpware.Retry(retry_status_codes=frozenset({408, 429, 500, 502, 503, 504}))
```

The single configured value adds **500** to httpware's default retry set. GitLab emits transient 500s under load; retrying once costs ~0.1 s and recovers most. Everything else takes httpware defaults.

**Intentional breaking changes from today's behavior** (all judged improvements):

- **POST no longer retried.** `create_tag` 429/500 now fails immediately. Today's behavior — retrying POST and relying on the "already exists" body-string check to swallow phantom duplicates — is fragile; failing fast is cleaner. Operator reruns on transient failure.
- **Backoff base 0.1 s, max sleep 5 s** (was 1 s base, no per-sleep cap). Worst-case total sleep across 3 attempts ≈ 10 s (was up to 30 s). Snappier CI, more reasonable bound.
- **No 30 s per-request wall cap.** Replaced by httpware's `RetryBudget` (10 deposits + 20% retry ratio default), which caps retry storms across the run rather than wall time within a single request. For semvertag's ~5 requests/run profile this is strictly better.
- **Retry-After honored verbatim, capped at `max_delay=5 s`.** Semvertag today takes `max(server_hint, local_backoff)` (never sleeps less than backoff); httpware honors the server hint directly. Cleaner.

`tests/unit/test_transport_retry.py` deletes entirely — that contract now belongs to httpware.

## Error translation: `semvertag/providers/_errors.py`

httpware raises `StatusError` subclasses with `exc.response` attached. semvertag classifies errors by operator action (`ConfigError`/exit 2 = "fix config", `AuthError`/exit 3 = "fix token", `ProviderAPIError`/exit 4 = "retry later"), which is orthogonal to HTTP status. One small module bridges them:

```python
# semvertag/providers/_errors.py

import httpware

from semvertag._errors import AuthError, ConfigError, ProviderAPIError


_TAG_EXISTS_FRAGMENT = "already exists"


def translate_gitlab(exc: httpware.StatusError, *, project_id: int) -> Exception:
    """Translate an httpware StatusError into the semvertag domain error for GitLab."""
    status = exc.response.status_code
    if isinstance(exc, httpware.UnauthorizedError):
        return AuthError("Token rejected: 401. Verify SEMVERTAG_TOKEN is valid and has 'api' scope.")
    if isinstance(exc, httpware.ForbiddenError):
        return AuthError(
            "Token missing scope or insufficient permission: 403. "
            "Add 'api' or 'write_repository' to the SEMVERTAG_TOKEN scopes on GitLab."
        )
    if isinstance(exc, httpware.NotFoundError):
        return ConfigError(
            f"GitLab project not found: project_id={project_id}. Verify CI_PROJECT_ID or --project-id."
        )
    if isinstance(exc, httpware.UnprocessableEntityError):
        return ConfigError(
            "Request rejected by GitLab: 422. Check tag name format and that the referenced commit exists."
        )
    if isinstance(exc, httpware.RateLimitedError):
        return ProviderAPIError("GitLab rate limit: 429. Retries exhausted after 3 attempts; try again later.")
    if isinstance(exc, httpware.ServerStatusError):
        return ProviderAPIError(
            f"GitLab API failure: {status}. Retries exhausted after 3 attempts. "
            "Try again or check GitLab status."
        )
    return ProviderAPIError(f"Unexpected GitLab response: {status}. Please file an issue.")


def translate_create_tag_bad_request(exc: httpware.BadRequestError, *, tag_name: str) -> Exception:
    """create_tag's 400 has an 'already exists' special case; everything else is a generic 400."""
    body = exc.response.text
    if _TAG_EXISTS_FRAGMENT in body.lower():
        return ConfigError(
            f"Tag already exists: '{tag_name}'. "
            "The tag was created by a concurrent run or previous invocation."
        )
    return ConfigError("Request rejected by GitLab: 400. Check tag name format and that the referenced commit exists.")
```

**Transport-layer failures** (`httpware.NetworkError`, `httpware.TimeoutError`, `httpware.RetryBudgetExhaustedError`) bubble up untranslated and are caught at the CLI boundary in `__main__.py` — same posture as today's `httpx2.RequestError` handling. The current `ProviderAPIError` wrapping in `_http.py` (`f"request failed: {type(exc).__name__}"`) goes away; httpware exceptions carry their own message. The wording change is acceptable under the breaking-changes-OK rule.

### Why not redesign the error tree from scratch?

Considered and rejected:

- **Re-export `httpware.NotFoundError` directly.** Loses operator-action grouping; operators lose exit-code signal; not all semvertag errors map to HTTP (e.g. "default branch empty", "pagination exceeded N pages") so the tree gets weird.
- **Collapse `AuthError` into `ConfigError`** (two-error tree: `UserError`/`TransientError`). Saves one class. Costs the "token expired?" vs "project_id wrong?" CI signal. Not worth the breaking change.
- **Multi-base `ConfigError(httpware.ClientError, SemvertagError)`.** Heavier than translation, no clearer.

The 25-line translation module is the minimum shape for "HTTP-status → operator-category" mapping. It expresses a product decision, not bureaucracy.

## Provider call-site shape

```python
# semvertag/providers/gitlab.py

import httpware

from semvertag.providers import _errors


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class GitLabProvider:
    name: typing.ClassVar[str] = "gitlab"
    config: GitLabConfig
    project_id: int
    http: httpware.Client

    def get_default_branch(self) -> str:
        try:
            project = self.http.get(
                f"{_API_PREFIX}/{self.project_id}",
                response_model=_ProjectResponse,
            )
        except httpware.StatusError as exc:
            raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc
        if not project.default_branch:
            raise ConfigError(
                "Default branch missing from GitLab response. "
                "Verify the project has a default branch configured."
            )
        return project.default_branch

    def list_tags(self) -> list[Tag]:
        # uses self.http.send(self.http.build_request("GET", url, params=params))
        # so it can read response.headers["link"] for pagination.
        # Same StatusError catch + translate pattern.
        ...

    def create_tag(self, name: str, commit_sha: str) -> None:
        try:
            self.http.send(self.http.build_request(
                "POST",
                f"{_API_PREFIX}/{self.project_id}/repository/tags",
                json={"tag_name": name, "ref": commit_sha},
            ))
        except httpware.BadRequestError as exc:
            raise _errors.translate_create_tag_bad_request(exc, tag_name=name) from exc
        except httpware.StatusError as exc:
            raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc
```

The `_url(self, path)` helper (`f"{self.config.endpoint.rstrip('/')}{path}"`) deletes — `httpware.Client(base_url=...)` handles URL joining.

## `ioc.py` wiring

```python
# semvertag/ioc.py

import httpware

def _build_gitlab_provider(settings: Settings) -> GitLabProvider:
    if settings.project_id is None:
        raise ConfigError("Project id missing. Set CI_PROJECT_ID or pass --project-id.")
    client = httpware.Client(
        base_url=settings.gitlab.endpoint,
        timeout=settings.request_timeout,
        headers={"PRIVATE-TOKEN": settings.gitlab.token.get_secret_value()},
        middleware=[httpware.Retry(retry_status_codes=frozenset({408, 429, 500, 502, 503, 504}))],
    )
    return GitLabProvider(
        config=settings.gitlab,
        project_id=settings.project_id,
        http=client,
    )


def _close_provider_client(provider: GitLabProvider) -> None:
    provider.http.close()


class ProvidersGroup(modern_di.Group):
    gitlab_provider = providers.Factory(
        scope=Scope.APP,
        creator=_build_gitlab_provider,
        cache_settings=providers.CacheSettings(finalizer=_close_provider_client),
    )
```

`TransportsGroup` deletes. `ALL_GROUPS` loses one entry. `gitlab_auth_headers` helper deletes — auth is a constant string at construction time.

### Test injection seam (plan-time detail)

The current DI override pattern lets tests inject a custom transport via `TransportsGroup.transport`. With httpware that override seam moves. Implementation plan should split `_build_gitlab_provider` into a thin `_build_gitlab_client(settings) -> httpware.Client` factory + a `_build_gitlab_provider(settings, client) -> GitLabProvider` factory, so tests override just the client-construction step with `httpware.Client(httpx2_client=httpx2.Client(transport=mock))`.

## Dependency changes

`pyproject.toml`:

- **Add**: `httpware[pydantic]` — gives us `Client`, `Retry`, the `StatusError` tree, and the default `PydanticDecoder`.
- **Keep**: `httpx2` — tests still need `httpx2.MockTransport`, and the injection seam is `httpware.Client(httpx2_client=httpx2.Client(transport=mock))`.
- **Keep**: `pydantic`, `pydantic-settings`, `modern-di-typer` — unchanged.
- **Drop nothing else.**

## Test impact summary

| File | Action | Reason |
|---|---|---|
| `tests/unit/test_transport_retry.py` (403 lines) | **delete** | Behavior now lives in httpware; tested upstream |
| `tests/unit/test_http_client.py` (186 lines) | **delete + replace** with `tests/unit/test_providers_errors.py` (~80 lines) | `HttpClient` is gone; translation module is the only new code to test |
| `tests/integration/test_gitlab_provider.py` (615 lines) | **rewrite injection seam, mostly preserve assertions** | Replace `httpx2.Client(transport=mock)` with `httpware.Client(httpx2_client=httpx2.Client(transport=mock))`; update assertions on `ProviderAPIError` wrapper-message wording where it changes; assertions on exception *type* and exit code remain unchanged |
| `tests/unit/test_ioc.py` | small edit | Drop `TransportsGroup` assertions; update `_build_gitlab_provider` call shape |
| Everything else | unchanged | No HTTP touch |

Net: ~600 lines deleted, ~80 added, ~615 modified. 100% coverage gate stays.

## Out of scope

- Adding GitHub / Bitbucket providers. The roadmap calls for them; doing them in this PR multiplies test surface and slows landing. The translation pattern (`translate_gitlab`) is named so adding `translate_github` / `translate_bitbucket` later is mechanical.
- Going async. semvertag is a CLI doing ~5 requests per run; async is pure overhead.
- Adopting `httpware.Bulkhead`. Only useful when there's contention; not relevant for a CLI.
- Adopting httpware's observability/OTel hooks. Semvertag has no tracing surface today; adding it is its own decision.

## Open items for the implementation plan

These are explicitly *plan-time* decisions, not design-time:

1. **DI override seam.** Decide on the `_build_gitlab_client` / `_build_gitlab_provider` split shape and the `modern_di` override pattern the integration test suite will use.
2. **`settings.request_timeout` type.** Verify the value `pydantic-settings` produces today is compatible with `httpware.Client(timeout=...)` (which forwards to `httpx2.Client(timeout=...)`). Almost certainly yes; verify rather than assume.
3. **`__main__.py` exception catching.** Decide whether to also catch `httpware.NetworkError` / `httpware.RetryBudgetExhaustedError` at the CLI boundary for friendly exit-code mapping (currently `httpx2.RequestError` is caught inside `_http.request_raw` and wrapped; with the new design those bubble untranslated unless we catch them).
4. **Pagination call-site detail.** `list_tags` needs both the parsed tag list *and* the response `Link` header. httpware's `client.get(url, response_model=T)` returns just `T`, not the response — confirmed by reading `client.py:147–157` (`return self._decoder.decode(response.content, response_model)`). Plan should pick one of: (a) untyped `send()` returning the raw `httpx2.Response`, then call `PydanticDecoder().decode(response.content, list[_TagItem])` explicitly; or (b) untyped `send()` then `response.json()` + manual `model_validate` (matches today's `_validate_tag_list` shape). (a) is more idiomatic; (b) is closer to today's code.

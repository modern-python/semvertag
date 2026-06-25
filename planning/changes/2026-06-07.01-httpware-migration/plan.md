# httpware migration — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port semvertag's provider HTTP stack from a hand-rolled `RetryingTransport` + `HttpClient` wrapper onto `httpware` 0.8+. Delete ~600 lines of in-tree HTTP plumbing; preserve operator-action exit-code semantics (`ConfigError`/2, `AuthError`/3, `ProviderAPIError`/4) via a small per-provider translation module.

**Architecture:** `GitLabProvider` holds a `httpware.Client` directly (no wrapper). One `try/except httpware.ClientError` per method calls `providers._errors.translate_gitlab(...)` to convert httpware's status- and transport-error tree into semvertag's domain errors. `httpware.Retry` middleware (configured to add HTTP 500 to its default retry set) replaces `RetryingTransport`. Wiring in `ioc.py` builds the client directly; `TransportsGroup` deletes.

**Tech Stack:** Python 3.10+, `httpware[pydantic]` 0.8+, `httpx2`, `pydantic`, `modern-di-typer`, `pytest`. Tests use `httpx2.MockTransport` injected via `httpware.Client(httpx2_client=httpx2.Client(transport=mock))`.

**Reference spec:** `planning/specs/2026-06-07-httpware-migration-design.md`

---

## File structure

**Create:**
- `semvertag/providers/_errors.py` — `translate_gitlab(exc, *, project_id)` + `translate_create_tag_bad_request(exc, *, tag_name)`. Handles `httpware.StatusError` subclasses *and* `httpware.NetworkError` / `httpware.TimeoutError` / `httpware.RetryBudgetExhaustedError`. Returns a `SemvertagError` subclass for the caller to `raise … from exc`.
- `tests/unit/test_providers_errors.py` — exhaustive translation tests (one per status code + one per transport error type + the BadRequest body-fragment branches).

**Modify:**
- `pyproject.toml` — add `httpware[pydantic]` to `[project] dependencies`.
- `semvertag/providers/gitlab.py` — `GitLabProvider.http: httpware.Client`. Drop `_url()`, `_translate_status()`, `gitlab_auth_headers()`, and all `_HTTP_*` constants. Keep `_LINK_ENTRY_RE`, `_next_page_url`, `_parse_rel_values`, `_same_origin`, `_validate_tag_list` (still pagination-internal). Each public method wraps its httpware call in `try/except httpware.ClientError` → `_errors.translate_gitlab(...)`. `create_tag` adds a leading `except httpware.BadRequestError` for the "already exists" body-string special case.
- `semvertag/ioc.py` — delete `TransportsGroup`; remove from `ALL_GROUPS`. Split provider construction into `_build_gitlab_client(settings) -> httpware.Client` (the test-overridable seam) + `_build_gitlab_provider(settings, client) -> GitLabProvider`. `_close_provider_client` calls `provider.http.close()`. Drop the `gitlab_auth_headers` import (helper deleted).
- `tests/integration/test_gitlab_provider.py` — rewrite `_make_provider` to inject via `httpware.Client(httpx2_client=httpx2.Client(transport=mock, base_url=...))`. Delete `_make_provider_with_retrying_transport` (transport-level retry composition is upstream now). Update imports (drop `_translate_status`, `gitlab_auth_headers`, `RetryingTransport`, `HttpClient`). Adjust the specific tests that pinned wrapper-message wording (`"request failed: ..."`) or that exercised POST retry-on-429 behavior (now: immediate `RateLimitedError` → `ProviderAPIError`).

**Delete:**
- `semvertag/_transport.py` (whole file)
- `semvertag/providers/_http.py` (whole file)
- `tests/unit/test_transport_retry.py` (403 lines — behavior now lives in httpware)
- `tests/unit/test_http_client.py` (186 lines — `HttpClient` is gone; translation tests replace it)

**Test inventory after the change:**
- `tests/unit/test_providers_errors.py` — NEW
- `tests/integration/test_gitlab_provider.py` — modified seam, mostly preserved
- `tests/unit/test_ioc.py` — unchanged (it tests strategy resolution, not provider wiring)
- All other test files — untouched

---

## Task 1: Add httpware dependency

**Files:**
- Modify: `pyproject.toml` — `dependencies` array, `requires-python`, `classifiers`

**Background:** httpware 0.8.0 ships with `requires-python = ">=3.11,<4"`. semvertag currently declares `>=3.10,<4` and lists Python 3.10 in `classifiers`. Adopting httpware forces semvertag to drop 3.10 support. This is a deliberate pre-1.0 breaking change, explicitly approved at plan-execution time.

- [ ] **Step 1: Update `pyproject.toml`**

Three coordinated edits:

1. Bump `requires-python` from `">=3.10,<4"` to `">=3.11,<4"`.
2. Remove `"Programming Language :: Python :: 3.10"` from `classifiers`.
3. Add `"httpware[pydantic]"` as the last entry of `dependencies`.

Resulting `dependencies` array:

```toml
dependencies = [
    "typer",
    "rich",
    "semver",
    "pydantic-settings",
    "modern-di-typer",
    "httpx2",
    "httpware[pydantic]",
]
```

- [ ] **Step 2: Resolve the lockfile**

Run: `uv lock --upgrade-package httpware`
Expected: `httpware` and its transitive deps appear in `uv.lock`; no errors.

- [ ] **Step 3: Install**

Run: `just install` (alias for `uv lock --upgrade && uv sync --all-extras --frozen --group lint`)
Expected: completes without errors.

- [ ] **Step 4: Smoke-test the import**

Run: `uv run python -c "import httpware; print(httpware.Client, httpware.Retry, httpware.StatusError, httpware.NetworkError)"`
Expected: prints four class repr lines, no `ImportError`.

- [ ] **Step 5: Run the existing test suite to confirm no regressions from the dep addition**

Run: `just test`
Expected: all tests pass, coverage stays at 100%.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add httpware[pydantic] dependency"
```

---

## Task 2: Create the translation module (TDD)

**Files:**
- Create: `semvertag/providers/_errors.py`
- Create: `tests/unit/test_providers_errors.py`

The translation module is the foundation — `gitlab.py` will depend on it in Task 3. We TDD it in isolation first.

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_providers_errors.py`:

```python
import httpx2
import pytest

import httpware

from semvertag._errors import AuthError, ConfigError, ProviderAPIError
from semvertag.providers._errors import translate_create_tag_bad_request, translate_gitlab


_PROJECT_ID = 4242


def _response(status: int, *, body: bytes = b"") -> httpx2.Response:
    return httpx2.Response(status_code=status, content=body)


def _status_error(cls: type[httpware.StatusError], status: int, body: bytes = b"") -> httpware.StatusError:
    return cls(_response(status, body=body))


# translate_gitlab — status errors

def test_translate_gitlab_401_becomes_auth_error_with_token_guidance() -> None:
    result = translate_gitlab(_status_error(httpware.UnauthorizedError, 401), project_id=_PROJECT_ID)
    assert isinstance(result, AuthError)
    assert "Token rejected" in str(result)
    assert "SEMVERTAG_TOKEN" in str(result)


def test_translate_gitlab_403_becomes_auth_error_with_scope_guidance() -> None:
    result = translate_gitlab(_status_error(httpware.ForbiddenError, 403), project_id=_PROJECT_ID)
    assert isinstance(result, AuthError)
    assert "403" in str(result)
    assert "api" in str(result) or "write_repository" in str(result)


def test_translate_gitlab_404_becomes_config_error_with_project_id() -> None:
    result = translate_gitlab(_status_error(httpware.NotFoundError, 404), project_id=_PROJECT_ID)
    assert isinstance(result, ConfigError)
    assert f"project_id={_PROJECT_ID}" in str(result)


def test_translate_gitlab_422_becomes_config_error() -> None:
    result = translate_gitlab(_status_error(httpware.UnprocessableEntityError, 422), project_id=_PROJECT_ID)
    assert isinstance(result, ConfigError)
    assert "422" in str(result)


def test_translate_gitlab_429_becomes_provider_api_error() -> None:
    result = translate_gitlab(_status_error(httpware.RateLimitedError, 429), project_id=_PROJECT_ID)
    assert isinstance(result, ProviderAPIError)
    assert "rate limit" in str(result).lower()


def test_translate_gitlab_500_becomes_provider_api_error() -> None:
    result = translate_gitlab(_status_error(httpware.InternalServerError, 500), project_id=_PROJECT_ID)
    assert isinstance(result, ProviderAPIError)
    assert "500" in str(result)


def test_translate_gitlab_503_becomes_provider_api_error() -> None:
    result = translate_gitlab(_status_error(httpware.ServiceUnavailableError, 503), project_id=_PROJECT_ID)
    assert isinstance(result, ProviderAPIError)


def test_translate_gitlab_unknown_4xx_falls_back_to_provider_api_error() -> None:
    # 418 is not specially mapped; ClientStatusError is the fallback for unknown 4xx
    result = translate_gitlab(_status_error(httpware.ClientStatusError, 418), project_id=_PROJECT_ID)
    assert isinstance(result, ProviderAPIError)
    assert "418" in str(result)


# translate_gitlab — transport errors

def test_translate_gitlab_timeout_becomes_provider_api_error() -> None:
    exc = httpware.TimeoutError("read timed out")
    result = translate_gitlab(exc, project_id=_PROJECT_ID)
    assert isinstance(result, ProviderAPIError)
    assert "timed out" in str(result).lower() or "timeout" in str(result).lower()


def test_translate_gitlab_network_error_becomes_provider_api_error() -> None:
    exc = httpware.NetworkError("connection refused")
    result = translate_gitlab(exc, project_id=_PROJECT_ID)
    assert isinstance(result, ProviderAPIError)


def test_translate_gitlab_retry_budget_exhausted_becomes_provider_api_error() -> None:
    exc = httpware.RetryBudgetExhaustedError(last_response=None, last_exception=None, attempts=3)
    result = translate_gitlab(exc, project_id=_PROJECT_ID)
    assert isinstance(result, ProviderAPIError)
    assert "retr" in str(result).lower()


# translate_create_tag_bad_request

def test_translate_create_tag_bad_request_already_exists_becomes_config_error() -> None:
    exc = _status_error(httpware.BadRequestError, 400, body=b'{"message":"Tag already exists"}')
    result = translate_create_tag_bad_request(exc, tag_name="v1.2.3")
    assert isinstance(result, ConfigError)
    assert "v1.2.3" in str(result)
    assert "already exists" in str(result).lower()


def test_translate_create_tag_bad_request_already_exists_is_case_insensitive() -> None:
    exc = _status_error(httpware.BadRequestError, 400, body=b'{"message":"Tag ALREADY EXISTS"}')
    result = translate_create_tag_bad_request(exc, tag_name="v1.2.3")
    assert isinstance(result, ConfigError)
    assert "already exists" in str(result).lower()


def test_translate_create_tag_bad_request_other_400_becomes_generic_config_error() -> None:
    exc = _status_error(httpware.BadRequestError, 400, body=b'{"message":"bad ref format"}')
    result = translate_create_tag_bad_request(exc, tag_name="v1.2.3")
    assert isinstance(result, ConfigError)
    assert "v1.2.3" not in str(result)
    assert "400" in str(result)
```

- [ ] **Step 2: Run the test to verify it fails (module does not exist yet)**

Run: `uv run pytest tests/unit/test_providers_errors.py -v`
Expected: `ModuleNotFoundError: No module named 'semvertag.providers._errors'`.

- [ ] **Step 3: Write the translation module**

Create `semvertag/providers/_errors.py`:

```python
import httpware

from semvertag._errors import AuthError, ConfigError, ProviderAPIError


_TAG_EXISTS_FRAGMENT = "already exists"


def translate_gitlab(exc: httpware.ClientError, *, project_id: int) -> Exception:
    """Translate an httpware ClientError into the semvertag domain error for GitLab.

    Handles both status errors (4xx/5xx) and transport-layer failures
    (network, timeout, retry budget exhaustion).
    """
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
            f"GitLab API failure: {exc.response.status_code}. "
            "Retries exhausted after 3 attempts. Try again or check GitLab status."
        )
    if isinstance(exc, httpware.StatusError):
        return ProviderAPIError(f"Unexpected GitLab response: {exc.response.status_code}. Please file an issue.")
    if isinstance(exc, httpware.TimeoutError):
        return ProviderAPIError("GitLab request timed out. Try again or increase SEMVERTAG_REQUEST_TIMEOUT.")
    if isinstance(exc, httpware.RetryBudgetExhaustedError):
        return ProviderAPIError(f"GitLab retries exhausted after {exc.attempts} attempts. Try again later.")
    if isinstance(exc, httpware.NetworkError):
        return ProviderAPIError("GitLab unreachable. Check network connectivity.")
    return ProviderAPIError(f"GitLab request failed: {type(exc).__name__}")


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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_providers_errors.py -v`
Expected: all 14 tests pass.

- [ ] **Step 5: Lint**

Run: `just lint`
Expected: clean (no ruff or ty findings).

- [ ] **Step 6: Commit**

```bash
git add semvertag/providers/_errors.py tests/unit/test_providers_errors.py
git commit -m "providers: add httpware-to-semvertag error translation module"
```

---

## Task 3: Port `GitLabProvider` to `httpware.Client`

**Files:**
- Modify: `semvertag/providers/gitlab.py` (rewrite the class + drop helpers; keep pagination internals)
- Modify: `tests/integration/test_gitlab_provider.py` (rewrite `_make_provider` seam; delete `_make_provider_with_retrying_transport`; fix imports; adjust the few tests that pinned removed behavior)

This is a port-style task, not pure TDD: the integration tests already describe the behavior contract. We update the seam + the production code together so tests stay meaningful throughout.

**Important:** This task leaves `_http.py`, `_transport.py`, `test_http_client.py`, and `test_transport_retry.py` in place — they still pass independently. Task 4 switches ioc.py wiring; Task 5 deletes them.

- [ ] **Step 1: Read the current state end-to-end (no edits)**

Read the full bodies of:
- `semvertag/providers/gitlab.py` (220 lines) — note `_url`, `_translate_status`, `gitlab_auth_headers`, the `_HTTP_*` constants (all going away), and `_LINK_ENTRY_RE` / `_next_page_url` / `_parse_rel_values` / `_same_origin` / `_validate_tag_list` (staying).
- `tests/integration/test_gitlab_provider.py` (615 lines) — note `_make_provider` (lines 46–56), `_make_provider_with_retrying_transport` (59–72, gets deleted), the imports (1–28), and search for tests that:
  - Assert on `"request failed:"` wrapper messages (those messages go away).
  - Exercise POST retry behavior (POST is no longer retried).
  - Use `RetryingTransport` or `_translate_status` or `gitlab_auth_headers` directly.

- [ ] **Step 2: Rewrite `semvertag/providers/gitlab.py`**

Replace the entire file contents with:

```python
import dataclasses
import re
import typing
import urllib.parse

import httpx2
import pydantic

import httpware

from semvertag._errors import ConfigError, ProviderAPIError
from semvertag._settings import GitLabConfig
from semvertag._types import Commit, Tag
from semvertag.providers import _errors


_API_PREFIX: typing.Final = "/api/v4/projects"
_TAGS_PER_PAGE: typing.Final = 100
_MAX_TAG_PAGES: typing.Final = 100


class _ProjectResponse(pydantic.BaseModel):
    default_branch: str | None


class _CommitItem(pydantic.BaseModel):
    id: str
    message: str


class _TagCommit(pydantic.BaseModel):
    id: str


class _TagItem(pydantic.BaseModel):
    name: str
    commit: _TagCommit


# RFC 8288 Link header: <uri-reference>;param=value;param="value";...
_LINK_ENTRY_RE: typing.Final = re.compile(
    r"<\s*(?P<url>[^>]*?)\s*>(?P<params>(?:\s*;\s*[^,;]+)*)",
)


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
        except httpware.ClientError as exc:
            raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc
        if not project.default_branch:
            msg = "Default branch missing from GitLab response. Verify the project has a default branch configured."
            raise ConfigError(msg)
        return project.default_branch

    def get_latest_commit_on_default_branch(self) -> Commit:
        default_branch: typing.Final = self.get_default_branch()
        try:
            response = self.http.send(self.http.build_request(
                "GET",
                f"{_API_PREFIX}/{self.project_id}/repository/commits",
                params={"ref_name": default_branch, "per_page": 1},
            ))
        except httpware.ClientError as exc:
            raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc
        items = _validate_commit_list(response)
        if not items:
            msg = f"No commits on default branch '{default_branch}'. The branch appears empty."
            raise ProviderAPIError(msg)
        head = items[0]
        return Commit(sha=head.id, message=head.message)

    def list_tags(self) -> list[Tag]:
        tags: list[Tag] = []
        url: str = f"{_API_PREFIX}/{self.project_id}/repository/tags"
        params: dict[str, typing.Any] | None = {"per_page": _TAGS_PER_PAGE, "page": 1}
        for _ in range(_MAX_TAG_PAGES):
            try:
                response = self.http.send(self.http.build_request("GET", url, params=params))
            except httpware.ClientError as exc:
                raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc
            items = _validate_tag_list(response)
            tags.extend(Tag(name=item.name, commit_sha=item.commit.id) for item in items)
            next_url = _next_page_url(response, current_url=str(response.request.url))
            if next_url is None:
                return tags
            if not _same_origin(next_url, self.config.endpoint):
                msg = (
                    "GitLab pagination Link header points to a different host than SEMVERTAG_GITLAB__ENDPOINT. "
                    "Refusing to follow to protect credentials."
                )
                raise ProviderAPIError(msg)
            url, params = next_url, None
        msg = (
            f"Tag pagination exceeded {_MAX_TAG_PAGES} pages. "
            "The project has an unexpected number of tags; please file an issue."
        )
        raise ProviderAPIError(msg)

    def create_tag(self, name: str, commit_sha: str) -> None:
        try:
            self.http.send(self.http.build_request(
                "POST",
                f"{_API_PREFIX}/{self.project_id}/repository/tags",
                json={"tag_name": name, "ref": commit_sha},
            ))
        except httpware.BadRequestError as exc:
            raise _errors.translate_create_tag_bad_request(exc, tag_name=name) from exc
        except httpware.ClientError as exc:
            raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc


def _next_page_url(response: httpx2.Response, current_url: str) -> str | None:
    link_header: typing.Final = response.headers.get("link")
    if not link_header:
        return None
    for match in _LINK_ENTRY_RE.finditer(link_header):
        url_part = match.group("url").strip()
        if not url_part:
            continue
        if "next" in _parse_rel_values(match.group("params")):
            return urllib.parse.urljoin(current_url, url_part)
    return None


def _validate_tag_list(response: httpx2.Response) -> list[_TagItem]:
    return _validate_list(response, _TagItem, label="tags")


def _validate_commit_list(response: httpx2.Response) -> list[_CommitItem]:
    return _validate_list(response, _CommitItem, label="commits")


_TModel = typing.TypeVar("_TModel", bound=pydantic.BaseModel)


def _validate_list(response: httpx2.Response, model: type[_TModel], *, label: str) -> list[_TModel]:
    try:
        payload = response.json()
    except (ValueError, httpx2.DecodingError) as exc:
        msg = f"GitLab {label} response malformed JSON."
        raise ProviderAPIError(msg) from exc
    if not isinstance(payload, list):
        msg = f"GitLab {label} response shape invalid: expected list."
        raise ProviderAPIError(msg)
    try:
        return [model.model_validate(item) for item in payload]
    except pydantic.ValidationError as exc:
        msg = f"GitLab {label} response shape invalid: {exc}"
        raise ProviderAPIError(msg) from exc


def _parse_rel_values(params_blob: str) -> set[str]:
    for raw_param in params_blob.split(";"):
        param = raw_param.strip()
        if not param:
            continue
        name, _, value = param.partition("=")
        if name.strip().lower() != "rel":
            continue
        cleaned = value.strip().strip('"').strip("'").lower()
        return set(cleaned.split())
    return set()


def _same_origin(url: str, endpoint: str) -> bool:
    parsed: typing.Final = urllib.parse.urlsplit(url)
    expected: typing.Final = urllib.parse.urlsplit(endpoint)
    return parsed.scheme == expected.scheme and parsed.netloc == expected.netloc
```

**Notes on the rewrite:**
- `_url(self, path)` is gone — `httpware.Client(base_url=...)` handles URL joining.
- All `_HTTP_*` constants gone — `isinstance` checks against `httpware.X` replace them.
- `gitlab_auth_headers` and `_translate_status` gone — moved into the client construction (Task 4) and `_errors.translate_gitlab` (Task 2) respectively.
- `get_latest_commit_on_default_branch` uses raw `send()` + `_validate_commit_list` rather than `response_model=list[_CommitItem]` — generic aliases like `list[X]` satisfy `type[T]` at runtime (via `TypeAdapter`) but trip static type checkers; keeping the validator approach matches `list_tags` and stays clean under `ty`.
- `list_tags` uses `self.http.send(self.http.build_request(...))` for raw response access. `response.request.url` gives us the absolute URL for `urljoin` (replacing the manual `current_url` tracking).

- [ ] **Step 3: Update integration test imports and helpers**

In `tests/integration/test_gitlab_provider.py`:

Replace the import block (lines 1–28):

```python
import typing

import httpx2
import pydantic
import pytest

import httpware

from semvertag._errors import AuthError, ConfigError, ProviderAPIError
from semvertag._settings import GitLabConfig
from semvertag._types import Commit, Tag
from semvertag.providers._base import Provider
from semvertag.providers.gitlab import (
    GitLabProvider,
    _next_page_url,
    _parse_rel_values,
)
from tests.conftest import (
    GITLAB_ENDPOINT,
    GITLAB_PROJECT_ID,
    GITLAB_TOKEN,
    HandlerCallable,
    compose_handler,
    default_handler,
)
```

(Dropped: `from semvertag import _transport`, `from semvertag._transport import RetryingTransport`, `from semvertag.providers._http import HttpClient`, `_translate_status`, `gitlab_auth_headers`.)

Replace `_make_provider` (lines 46–56):

```python
_TOKEN_HEADER: typing.Final = "PRIVATE-TOKEN"


def _make_provider(handler: HandlerCallable) -> tuple[GitLabProvider, httpware.Client]:
    transport: typing.Final = httpx2.MockTransport(handler)
    config: typing.Final = GitLabConfig(endpoint=GITLAB_ENDPOINT, token=pydantic.SecretStr(GITLAB_TOKEN))
    client: typing.Final = httpware.Client(
        httpx2_client=httpx2.Client(transport=transport, base_url=GITLAB_ENDPOINT),
        headers={_TOKEN_HEADER: config.token.get_secret_value()},
    )
    provider: typing.Final = GitLabProvider(config=config, project_id=GITLAB_PROJECT_ID, http=client)
    return provider, client
```

**Note:** `httpware.Client(httpx2_client=...)` forbids combining `httpx2_client=` with `base_url=`/`timeout=`/etc. (per `client.py:93–104` — it'll raise `TypeError` if mixed). Configure the underlying `httpx2.Client` with `base_url`; only `headers=` and `middleware=` are safe on the outer `httpware.Client(...)` call in test paths. Production (Task 4) uses the all-kwargs form instead.

Delete `_make_provider_with_retrying_transport` entirely (lines 59–72).

- [ ] **Step 4: Run integration tests to surface remaining failures**

Run: `uv run pytest tests/integration/test_gitlab_provider.py -v`
Expected: many failures. Sort them into three buckets:
  1. **Import errors** in tests that used `_translate_status` or `gitlab_auth_headers` directly — those tests test deleted functions; **delete the test functions** (they belong to the deleted helper layer).
  2. **Assertion failures on exception message wording** — anywhere a test pinned `"request failed:"` (the old `_http.request_raw` wrapper) or specific text from the deleted `_translate_status`. Update the assertion to the new message (from `_errors.translate_gitlab`).
  3. **Behavioral failures from POST not retrying** — any test that called `create_tag` against a 429-then-201 handler expecting success. With POST no longer retried, the test should expect `ProviderAPIError` (from `translate_gitlab` mapping `RateLimitedError`). Update those tests to assert the new behavior.

- [ ] **Step 5: Fix the failures bucket by bucket**

For each failure in bucket (1): delete the test function. Note in commit message which ones were removed.

For each failure in bucket (2): update the `assert "..." in str(exc.value)` to match `_errors.translate_gitlab`'s output for that status code. Cross-reference the message strings in `semvertag/providers/_errors.py`.

For each failure in bucket (3): change `assert_success`-style assertions to `pytest.raises(ProviderAPIError)` and verify `"rate limit"` appears in the message.

Also check `tests/integration/test_gitlab_provider.py` for any tests calling `_next_page_url` with the old `current_url` parameter shape — the parameter is unchanged in the rewrite, so these should still pass; if any break, the rewrite of `_next_page_url` is at fault, not the test.

- [ ] **Step 6: Re-run the integration tests**

Run: `uv run pytest tests/integration/test_gitlab_provider.py -v`
Expected: all tests pass.

- [ ] **Step 7: Run the full test suite to catch cross-file fallout**

Run: `just test`
Expected: `test_transport_retry.py` and `test_http_client.py` still pass (they test the legacy modules, which still exist). Coverage should still be 100%.

If coverage dropped below 100% on `semvertag/providers/gitlab.py`, identify which branches lost coverage and either:
- Add the missing branch tests to `test_gitlab_provider.py`, or
- Confirm the lost branches were unreachable post-refactor and add `# pragma: no cover` with a one-line justification.

- [ ] **Step 8: Lint**

Run: `just lint`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add semvertag/providers/gitlab.py tests/integration/test_gitlab_provider.py
git commit -m "providers/gitlab: port to httpware.Client; remove transport-layer concerns"
```

---

## Task 4: Switch `ioc.py` wiring to `httpware.Client`

**Files:**
- Modify: `semvertag/ioc.py`

After this task, `_transport.py` and `_http.py` have no remaining importers — Task 5 will delete them.

- [ ] **Step 1: Rewrite `semvertag/ioc.py`**

Replace the entire file contents with:

```python
import typing

import modern_di
from modern_di import Scope, providers

import httpware

from semvertag._errors import ConfigError
from semvertag._settings import Settings
from semvertag._use_case import SemvertagUseCase
from semvertag.providers.gitlab import GitLabProvider
from semvertag.strategies._base import BumpStrategy
from semvertag.strategies.branch_prefix import BranchPrefixStrategy
from semvertag.strategies.conventional_commits import ConventionalCommitsStrategy


_TOKEN_HEADER: typing.Final = "PRIVATE-TOKEN"
_RETRY_STATUS_CODES: typing.Final = frozenset({408, 429, 500, 502, 503, 504})


def _build_gitlab_client(settings: Settings) -> httpware.Client:
    return httpware.Client(
        base_url=settings.gitlab.endpoint,
        timeout=settings.request_timeout,
        headers={_TOKEN_HEADER: settings.gitlab.token.get_secret_value()},
        middleware=[httpware.Retry(retry_status_codes=_RETRY_STATUS_CODES)],
    )


def _build_gitlab_provider(settings: Settings, client: httpware.Client) -> GitLabProvider:
    if settings.project_id is None:
        msg = "Project id missing. Set CI_PROJECT_ID or pass --project-id."
        raise ConfigError(msg)
    return GitLabProvider(
        config=settings.gitlab,
        project_id=settings.project_id,
        http=client,
    )


def _build_branch_prefix_strategy(settings: Settings) -> BranchPrefixStrategy:
    return BranchPrefixStrategy(config=settings.branch_prefix)


def _build_conventional_commits_strategy(settings: Settings) -> ConventionalCommitsStrategy:
    return ConventionalCommitsStrategy(config=settings.conventional_commits)


def _build_current_strategy(settings: Settings) -> BumpStrategy:
    if settings.strategy == "conventional-commits":
        return _build_conventional_commits_strategy(settings)
    return _build_branch_prefix_strategy(settings)


def _close_provider_client(provider: GitLabProvider) -> None:
    provider.http.close()


class SettingsGroup(modern_di.Group):
    settings = providers.ContextProvider(scope=Scope.APP, context_type=Settings)


class ProvidersGroup(modern_di.Group):
    gitlab_client = providers.Factory(scope=Scope.APP, creator=_build_gitlab_client)
    gitlab_provider = providers.Factory(
        scope=Scope.APP,
        creator=_build_gitlab_provider,
        kwargs={"client": gitlab_client},
        cache_settings=providers.CacheSettings(finalizer=_close_provider_client),
    )


class StrategiesGroup(modern_di.Group):
    branch_prefix_strategy = providers.Factory(scope=Scope.APP, creator=_build_branch_prefix_strategy)
    conventional_commits_strategy = providers.Factory(scope=Scope.APP, creator=_build_conventional_commits_strategy)
    current_strategy = providers.Factory(scope=Scope.APP, creator=_build_current_strategy)


class UseCasesGroup(modern_di.Group):
    semvertag_use_case = providers.Factory(
        scope=Scope.APP,
        creator=SemvertagUseCase,
        kwargs={
            "provider": ProvidersGroup.gitlab_provider,
            "strategy": StrategiesGroup.current_strategy,
        },
    )


ALL_GROUPS: typing.Final[list[type[modern_di.Group]]] = [
    SettingsGroup,
    ProvidersGroup,
    StrategiesGroup,
    UseCasesGroup,
]


container: typing.Final = modern_di.Container(groups=ALL_GROUPS)
```

**Notes:**
- `TransportsGroup` deletes; `ALL_GROUPS` shrinks by one entry.
- Imports of `httpx2`, `_transport.RetryingTransport`, `_http.HttpClient`, `gitlab.gitlab_auth_headers`, and `gitlab._translate_status` are gone.
- The provider factory is split: `gitlab_client` is the new test-overridable seam (Task 6 sketches the override pattern).
- `_close_provider_client` calls `httpware.Client.close()` (the sync close method); `httpware.Client` is itself a context manager but `close()` works for finalizer use.

- [ ] **Step 2: Run the full test suite**

Run: `just test`
Expected: all tests pass; coverage stays at 100%.

If `test_ioc.py` references `TransportsGroup`, fix that import (the file as of writing does not). If any test passes the old `_build_gitlab_provider(settings, transport=...)` signature, update it to the new two-step `_build_gitlab_client(settings)` + `_build_gitlab_provider(settings, client)` shape.

- [ ] **Step 3: Lint**

Run: `just lint`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add semvertag/ioc.py
git commit -m "ioc: build httpware.Client directly; drop TransportsGroup"
```

---

## Task 5: Delete legacy modules and their tests

**Files:**
- Delete: `semvertag/_transport.py`
- Delete: `semvertag/providers/_http.py`
- Delete: `tests/unit/test_transport_retry.py`
- Delete: `tests/unit/test_http_client.py`

After Tasks 3 and 4, nothing imports these. Verify, then delete.

- [ ] **Step 1: Verify no remaining importers**

Run: `grep -rn "from semvertag._transport\|from semvertag.providers._http\|RetryingTransport\|HttpClient" semvertag/ tests/ --include='*.py'`
Expected output: matches only inside `_transport.py`, `_http.py`, `test_transport_retry.py`, and `test_http_client.py` themselves.

If any other file matches, stop and resolve before deleting. Likely missed update in Task 3.

- [ ] **Step 2: Delete the four files**

Run:
```bash
git rm semvertag/_transport.py semvertag/providers/_http.py
git rm tests/unit/test_transport_retry.py tests/unit/test_http_client.py
```

- [ ] **Step 3: Run the full test suite**

Run: `just test`
Expected: all tests pass; coverage stays at 100%. (Coverage scope auto-shrinks — `--cov=semvertag` collects whatever modules exist.)

- [ ] **Step 4: Check the `pyproject.toml` coverage `fail_under` and the per-module branch-coverage gates**

Run: `grep -n "fail_under\|test-branch" /Users/kevinsmith/src/pypi/autosemver/pyproject.toml /Users/kevinsmith/src/pypi/autosemver/Justfile`

If any `just test-branch-*` recipe targets a module we deleted (`_transport` or `_http`), remove that recipe from `Justfile`. If `pyproject.toml` references either module in coverage configuration, update it.

- [ ] **Step 5: Lint**

Run: `just lint`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git commit -m "providers: delete legacy _transport and _http modules"
```

---

## Task 6: Final validation

**Files:** none modified — this is the verification gate.

- [ ] **Step 1: Full lint sweep**

Run: `just lint-ci`
Expected: clean.

- [ ] **Step 2: Full test sweep with branch coverage**

Run: `just test-branch`
Expected: all tests pass; coverage stays at 100% statement + branch.

- [ ] **Step 3: Docs build (the project ships docs to ReadTheDocs)**

Run: `mkdocs build --strict`
Expected: clean build. If a doc page references `RetryingTransport` or `HttpClient` by name, update the prose to reference `httpware.Retry` / `httpware.Client`.

- [ ] **Step 4: End-to-end smoke against a real (or recorded) GitLab endpoint** *(optional but recommended)*

If you have a sandbox GitLab project: set `SEMVERTAG_GITLAB__ENDPOINT`, `SEMVERTAG_TOKEN`, `CI_PROJECT_ID`, and run `uv run semvertag --dry-run` (or whatever the project's read-only CLI invocation is). Confirm:
  - Default branch is fetched (200 → success).
  - Latest commit is fetched.
  - Tags are listed and paginated correctly.
  - No `_http` or `_transport` import-time errors.

If no sandbox is available, skip this step. The integration tests with `httpx2.MockTransport` cover the same paths.

- [ ] **Step 5: Skim `git log --oneline` to confirm the commit history reads cleanly**

Expected sequence (or similar):
```
chore: add httpware[pydantic] dependency
providers: add httpware-to-semvertag error translation module
providers/gitlab: port to httpware.Client; remove transport-layer concerns
ioc: build httpware.Client directly; drop TransportsGroup
providers: delete legacy _transport and _http modules
```

- [ ] **Step 6 — Optional: invoke `superpowers:requesting-code-review`**

Per CLAUDE.md the project's workflow is brainstorm → plan → TDD → review. Run a review subagent against the diff before merging.

---

## Self-review notes

- **Spec coverage:** Every spec section (`Target shape`, `Retry config`, `Error translation`, `Provider call-site shape`, `ioc.py wiring`, `Dependency changes`, `Test impact`, the four `Open items`) is implemented by at least one task. The four open items from the spec are all resolved in the plan: (1) DI split → Task 4 step 1, (2) `request_timeout` is a `float` (verified: `_settings.py:66`) → Task 4's `timeout=settings.request_timeout` works directly, (3) `__main__.py` catches `SemvertagError` already (verified: `__main__.py:160`) → no change needed because `translate_gitlab` produces semvertag domain errors that bubble through unchanged, (4) pagination uses `self.http.send(self.http.build_request(...))` returning the raw response → Task 3 step 2.
- **Placeholder scan:** No `TBD`/`TODO`/`...`/"appropriate error handling"/"similar to" patterns in any task step. The `# pragma: no cover` mention in Task 3 step 7 is a contingency directive, not a placeholder.
- **Type consistency:** `GitLabProvider.http: httpware.Client` used uniformly across Tasks 3 (production), 3 (tests via `_make_provider`), 4 (`_build_gitlab_provider` signature), 4 (`_close_provider_client`). `translate_gitlab(exc, *, project_id)` signature consistent across Task 2 (definition), Task 3 (call sites). `_build_gitlab_client` / `_build_gitlab_provider` split shape consistent between Task 4 step 1 and `ProvidersGroup` factory wiring within the same task.

---

## Execution handoff

(Filled in by the launching session — see `superpowers:writing-plans` skill.)

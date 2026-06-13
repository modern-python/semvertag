---
status: shipped
date: 2026-06-08
slug: github-provider
supersedes: null
superseded_by: null
pr: null
outcome: shipped (#4)
---

# GitHub provider — design spec

**Date:** 2026-06-08
**Status:** Approved, ready for implementation planning
**Topic slug:** `github-provider`
**Predecessors:** `2026-06-07-httpware-migration-design.md`, `2026-06-08-httpware-decoder-adoption-design.md` (established the httpware-backed provider shape and the per-provider error translation pattern this spec parallels)

## Goal

Add `GitHubProvider` so `semvertag` works against `github.com` and GitHub Enterprise repos with the same CLI it works against GitLab today. After this lands, the package description `"Auto-tag GitLab repos with semantic version tags"` becomes `"Auto-tag GitLab and GitHub repos…"` honestly: the closing feature gap.

The new provider parallels the existing `GitLabProvider` method-for-method, conforms to the existing `Provider` `typing.Protocol`, and reuses every cross-cutting piece (`httpware.Client` + `Retry` + `PydanticDecoder`, the operator-action error tree, Link-header pagination, the `current_strategy` selector idiom in `ioc.py`).

## Background

semvertag was originally GitLab-only — `_archive/bmad/4-3b-gitlab-ci-catalog-component.md` (since cleared) framed a parallel `GitHubProvider` as the obvious next direction but it was never shipped. As of v0.2.0:

- `Provider` is already a `typing.Protocol` in `semvertag/providers/_base.py` with four methods (`get_default_branch`, `get_latest_commit_on_default_branch`, `list_tags`, `create_tag`).
- `GitHubConfig` already exists in `semvertag/_settings.py` with a `token: SecretStr` field and aliases (`SEMVERTAG_GITHUB__TOKEN`, `SEMVERTAG_TOKEN`, `GITHUB_TOKEN`). It has no `endpoint` field today.
- `Settings.github = GitHubConfig` is wired.
- `ioc.py` hardcodes `provider=ProvidersGroup.gitlab_provider` in the `UseCasesGroup.semvertag_use_case` factory — there's no provider selection layer.
- `__main__.py` CLI is GitLab-specific (`--project-id`, `--gitlab-endpoint`, help text says "GitLab repos").
- `Settings.project_id: int | None` (aliases `SEMVERTAG_PROJECT_ID`, `CI_PROJECT_ID`) is the GitLab repo identifier. There is no analogue for the GitHub `OWNER/REPO` string.
- The two design-pattern predecessors (httpware migration + decoder adoption) established: the `httpware.Client(httpx2_client=…)` test seam, `httpware.Retry` for retry policy, `httpware.PydanticDecoder` via `response_model=` / `send_with_response`, the four-class `httpware.ClientError` translator chain (`UnauthorizedError`, `ForbiddenError`, `NotFoundError`, …) mapped to semvertag's operator-action errors (`AuthError`/3, `ConfigError`/2, `ProviderAPIError`/4). `GitHubProvider` adopts those patterns directly — nothing novel architecturally.

## Non-goals

- **`action.yml` (GitHub Actions composite-action wrapper).** Deferred to a follow-up. v0.2.0 docs prove the inline `uvx semvertag tag` recipe works for GitLab; the same pattern with `actions/setup-python` works for GitHub Actions and is documented in `docs/providers/github.md`. A composite action is nicer DX but doesn't unblock anything.
- **Bitbucket provider.** Out of scope; same pattern applies but is its own PR.
- **GitHub App authentication.** Personal Access Tokens (classic or fine-grained) and `GITHUB_TOKEN` (GHA-issued installation token) are supported; GitHub App authentication via JWT exchange is not.
- **ETag / conditional requests.** GitHub supports `If-None-Match: <etag>` for cheaper polling; semvertag does ~5 requests per run, so the optimization isn't worth the cache layer.
- **Updating the GitLab CI Catalog descriptor.** Not GitHub-related.

## Target shape

```
semvertag/
├── _settings.py            ← add Settings.provider, Settings.repo; add GitHubConfig.endpoint;
│                             add @model_validator that auto-detects from CI env + enforces
│                             the right repo identifier per provider
├── _link_pagination.py     ← NEW: extract _LINK_ENTRY_RE, _next_page_url, _parse_rel_values,
│                             _same_origin from providers/gitlab.py
├── providers/
│   ├── _base.py            ← unchanged (Provider Protocol already exists)
│   ├── _errors.py          ← extract _translate_transport(exc, *, provider_label) shared by
│   │                         both translators; add translate_github(exc, *, repo) and
│   │                         translate_create_tag_github_unprocessable(exc, *, tag_name)
│   ├── gitlab.py           ← import pagination helpers from _link_pagination; thread through
│   │                         _translate_gitlab_transport → _translate_transport (no public-API
│   │                         change)
│   └── github.py           ← NEW: GitHubProvider parallel to GitLabProvider
├── ioc.py                  ← add github_client / github_provider factories; replace direct
│                             gitlab_provider wiring with a current_provider selector that
│                             dispatches on settings.provider
└── __main__.py             ← add --provider, --repo, --github-endpoint flags; route --token
                              to the active provider; refresh help text and package description

docs/providers/github.md    ← NEW (parallel to gitlab.md)
README.md                   ← update hero to mention GitHub; add an "Use in GitHub Actions"
                              section with the inline-job recipe
pyproject.toml              ← description: "Auto-tag GitLab and GitHub repos with semantic
                              version tags — one tool, two strategies, two providers."
```

Provider Protocol unchanged. The new `GitHubProvider` conforms by implementing the same four methods with the same return types (`str`, `Commit`, `list[Tag]`, `None`).

## Provider selection

`Settings` gains a `provider: Literal["gitlab", "github"] | None` field plus a `@model_validator(mode="after")` that resolves it. Selection rules, in order:

1. **Explicit override wins.** If `--provider` flag or `SEMVERTAG_PROVIDER` / `PROVIDER` env var set → use that.
2. **GitHub Actions env.** Else if `GITHUB_ACTIONS=true` → `"github"`.
3. **GitLab CI env.** Else if `GITLAB_CI=true` → `"gitlab"`.
4. **Both set.** Raise `ConfigError("ambiguous CI context; pass --provider to disambiguate")`.
5. **Neither set.** Default to `"gitlab"` (back-compat with 0.2.x users running outside CI).

The validator runs at `Settings()` construction AND after `apply_cli_overlay` (which already re-validates per existing behavior). After the validator runs, `settings.provider` is always concretely `"gitlab"` or `"github"` — never `None` — so `ioc.py` reads it directly without re-resolving.

The same validator also enforces the matching repo identifier:

- `provider == "github"` requires `settings.repo` to be set; otherwise `ValueError("provider=github requires repo (set GITHUB_REPOSITORY or pass --repo OWNER/REPO)")`.
- `provider == "gitlab"` requires `settings.project_id` to be set; same shape.

`__main__.py` already converts `pydantic.ValidationError` into `ConfigError` with exit code 2, so these validator errors surface as the expected operator-facing exit-3 wait, exit-2 messages.

### Settings changes

```python
class GitHubConfig(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(env_prefix="SEMVERTAG_GITHUB__", ...)
    endpoint: str = "https://api.github.com"   # NEW — GitHub Enterprise users override
    token: pydantic.SecretStr = ...            # already exists; alias chain unchanged


class Settings(pydantic_settings.BaseSettings):
    # NEW
    provider: typing.Literal["gitlab", "github"] | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("SEMVERTAG_PROVIDER", "PROVIDER"),
    )
    repo: str | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("SEMVERTAG_REPO", "GITHUB_REPOSITORY"),
    )

    # existing — unchanged
    project_id: int | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("SEMVERTAG_PROJECT_ID", "CI_PROJECT_ID"),
    )

    @pydantic.model_validator(mode="after")
    def _resolve_provider(self) -> typing.Self:
        if self.provider is None:
            self.provider = _detect_provider_from_env()
        if self.provider == "github" and not self.repo:
            raise ValueError(
                "provider=github requires `repo` (set GITHUB_REPOSITORY or pass --repo OWNER/REPO)"
            )
        if self.provider == "gitlab" and self.project_id is None:
            raise ValueError(
                "provider=gitlab requires `project_id` (set CI_PROJECT_ID or pass --project-id N)"
            )
        return self
```

The `_detect_provider_from_env()` free function (or `Settings` classmethod) reads `os.environ` for `GITHUB_ACTIONS` / `GITLAB_CI` per the rules above. Implementation detail; plan handles placement.

## GitHubProvider implementation

```python
import dataclasses
import typing

import httpware
import pydantic

from semvertag import _link_pagination
from semvertag._errors import ConfigError, ProviderAPIError
from semvertag._settings import GitHubConfig
from semvertag._types import Commit, Tag
from semvertag.providers import _errors


_API_PREFIX: typing.Final = "/repos"
_TAGS_PER_PAGE: typing.Final = 100
_MAX_TAG_PAGES: typing.Final = 100


class _RepoResponse(pydantic.BaseModel):
    default_branch: str | None


class _CommitAuthor(pydantic.BaseModel):
    message: str


class _CommitItem(pydantic.BaseModel):
    sha: str
    commit: _CommitAuthor   # GitHub nests message under .commit: {sha, commit: {message, author, ...}}


class _TagCommit(pydantic.BaseModel):
    sha: str


class _TagItem(pydantic.BaseModel):
    name: str
    commit: _TagCommit       # {name, commit: {sha, url}}


class _CommitList(pydantic.RootModel[list[_CommitItem]]):
    pass


class _TagList(pydantic.RootModel[list[_TagItem]]):
    pass


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class GitHubProvider:
    name: typing.ClassVar[str] = "github"
    config: GitHubConfig
    repo: str   # "OWNER/REPO"
    http: httpware.Client

    def get_default_branch(self) -> str:
        try:
            repo_info = self.http.get(f"{_API_PREFIX}/{self.repo}", response_model=_RepoResponse)
        except httpware.ClientError as exc:
            raise _errors.translate_github(exc, repo=self.repo) from exc
        if not repo_info.default_branch:
            raise ConfigError("Default branch missing from GitHub response. Verify the repo has a default branch.")
        return repo_info.default_branch

    def get_latest_commit_on_default_branch(self) -> Commit:
        default_branch: typing.Final = self.get_default_branch()
        try:
            commits = self.http.get(
                f"{_API_PREFIX}/{self.repo}/commits",
                params={"sha": default_branch, "per_page": 1},
                response_model=_CommitList,
            )
        except httpware.ClientError as exc:
            raise _errors.translate_github(exc, repo=self.repo) from exc
        if not commits.root:
            raise ProviderAPIError(f"No commits on default branch '{default_branch}'. The branch appears empty.")
        head = commits.root[0]
        return Commit(sha=head.sha, message=head.commit.message)

    def list_tags(self) -> list[Tag]:
        tags: list[Tag] = []
        url: str = f"{_API_PREFIX}/{self.repo}/tags"
        params: dict[str, typing.Any] | None = {"per_page": _TAGS_PER_PAGE, "page": 1}
        for _ in range(_MAX_TAG_PAGES):
            try:
                response, page = self.http.send_with_response(
                    self.http.build_request("GET", url, params=params),
                    response_model=_TagList,
                )
            except httpware.ClientError as exc:
                raise _errors.translate_github(exc, repo=self.repo) from exc
            tags.extend(Tag(name=item.name, commit_sha=item.commit.sha) for item in page.root)
            next_url = _link_pagination.next_page_url(response, current_url=str(response.request.url))
            if next_url is None:
                return tags
            if not _link_pagination.same_origin(next_url, self.config.endpoint):
                raise ProviderAPIError(
                    "GitHub pagination Link header points to a different host than SEMVERTAG_GITHUB__ENDPOINT. "
                    "Refusing to follow to protect credentials."
                )
            url, params = next_url, None
        raise ProviderAPIError(
            f"Tag pagination exceeded {_MAX_TAG_PAGES} pages. "
            "The repo has an unexpected number of tags; please file an issue."
        )

    def create_tag(self, name: str, commit_sha: str) -> None:
        try:
            self.http.send(self.http.build_request(
                "POST",
                f"{_API_PREFIX}/{self.repo}/git/refs",
                json={"ref": f"refs/tags/{name}", "sha": commit_sha},
            ))
        except httpware.UnprocessableEntityError as exc:
            raise _errors.translate_create_tag_github_unprocessable(exc, tag_name=name) from exc
        except httpware.ClientError as exc:
            raise _errors.translate_github(exc, repo=self.repo) from exc
```

### API differences from GitLab worth flagging

| Concern | GitLab | GitHub |
|---|---|---|
| Repo identifier | `int project_id` | `OWNER/REPO` string |
| Commit shape | `{id, message}` | `{sha, commit: {message}}` (extra nesting) |
| Tag shape | `{name, commit: {id}}` | `{name, commit: {sha}}` |
| Create-tag endpoint | `POST /projects/{id}/repository/tags` body `{tag_name, ref}` | `POST /repos/{owner}/{repo}/git/refs` body `{ref: "refs/tags/X", sha}` |
| Tag already exists | `400` + body fragment `"already exists"` | `422` + body `{errors: [{resource: "Reference", code: "already_exists"}]}` |
| Pagination | RFC 8288 Link header | RFC 8288 Link header (identical) |
| Auth header | `PRIVATE-TOKEN: <token>` | `Authorization: Bearer <token>` + `Accept: application/vnd.github+json` + `X-GitHub-Api-Version: 2022-11-28` |

The auth headers and API-version pinning are set in `ioc._build_github_client`, not in the provider class.

## Error translation: `_errors.py`

Three changes in `semvertag/providers/_errors.py`:

1. **Extract `_translate_transport(exc, *, provider_label: str)`** for the transport-side branches that are uniform across providers — `DecodeError`, `TimeoutError`, `RetryBudgetExhaustedError`, `NetworkError`, and the generic `ClientError` fallback. The only variation between providers is the brand name in the message; parameterizing on `provider_label: str` is the textbook case for extraction. Both `translate_gitlab` and `translate_github` delegate their transport branches to this helper.

   ```python
   def _translate_transport(exc: httpware.ClientError, *, provider_label: str) -> Exception:
       if isinstance(exc, httpware.DecodeError):
           return ProviderAPIError(
               f"{provider_label} {exc.model.__name__} response could not be decoded: {exc.original}"
           )
       if isinstance(exc, httpware.TimeoutError):
           return ProviderAPIError(
               f"{provider_label} request timed out. Try again or increase SEMVERTAG_REQUEST_TIMEOUT."
           )
       if isinstance(exc, httpware.RetryBudgetExhaustedError):
           return ProviderAPIError(
               f"{provider_label} retries exhausted after {exc.attempts} attempts. Try again later."
           )
       if isinstance(exc, httpware.NetworkError):
           return ProviderAPIError(f"{provider_label} unreachable. Check network connectivity.")
       return ProviderAPIError(f"{provider_label} request failed: {type(exc).__name__}")
   ```

2. **Add `translate_github(exc, *, repo: str)`.** Parallel to `translate_gitlab` — same dispatch order, different actionable hints in the per-status messages. Falls through to `_translate_transport(exc, provider_label="GitHub")` for non-status errors.

   ```python
   def translate_github(exc: httpware.ClientError, *, repo: str) -> Exception:
       if isinstance(exc, httpware.UnauthorizedError):
           return AuthError("Token rejected: 401. Verify SEMVERTAG_TOKEN is valid.")
       if isinstance(exc, httpware.ForbiddenError):
           return AuthError(
               "Token missing scope or insufficient permission: 403. "
               "Verify SEMVERTAG_TOKEN has 'contents: write' scope "
               "(or 'public_repo' / 'repo' for classic PATs)."
           )
       if isinstance(exc, httpware.NotFoundError):
           return ConfigError(
               f"GitHub repo not found: repo='{repo}'. Verify GITHUB_REPOSITORY or --repo OWNER/REPO."
           )
       if isinstance(exc, httpware.UnprocessableEntityError):
           # Generic 422. The create_tag-specific 422 ("already_exists") is handled separately
           # by translate_create_tag_github_unprocessable below.
           return ConfigError(
               "Request rejected by GitHub: 422. Check ref format and that the referenced sha exists."
           )
       if isinstance(exc, httpware.RateLimitedError):
           return ProviderAPIError(
               "GitHub rate limit: 429. Retries exhausted after 3 attempts; "
               "try again later or check token rate-limit budget."
           )
       if isinstance(exc, httpware.ServerStatusError):
           return ProviderAPIError(
               f"GitHub API failure: {exc.response.status_code}. "
               "Retries exhausted after 3 attempts. Try again or check https://www.githubstatus.com."
           )
       if isinstance(exc, httpware.StatusError):
           return ProviderAPIError(
               f"Unexpected GitHub response: {exc.response.status_code}. Please file an issue."
           )
       return _translate_transport(exc, provider_label="GitHub")
   ```

3. **Add `translate_create_tag_github_unprocessable(exc, *, tag_name: str)`** for the 422-already-exists special case. Inspects body for the structured `"already_exists"` code (durable contract) OR the human-readable `"already exists"` substring (safety net):

   ```python
   def translate_create_tag_github_unprocessable(
       exc: httpware.UnprocessableEntityError, *, tag_name: str
   ) -> Exception:
       body = exc.response.text
       if "already_exists" in body or "already exists" in body.lower():
           return ConfigError(
               f"Tag already exists: '{tag_name}'. "
               "The tag was created by a concurrent run or previous invocation."
           )
       return ConfigError(
           "Request rejected by GitHub: 422. Check ref format and that the referenced sha exists."
       )
   ```

`_translate_gitlab_transport` deletes; `translate_gitlab` is updated to call `_translate_transport(exc, provider_label="GitLab")` for its transport branches. No behavior change for the GitLab side — messages remain bit-identical because the parameterization only varies the label string.

### Why per-status branches stay duplicated

Each per-status branch carries provider-specific actionable hints — different token scopes, different repo-identifier vocabulary, different status-page URLs, different error-page concerns (token rate-limit budget on GitHub vs no equivalent on GitLab). Collapsing those would force a `MessageBuilder` abstraction that squeezes real diversity through a uniform surface. The dedup at the transport layer works because the messages have *no* provider-specific content; the status layer does, so it stays per-provider.

## Pagination helpers extraction: `_link_pagination.py`

New module `semvertag/_link_pagination.py` (private to semvertag — module name starts with `_`):

```python
import re
import typing
import urllib.parse

import httpx2


# RFC 8288 Link header: <uri-reference>;param=value;param="value";...
LINK_ENTRY_RE: typing.Final = re.compile(
    r"<\s*(?P<url>[^>]*?)\s*>(?P<params>(?:\s*;\s*[^,;]+)*)",
)


def next_page_url(response: httpx2.Response, *, current_url: str) -> str | None:
    """Walk the response's Link header and return the absolute URL of rel='next', or None."""
    link_header = response.headers.get("link")
    if not link_header:
        return None
    for match in LINK_ENTRY_RE.finditer(link_header):
        url_part = match.group("url").strip()
        if not url_part:
            continue
        if "next" in _parse_rel_values(match.group("params")):
            return urllib.parse.urljoin(current_url, url_part)
    return None


def same_origin(url: str, endpoint: str) -> bool:
    """Return True if `url` shares scheme + netloc with `endpoint`. Guards credential leaks."""
    parsed = urllib.parse.urlsplit(url)
    expected = urllib.parse.urlsplit(endpoint)
    return parsed.scheme == expected.scheme and parsed.netloc == expected.netloc


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
```

The public surface drops the leading underscore (`_next_page_url` → `next_page_url`, `_same_origin` → `same_origin`, `_LINK_ENTRY_RE` → `LINK_ENTRY_RE`) since the whole module is private. `_parse_rel_values` stays underscored as a module-internal helper. `providers/gitlab.py` imports from this module; the existing test that exercises `_next_page_url` / `_parse_rel_values` directly from `gitlab.py` shifts to importing from `_link_pagination` (these are tests of the helpers, not of GitLab logic).

## Wiring: ioc.py

```python
_GITLAB_TOKEN_HEADER: typing.Final = "PRIVATE-TOKEN"
_GITHUB_ACCEPT: typing.Final = "application/vnd.github+json"
_GITHUB_API_VERSION: typing.Final = "2022-11-28"
_RETRY_STATUS_CODES: typing.Final = frozenset({408, 429, 500, 502, 503, 504})


def _build_gitlab_client(settings: Settings) -> httpware.Client:
    return httpware.Client(
        base_url=settings.gitlab.endpoint,
        timeout=settings.request_timeout,
        headers={_GITLAB_TOKEN_HEADER: settings.gitlab.token.get_secret_value()},
        middleware=[httpware.Retry(retry_status_codes=_RETRY_STATUS_CODES)],
    )


def _build_github_client(settings: Settings) -> httpware.Client:
    return httpware.Client(
        base_url=settings.github.endpoint,
        timeout=settings.request_timeout,
        headers={
            "Authorization": f"Bearer {settings.github.token.get_secret_value()}",
            "Accept": _GITHUB_ACCEPT,
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        },
        middleware=[httpware.Retry(retry_status_codes=_RETRY_STATUS_CODES)],
    )


def _build_gitlab_provider(settings: Settings, client: httpware.Client) -> GitLabProvider:
    assert settings.project_id is not None  # noqa: S101 — invariant from Settings._resolve_provider validator
    return GitLabProvider(config=settings.gitlab, project_id=settings.project_id, http=client)


def _build_github_provider(settings: Settings, client: httpware.Client) -> GitHubProvider:
    assert settings.repo is not None  # noqa: S101 — invariant from Settings._resolve_provider validator
    return GitHubProvider(config=settings.github, repo=settings.repo, http=client)


def _build_current_provider(
    settings: Settings,
    gitlab_provider: GitLabProvider,
    github_provider: GitHubProvider,
) -> Provider:
    if settings.provider == "github":
        return github_provider
    return gitlab_provider


def _close_gitlab_provider(provider: GitLabProvider) -> None:
    provider.http.close()


def _close_github_provider(provider: GitHubProvider) -> None:
    provider.http.close()


class ProvidersGroup(modern_di.Group):
    gitlab_client = providers.Factory(scope=Scope.APP, creator=_build_gitlab_client)
    gitlab_provider = providers.Factory(
        scope=Scope.APP, creator=_build_gitlab_provider,
        kwargs={"client": gitlab_client},
        cache_settings=providers.CacheSettings(finalizer=_close_gitlab_provider),
    )
    github_client = providers.Factory(scope=Scope.APP, creator=_build_github_client)
    github_provider = providers.Factory(
        scope=Scope.APP, creator=_build_github_provider,
        kwargs={"client": github_client},
        cache_settings=providers.CacheSettings(finalizer=_close_github_provider),
    )
    current_provider = providers.Factory(
        scope=Scope.APP, creator=_build_current_provider,
        kwargs={"gitlab_provider": gitlab_provider, "github_provider": github_provider},
    )
```

`UseCasesGroup.semvertag_use_case` switches `provider=ProvidersGroup.current_provider` (was `gitlab_provider`).

**Eager vs lazy client construction.** `current_provider` declares both `gitlab_provider` and `github_provider` as kwargs, so modern-di eagerly resolves both — constructing **both** `httpware.Client` instances even though only one is used per invocation. Connection pools in `httpx2` are lazy (no sockets open until a request fires); the unused client is essentially free. The alternative (`container.resolve_provider()` inside the factory body to lazily pick one) trades a tiny efficiency win for noticeably more wiring complexity. Eager is the right call.

`_close_gitlab_provider` / `_close_github_provider` are separate one-liners (rather than a single closure-based finalizer) because modern-di's finalizer takes a parameter typed to the cached object — using separate finalizers keeps each factory's typing clean.

## Wiring: __main__.py CLI

Three new flags + provider-aware `--token` routing:

```python
provider: typing.Annotated[
    str | None,
    typer.Option("--provider", help="Provider: 'github' or 'gitlab' (default: auto-detect from CI env)."),
] = None,
repo: typing.Annotated[
    str | None,
    typer.Option("--repo", help="GitHub repo as OWNER/REPO (or set GITHUB_REPOSITORY)."),
] = None,
github_endpoint: typing.Annotated[
    str | None,
    typer.Option("--github-endpoint", help="GitHub API endpoint URL (for GitHub Enterprise)."),
] = None,
```

`--project-id`, `--gitlab-endpoint`, `--strategy`, `--default-branch`, `--request-timeout`, `--token` stay as-is in signature. The `--project-id` and `--gitlab-endpoint` help text doesn't need adjusting — they're GitLab-specific and that's now explicit in the broader CLI surface.

`--token` routing — needs to dispatch on the *resolved* provider. The CLI runs `apply_cli_overlay` once with non-token overrides (which triggers the `_resolve_provider` validator and gives us the active provider), then applies the token in a second pass:

```python
# In _main_callback, after the first apply_cli_overlay call:
if token is not None:
    settings = apply_cli_overlay(
        settings, {f"{settings.provider}.token": pydantic.SecretStr(token)}
    )
```

Two-pass overlay is mildly awkward but it's the cleanest way to handle "the token belongs to whichever provider we end up using." Alternative (force users to pass `--gitlab-token` / `--github-token` explicitly) is uglier from a UX standpoint — `--token` as the catch-all is what the existing CLI promised.

Help text on `MAIN_APP`: `"Auto-tag GitLab and GitHub repos with semantic version tags — one tool, two strategies, two providers."`

## Wiring: docs + README + pyproject.toml

- **`docs/providers/github.md`** — parallel to the existing `docs/providers/gitlab.md`. Sections:
  - **Required scopes**: `contents: write` for fine-grained PATs; `public_repo` (public repos) or `repo` (private repos) for classic PATs; for `GITHUB_TOKEN` inside GH Actions, ensure the workflow has `permissions: contents: write`.
  - **Environment variables**: `GITHUB_TOKEN` / `SEMVERTAG_GITHUB__TOKEN` / `SEMVERTAG_TOKEN`, `GITHUB_REPOSITORY` / `SEMVERTAG_REPO`, `SEMVERTAG_GITHUB__ENDPOINT` (Enterprise).
  - **Inline GH-Actions job recipe** — mirror the GitLab CI recipe shape, swap to `actions/setup-python@v5` + `uvx semvertag tag`. Provide a minimal `permissions:` block.
  - **Troubleshooting**: 401 (token rejected), 403 (scope), 404 (repo), 422 (tag exists / ref format).

- **`README.md`** — hero string updated to mention GitHub. Add a "Use in GitHub Actions" section with the inline-job recipe (same shape as the existing GitLab CI section).

- **`pyproject.toml`** — `description = "Auto-tag GitLab and GitHub repos with semantic version tags — one tool, two strategies, two providers."`. Add `"github"` to keywords.

## Test impact

| File | Action |
|---|---|
| `tests/unit/test_settings.py` | Add tests for: (a) `_resolve_provider` env auto-detection (GITHUB_ACTIONS only → github, GITLAB_CI only → gitlab, both → ConfigError, neither → gitlab default), (b) explicit `provider=github` requires `repo`, (c) explicit `provider=gitlab` requires `project_id`, (d) GitHubConfig.endpoint defaults + override |
| `tests/unit/test_providers_errors.py` | Add tests parallel to `translate_gitlab_*` tests for every `translate_github` branch (401/403/404/422/429/500/transport errors) + tests for `translate_create_tag_github_unprocessable` ("already_exists" structured code, "already exists" message-string safety net, generic 422 fallback). Verify shared `_translate_transport` produces identical-shape messages for both providers (parameterized on label) |
| `tests/integration/test_github_provider.py` | NEW — full integration suite parallel to `test_gitlab_provider.py`. Uses `httpx2.MockTransport` with GitHub-shaped JSON payloads. Covers all four provider methods + pagination + Link-header same-origin guard + tag-creation 422-already-exists path |
| `tests/unit/test_ioc.py` | Add tests for `current_provider` resolution (provider=github → returns GitHubProvider, provider=gitlab → returns GitLabProvider) |
| `tests/integration/test_cli_*.py` | Add CLI smoke tests for `--provider github --repo OWNER/REPO`, env-driven auto-detection round-trips, `--token` routing to the active provider |
| `tests/unit/test_link_pagination.py` | NEW (or move existing `_next_page_url` / `_parse_rel_values` tests here from wherever they currently live in `test_gitlab_provider.py`) |

Coverage stays at 100% statement+branch.

## Open items for the implementation plan

These are plan-time decisions, not design-time:

1. **`_detect_provider_from_env()` placement.** Free function in `_settings.py` (simplest) vs `Settings` classmethod (more discoverable from the validator). Either works; pick at plan-time. Same for whether the validator mutates `self.provider` directly or returns a new instance — pydantic's `model_validator(mode="after")` supports both; `self.provider = ...` is cleaner for a single-field tweak.

2. **`_link_pagination.py` public-vs-underscore naming.** Spec drops the leading underscore on the public names (`next_page_url`, `same_origin`, `LINK_ENTRY_RE`) since the whole module is private. If the implementer prefers to keep them underscored (`_next_page_url`, `_same_origin`, `_LINK_ENTRY_RE`) for consistency with the originals in `gitlab.py`, that's acceptable — pick one convention and apply uniformly.

3. **CLI `--token` routing precise call order.** Spec sketches a two-pass overlay; the plan should confirm this works given `apply_cli_overlay`'s current implementation (which `model_validate`s the result, triggering `_resolve_provider`). If the order trips a chicken-and-egg with the validator, fall back to a one-pass overlay that requires the user to know `--gitlab-token` / `--github-token` (uglier; flag in the plan if needed).

4. **Test fixture sharing for GitHub vs GitLab integration tests.** The existing `_make_provider` helper in `test_gitlab_provider.py` is GitLab-specific. The plan can either (a) parameterize an existing helper, (b) create a parallel `_make_github_provider` helper, or (c) build a tiny shared factory in `tests/conftest.py` that both files use. (c) is cleanest if both sides converge; otherwise (b) is fine. Plan-time call.

5. **`tests/unit/test_link_pagination.py` — new file vs. moved tests.** The pagination helpers are tested today inside `tests/integration/test_gitlab_provider.py` (the `_next_page_url` / `_parse_rel_values` cases). Two options for the plan: (a) extract those existing test cases into `tests/unit/test_link_pagination.py` (cleaner — pagination is a utility, not a GitLab integration concern), or (b) leave them in `test_gitlab_provider.py` and skip the new test file. (a) is preferred but optional. The plan should call this explicitly.

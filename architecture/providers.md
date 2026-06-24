# Providers

A provider is the API adapter for one forge. It hides REST-vs-REST differences
behind a small, forge-neutral contract so the use-case can read commits and tags
and create a tag without knowing whether it is talking to GitLab or GitHub.
Two providers ship today.

## The contract

`semvertag/providers/_base.py` defines `Provider`, a `typing.Protocol`
(structural — providers are matched by shape, registered in the IoC container,
not by subclassing). The abstract operations:

- `name: str` — the provider id.
- `get_default_branch(self) -> str` — the repo's default branch name. Both
  concrete providers carry an optional `default_branch: str | None = None`
  (wired from `settings.default_branch` in `semvertag/ioc.py`): when set, this
  short-circuits to the override and the default-branch API call is skipped
  entirely; when `None`, the forge API is queried as before. The override is
  the seam where `--default-branch` / `SEMVERTAG_DEFAULT_BRANCH` lands — a
  blank value (empty or whitespace, e.g. a declared-but-empty env var in CI) is
  normalized to "unset" at the settings edge, falling back to the API.
- `get_latest_commit_on_default_branch(self) -> Commit` — head commit of that
  branch as a frozen `Commit` (`sha`, `message`).
- `list_tags(self) -> list[Tag]` — every tag as `Tag` (`name`, `commit_sha`).
- `create_tag(self, name: str, commit_sha: str) -> None` — create a tag
  pointing at a commit; side-effecting, returns nothing.

Both concrete providers are frozen, slotted, kw-only dataclasses holding their
forge config, a repo identifier, and an `httpware.Client`.

## GitLab

`semvertag/providers/gitlab.py` targets the GitLab v4 REST API under
`/api/v4/projects/{project_id}`:

- default branch — `GET /api/v4/projects/{id}`, reads `default_branch`; a null
  value raises `ConfigError`.
- latest commit — `GET .../repository/commits?ref_name={branch}&per_page=1`,
  takes element `[0]`; an empty list raises `ProviderAPIError`.
- tags — `GET .../repository/tags?per_page=100`, paginated (below).
- create — `POST .../repository/tags` with `{"tag_name": name, "ref":
  commit_sha}`.

Auth is the `PRIVATE-TOKEN` header, set once when the client is built in
`semvertag/ioc.py` (`_build_gitlab_client`) from `settings.gitlab.token`.

## GitHub

`semvertag/providers/github.py` targets the GitHub REST API under
`/repos/{owner}/{repo}`:

- default branch — `GET /repos/{repo}`, reads `default_branch` (null →
  `ConfigError`).
- latest commit — `GET /repos/{repo}/commits?sha={branch}&per_page=1`, element
  `[0]` (empty → `ProviderAPIError`); the message lives at `commit.message` in
  the GitHub payload shape.
- tags — `GET /repos/{repo}/tags?per_page=100`, paginated.
- create — `POST /repos/{repo}/git/refs` with `{"ref":
  "refs/tags/{name}", "sha": commit_sha}` (the git-refs endpoint, not a tags
  endpoint).

Auth and the GitHub-required headers are set when the client is built
(`_build_github_client`): `Authorization: Bearer <token>`, `Accept:
application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`.

## HTTP client

Every request goes through an `httpware.Client` constructed in
`semvertag/ioc.py`. The factories set `base_url` (from the provider's
`endpoint`), `timeout` (`settings.request_timeout`), the auth headers above, and
a single middleware: `httpware.Retry` over status codes
`{408, 429, 500, 502, 503, 504}`. Both clients are eagerly resolved by
modern-di, which is safe because httpx2 connection pools are lazy — the unused
client opens no sockets. Clients are closed by a modern-di cache finalizer
(`_close_client`). Responses are decoded by httpware against pydantic
`response_model`s (`_ProjectResponse`, `_CommitList`, `_TagList`, …) via the
`get` / `get_with_response` helpers; a decode failure surfaces as
`httpware.DecodeError` and is translated to `ProviderAPIError`.

Both clients also set a 1 MiB `max_error_body_bytes` cap (`_MAX_ERROR_BODY_BYTES`
in `semvertag/ioc.py`): httpware raises `ResponseTooLargeError` on a 4xx/5xx
whose declared `Content-Length` exceeds the cap, before reading the body — a
defensive bound against a hostile or malfunctioning endpoint. That error is an
`httpware.ClientError` (not a `StatusError`), so `_translate_transport` maps it
to `ProviderAPIError`. Real GitLab/GitHub error bodies are tiny JSON and never
approach the cap.

## Link-header pagination

Tag listing walks RFC 8288 `Link` headers. `semvertag/_link_pagination.py`
exposes `next_page_url(response, *, current_url)`, which parses the `Link`
header, finds the `rel="next"` entry, and resolves it against the current URL
(returning `None` when there is no next page). Both providers call it inside
`list_tags`: after each page they request the next URL until `next_page_url`
returns `None`, capped at `_MAX_TAG_PAGES = 100` (exceeding it raises
`ProviderAPIError`). Before following a next URL, `same_origin(next_url,
endpoint)` checks that scheme + netloc match the configured endpoint; a
cross-host `Link` is refused with `ProviderAPIError` so a malicious or
misconfigured server cannot redirect a token-bearing request to another host.

## Secret redaction

`semvertag/_redact.py` exposes `redact(text)`, which substitutes `***` for any
substring matching known token shapes — GitLab `glpat-…`, GitHub
`github_pat_…` / `ghp_` / `gho_` / `ghu_` / `ghs_` / `ghr_…`, Bitbucket
`ATBB…`, and any bare 32+-char hex run. It is applied at the output boundary:
`RichOutput` (`semvertag/_output.py`) runs `redact` on all three paths
(`progress`, `emit`, `error`). `JsonOutput` is more selective: `progress` is a
no-op (nothing is printed), `emit` writes the result envelope as raw JSON
without redaction, and only `error` passes its message through `redact` before
printing to stderr. A token that leaks into an error message never reaches the
terminal, but a token embedded in a result field would appear unredacted in JSON
output.

## Errors

`semvertag/_errors.py` defines the domain hierarchy, each carrying an
`exit_code` the CLI uses verbatim: `SemvertagError` (1, base), `ConfigError`
(2), `AuthError` (3), `ProviderAPIError` (4). `semvertag/providers/_errors.py`
translates raw `httpware.ClientError`s into these via `translate_gitlab` /
`translate_github`, which split into:

- status errors — 401/403 → `AuthError` (with forge-specific scope hints),
  404 → `ConfigError` (project/repo not found), 422 → `ConfigError`,
  429/5xx → `ProviderAPIError` (retries exhausted), other → `ProviderAPIError`.
- transport errors (shared `_translate_transport`) — `DecodeError`,
  `TimeoutError`, `RetryBudgetExhaustedError`, `NetworkError`, and a fallback
  all → `ProviderAPIError`.
- tag-creation specials — a 400 ("already exists", GitLab) or 422
  ("already_exists", GitHub) on create becomes a `ConfigError` naming the tag,
  distinguishing a concurrent/duplicate run from a malformed request.

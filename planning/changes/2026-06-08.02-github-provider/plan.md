# GitHub provider implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GitHubProvider` so `semvertag` works against `github.com` and GitHub Enterprise repos with the same CLI it works against GitLab today. After this lands the package description `"Auto-tag GitLab repos with semantic version tags"` becomes `"Auto-tag GitLab and GitHub repos with semantic version tags — one tool, two strategies, two providers."`

**Architecture:** The new `GitHubProvider` parallels `GitLabProvider` method-for-method, conforms to the existing `Provider` `typing.Protocol`, and reuses every cross-cutting piece (`httpware.Client` + `httpware.Retry` + `httpware.PydanticDecoder`, the operator-action error tree, Link-header pagination). `Settings.provider` gains an env-aware `@model_validator(mode="after")` that auto-detects from `GITHUB_ACTIONS` / `GITLAB_CI` and enforces the right repo identifier per provider. `ioc.py` adds a `current_provider` selector that mirrors the existing `current_strategy` selector. Refactors land first (pagination helpers + transport-translator extraction) so the new code can hang off them cleanly.

**Tech Stack:** Python 3.11+, `httpware[pydantic]>=0.8.2`, `pydantic 2.13+` (RootModel, model_validator), `pydantic-settings 2+` (env + alias chains), `typer` (CLI), `modern-di` (DI), `pytest` (test runner). Tests use `httpx2.MockTransport` injected via `httpware.Client(httpx2_client=...)`.

**Reference spec:** `planning/specs/2026-06-08-github-provider-design.md`

---

## File structure

**Create:**
- `semvertag/_link_pagination.py` — extracted from `providers/gitlab.py`. Public surface: `next_page_url(response, *, current_url) -> str | None`, `same_origin(url, endpoint) -> bool`, `LINK_ENTRY_RE` constant. Module-internal: `_parse_rel_values`.
- `semvertag/providers/github.py` — `GitHubProvider` class + four `pydantic.BaseModel` types (`_RepoResponse`, `_CommitItem` with nested `_CommitAuthor`, `_TagItem` with nested `_TagCommit`) + two `pydantic.RootModel` wrappers (`_CommitList`, `_TagList`) + domain constants (`_API_PREFIX = "/repos"`, `_TAGS_PER_PAGE = 100`, `_MAX_TAG_PAGES = 100`).
- `tests/unit/test_link_pagination.py` — extracted from `tests/integration/test_gitlab_provider.py` (the 6 tests at lines 572-592). Imports from `semvertag._link_pagination`.
- `tests/integration/test_github_provider.py` — full integration suite parallel to `test_gitlab_provider.py`. Uses `httpx2.MockTransport` with GitHub-shaped JSON.
- `docs/providers/github.md` — parallel to `docs/providers/gitlab.md`.

**Modify:**
- `semvertag/_settings.py` — add `Settings.provider`, `Settings.repo`, `GitHubConfig.endpoint`, `_detect_provider_from_env()` free function, `@model_validator(mode="after") _resolve_provider`.
- `semvertag/providers/_errors.py` — extract `_translate_transport(exc, *, provider_label: str)` shared by both translators; rewrite `_translate_gitlab_transport` callers to use it; add `translate_github(exc, *, repo)` and `translate_create_tag_github_unprocessable(exc, *, tag_name)`.
- `semvertag/providers/gitlab.py` — import pagination helpers from `_link_pagination` (drop in-module `_LINK_ENTRY_RE` / `_next_page_url` / `_parse_rel_values` / `_same_origin`).
- `semvertag/ioc.py` — add `_build_github_client` / `_build_github_provider` / `_close_github_provider` / `_build_current_provider`; add `github_client` / `github_provider` / `current_provider` factories in `ProvidersGroup`; switch `UseCasesGroup.semvertag_use_case` to reference `current_provider` instead of `gitlab_provider`.
- `semvertag/__main__.py` — add `--provider`, `--repo`, `--github-endpoint` flags; add `provider`/`repo`/`github_endpoint` to `_collect_overrides`; move `--token` handling out of `_collect_overrides` into a second-pass overlay applied after the active provider is resolved; refresh `MAIN_APP` help string.
- `tests/integration/test_gitlab_provider.py` — drop the 6 pagination tests at lines 572-592 (they move to `test_link_pagination.py`); drop the now-removed `_next_page_url` / `_parse_rel_values` imports.
- `tests/conftest.py` — add `GITHUB_ENDPOINT` / `GITHUB_TOKEN` / `GITHUB_REPO` constants + a shared `_make_github_provider(handler)` helper (or `_make_provider(handler, *, provider="gitlab")` parameterized helper — Task 5 picks).
- `tests/unit/test_settings.py` — add tests for `_resolve_provider` (env auto-detection rules, explicit override, both-set conflict, repo-identifier enforcement) + `GitHubConfig.endpoint` defaults.
- `tests/unit/test_providers_errors.py` — add ~15 tests for `translate_github` branches + tests for `translate_create_tag_github_unprocessable` + tests confirming `_translate_transport` produces identical-shape output for both labels.
- `tests/unit/test_ioc.py` — add tests for `current_provider` resolution under both `settings.provider` values.
- `tests/integration/test_cli_*.py` (specifically `test_cli_main_verb.py` and `test_cli_quiet_json_matrix.py`) — add smoke tests for `--provider github --repo OWNER/REPO`, env-driven auto-detection, and `--token` routing.
- `README.md` — hero string updated to mention GitHub; new "Use in GitHub Actions" section with the inline-job recipe.
- `pyproject.toml` — `description` updated; add `"github"` to `keywords`.

**No deletions of whole files.**

---

## Task 1: Extract `_link_pagination.py` (pure refactor)

Pagination helpers are used by GitLab today and will be used by GitHub in Task 5. Extracting them first is a pure refactor with no behavior change — green to green.

**Files:**
- Create: `semvertag/_link_pagination.py`
- Create: `tests/unit/test_link_pagination.py`
- Modify: `semvertag/providers/gitlab.py` (remove the pagination helpers + imports they use; import from new module)
- Modify: `tests/integration/test_gitlab_provider.py` (remove pagination tests + their imports)

- [ ] **Step 1: Create the new pagination module**

Create `semvertag/_link_pagination.py`:

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

Public symbols drop the leading underscore (`next_page_url` instead of `_next_page_url`, etc.) because the whole module is private. `_parse_rel_values` stays underscored — it's a module-internal helper.

- [ ] **Step 2: Move the 6 pagination tests to a new unit test file**

Create `tests/unit/test_link_pagination.py`. The 6 tests live today at `tests/integration/test_gitlab_provider.py:572-592`. Find them by their names:

- `test_next_page_url_skips_entries_with_empty_uri_reference`
- `test_next_page_url_returns_none_when_link_header_absent`
- `test_next_page_url_returns_none_when_only_non_next_rel_present`
- `test_parse_rel_values_returns_empty_set_when_no_rel_param_present`
- `test_parse_rel_values_skips_non_rel_params_before_finding_rel`
- (the 6th — find via `grep -n "_parse_rel_values\|_next_page_url" tests/integration/test_gitlab_provider.py` to identify all six in case the count differs)

Cut those test functions verbatim from `test_gitlab_provider.py`. Paste into `tests/unit/test_link_pagination.py`. Update imports at the top:

```python
import httpx2

from semvertag._link_pagination import next_page_url, _parse_rel_values
```

(Drop `_` prefix in calls: replace `_next_page_url(` → `next_page_url(`. Keep `_parse_rel_values(` since it stays underscored.)

The tests also reference `GITLAB_ENDPOINT` and `_TAGS_PATH` from `test_gitlab_provider.py`. These are URL strings used as `current_url=` arguments — replace with literal strings in the test file (e.g., `current_url="https://gitlab.example.test/api/v4/projects/999/repository/tags"`). The tests are about pagination semantics, not GitLab specifically.

- [ ] **Step 3: Remove the pagination helpers from `gitlab.py`**

In `semvertag/providers/gitlab.py`, delete:
- `import re` (no longer needed once the regex moves out)
- `import urllib.parse` (no longer needed if all uses moved)
- The `_LINK_ENTRY_RE` constant
- `def _next_page_url(...)` and its body
- `def _parse_rel_values(...)` and its body
- `def _same_origin(...)` and its body

Add at the top:

```python
from semvertag import _link_pagination
```

In `list_tags`, replace:
- `_next_page_url(response, current_url=str(response.request.url))` → `_link_pagination.next_page_url(response, current_url=str(response.request.url))`
- `_same_origin(next_url, self.config.endpoint)` → `_link_pagination.same_origin(next_url, self.config.endpoint)`

- [ ] **Step 4: Remove pagination test imports from `test_gitlab_provider.py`**

In `tests/integration/test_gitlab_provider.py`, drop these names from the `from semvertag.providers.gitlab import` line:

```python
from semvertag.providers.gitlab import (
    GitLabProvider,
    # _next_page_url,   ← remove
    # _parse_rel_values,  ← remove
)
```

Leave `GitLabProvider`.

If `re` or `urllib.parse` are still imported in `test_gitlab_provider.py` and unused, drop them (ruff will flag).

- [ ] **Step 5: Run pagination tests in their new location**

Run: `uv run pytest tests/unit/test_link_pagination.py -v`
Expected: 6 tests pass.

- [ ] **Step 6: Run integration tests to confirm the gitlab side still works**

Run: `uv run pytest tests/integration/test_gitlab_provider.py -v 2>&1 | tail -5`
Expected: all GitLab integration tests pass (the 6 pagination tests are no longer in this file). Count drops by 6 from previous baseline.

- [ ] **Step 7: Full suite + coverage + lint**

Run: `just test && just lint-ci`
Expected: 333 tests pass (same total — moved, not removed), 100% coverage, lint clean.

- [ ] **Step 8: Commit**

```bash
git add semvertag/_link_pagination.py semvertag/providers/gitlab.py tests/unit/test_link_pagination.py tests/integration/test_gitlab_provider.py
git commit -m "refactor: extract Link-header pagination to _link_pagination module"
```

---

## Task 2: Extract `_translate_transport` helper in `_errors.py` (pure refactor)

`translate_gitlab` currently delegates transport-side errors to `_translate_gitlab_transport`. The new `translate_github` (Task 4) will need the same transport-side branches with one parameter change (provider label string). Extracting now keeps both translators thin.

**Files:**
- Modify: `semvertag/providers/_errors.py`

- [ ] **Step 1: Replace `_translate_gitlab_transport` with parameterized `_translate_transport`**

In `semvertag/providers/_errors.py`, find `_translate_gitlab_transport`:

```python
def _translate_gitlab_transport(exc: httpware.ClientError) -> Exception:
    if isinstance(exc, httpware.DecodeError):
        return ProviderAPIError(f"GitLab {exc.model.__name__} response could not be decoded: {exc.original}")
    if isinstance(exc, httpware.TimeoutError):
        return ProviderAPIError("GitLab request timed out. Try again or increase SEMVERTAG_REQUEST_TIMEOUT.")
    if isinstance(exc, httpware.RetryBudgetExhaustedError):
        return ProviderAPIError(f"GitLab retries exhausted after {exc.attempts} attempts. Try again later.")
    if isinstance(exc, httpware.NetworkError):
        return ProviderAPIError("GitLab unreachable. Check network connectivity.")
    return ProviderAPIError(f"GitLab request failed: {type(exc).__name__}")
```

Replace with:

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

- [ ] **Step 2: Update `translate_gitlab` to call the parameterized helper**

In the same file, find the `translate_gitlab` dispatcher:

```python
def translate_gitlab(exc: httpware.ClientError, *, project_id: int) -> Exception:
    ...
    if isinstance(exc, httpware.StatusError):
        return _translate_gitlab_status(exc, project_id=project_id)
    return _translate_gitlab_transport(exc)
```

Replace the last line with:

```python
    return _translate_transport(exc, provider_label="GitLab")
```

- [ ] **Step 3: Run existing translator tests to confirm no behavior change**

Run: `uv run pytest tests/unit/test_providers_errors.py -v`
Expected: all 16 tests pass with identical output. The parameterization only varies the label string; "GitLab request timed out..." remains identical to before.

- [ ] **Step 4: Full suite + lint**

Run: `just test && just lint-ci`
Expected: 333 tests pass, 100% coverage, lint clean.

- [ ] **Step 5: Commit**

```bash
git add semvertag/providers/_errors.py
git commit -m "refactor(providers/_errors): extract _translate_transport(exc, *, provider_label)"
```

---

## Task 3: Settings — add `provider`, `repo`, `GitHubConfig.endpoint`, validator (TDD)

Settings layer is foundational — every later task depends on `Settings.provider` resolving correctly. TDD-style: write tests for every rule, then implement.

**Files:**
- Modify: `semvertag/_settings.py`
- Modify: `tests/unit/test_settings.py`

- [ ] **Step 1: Write failing tests for `_detect_provider_from_env` + `_resolve_provider`**

Append to `tests/unit/test_settings.py` (find the appropriate spot — top-level test functions):

```python
import pytest

from semvertag._errors import ConfigError
from semvertag._settings import Settings


def test_provider_defaults_to_gitlab_when_no_ci_env_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    monkeypatch.delenv("SEMVERTAG_PROVIDER", raising=False)
    monkeypatch.delenv("PROVIDER", raising=False)
    settings = Settings(project_id=999)
    assert settings.provider == "gitlab"


def test_provider_detects_github_from_github_actions_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITLAB_CI", raising=False)
    monkeypatch.delenv("SEMVERTAG_PROVIDER", raising=False)
    settings = Settings(repo="owner/repo")
    assert settings.provider == "github"


def test_provider_detects_gitlab_from_gitlab_ci_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.delenv("SEMVERTAG_PROVIDER", raising=False)
    settings = Settings(project_id=999)
    assert settings.provider == "gitlab"


def test_provider_raises_when_both_ci_envs_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.delenv("SEMVERTAG_PROVIDER", raising=False)
    with pytest.raises(Exception, match="ambiguous"):
        Settings(project_id=999, repo="owner/repo")


def test_explicit_provider_overrides_auto_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")  # auto-detect says "github"
    monkeypatch.setenv("GITLAB_CI", "true")  # would be ambiguous
    settings = Settings(provider="gitlab", project_id=999)  # explicit wins
    assert settings.provider == "gitlab"


def test_provider_github_requires_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    with pytest.raises(Exception, match="provider=github requires .*repo"):
        Settings(provider="github")  # no repo


def test_provider_gitlab_requires_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    with pytest.raises(Exception, match="provider=gitlab requires .*project_id"):
        Settings(provider="gitlab")  # no project_id


def test_github_config_endpoint_defaults_to_api_github_com() -> None:
    settings = Settings(provider="github", repo="owner/repo")
    assert settings.github.endpoint == "https://api.github.com"


def test_github_config_endpoint_overridable_for_enterprise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMVERTAG_GITHUB__ENDPOINT", "https://github.acme.com/api/v3")
    settings = Settings(provider="github", repo="owner/repo")
    assert settings.github.endpoint == "https://github.acme.com/api/v3"


def test_repo_alias_picks_up_github_repository_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "octocat/Hello-World")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    settings = Settings()
    assert settings.repo == "octocat/Hello-World"
    assert settings.provider == "github"
```

If `tests/unit/test_settings.py` doesn't exist yet, create it with `import pytest` at the top and the test functions above.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_settings.py -v 2>&1 | tail -20`
Expected: tests fail with various errors — `Settings.provider` doesn't exist as a field; `Settings.repo` doesn't exist; the validator hasn't been added; `GitHubConfig` lacks `endpoint`. Read the failures to confirm they're all "missing implementation" not "wrong test setup".

- [ ] **Step 3: Implement the Settings changes**

Edit `semvertag/_settings.py`. Add `os` import at the top with the other stdlib imports:

```python
import logging
import os
import typing
```

In `GitHubConfig`, add `endpoint`:

```python
class GitHubConfig(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="SEMVERTAG_GITHUB__",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    endpoint: str = "https://api.github.com"   # NEW
    token: pydantic.SecretStr = pydantic.Field(
        default=pydantic.SecretStr(""),
        validation_alias=pydantic.AliasChoices(
            "SEMVERTAG_GITHUB__TOKEN",
            "SEMVERTAG_TOKEN",
            "GITHUB_TOKEN",
        ),
    )
```

Add the env-detection helper above the `Settings` class:

```python
def _detect_provider_from_env() -> typing.Literal["gitlab", "github"]:
    github_ci = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    gitlab_ci = os.environ.get("GITLAB_CI", "").lower() == "true"
    if github_ci and gitlab_ci:
        msg = (
            "Ambiguous CI context: both GITHUB_ACTIONS and GITLAB_CI are set. "
            "Pass --provider github|gitlab or set SEMVERTAG_PROVIDER to disambiguate."
        )
        raise ValueError(msg)
    if github_ci:
        return "github"
    return "gitlab"
```

In `Settings`, add the new fields and the validator:

```python
class Settings(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix=_ENV_PREFIX,
        env_nested_delimiter=_ENV_NESTED_DELIMITER,
        case_sensitive=False,
        extra="ignore",
    )

    strategy: typing.Literal["branch-prefix", "conventional-commits"] = "branch-prefix"
    provider: typing.Literal["gitlab", "github"] | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("SEMVERTAG_PROVIDER", "PROVIDER"),
    )
    default_branch: str | None = None
    request_timeout: float = pydantic.Field(default=8.0, gt=0)
    project_id: int | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("SEMVERTAG_PROJECT_ID", "CI_PROJECT_ID"),
    )
    repo: str | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("SEMVERTAG_REPO", "GITHUB_REPOSITORY"),
    )
    gitlab: GitLabConfig = pydantic.Field(default_factory=GitLabConfig)
    github: GitHubConfig = pydantic.Field(default_factory=GitHubConfig)
    branch_prefix: BranchPrefixConfig = pydantic.Field(default_factory=BranchPrefixConfig)
    conventional_commits: ConventionalCommitsConfig = pydantic.Field(default_factory=ConventionalCommitsConfig)

    @pydantic.field_validator("request_timeout")
    @classmethod
    def _clamp_request_timeout(cls, value: float) -> float:
        if value > _REQUEST_TIMEOUT_CEILING:
            _logger.warning(
                "request_timeout=%.3f exceeds ceiling %.1f; clamping to %.1f",
                value,
                _REQUEST_TIMEOUT_CEILING,
                _REQUEST_TIMEOUT_CEILING,
            )
            return _REQUEST_TIMEOUT_CEILING
        return value

    @pydantic.model_validator(mode="after")
    def _resolve_provider(self) -> "Settings":
        if self.provider is None:
            self.provider = _detect_provider_from_env()
        if self.provider == "github" and not self.repo:
            msg = "provider=github requires `repo` (set GITHUB_REPOSITORY or pass --repo OWNER/REPO)"
            raise ValueError(msg)
        if self.provider == "gitlab" and self.project_id is None:
            msg = "provider=gitlab requires `project_id` (set CI_PROJECT_ID or pass --project-id N)"
            raise ValueError(msg)
        return self
```

The validator mutates `self.provider` in place — this is safe inside a `model_validator(mode="after")` because the model instance is fully constructed by that point. Pydantic accepts the return.

- [ ] **Step 4: Run the new settings tests**

Run: `uv run pytest tests/unit/test_settings.py -v 2>&1 | tail -20`
Expected: all 10 new tests pass.

- [ ] **Step 5: Run the full suite — settings change cascades**

Run: `just test 2>&1 | tail -15`
Expected: existing tests that build `Settings(project_id=N)` still pass (they implicitly default `provider` to `"gitlab"` via the validator and `project_id` is satisfied). Existing tests that build `Settings()` with no args may now fail because the validator requires either `project_id` or `repo` once `provider` resolves. If that happens, the failing tests are in `tests/unit/test_ioc.py` (`_settings` fixture passes `project_id=999`, fine) and the integration CLI tests. Cross-check each failure.

Most likely failure points to investigate:
- `tests/integration/test_cli_*.py` — CLI tests construct `Settings` via the `_main_callback` flow which goes through `apply_cli_overlay`. If they set up the env without `project_id` / `repo`, they'll fail. Fix: set `CI_PROJECT_ID` or `SEMVERTAG_PROJECT_ID` in test fixtures, or pass `--project-id`.

For each failing test, the fix is to add a `project_id` (when testing GitLab paths) or `repo` (when testing GitHub paths). DO NOT loosen the validator to make tests pass — that would defeat the purpose.

- [ ] **Step 6: Fix any cascading test failures**

Walk each failure individually. The fix is always one of:
- Add `project_id=999` to a `Settings(...)` call
- Set `monkeypatch.setenv("CI_PROJECT_ID", "999")` in a fixture
- Set `monkeypatch.delenv("GITHUB_ACTIONS", raising=False)` + `monkeypatch.delenv("GITLAB_CI", raising=False)` to nail the default-provider state

Re-run after each fix.

- [ ] **Step 7: Lint**

Run: `just lint-ci`
Expected: clean. (The validator's `# noqa` may be needed if ruff flags self-mutation; usually not.)

- [ ] **Step 8: Commit**

```bash
git add semvertag/_settings.py tests/unit/test_settings.py
git commit -m "settings: add provider/repo fields + env-aware _resolve_provider validator"
```

If you fixed cascading tests in Step 6, include those files in the same commit (the fixes are entirely defensive and not worth their own commit).

---

## Task 4: Add `translate_github` + `translate_create_tag_github_unprocessable` (TDD)

Translator additions. No production caller yet — `GitHubProvider` arrives in Task 5. TDD here so the translator is fully exercised before being used.

**Files:**
- Modify: `semvertag/providers/_errors.py`
- Modify: `tests/unit/test_providers_errors.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_providers_errors.py`. Reuse the existing `_response()` and `_status_error()` helpers (no need to redefine).

```python
from semvertag.providers._errors import translate_create_tag_github_unprocessable, translate_github


_REPO = "octocat/Hello-World"


# translate_github — status errors

def test_translate_github_401_becomes_auth_error_with_token_guidance() -> None:
    result = translate_github(_status_error(httpware.UnauthorizedError, 401), repo=_REPO)
    assert isinstance(result, AuthError)
    assert "Token rejected" in str(result)
    assert "SEMVERTAG_TOKEN" in str(result)


def test_translate_github_403_becomes_auth_error_with_scope_guidance() -> None:
    result = translate_github(_status_error(httpware.ForbiddenError, 403), repo=_REPO)
    assert isinstance(result, AuthError)
    assert "403" in str(result)
    assert "contents: write" in str(result) or "public_repo" in str(result) or "repo" in str(result)


def test_translate_github_404_becomes_config_error_with_repo() -> None:
    result = translate_github(_status_error(httpware.NotFoundError, 404), repo=_REPO)
    assert isinstance(result, ConfigError)
    assert f"repo='{_REPO}'" in str(result)


def test_translate_github_422_becomes_config_error() -> None:
    result = translate_github(_status_error(httpware.UnprocessableEntityError, 422), repo=_REPO)
    assert isinstance(result, ConfigError)
    assert "422" in str(result)


def test_translate_github_429_becomes_provider_api_error() -> None:
    result = translate_github(_status_error(httpware.RateLimitedError, 429), repo=_REPO)
    assert isinstance(result, ProviderAPIError)
    assert "rate limit" in str(result).lower()


def test_translate_github_500_becomes_provider_api_error_with_status_page() -> None:
    result = translate_github(_status_error(httpware.InternalServerError, 500), repo=_REPO)
    assert isinstance(result, ProviderAPIError)
    assert "500" in str(result)
    assert "githubstatus.com" in str(result)


def test_translate_github_503_becomes_provider_api_error() -> None:
    result = translate_github(_status_error(httpware.ServiceUnavailableError, 503), repo=_REPO)
    assert isinstance(result, ProviderAPIError)


def test_translate_github_unknown_4xx_falls_back_to_provider_api_error() -> None:
    result = translate_github(_status_error(httpware.ClientStatusError, 418), repo=_REPO)
    assert isinstance(result, ProviderAPIError)
    assert "418" in str(result)


# translate_github — transport errors (via shared _translate_transport)

def test_translate_github_timeout_becomes_provider_api_error() -> None:
    exc = httpware.TimeoutError("read timed out")
    result = translate_github(exc, repo=_REPO)
    assert isinstance(result, ProviderAPIError)
    assert "GitHub request timed out" in str(result)


def test_translate_github_network_error_becomes_provider_api_error() -> None:
    exc = httpware.NetworkError("connection refused")
    result = translate_github(exc, repo=_REPO)
    assert isinstance(result, ProviderAPIError)
    assert "GitHub unreachable" in str(result)


def test_translate_github_retry_budget_exhausted_becomes_provider_api_error() -> None:
    exc = httpware.RetryBudgetExhaustedError(last_response=None, last_exception=None, attempts=3)
    result = translate_github(exc, repo=_REPO)
    assert isinstance(result, ProviderAPIError)
    assert "GitHub retries exhausted" in str(result)


def test_translate_github_decode_error_becomes_provider_api_error() -> None:
    underlying = ValueError("invalid")
    exc = httpware.DecodeError(
        response=_response(200, body=b"null"),
        model=type("FakeModel", (), {}),
        original=underlying,
    )
    result = translate_github(exc, repo=_REPO)
    assert isinstance(result, ProviderAPIError)
    assert "GitHub FakeModel response could not be decoded" in str(result)


def test_translate_github_unknown_client_error_falls_back_to_provider_api_error() -> None:
    exc = httpware.ClientError("unknown")
    result = translate_github(exc, repo=_REPO)
    assert isinstance(result, ProviderAPIError)
    assert "GitHub request failed" in str(result)


# translate_create_tag_github_unprocessable

def test_translate_create_tag_github_already_exists_structured_becomes_config_error() -> None:
    exc = _status_error(
        httpware.UnprocessableEntityError,
        422,
        body=b'{"message":"Reference already exists","errors":[{"resource":"Reference","code":"already_exists"}]}',
    )
    result = translate_create_tag_github_unprocessable(exc, tag_name="v1.2.3")
    assert isinstance(result, ConfigError)
    assert "v1.2.3" in str(result)
    assert "already exists" in str(result).lower()


def test_translate_create_tag_github_already_exists_message_only_becomes_config_error() -> None:
    # Safety-net match on the human-readable message even if structured code is absent.
    exc = _status_error(httpware.UnprocessableEntityError, 422, body=b'{"message":"Reference already exists"}')
    result = translate_create_tag_github_unprocessable(exc, tag_name="v1.2.3")
    assert isinstance(result, ConfigError)
    assert "already exists" in str(result).lower()


def test_translate_create_tag_github_other_422_becomes_generic_config_error() -> None:
    exc = _status_error(httpware.UnprocessableEntityError, 422, body=b'{"message":"Invalid ref format"}')
    result = translate_create_tag_github_unprocessable(exc, tag_name="v1.2.3")
    assert isinstance(result, ConfigError)
    assert "v1.2.3" not in str(result)
    assert "422" in str(result)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_providers_errors.py -v 2>&1 | tail -10`
Expected: 16 failures (one per new test) — `ImportError` on `translate_github` / `translate_create_tag_github_unprocessable`.

- [ ] **Step 3: Add the translator functions**

In `semvertag/providers/_errors.py`, append after `translate_gitlab` and `translate_create_tag_bad_request`:

```python
def translate_github(exc: httpware.ClientError, *, repo: str) -> Exception:
    """Translate an httpware ClientError into the semvertag domain error for GitHub.

    Mirrors translate_gitlab's dispatch order; status branches carry GitHub-specific
    actionable hints. Transport branches (DecodeError, TimeoutError, RetryBudget,
    NetworkError, fallback) delegate to the shared _translate_transport.
    """
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


def translate_create_tag_github_unprocessable(
    exc: httpware.UnprocessableEntityError, *, tag_name: str
) -> Exception:
    """create_tag's 422 has an 'already_exists' special case; everything else is a generic 422."""
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

If ruff flags `translate_github` for `PLR0911` (too many returns, max 6) or `C901` (complexity), follow the same pattern that exists for `translate_gitlab` (split into `_translate_github_status` + delegation). The existing `_translate_gitlab_status` extraction is the precedent; mirror it. If it doesn't trip the limit, keep flat for readability — easier to scan.

- [ ] **Step 4: Run the new tests**

Run: `uv run pytest tests/unit/test_providers_errors.py -v 2>&1 | tail -10`
Expected: all 16 new tests pass; the original 16 (translate_gitlab side) still pass. Total in this file: 32 tests.

- [ ] **Step 5: Full suite + lint**

Run: `just test && just lint-ci`
Expected: 349 tests pass (was 333; +16 new), 100% coverage, lint clean.

- [ ] **Step 6: Commit**

```bash
git add semvertag/providers/_errors.py tests/unit/test_providers_errors.py
git commit -m "providers/_errors: add translate_github + translate_create_tag_github_unprocessable"
```

---

## Task 5: Create `GitHubProvider` + integration test suite

The biggest task. `GitHubProvider` parallels `GitLabProvider`; the integration tests parallel `test_gitlab_provider.py`. By the end of this task the provider works in isolation, but isn't wired through DI yet (that's Task 6).

**Files:**
- Create: `semvertag/providers/github.py`
- Create: `tests/integration/test_github_provider.py`
- Modify: `tests/conftest.py` (add GitHub constants + a `_make_github_provider` helper)

- [ ] **Step 1: Add GitHub constants + helper to `tests/conftest.py`**

In `tests/conftest.py`, add near the existing `GITLAB_*` constants:

```python
GITHUB_ENDPOINT: typing.Final = "https://api.github.test"
GITHUB_TOKEN: typing.Final = "ghp_XXXXXXXXXXXXXXXXXXXX"
GITHUB_REPO: typing.Final = "owner/repo"
```

A `_make_github_provider` helper isn't strictly required at conftest scope (the integration test file can define its own — same pattern as `_make_provider` in `test_gitlab_provider.py`). Skip the conftest helper for now; revisit if a second file needs it.

- [ ] **Step 2: Create the provider module**

Create `semvertag/providers/github.py`:

```python
import dataclasses
import typing

import httpware
import httpx2  # noqa: F401 — typing reference in pagination call site
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
    commit: _CommitAuthor


class _TagCommit(pydantic.BaseModel):
    sha: str


class _TagItem(pydantic.BaseModel):
    name: str
    commit: _TagCommit


class _CommitList(pydantic.RootModel[list[_CommitItem]]):
    pass


class _TagList(pydantic.RootModel[list[_TagItem]]):
    pass


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class GitHubProvider:
    name: typing.ClassVar[str] = "github"
    config: GitHubConfig
    repo: str
    http: httpware.Client

    def get_default_branch(self) -> str:
        try:
            repo_info = self.http.get(
                f"{_API_PREFIX}/{self.repo}",
                response_model=_RepoResponse,
            )
        except httpware.ClientError as exc:
            raise _errors.translate_github(exc, repo=self.repo) from exc
        if not repo_info.default_branch:
            msg = "Default branch missing from GitHub response. Verify the repo has a default branch."
            raise ConfigError(msg)
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
            msg = f"No commits on default branch '{default_branch}'. The branch appears empty."
            raise ProviderAPIError(msg)
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
                msg = (
                    "GitHub pagination Link header points to a different host than SEMVERTAG_GITHUB__ENDPOINT. "
                    "Refusing to follow to protect credentials."
                )
                raise ProviderAPIError(msg)
            url, params = next_url, None
        msg = (
            f"Tag pagination exceeded {_MAX_TAG_PAGES} pages. "
            "The repo has an unexpected number of tags; please file an issue."
        )
        raise ProviderAPIError(msg)

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

Drop the `import httpx2` line if ruff flags it unused — pagination call sites use `response.request.url` via the response object passed in, not via direct `httpx2.X` references.

- [ ] **Step 3: Create the integration test file**

Create `tests/integration/test_github_provider.py`. Use `test_gitlab_provider.py` as a structural reference. Below is the **minimum viable set** of tests — happy path for each method + error translation + pagination. The implementer should expand coverage as needed to hit 100% on `github.py`; the existing `test_gitlab_provider.py` has ~50 tests and the GitHub counterpart will be similar in scale.

Start with this skeleton:

```python
import typing

import httpx2
import pydantic
import pytest

import httpware

from semvertag._errors import AuthError, ConfigError, ProviderAPIError
from semvertag._settings import GitHubConfig
from semvertag._types import Commit, Tag
from semvertag.providers._base import Provider
from semvertag.providers.github import GitHubProvider
from tests.conftest import (
    GITHUB_ENDPOINT,
    GITHUB_REPO,
    GITHUB_TOKEN,
    HandlerCallable,
    compose_handler,
    default_handler,
)


_REPO_PATH: typing.Final = f"/repos/{GITHUB_REPO}"
_COMMITS_PATH: typing.Final = f"{_REPO_PATH}/commits"
_TAGS_PATH: typing.Final = f"{_REPO_PATH}/tags"
_REFS_PATH: typing.Final = f"{_REPO_PATH}/git/refs"
_DEFAULT_BRANCH: typing.Final = "main"
_DEFAULT_COMMIT_SHA: typing.Final = "abc1234"
_DEFAULT_COMMIT_MESSAGE: typing.Final = "default test commit"
_BEARER_HEADER: typing.Final = "Authorization"


def _github_default_handler(request: httpx2.Request) -> httpx2.Response:
    method = request.method
    path = request.url.path
    if method == "GET" and path == _REPO_PATH:
        return httpx2.Response(200, json={"default_branch": _DEFAULT_BRANCH})
    if method == "GET" and path == _COMMITS_PATH:
        return httpx2.Response(200, json=[
            {"sha": _DEFAULT_COMMIT_SHA, "commit": {"message": _DEFAULT_COMMIT_MESSAGE}}
        ])
    if method == "GET" and path == _TAGS_PATH:
        return httpx2.Response(200, json=[
            {"name": "v0.1.0", "commit": {"sha": "old1234"}},
            {"name": "v0.2.0", "commit": {"sha": "new1234"}},
        ])
    if method == "POST" and path == _REFS_PATH:
        return httpx2.Response(201, json={"ref": "refs/tags/v1.0.0", "object": {"sha": _DEFAULT_COMMIT_SHA}})
    return httpx2.Response(404, json={"message": "Not Found"})


def _make_provider(handler: HandlerCallable) -> tuple[GitHubProvider, httpx2.Client]:
    transport = httpx2.MockTransport(handler)
    config = GitHubConfig(endpoint=GITHUB_ENDPOINT, token=pydantic.SecretStr(GITHUB_TOKEN))
    inner = httpx2.Client(
        transport=transport,
        base_url=GITHUB_ENDPOINT,
        headers={
            _BEARER_HEADER: f"Bearer {config.token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    client = httpware.Client(httpx2_client=inner)
    provider = GitHubProvider(config=config, repo=GITHUB_REPO, http=client)
    # Return the inner httpx2.Client so tests can use it as a context manager
    # for teardown; httpware.Client doesn't own its lifecycle when constructed via httpx2_client=.
    return provider, inner


# Protocol conformance

def test_github_provider_satisfies_provider_protocol() -> None:
    provider, _client = _make_provider(_github_default_handler)
    assert isinstance(provider, Provider)


# Happy paths

def test_get_default_branch_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, client = _make_provider(_github_default_handler)
    with client:
        assert provider.get_default_branch() == _DEFAULT_BRANCH


def test_get_latest_commit_returns_head(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, client = _make_provider(_github_default_handler)
    with client:
        commit = provider.get_latest_commit_on_default_branch()
    assert commit == Commit(sha=_DEFAULT_COMMIT_SHA, message=_DEFAULT_COMMIT_MESSAGE)


def test_list_tags_returns_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, client = _make_provider(_github_default_handler)
    with client:
        tags = provider.list_tags()
    assert tags == [
        Tag(name="v0.1.0", commit_sha="old1234"),
        Tag(name="v0.2.0", commit_sha="new1234"),
    ]


def test_create_tag_succeeds_on_201(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, client = _make_provider(_github_default_handler)
    with client:
        provider.create_tag("v1.0.0", _DEFAULT_COMMIT_SHA)  # raises on failure; nothing to assert


# Status-error translation paths

def test_get_default_branch_raises_auth_error_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    overrides = {("GET", _REPO_PATH): httpx2.Response(401, json={"message": "Bad credentials"})}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(AuthError, match="Token rejected"):
        provider.get_default_branch()


def test_get_default_branch_raises_auth_error_on_403(monkeypatch: pytest.MonkeyPatch) -> None:
    overrides = {("GET", _REPO_PATH): httpx2.Response(403, json={"message": "Forbidden"})}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(AuthError, match="403"):
        provider.get_default_branch()


def test_get_default_branch_raises_config_error_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    overrides = {("GET", _REPO_PATH): httpx2.Response(404, json={"message": "Not Found"})}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ConfigError, match=f"repo='{GITHUB_REPO}'"):
        provider.get_default_branch()


def test_get_default_branch_raises_config_error_when_default_branch_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    overrides = {("GET", _REPO_PATH): httpx2.Response(200, json={"default_branch": None})}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ConfigError, match="Default branch missing"):
        provider.get_default_branch()


# create_tag — already-exists 422

def test_create_tag_already_exists_structured_becomes_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    overrides = {
        ("POST", _REFS_PATH): httpx2.Response(
            422,
            json={
                "message": "Reference already exists",
                "errors": [{"resource": "Reference", "code": "already_exists"}],
            },
        )
    }
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ConfigError, match="Tag already exists.*v1.0.0"):
        provider.create_tag("v1.0.0", _DEFAULT_COMMIT_SHA)


def test_create_tag_other_422_becomes_generic_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    overrides = {("POST", _REFS_PATH): httpx2.Response(422, json={"message": "Invalid ref format"})}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ConfigError, match="422"):
        provider.create_tag("invalid name", _DEFAULT_COMMIT_SHA)


# Pagination

def test_list_tags_follows_link_header_next(monkeypatch: pytest.MonkeyPatch) -> None:
    page1_url = f"{GITHUB_ENDPOINT}{_TAGS_PATH}?per_page=100&page=2"

    def handler(request: httpx2.Request) -> httpx2.Response:
        page = request.url.params.get("page", "1")
        if request.method == "GET" and request.url.path == _TAGS_PATH and page == "1":
            return httpx2.Response(
                200,
                json=[{"name": "v0.1.0", "commit": {"sha": "old1234"}}],
                headers={"link": f'<{page1_url}>; rel="next"'},
            )
        if request.method == "GET" and request.url.path == _TAGS_PATH and page == "2":
            return httpx2.Response(200, json=[{"name": "v0.2.0", "commit": {"sha": "new1234"}}])
        return httpx2.Response(404)

    provider, client = _make_provider(handler)
    with client:
        tags = provider.list_tags()
    assert tags == [
        Tag(name="v0.1.0", commit_sha="old1234"),
        Tag(name="v0.2.0", commit_sha="new1234"),
    ]


def test_list_tags_refuses_cross_origin_next_link(monkeypatch: pytest.MonkeyPatch) -> None:
    evil_url = "https://evil.test/repos/owner/repo/tags?page=2"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json=[{"name": "v0.1.0", "commit": {"sha": "old1234"}}],
            headers={"link": f'<{evil_url}>; rel="next"'},
        )

    provider, client = _make_provider(handler)
    with client, pytest.raises(ProviderAPIError, match="different host"):
        provider.list_tags()


# Decoder-failure path

def test_get_default_branch_raises_provider_api_error_on_malformed_body(monkeypatch: pytest.MonkeyPatch) -> None:
    overrides = {("GET", _REPO_PATH): httpx2.Response(200, text="not json at all")}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_RepoResponse response could not be decoded"):
        provider.get_default_branch()
```

If `tests.conftest` doesn't already export `compose_handler` and `default_handler` (it does — `test_gitlab_provider.py` uses them), the imports above just work. If `compose_handler`'s signature doesn't match the pattern above, read the existing `tests/conftest.py` and adjust accordingly.

This skeleton has ~14 tests. Run them and check coverage; add more (e.g., 429, 5xx, NetworkError via raising handler, RetryBudget) until `semvertag/providers/github.py` reaches 100% statement + branch.

- [ ] **Step 4: Run the integration tests**

Run: `uv run pytest tests/integration/test_github_provider.py -v 2>&1 | tail -25`
Expected: most tests pass. Any failures: read the actual error, fix either the handler shape (JSON body mismatch) or the test expectation. The provider code is the spec's source of truth; the test should match it.

- [ ] **Step 5: Full suite + coverage**

Run: `just test 2>&1 | tail -5`
Expected: ~363 tests pass (was 349; +14 from GitHub integration tests), 100% coverage **on existing modules**. The new `semvertag/providers/github.py` will have 100% coverage if the integration tests exercise every branch — verify in the `Cover` column of the report. Add tests as needed for any uncovered lines.

- [ ] **Step 6: Lint**

Run: `just lint-ci`
Expected: clean. If ruff flags `httpx2` import in `github.py` as unused, remove it (the type reference in the helper signature uses the response object directly).

- [ ] **Step 7: Commit**

```bash
git add semvertag/providers/github.py tests/conftest.py tests/integration/test_github_provider.py
git commit -m "providers/github: add GitHubProvider with integration test suite"
```

---

## Task 6: Wire `current_provider` in ioc.py + update CLI, docs, README, pyproject

The provider class works in isolation. This task plumbs it into the DI container, the CLI, the docs, and the public-facing project metadata.

**Files:**
- Modify: `semvertag/ioc.py`
- Modify: `semvertag/__main__.py`
- Modify: `tests/unit/test_ioc.py`
- Modify: `tests/integration/test_cli_main_verb.py` (and possibly `test_cli_quiet_json_matrix.py`)
- Create: `docs/providers/github.md`
- Modify: `README.md`
- Modify: `pyproject.toml`

- [ ] **Step 1: Rewrite `semvertag/ioc.py`**

Replace the entire file contents with:

```python
import typing

import httpware
import modern_di
from modern_di import Scope, providers

from semvertag._errors import ConfigError
from semvertag._settings import Settings
from semvertag._use_case import SemvertagUseCase
from semvertag.providers._base import Provider
from semvertag.providers.github import GitHubProvider
from semvertag.providers.gitlab import GitLabProvider
from semvertag.strategies._base import BumpStrategy
from semvertag.strategies.branch_prefix import BranchPrefixStrategy
from semvertag.strategies.conventional_commits import ConventionalCommitsStrategy


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
    if settings.project_id is None:
        msg = "Project id missing. Set CI_PROJECT_ID or pass --project-id."
        raise ConfigError(msg)
    return GitLabProvider(config=settings.gitlab, project_id=settings.project_id, http=client)


def _build_github_provider(settings: Settings, client: httpware.Client) -> GitHubProvider:
    if settings.repo is None:
        msg = "Repo missing. Set GITHUB_REPOSITORY or pass --repo OWNER/REPO."
        raise ConfigError(msg)
    return GitHubProvider(config=settings.github, repo=settings.repo, http=client)


def _build_current_provider(
    settings: Settings,
    gitlab_provider: GitLabProvider,
    github_provider: GitHubProvider,
) -> Provider:
    if settings.provider == "github":
        return github_provider
    return gitlab_provider


def _build_branch_prefix_strategy(settings: Settings) -> BranchPrefixStrategy:
    return BranchPrefixStrategy(config=settings.branch_prefix)


def _build_conventional_commits_strategy(settings: Settings) -> ConventionalCommitsStrategy:
    return ConventionalCommitsStrategy(config=settings.conventional_commits)


def _build_current_strategy(settings: Settings) -> BumpStrategy:
    if settings.strategy == "conventional-commits":
        return _build_conventional_commits_strategy(settings)
    return _build_branch_prefix_strategy(settings)


def _close_gitlab_provider(provider: GitLabProvider) -> None:
    provider.http.close()


def _close_github_provider(provider: GitHubProvider) -> None:
    provider.http.close()


class SettingsGroup(modern_di.Group):
    settings = providers.ContextProvider(scope=Scope.APP, context_type=Settings)


class ProvidersGroup(modern_di.Group):
    gitlab_client = providers.Factory(scope=Scope.APP, creator=_build_gitlab_client)
    gitlab_provider = providers.Factory(
        scope=Scope.APP,
        creator=_build_gitlab_provider,
        kwargs={"client": gitlab_client},
        cache_settings=providers.CacheSettings(finalizer=_close_gitlab_provider),
    )
    github_client = providers.Factory(scope=Scope.APP, creator=_build_github_client)
    github_provider = providers.Factory(
        scope=Scope.APP,
        creator=_build_github_provider,
        kwargs={"client": github_client},
        cache_settings=providers.CacheSettings(finalizer=_close_github_provider),
    )
    current_provider = providers.Factory(
        scope=Scope.APP,
        creator=_build_current_provider,
        kwargs={"gitlab_provider": gitlab_provider, "github_provider": github_provider},
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
            "provider": ProvidersGroup.current_provider,
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

Key changes from before:
- `_build_github_client`, `_build_github_provider`, `_build_current_provider`, `_close_github_provider` added
- `_close_provider_client` renamed → `_close_gitlab_provider` for symmetry
- `ProvidersGroup` adds `github_client`, `github_provider`, `current_provider`
- `UseCasesGroup.semvertag_use_case` references `ProvidersGroup.current_provider` (was `gitlab_provider`)

- [ ] **Step 2: Add `current_provider` resolution tests**

In `tests/unit/test_ioc.py`, add:

```python
def test_container_resolves_github_provider_when_settings_provider_is_github() -> None:
    settings = Settings(provider="github", repo="owner/repo")
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        provider = ioc.container.resolve_provider(ioc.ProvidersGroup.current_provider)
        assert isinstance(provider, GitHubProvider)
        assert provider.name == "github"


def test_container_resolves_gitlab_provider_when_settings_provider_is_gitlab() -> None:
    settings = Settings(provider="gitlab", project_id=999)
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        provider = ioc.container.resolve_provider(ioc.ProvidersGroup.current_provider)
        assert isinstance(provider, GitLabProvider)
        assert provider.name == "gitlab"
```

Add the import at the top:

```python
from semvertag.providers.github import GitHubProvider
from semvertag.providers.gitlab import GitLabProvider
```

- [ ] **Step 3: Rewrite `_main_callback` in `semvertag/__main__.py`**

The function gets three new params, and `--token` moves out of `_collect_overrides` into a second-pass overlay.

Find and replace `_collect_overrides`:

```python
def _collect_overrides(  # noqa: PLR0913
    *,
    project_id: int | None,
    strategy: str | None,
    default_branch: str | None,
    gitlab_endpoint: str | None,
    github_endpoint: str | None,
    provider: str | None,
    repo: str | None,
    request_timeout: float | None,
) -> dict[str, typing.Any]:
    overrides: dict[str, typing.Any] = {}
    if provider is not None:
        overrides["provider"] = provider
    if project_id is not None:
        overrides["project_id"] = project_id
    if repo is not None:
        overrides["repo"] = repo
    if strategy is not None:
        overrides["strategy"] = strategy
    if default_branch is not None:
        overrides["default_branch"] = default_branch
    if gitlab_endpoint is not None:
        overrides["gitlab.endpoint"] = gitlab_endpoint
    if github_endpoint is not None:
        overrides["github.endpoint"] = github_endpoint
    if request_timeout is not None:
        overrides["request_timeout"] = request_timeout
    return overrides
```

Note: `token` is no longer a parameter.

Find and replace `_main_callback`:

```python
@MAIN_APP.callback()
def _main_callback(  # noqa: PLR0913
    ctx: typer.Context,
    project_id: typing.Annotated[
        int | None,
        typer.Option("--project-id", help="GitLab project id (or set CI_PROJECT_ID)."),
    ] = None,
    repo: typing.Annotated[
        str | None,
        typer.Option("--repo", help="GitHub repo as OWNER/REPO (or set GITHUB_REPOSITORY)."),
    ] = None,
    provider: typing.Annotated[
        str | None,
        typer.Option("--provider", help="Provider: 'github' or 'gitlab' (default: auto-detect from CI env)."),
    ] = None,
    strategy: typing.Annotated[
        str | None,
        typer.Option("--strategy", help="Bump strategy: branch-prefix | conventional-commits."),
    ] = None,
    token: typing.Annotated[
        str | None,
        typer.Option("--token", help="API token (overrides SEMVERTAG_TOKEN); routed to the active provider."),
    ] = None,
    default_branch: typing.Annotated[
        str | None,
        typer.Option("--default-branch", help="Default branch name override."),
    ] = None,
    gitlab_endpoint: typing.Annotated[
        str | None,
        typer.Option("--gitlab-endpoint", help="GitLab API endpoint URL."),
    ] = None,
    github_endpoint: typing.Annotated[
        str | None,
        typer.Option("--github-endpoint", help="GitHub API endpoint URL (for GitHub Enterprise)."),
    ] = None,
    request_timeout: typing.Annotated[
        float | None,
        typer.Option("--request-timeout", help="Per-request timeout in seconds (clamped to 10)."),
    ] = None,
    _version: typing.Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = None,
) -> None:
    if ctx.resilient_parsing:
        return

    try:
        settings = Settings()
        try:
            overrides = _collect_overrides(
                project_id=project_id,
                strategy=strategy,
                default_branch=default_branch,
                gitlab_endpoint=gitlab_endpoint,
                github_endpoint=github_endpoint,
                provider=provider,
                repo=repo,
                request_timeout=request_timeout,
            )
            settings = apply_cli_overlay(settings, overrides)
            # Second pass: route --token to the resolved active provider.
            if token is not None:
                settings = apply_cli_overlay(
                    settings, {f"{settings.provider}.token": pydantic.SecretStr(token)}
                )
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
    except pydantic.ValidationError as exc:
        err = _config_error_from_validation(exc)
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=err.exit_code) from err
    except ConfigError as err:
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=err.exit_code) from err

    app_container = modern_di_typer.fetch_di_container(ctx)
    app_container.set_context(Settings, settings)
```

And update `MAIN_APP`:

```python
MAIN_APP: typing.Final = typer.Typer(
    name="semvertag",
    help=(
        "Auto-tag GitLab and GitHub repos with semantic version tags — "
        "one tool, two strategies, two providers."
    ),
    no_args_is_help=True,
    add_completion=True,
)
```

- [ ] **Step 4: Run CLI integration tests; fix breakage**

Run: `uv run pytest tests/integration/test_cli_main_verb.py tests/integration/test_cli_quiet_json_matrix.py -v 2>&1 | tail -30`
Expected: most pass; some may fail because they construct `Settings` paths that no longer satisfy the validator (e.g., `Settings()` with no `project_id` and no env). Fix each failure by either (a) adding `monkeypatch.setenv("CI_PROJECT_ID", "999")` to the test fixture, or (b) updating the test to pass `--project-id 999` to the CLI invocation.

- [ ] **Step 5: Add CLI smoke tests for GitHub paths**

In `tests/integration/test_cli_main_verb.py` (or wherever the existing CLI smoke tests live), add:

```python
def test_main_callback_accepts_github_provider_with_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    runner = CliRunner()
    result = runner.invoke(
        MAIN_APP,
        ["--provider", "github", "--repo", "owner/repo", "--token", "ghp_xxx", "tag", "--quiet"],
        # ... whatever invocation shape the existing tests use
    )
    # Assert the callback succeeded (resolved settings.provider == "github" without error)
    # The actual `tag` execution will fail because no real network; check exit code
    # is the expected ProviderAPIError exit (4), not ConfigError exit (2).
    assert result.exit_code in (0, 4)


def test_main_callback_auto_detects_github_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_xxx")
    runner = CliRunner()
    result = runner.invoke(MAIN_APP, ["tag", "--quiet"])
    assert result.exit_code in (0, 4)
```

Adjust the invocation shape to match the existing tests' conventions in that file.

- [ ] **Step 6: Run the full suite again**

Run: `just test 2>&1 | tail -5`
Expected: all tests pass, 100% coverage.

- [ ] **Step 7: Lint**

Run: `just lint-ci`
Expected: clean.

- [ ] **Step 8: Create `docs/providers/github.md`**

Use `docs/providers/gitlab.md` as a structural reference (read it first; mirror the section order and tone). The new file should cover:

- **Authentication**: PAT (classic with `repo` or `public_repo`; fine-grained with `contents: write`) or `GITHUB_TOKEN` from GitHub Actions (workflow must declare `permissions: contents: write`).
- **Environment variables**: `GITHUB_TOKEN` / `SEMVERTAG_GITHUB__TOKEN` / `SEMVERTAG_TOKEN`, `GITHUB_REPOSITORY` / `SEMVERTAG_REPO`, `SEMVERTAG_GITHUB__ENDPOINT` (for GitHub Enterprise).
- **Inline GitHub Actions job recipe** — mirror the GitLab CI recipe shape. Use `actions/setup-python@v5` + `uvx semvertag tag`. Include a minimal workflow YAML:

  ```yaml
  name: semvertag
  on:
    push:
      branches: [main]
  permissions:
    contents: write
  jobs:
    tag:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
          with:
            fetch-depth: 0
        - uses: actions/setup-python@v5
          with:
            python-version: "3.13"
        - run: pip install uv
        - run: uvx semvertag tag --strategy conventional-commits
          env:
            GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  ```

- **Troubleshooting**: 401 (token rejected/invalid), 403 (scope missing — direct user to `contents: write`), 404 (repo not found — check `GITHUB_REPOSITORY`), 422 (tag exists / invalid ref format).

- [ ] **Step 9: Update `README.md`**

Two changes:

1. Hero string at the top — change `"Auto-tag GitLab repos with semantic version tags"` to `"Auto-tag GitLab and GitHub repos with semantic version tags"`.

2. Add a new "Use in GitHub Actions" section parallel to the existing GitLab CI section. Copy the inline YAML from `docs/providers/github.md` (Step 8) into this section. The README version can be a 5-7 line excerpt linking to the full docs.

- [ ] **Step 10: Update `pyproject.toml`**

Find the `description` and `keywords` lines:

```toml
description = "Auto-tag GitLab repos with semantic version tags — one tool, two strategies."
...
keywords = ["semver", "gitlab", "ci", "auto-tag", "conventional-commits"]
```

Replace with:

```toml
description = "Auto-tag GitLab and GitHub repos with semantic version tags — one tool, two strategies, two providers."
...
keywords = ["semver", "gitlab", "github", "ci", "auto-tag", "conventional-commits"]
```

- [ ] **Step 11: Full suite + lint + docs build**

Run:
```bash
just lint-ci
just test
uv run --with mkdocs --with mkdocs-material mkdocs build --strict
```

Expected: all clean. The docs build should pick up the new `docs/providers/github.md` automatically if `mkdocs.yml`'s nav is auto-discovered; if it has an explicit nav, add an entry for it.

- [ ] **Step 12: Commit**

```bash
git add semvertag/ioc.py semvertag/__main__.py tests/unit/test_ioc.py tests/integration/test_cli_main_verb.py docs/providers/github.md README.md pyproject.toml
git commit -m "ioc+cli+docs: wire GitHub provider end-to-end"
```

If you also modified `tests/integration/test_cli_quiet_json_matrix.py`, include it in the commit.

---

## Task 7: Final validation

**Files:** none modified — verification gate.

- [ ] **Step 1: Full lint sweep**

Run: `just lint-ci`
Expected: clean.

- [ ] **Step 2: Full test sweep with branch coverage**

Run: `just test-branch`
Expected: all tests pass; 100% statement + branch coverage on all modules including the new `semvertag/providers/github.py` and `semvertag/_link_pagination.py`.

- [ ] **Step 3: Docs build**

Run: `uv run --with mkdocs --with mkdocs-material mkdocs build --strict`
Expected: clean.

- [ ] **Step 4: Verify the GitHub provider boots end-to-end via DI**

Run:
```bash
uv run python -c "
import os
os.environ['GITHUB_ACTIONS'] = 'true'
os.environ['GITHUB_REPOSITORY'] = 'octocat/Hello-World'
os.environ['GITHUB_TOKEN'] = 'ghp_xxx'

from semvertag import ioc
from semvertag._settings import Settings
from semvertag.providers._base import Provider
from semvertag.providers.github import GitHubProvider

with ioc.container:
    ioc.container.set_context(Settings, Settings())
    provider = ioc.container.resolve_provider(ioc.ProvidersGroup.current_provider)
    assert isinstance(provider, GitHubProvider), f'expected GitHubProvider, got {type(provider).__name__}'
    assert isinstance(provider, Provider)
    print(f'GitHub DI seam OK: provider={provider.name}, repo={provider.repo}')
"
```
Expected: prints `GitHub DI seam OK: provider=github, repo=octocat/Hello-World`. If it fails, the wiring in Task 6 is broken — re-check `_build_current_provider` and the `ProvidersGroup.current_provider` factory's `kwargs`.

- [ ] **Step 5: Verify back-compat — GitLab path still works under DI**

Run:
```bash
uv run python -c "
import os
for k in ('GITHUB_ACTIONS', 'GITLAB_CI', 'GITHUB_REPOSITORY', 'SEMVERTAG_REPO', 'SEMVERTAG_PROVIDER'):
    os.environ.pop(k, None)
os.environ['CI_PROJECT_ID'] = '999'

from semvertag import ioc
from semvertag._settings import Settings
from semvertag.providers._base import Provider
from semvertag.providers.gitlab import GitLabProvider

with ioc.container:
    ioc.container.set_context(Settings, Settings())
    provider = ioc.container.resolve_provider(ioc.ProvidersGroup.current_provider)
    assert isinstance(provider, GitLabProvider), f'expected GitLabProvider, got {type(provider).__name__}'
    print(f'GitLab DI seam OK: provider={provider.name}, project_id={provider.project_id}')
"
```
Expected: prints `GitLab DI seam OK: provider=gitlab, project_id=999`. Confirms the default-to-gitlab back-compat for 0.2.x users running outside CI.

- [ ] **Step 6: Skim `git log --oneline main..HEAD` for clean history**

Expected sequence:
```
<sha> ioc+cli+docs: wire GitHub provider end-to-end
<sha> providers/github: add GitHubProvider with integration test suite
<sha> providers/_errors: add translate_github + translate_create_tag_github_unprocessable
<sha> settings: add provider/repo fields + env-aware _resolve_provider validator
<sha> refactor(providers/_errors): extract _translate_transport(exc, *, provider_label)
<sha> refactor: extract Link-header pagination to _link_pagination module
```

- [ ] **Step 7 — Optional**: The controller will dispatch a final cross-cutting code review separately.

---

## Self-review notes

- **Spec coverage:** Every spec section maps to a task: Target shape → Tasks 1-6; Provider selection (auto-detection + validator) → Task 3; GitHubProvider implementation → Task 5; Error translation (extract transport + add github) → Tasks 2 and 4; Pagination helpers extraction → Task 1; Wiring (ioc.py + CLI + docs + README + pyproject) → Task 6. The five spec open items are all resolved at plan-time inside the task steps: (1) `_detect_provider_from_env` placed as a free function in `_settings.py` (Task 3 Step 3); (2) `_link_pagination` public-no-underscore naming committed (Task 1 Step 1); (3) two-pass `--token` overlay confirmed to work (the second `apply_cli_overlay` call in Task 6 Step 3); (4) integration-test fixture sharing — skip the shared conftest helper; each integration file owns its own `_make_provider` (Task 5 Step 2 inline); (5) pagination tests moved to `tests/unit/test_link_pagination.py` (Task 1 Step 2).
- **Placeholder scan:** No `TBD`, `TODO`, "appropriate error handling", or "similar to Task N" patterns. Task 5 Step 3 explicitly says "this skeleton has ~14 tests; add more until 100% coverage" — that's a definite directive, not a TBD: the implementer keeps adding tests using the same patterns until coverage gate passes.
- **Type consistency:** `GitHubProvider.repo: str` consistent across Task 5 (definition) and Task 6 (ioc factory). `Settings.provider: Literal["gitlab", "github"] | None` consistent across Task 3 (definition) and Task 6 (factory dispatch on it). `_translate_transport(exc, *, provider_label: str)` signature defined in Task 2, called with `provider_label="GitLab"` in Task 2 (updated `translate_gitlab`) and `provider_label="GitHub"` in Task 4 (`translate_github`). `httpware.DecodeError`/`UnprocessableEntityError`/`StatusError`/`ClientError` references all match httpware 0.8.2's public surface (already pinned).

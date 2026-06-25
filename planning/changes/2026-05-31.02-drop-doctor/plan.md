# Drop `semvertag doctor` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the `semvertag doctor` subcommand and everything that exists only to serve it — the `semvertag/doctor/` package, the four `check_*` methods on the `Provider` Protocol, and the `_provenance` tracking in `Settings` — relying on the main command's existing typed errors (`AuthError`/`ConfigError`/`ProviderAPIError`) for diagnosis.

**Architecture:** Pure deletion, no new code. Three waves on one worktree, each leaving tests green. Wave A drops the doctor package + CLI command + doctor's own tests. Wave B drops the provider `check_*` surface (Protocol + methods + tests). Wave C drops `_provenance` machinery + Justfile recipe + doc references.

**Tech Stack:** Python 3.10+, `pytest`, `ty`, `ruff`, `uv`, `just`. Nothing new.

**Spec:** `planning/specs/2026-05-31-drop-doctor-design.md`

---

## Task 1: Spawn worktree and verify baseline

**Files:** none in main checkout (worktree creation).

- [ ] **Step 1: Spawn the worktree**

Use the `superpowers:using-git-worktrees` skill. Suggested branch name: `feat/drop-doctor`. Suggested path: `.worktrees/feat-drop-doctor` (matches the existing project-local pattern from the previous feature).

- [ ] **Step 2: Verify clean baseline inside the worktree**

Run (in the worktree): `git status` — must be clean, on branch `feat/drop-doctor`.

Run: `just lint-ci`
Expected: PASS (eof-fixer, ruff format, ruff check, ty check all green).

Run: `uv run pytest -q`
Expected: 438 passed, 1 skipped.

Run: `uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

If any baseline check fails, stop and report — the merged main is not in the expected state and the plan can't proceed.

---

## Task 2: Wave A — Drop the doctor subsystem

**Files:**
- Delete: `semvertag/doctor/__init__.py`
- Delete: `semvertag/doctor/_checks.py`
- Delete: `semvertag/doctor/_render.py`
- Modify: `semvertag/__main__.py` (remove the `_doctor_command`, `_collect_doctor_overrides`, and the two `from semvertag.doctor …` imports)
- Delete: `tests/integration/test_cli_doctor.py`
- Delete: `tests/unit/test_doctor_checks.py`
- Delete: `tests/unit/test_doctor_render.py`

- [ ] **Step 1: Delete the doctor package**

```bash
git rm -r semvertag/doctor
```

- [ ] **Step 2: Delete the doctor test files**

```bash
git rm tests/integration/test_cli_doctor.py tests/unit/test_doctor_checks.py tests/unit/test_doctor_render.py
```

- [ ] **Step 3: Remove doctor imports from `semvertag/__main__.py`**

In `semvertag/__main__.py`, delete these two import lines (currently at lines 14-15):

```python
from semvertag.doctor._checks import resolve_exit_code, run_checks
from semvertag.doctor._render import build_doctor_result, render_doctor_human, render_doctor_json
```

- [ ] **Step 4: Remove `_doctor_command` from `semvertag/__main__.py`**

Delete the entire `_doctor_command` function (currently `@MAIN_APP.command("doctor")` decorator at line 200, function body spans roughly lines 200-283). The function starts:

```python
@MAIN_APP.command("doctor")
def _doctor_command(  # noqa: PLR0913
    project_id: typing.Annotated[
        ...
```

and ends with:

```python
    except OSError as exc:
        if exc.errno == errno.EPIPE:
            raise typer.Exit(code=0) from exc
        raise
```

Delete everything from the `@MAIN_APP.command("doctor")` decorator through the trailing `raise` (inclusive).

- [ ] **Step 5: Remove `_collect_doctor_overrides` from `semvertag/__main__.py`**

Delete the `_collect_doctor_overrides` function (currently around lines 72-94). The whole function:

```python
def _collect_doctor_overrides(  # noqa: PLR0913
    *,
    project_id: int | None,
    provider: str | None,
    token: str | None,
    default_branch: str | None,
    gitlab_endpoint: str | None,
    request_timeout: float | None,
) -> dict[str, tuple[typing.Any, str]]:
    overrides: dict[str, tuple[typing.Any, str]] = {}
    if project_id is not None:
        overrides["project_id"] = (project_id, "--project-id")
    if provider is not None:
        overrides["provider"] = (provider, "--provider")
    if token is not None:
        overrides["gitlab.token"] = (pydantic.SecretStr(token), "--token")
    if default_branch is not None:
        overrides["default_branch"] = (default_branch, "--default-branch")
    if gitlab_endpoint is not None:
        overrides["gitlab.endpoint"] = (gitlab_endpoint, "--gitlab-endpoint")
    if request_timeout is not None:
        overrides["request_timeout"] = (request_timeout, "--request-timeout")
    return overrides
```

- [ ] **Step 6: Verify lint and tests**

Run: `just lint-ci`
Expected: PASS. If ruff flags any now-unused imports in `__main__.py` (e.g. anything that was only used by the doctor command), let `ruff check --fix` remove them by running `just lint` (which uses `--fix`), then re-run `just lint-ci`.

Run: `uv run pytest -q`
Expected: PASS. Test count drops from 438 by however many doctor tests were deleted (likely ~50-70 tests). No failures.

- [ ] **Step 7: Verify `doctor` subcommand is gone**

Run: `uv run semvertag --help`
Expected output: no `doctor` subcommand listed. Only the main callback options.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: drop doctor subcommand and its package

The semvertag doctor subcommand and the entire semvertag/doctor/ package
are removed. The main semvertag command's existing typed errors
(AuthError/ConfigError/ProviderAPIError) already produce the same exit
codes for the same failure modes that doctor diagnosed, so no
replacement is needed.

Provider check_* methods and Settings._provenance machinery remain in
place temporarily and will be removed in subsequent commits."
```

---

## Task 3: Wave B — Drop the provider `check_*` surface

**Files:**
- Modify: `semvertag/providers/_base.py` (drop 4 `check_*` from Protocol)
- Modify: `semvertag/providers/gitlab.py` (drop 4 methods + `_safe_get` + `_evaluate_scopes_payload` + dead constants)
- Modify: `tests/integration/test_gitlab_provider.py` (drop check_* section + shrink protocol-conformance list)

- [ ] **Step 1: Shrink the `Provider` Protocol**

In `semvertag/providers/_base.py`, delete the four `check_*` method declarations (currently lines 14-17):

```python
    def check_token(self) -> CheckResult: ...
    def check_scopes(self) -> CheckResult: ...
    def check_project_access(self) -> CheckResult: ...
    def check_protected_tags(self) -> CheckResult: ...
```

After deletion, the `Provider` Protocol body should have 5 members: `name`, `get_default_branch`, `get_latest_commit_on_default_branch`, `list_tags`, `create_tag`.

Check the imports at the top of `_base.py`. If `CheckResult` is no longer referenced (it was likely the only doctor-related symbol imported there), remove it from the `from semvertag._types import …` line. The post-edit imports should be:

```python
from semvertag._types import Commit, Tag
```

- [ ] **Step 2: Drop the four `check_*` methods from `gitlab.py`**

In `semvertag/providers/gitlab.py`:

1. Delete `check_token` (currently starts around line 141, ends just before `check_scopes`).
2. Delete `check_scopes` (currently starts around line 170, ends just before `check_project_access`).
3. Delete `check_project_access` (currently starts around line 185, ends just before `check_protected_tags`).
4. Delete `check_protected_tags` (currently starts around line 224, ends just before `_auth_headers` or `_url`).

- [ ] **Step 3: Drop `_safe_get` from `gitlab.py`**

In the same file, delete the `_safe_get` method (currently around line 260-269). It looks like:

```python
    def _safe_get(self, url: str) -> tuple[httpx2.Response | None, str | None]:
        try:
            return self.http.request_raw("GET", url), None
        except ProviderAPIError as exc:
            cause = exc.__cause__
            error_kind = type(cause).__name__ if isinstance(cause, httpx2.RequestError) else "RequestError"
            return None, error_kind
```

- [ ] **Step 4: Drop `_evaluate_scopes_payload` from `gitlab.py`**

In the same file, delete the module-level `_evaluate_scopes_payload` function (currently around line 330). It looks like:

```python
def _evaluate_scopes_payload(response: httpx2.Response) -> CheckResult:
    try:
        payload = response.json()
    except (ValueError, httpx2.DecodingError):
        payload = None
    if not isinstance(payload, dict):
        return CheckResult(
            name="scopes",
            ...
```

Delete the entire function through its `return CheckResult(...)` tail.

- [ ] **Step 5: Drop unused constants from `gitlab.py`**

After Steps 2-4, several module-level constants no longer have any caller. Delete:

```python
_USER_PATH: typing.Final = "/api/v4/user"                                 # line ~16
_TOKEN_INTROSPECTION_PATH: typing.Final = "/api/v4/personal_access_tokens/self"  # line ~17
_API_SCOPE: typing.Final = "api"                                          # line ~34
```

Do NOT preemptively delete other constants. Run `ruff check` after this step (see Step 6) and let it tell you about any additional unused symbols.

- [ ] **Step 6: Check for unused imports/symbols and update imports**

Run: `uv run ruff check semvertag/providers/gitlab.py`
Expected: may flag unused imports (e.g. `CheckResult` import from `_types` if it was only used by check_* methods).

If `CheckResult` is no longer referenced in `gitlab.py`, remove it from the import statement:

```python
# Before:
from semvertag._types import CheckResult, Commit, Tag
# After:
from semvertag._types import Commit, Tag
```

Run `just lint` to auto-fix anything else ruff catches. Then verify with `just lint-ci`.

- [ ] **Step 7: Drop the check_* test section from `tests/integration/test_gitlab_provider.py`**

The doctor test section starts with the section marker:

```python
# AC8 -- Doctor methods
```

at line 581 of the current file (line numbers may shift slightly after Wave A; search for the marker text). Delete everything from this line through the end of the file. The file currently ends at line 751 with the last `check_*` test (`test_check_token_returns_failed_on_403`).

- [ ] **Step 8: Shrink the protocol-conformance test in the same file**

In `tests/integration/test_gitlab_provider.py`, find `test_gitlab_provider_exposes_every_member_required_by_protocol` (around line 75). Update the `expected_members` tuple to drop the four `check_*` names:

```python
def test_gitlab_provider_exposes_every_member_required_by_protocol() -> None:
    expected_members: typing.Final = (
        "name",
        "get_default_branch",
        "get_latest_commit_on_default_branch",
        "list_tags",
        "create_tag",
    )
    for member in expected_members:
        assert hasattr(GitLabProvider, member), f"GitLabProvider is missing Provider member: {member!r}"
    assert Provider.__name__ == "Provider"
```

- [ ] **Step 9: Verify lint and tests**

Run: `just lint-ci`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS. Test count drops further by however many check_* tests were in the section (likely ~17 tests per the grep). No failures.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "providers: drop check_* methods after doctor removal

The Provider Protocol now has 5 members instead of 9. GitLabProvider's
four check_* methods, the _safe_get helper, _evaluate_scopes_payload,
and the constants only they consumed (_USER_PATH,
_TOKEN_INTROSPECTION_PATH, _API_SCOPE) are removed."
```

---

## Task 4: Wave C — Drop `_provenance` and remaining references

**Files:**
- Modify: `semvertag/_settings.py` (drop `_provenance` machinery)
- Delete: `tests/unit/test_provenance.py`
- Modify: `Justfile` (drop `test-doctor` recipe)
- Modify: `CLAUDE.md` (drop `test-doctor` bullet)
- Modify: `docs/providers/gitlab.md` (drop doctor mentions on lines 75 and 160)

- [ ] **Step 1: Drop `_provenance` field from `Settings`**

In `semvertag/_settings.py`, delete the `_provenance` `PrivateAttr` line in the `Settings` class (currently line 75):

```python
    _provenance: dict[str, ConfigSource] = pydantic.PrivateAttr(default_factory=dict)
```

- [ ] **Step 2: Drop `_record_env_provenance` from the `Settings` class**

In the same file, delete the model_validator method (currently lines 120-123):

```python
    @pydantic.model_validator(mode="after")
    def _record_env_provenance(self) -> "Settings":
        _scan_model(self, "", self._provenance)
        return self
```

- [ ] **Step 3: Drop the provenance-only module helpers**

In the same file, delete these three module-level helpers (currently lines 146-171):

```python
def _scan_model(model: pydantic.BaseModel, prefix: str, provenance: dict[str, ConfigSource]) -> None:
    for field_name in type(model).model_fields:
        full_key = f"{prefix}{field_name}"
        value = getattr(model, field_name)
        if isinstance(value, pydantic.BaseModel):
            _scan_model(value, f"{full_key}.", provenance)
            continue
        provenance[full_key] = _resolve_source(full_key)


def _resolve_source(full_key: str) -> ConfigSource:
    candidates: typing.Final = _candidate_env_names(full_key)
    found: typing.Final = _find_aliased_env(candidates)
    if found is None:
        return ConfigSource(layer="default", detail="default")
    matched_alias, _value = found
    return ConfigSource(layer="env", detail=matched_alias)


def _candidate_env_names(full_key: str) -> tuple[str, ...]:
    if full_key in _TOKEN_ALIASES_BY_PATH:
        return _TOKEN_ALIASES_BY_PATH[full_key]
    if full_key in _TOP_LEVEL_FIELD_ALIASES:
        return _TOP_LEVEL_FIELD_ALIASES[full_key]
    default_env_name: typing.Final = _ENV_PREFIX + full_key.upper().replace(".", _ENV_NESTED_DELIMITER)
    return (default_env_name,)
```

- [ ] **Step 4: Trim the provenance-tracking block in `apply_cli_overlay`**

In the same file, find `apply_cli_overlay` (currently around line 190). The function currently ends with:

```python
def apply_cli_overlay(
    settings: Settings,
    overrides: dict[str, tuple[typing.Any, str]],
) -> Settings:
    update_top, nested_updates = _split_overrides(settings, overrides)
    for head, leaf_updates in nested_updates.items():
        update_top[head] = _revalidate_nested(settings, head, leaf_updates)

    copied: typing.Final = settings.model_copy(update=update_top, deep=True)
    raw_data: typing.Final = {name: getattr(copied, name) for name in type(copied).model_fields}
    new_settings: typing.Final = type(copied).model_validate(raw_data)

    new_provenance: typing.Final = dict(settings._provenance)  # noqa: SLF001
    for dotted_key, (_value, flag_detail) in overrides.items():
        new_provenance[dotted_key] = ConfigSource(layer="cli", detail=flag_detail)
    new_settings._provenance = new_provenance  # noqa: SLF001
    return new_settings
```

Delete the last block (the four lines starting `new_provenance: typing.Final = dict(...)` through `new_settings._provenance = new_provenance  # noqa: SLF001`). The function's new ending is:

```python
    copied: typing.Final = settings.model_copy(update=update_top, deep=True)
    raw_data: typing.Final = {name: getattr(copied, name) for name in type(copied).model_fields}
    new_settings: typing.Final = type(copied).model_validate(raw_data)
    return new_settings
```

- [ ] **Step 5: Remove now-unused imports from `_settings.py`**

The `from semvertag._types import ConfigSource` import (currently line 8) may now be unused — `ConfigSource` was only referenced by the provenance machinery. Verify by running `uv run ruff check semvertag/_settings.py` after the previous steps; if ruff flags it, remove that import line.

If `_logger` (line 13) is still used by `_clamp_request_timeout`, leave it. (It is — the clamp logs a warning. Don't delete.)

- [ ] **Step 6: Delete the provenance test file**

```bash
git rm tests/unit/test_provenance.py
```

- [ ] **Step 7: Drop the `test-doctor` recipe from `Justfile`**

Delete the last 3 lines of `Justfile`:

```
test-doctor:
    uv run --no-sync pytest -o "addopts=" --cov=semvertag.doctor --cov-branch --cov-fail-under=100 --cov-report=term-missing tests/unit/test_doctor_checks.py tests/unit/test_doctor_render.py
```

(Plus the blank line above it.)

- [ ] **Step 8: Drop the `test-doctor` bullet from `CLAUDE.md`**

In `CLAUDE.md`, find this bullet around line 43:

```markdown
- `just test-branch-strategies` / `just test-cc-strategies` / `just test-doctor`
  — 100% branch coverage gates on specific modules
```

Edit to:

```markdown
- `just test-branch-strategies` / `just test-cc-strategies`
  — 100% branch coverage gates on specific modules
```

- [ ] **Step 9: Drop doctor mentions from `docs/providers/gitlab.md`**

In `docs/providers/gitlab.md`, two doctor mentions need editing:

Around line 75, the text currently says:

```markdown
The component pushes a tag, so the token it uses MUST carry write
access to the repository. semvertag reads the token from these env
vars in order: `SEMVERTAG_GITLAB__TOKEN`, `SEMVERTAG_TOKEN`,
`CI_JOB_TOKEN`, `GITLAB_TOKEN`. The first set value wins.

Run `uvx semvertag doctor` locally (or as a CI pre-flight) to confirm
the token scope is correct. The diagnostic reports the GitLab API's
response to a scope-probe call and names which scopes are missing.
```

Delete the entire paragraph that starts `Run \`uvx semvertag doctor\` locally` (lines 75-77 in the current file, including the leading blank line above it if it creates a double-blank).

Around line 160, the text currently says:

```markdown
- **`Token missing scope or insufficient permission: 403`** — the
  token does not have `api` + `write_repository` scope, or the
  project's protected-tag rules disallow the bot from creating tags.
  Verify the `SEMVERTAG_TOKEN` scopes in GitLab UI (Settings → Access
  Tokens), or run `uvx semvertag doctor` locally for a named
  diagnosis.
```

Edit to remove the doctor reference:

```markdown
- **`Token missing scope or insufficient permission: 403`** — the
  token does not have `api` + `write_repository` scope, or the
  project's protected-tag rules disallow the bot from creating tags.
  Verify the `SEMVERTAG_TOKEN` scopes in GitLab UI (Settings → Access
  Tokens).
```

- [ ] **Step 10: Verify lint, tests, and docs build**

Run: `just lint-ci`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS. Test count drops by the number of provenance tests (~14 per the file size of `test_provenance.py`).

Run: `uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "chore: drop _provenance tracking and remaining doctor references

Settings no longer tracks per-field provenance (the only consumer was
doctor's render). Justfile drops the test-doctor recipe. CLAUDE.md and
docs/providers/gitlab.md drop doctor references."
```

---

## Task 5: Pre-merge verification gate

**Files:** none modified.

- [ ] **Step 1: Lint**

Run: `just lint-ci`
Expected: PASS (all four checks).

- [ ] **Step 2: Full test suite**

Run: `uv run pytest`
Expected: PASS. Final count significantly lower than 438 (likely ~350-360) reflecting deleted tests, not regressions. No failures, no errors.

- [ ] **Step 3: Branch-coverage gates that should be unaffected**

Run: `just test-branch-strategies`
Expected: 100% on `semvertag.strategies.branch_prefix`.

Run: `just test-cc-strategies`
Expected: 100% on `semvertag.strategies.conventional_commits`.

(`just test-doctor` should NOT exist anymore — verify with `just --list | grep test-doctor` returning nothing.)

- [ ] **Step 4: Docs build**

Run: `uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

- [ ] **Step 5: LOC delta sanity check**

Run: `git diff main --stat`
Expected: a clear net negative across the source tree (target: ~400+ LOC removed, ~38 KB of test files removed). If the delta is positive or near zero, something went wrong — review before proceeding.

Run: `git log --oneline main..HEAD`
Expected: exactly 3 commits (one per wave).

---

## Task 6: Code review via subagent

**Files:** none modified directly; review may prompt fixup commits.

- [ ] **Step 1: Invoke `superpowers:requesting-code-review`**

Dispatch a code-review subagent against the worktree branch. Review scope: the full diff between `main` and `HEAD` of the worktree (3 commits).

Brief the reviewer on:
- The work is purely deletion; expect no new code.
- The spec is at `planning/specs/2026-05-31-drop-doctor-design.md`.
- The Section 2 table of "doctor failure mode → main command equivalent" is the load-bearing assumption; ask them to verify the main command's typed errors really do produce the listed exit codes.
- Don't re-litigate the decision to remove doctor (already agreed).

- [ ] **Step 2: Process findings with `superpowers:receiving-code-review`**

Use the receiving-code-review skill to evaluate findings. Address legitimate Important/Critical issues with fixup commits in the worktree; note Minor issues for follow-up.

- [ ] **Step 3: Re-run Task 5 if any code changed**

If review prompted any code changes, re-run the full verification gate (Task 5) before proceeding.

---

## Task 7: Land the worktree

**Files:** none modified by hand; merge + cleanup.

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Use the skill to merge to `main` (fast-forward expected — main hasn't moved during this work) and clean up the worktree.

- [ ] **Step 2: Verify the work is on `main`**

Run (in the main checkout): `git log --oneline -5`
Expected: the three drop-doctor commits are at HEAD.

Run: `just lint-ci && uv run pytest -q`
Expected: green on `main`.

Run: `ls semvertag/doctor 2>&1`
Expected: "No such file or directory".

---

## Success criteria

When all tasks above are done:

- `semvertag/doctor/` no longer exists in the working tree.
- `Provider` Protocol has 5 methods (was 9).
- `Settings` class has no `_provenance` field; `_scan_model`, `_resolve_source`, `_candidate_env_names`, and `_record_env_provenance` are all gone.
- `gitlab.py` is meaningfully shorter (target: ~120 LOC reduction from the current 372).
- `_settings.py` is meaningfully shorter (target: ~50 LOC reduction).
- `__main__.py` is meaningfully shorter (target: ~100 LOC reduction).
- `Justfile` has no `test-doctor` recipe.
- `CLAUDE.md` and `docs/providers/gitlab.md` have no doctor references.
- The main `semvertag` command still raises `AuthError`/`ConfigError`/`ProviderAPIError` with exit codes 3/2/4 for the failure modes listed in the spec's Section 2 table.
- `just lint-ci`, `uv run pytest`, and `mkdocs build --strict` all green.

# Settings `AliasChoices` Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hand-coded env-alias machinery in `semvertag/_settings.py` with Pydantic's native `AliasChoices` by promoting `GitLabConfig` and `GitHubConfig` from `BaseModel` to `BaseSettings` and adding `validation_alias` to their `token` fields and to `Settings.project_id`.

**Architecture:** Single file (`semvertag/_settings.py`) edited in two commits on one worktree. No tests added or modified — `tests/unit/test_settings.py` pins the alias precedence and should pass unchanged. Net deletion ~75-85 LOC.

**Tech Stack:** `pydantic`, `pydantic-settings`. Both already project deps; no new packages.

**Spec:** `planning/specs/2026-05-31-settings-aliaschoices-design.md`

---

## Task 1: Spawn worktree and verify baseline

**Files:** none in main checkout (worktree creation).

- [ ] **Step 1: Spawn the worktree**

Use the `superpowers:using-git-worktrees` skill. Suggested branch: `feat/settings-aliaschoices`. Suggested path: `.worktrees/feat-settings-aliaschoices`.

- [ ] **Step 2: Verify clean baseline inside the worktree**

Run (inside the worktree, after `cd` and `uv sync --all-extras --group lint`):

```bash
pwd
git branch --show-current
git status
```

Expected: cwd is the worktree path, branch is `feat/settings-aliaschoices`, status clean.

Run: `just lint-ci`
Expected: PASS.

Run: `uv run pytest -q`
Expected: 334 passed, 1 skipped.

Run: `uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

If any baseline check fails, stop and report — main is not in the expected post-drop-doctor state.

---

## Task 2: Wave A — Adopt `AliasChoices` on nested configs and `project_id`

**Files:**
- Modify: `semvertag/_settings.py` (lines 46-52 for `GitLabConfig` and `GitHubConfig`; line 67 for `project_id`; lines 74-102 for the two model_validators)

- [ ] **Step 1: Replace `GitLabConfig` body**

In `semvertag/_settings.py`, find the current `GitLabConfig` definition (currently lines 46-49):

```python
class GitLabConfig(pydantic.BaseModel):
    endpoint: str = "https://gitlab.com"
    token: pydantic.SecretStr = pydantic.Field(default=pydantic.SecretStr(""))
```

Replace it with:

```python
class GitLabConfig(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="SEMVERTAG_GITLAB__",
        case_sensitive=False,
        extra="ignore",
    )

    endpoint: str = "https://gitlab.com"
    token: pydantic.SecretStr = pydantic.Field(
        default=pydantic.SecretStr(""),
        validation_alias=pydantic.AliasChoices(
            "SEMVERTAG_GITLAB__TOKEN",
            "SEMVERTAG_TOKEN",
            "CI_JOB_TOKEN",
            "GITLAB_TOKEN",
        ),
    )
```

- [ ] **Step 2: Replace `GitHubConfig` body**

Find the current `GitHubConfig` definition (currently lines 51-52):

```python
class GitHubConfig(pydantic.BaseModel):
    token: pydantic.SecretStr = pydantic.Field(default=pydantic.SecretStr(""))
```

Replace it with:

```python
class GitHubConfig(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="SEMVERTAG_GITHUB__",
        case_sensitive=False,
        extra="ignore",
    )

    token: pydantic.SecretStr = pydantic.Field(
        default=pydantic.SecretStr(""),
        validation_alias=pydantic.AliasChoices(
            "SEMVERTAG_GITHUB__TOKEN",
            "SEMVERTAG_TOKEN",
            "GITHUB_TOKEN",
        ),
    )
```

- [ ] **Step 3: Add `validation_alias` to `Settings.project_id`**

In the `Settings` class, find the `project_id` field declaration (currently line 67):

```python
    project_id: int | None = pydantic.Field(default=None)
```

Replace it with:

```python
    project_id: int | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("SEMVERTAG_PROJECT_ID", "CI_PROJECT_ID"),
    )
```

- [ ] **Step 4: Delete `_inject_token_aliases` model_validator**

In the `Settings` class, find this method (currently lines 74-87):

```python
    @pydantic.model_validator(mode="before")
    @classmethod
    def _inject_token_aliases(cls, data: typing.Any) -> typing.Any:  # noqa: ANN401
        if not isinstance(data, dict):
            return data
        provider: typing.Final = _resolve_active_provider(data)
        nested_key: typing.Final = _PROVIDER_TO_NESTED_KEY.get(provider)
        if nested_key is None:
            return data
        aliases: typing.Final = _TOKEN_ALIASES_BY_PATH.get(f"{nested_key}.token")
        if aliases is None:
            return data
        _inject_token(data, nested_key, aliases)
        return data
```

Delete the entire method including the two decorator lines and the blank line that follows it (don't leave a double-blank).

- [ ] **Step 5: Delete `_inject_top_level_aliases` model_validator**

In the same class, find this method (currently lines 89-102):

```python
    @pydantic.model_validator(mode="before")
    @classmethod
    def _inject_top_level_aliases(cls, data: typing.Any) -> typing.Any:  # noqa: ANN401
        if not isinstance(data, dict):
            return data
        for field_name, aliases in _TOP_LEVEL_FIELD_ALIASES.items():
            if field_name in data and data[field_name] is not None:
                continue
            found = _find_aliased_env(aliases)
            if found is None:
                continue
            _matched_alias, value = found
            data[field_name] = value
        return data
```

Delete the entire method including the two decorator lines and the blank line that follows it.

- [ ] **Step 6: Run tests**

DO NOT touch the constants (`_GITLAB_TOKEN_ALIASES`, `_GITHUB_TOKEN_ALIASES`, etc.) or the helpers (`_resolve_active_provider`, `_inject_token`, `_find_aliased_env`, `_find_env_value`) yet. They become unused after this wave but stay until Wave B for a cleaner diff.

Run: `uv run pytest tests/unit/test_settings.py -v`
Expected: ALL 13 tests PASS, no failures.

If any test fails: read the failure carefully. The most common failure mode would be the `case_sensitive=False` interaction with `validation_alias` (env var names with mixed case vs the all-caps alias strings). If you see a token-resolution test failing on a case-mismatch, surface it — don't silently tweak the spec.

Run: `uv run pytest -q`
Expected: 334 passed, 1 skipped (same as baseline).

- [ ] **Step 7: Lint check**

Run: `just lint-ci`
Expected: PASS.

Note on why this should pass cleanly even though the alias machinery is now dead: the helpers and constants reference each other (`_inject_token` calls `_find_aliased_env`; `_TOKEN_ALIASES_BY_PATH` references `_GITLAB_TOKEN_ALIASES`; etc.) and `import os` is still consumed by `_find_aliased_env`. Ruff sees an internally-consistent cluster of private symbols and doesn't flag them. The cluster gets deleted wholesale in Wave B.

If lint fails for an unexpected reason (e.g., a stray import order issue caused by the edits), fix the actual issue. Do NOT add `# noqa` suppressions to paper over anything — surface it instead.

- [ ] **Step 8: Verify cwd before committing**

```bash
pwd
git branch --show-current
```

The output MUST show `/Users/kevinsmith/src/pypi/autosemver/.worktrees/feat-settings-aliaschoices` (or whatever path the worktree was created at — definitely under `.worktrees/`) and branch `feat/settings-aliaschoices`. If `pwd` shows the main repo root or branch shows `main`, STOP — do not commit. The Wave A drop-doctor implementer accidentally committed to main because cwd was wrong; do not repeat that.

- [ ] **Step 9: Commit**

```bash
git add semvertag/_settings.py
git commit -m "settings: route nested token aliases through pydantic AliasChoices

GitLabConfig and GitHubConfig are now pydantic_settings.BaseSettings
subclasses with their own env_prefix. Their token fields use
AliasChoices to express the same precedence chain that
_inject_token_aliases previously implemented manually. Settings.project_id
also gets a validation_alias for SEMVERTAG_PROJECT_ID and CI_PROJECT_ID.

The two model_validators (_inject_token_aliases and
_inject_top_level_aliases) are removed. The alias-map constants and
helper functions are now unused; they will be deleted in the next
commit for a clean per-commit diff."
```

---

## Task 3: Wave B — Drop the dead alias machinery

**Files:**
- Modify: `semvertag/_settings.py` (delete `import os` + 7 alias constants + 4 helper functions + any temporary `# noqa` comments added in Wave A)

- [ ] **Step 1: Delete `import os`**

In `semvertag/_settings.py`, find the import (currently line 2):

```python
import os
```

Delete it. After this and the Wave A changes, `os` is no longer referenced anywhere in the file.

- [ ] **Step 2: Delete the 7 alias-map module constants**

Delete the entire block (currently lines 14-43, between `_logger` and `_REQUEST_TIMEOUT_CEILING`):

```python
_GITLAB_TOKEN_ALIASES: typing.Final[tuple[str, ...]] = (
    "SEMVERTAG_GITLAB__TOKEN",
    "SEMVERTAG_TOKEN",
    "CI_JOB_TOKEN",
    "GITLAB_TOKEN",
)
_GITHUB_TOKEN_ALIASES: typing.Final[tuple[str, ...]] = (
    "SEMVERTAG_GITHUB__TOKEN",
    "SEMVERTAG_TOKEN",
    "GITHUB_TOKEN",
)
_PROJECT_ID_ALIASES: typing.Final[tuple[str, ...]] = (
    "SEMVERTAG_PROJECT_ID",
    "CI_PROJECT_ID",
)
_TOKEN_ALIASES_BY_PATH: typing.Final[dict[str, tuple[str, ...]]] = {
    "gitlab.token": _GITLAB_TOKEN_ALIASES,
    "github.token": _GITHUB_TOKEN_ALIASES,
}
_TOP_LEVEL_FIELD_ALIASES: typing.Final[dict[str, tuple[str, ...]]] = {
    "project_id": _PROJECT_ID_ALIASES,
}
_PROVIDER_TO_NESTED_KEY: typing.Final[dict[str, str]] = {
    "gitlab": "gitlab",
    "github": "github",
}
```

Also delete `_PROVIDER_ENV_VAR` (currently line 43):

```python
_PROVIDER_ENV_VAR: typing.Final = _ENV_PREFIX + "PROVIDER"
```

**Keep** `_REQUEST_TIMEOUT_CEILING`, `_ENV_PREFIX`, `_ENV_NESTED_DELIMITER` — they're still in use.

- [ ] **Step 3: Delete `_resolve_active_provider`**

Currently lines 118-124:

```python
def _resolve_active_provider(data: dict[str, typing.Any]) -> str:
    raw = data.get("provider")
    if raw is None:
        raw = _find_env_value((_PROVIDER_ENV_VAR,))
    if raw is None:
        raw = "gitlab"
    return str(raw).lower()
```

Delete the entire function.

- [ ] **Step 4: Delete `_inject_token`**

Currently lines 127-135:

```python
def _inject_token(data: dict[str, typing.Any], nested_key: str, aliases: tuple[str, ...]) -> None:
    nested: typing.Final = data.setdefault(nested_key, {})
    if not isinstance(nested, dict) or "token" in nested:
        return
    found: typing.Final = _find_aliased_env(aliases)
    if found is None:
        return
    _matched_alias, value = found
    nested["token"] = value
```

Delete the entire function.

- [ ] **Step 5: Delete `_find_aliased_env`**

Currently lines 138-144:

```python
def _find_aliased_env(candidates: tuple[str, ...]) -> tuple[str, str] | None:
    env_lower_to_value: typing.Final = {key.lower(): value for key, value in os.environ.items()}
    for alias in candidates:
        value = env_lower_to_value.get(alias.lower())
        if value:
            return alias, value
    return None
```

Delete the entire function.

- [ ] **Step 6: Delete `_find_env_value`**

Currently lines 147-151:

```python
def _find_env_value(candidates: tuple[str, ...]) -> str | None:
    found: typing.Final = _find_aliased_env(candidates)
    if found is None:
        return None
    return found[1]
```

Delete the entire function.

- [ ] **Step 7: Verify no stray `# noqa` comments**

Run: `grep -n "noqa" semvertag/_settings.py`

Expected: no matches. The pre-Wave-A file had two `# noqa: ANN401` comments on the two model_validators (`_inject_token_aliases` and `_inject_top_level_aliases`); Wave A deleted both methods along with their noqa annotations. If you see any matches, investigate — it may indicate a temporary suppression added during Wave A that should be cleaned up alongside the symbol it was suppressing.

- [ ] **Step 8: Run lint and tests**

Run: `just lint-ci`
Expected: ALL CHECKS PASS (eof-fixer, ruff format, ruff check, ty check). The unused-symbol warnings from Wave A are now resolved by deletion.

Run: `uv run pytest -q`
Expected: 334 passed, 1 skipped.

Run: `uv run pytest tests/unit/test_settings.py -v`
Expected: ALL 13 tests PASS.

Run: `uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

- [ ] **Step 9: Verify file shape sanity**

Run: `wc -l semvertag/_settings.py`
Expected: ~130-140 LOC (was 211 before Wave A; target ~75-85 LOC reduction). If the file is meaningfully larger or smaller than expected, surface the discrepancy — it could indicate something the plan missed.

Run: `grep -nE "_GITLAB_TOKEN_ALIASES|_GITHUB_TOKEN_ALIASES|_PROJECT_ID_ALIASES|_TOKEN_ALIASES_BY_PATH|_TOP_LEVEL_FIELD_ALIASES|_PROVIDER_TO_NESTED_KEY|_PROVIDER_ENV_VAR|_resolve_active_provider|_inject_token|_find_aliased_env|_find_env_value|_inject_token_aliases|_inject_top_level_aliases" semvertag/_settings.py`
Expected: NO matches. All the deleted symbols are gone.

Run: `grep -nE "^import os$" semvertag/_settings.py`
Expected: NO matches.

- [ ] **Step 10: Verify cwd before committing**

```bash
pwd
git branch --show-current
```

The output MUST show the worktree path and branch `feat/settings-aliaschoices`. If not, STOP.

- [ ] **Step 11: Commit**

```bash
git add semvertag/_settings.py
git commit -m "settings: drop hand-coded env-alias machinery superseded by AliasChoices

Delete the 7 alias-map module constants, the 4 helper functions
(_resolve_active_provider, _inject_token, _find_aliased_env,
_find_env_value), and the now-unused 'import os'. The validation
behavior is unchanged; pydantic AliasChoices on the nested
BaseSettings subclasses produces the same precedence."
```

---

## Task 4: Pre-merge verification gate

**Files:** none modified.

- [ ] **Step 1: Lint**

Run: `just lint-ci`
Expected: PASS.

- [ ] **Step 2: Full test suite**

Run: `uv run pytest`
Expected: 334 passed, 1 skipped (no change from baseline; no tests added or removed).

- [ ] **Step 3: Branch-coverage gates (unaffected by this work)**

Run: `just test-branch-strategies`
Expected: 100% on `semvertag.strategies.branch_prefix`.

Run: `just test-cc-strategies`
Expected: 100% on `semvertag.strategies.conventional_commits`.

- [ ] **Step 4: Docs build**

Run: `uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

- [ ] **Step 5: LOC + commit sanity check**

Run: `git diff main --stat -- semvertag/_settings.py`
Expected: net negative ~75-85 LOC (was 211; target ~130-140).

Run: `git log --oneline main..HEAD`
Expected: exactly 2 commits (`settings: route nested token aliases…` and `settings: drop hand-coded env-alias machinery…`).

- [ ] **Step 6: Smoke-test the public API by hand**

```bash
SEMVERTAG_GITLAB__TOKEN=nested SEMVERTAG_TOKEN=flat CI_JOB_TOKEN=ci \
  uv run python -c "from semvertag._settings import Settings; s = Settings(); print('gitlab.token =', s.gitlab.token.get_secret_value())"
```
Expected output: `gitlab.token = nested`

```bash
CI_JOB_TOKEN=ci uv run python -c "from semvertag._settings import Settings; s = Settings(); print('gitlab.token =', s.gitlab.token.get_secret_value())"
```
Expected output: `gitlab.token = ci`

```bash
CI_PROJECT_ID=777 uv run python -c "from semvertag._settings import Settings; s = Settings(); print('project_id =', s.project_id)"
```
Expected output: `project_id = 777`

If any of these produces wrong output, the AliasChoices wiring is not working as expected. Surface it; do not silently adjust.

---

## Task 5: Code review via subagent

**Files:** none modified directly; review may prompt fixup commits.

- [ ] **Step 1: Invoke `superpowers:requesting-code-review`**

Dispatch a code-review subagent against the worktree branch (2 commits between `main` and HEAD).

Brief the reviewer on:
- The work is a refactor: machinery replacement, no behavior change.
- The spec is at `planning/specs/2026-05-31-settings-aliaschoices-design.md`. The "Semantic shift to be aware of" section is the one place behavior changes (both providers' tokens populated even when only one is active); confirm the reviewer accepts this is the intended trade-off.
- Existing tests in `tests/unit/test_settings.py` should pass unchanged. If they had to be modified, that's a regression.
- The 6 smoke-test outputs from Task 4 Step 6 are the practical contract.

- [ ] **Step 2: Process findings with `superpowers:receiving-code-review`**

Use the receiving-code-review skill to evaluate findings. Address legitimate Important/Critical issues with fixup commits in the worktree.

- [ ] **Step 3: Re-run Task 4 if any code changed**

If review prompted any code changes, re-run the full verification gate (Task 4) before proceeding.

---

## Task 6: Land the worktree

**Files:** none modified by hand.

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Use the skill to merge to `main` (fast-forward expected — main shouldn't have moved during this work) and clean up the worktree.

- [ ] **Step 2: Verify the work is on `main`**

Run (in the main checkout): `git log --oneline -3`
Expected: the two settings commits are at HEAD (or two commits below a merge commit if a merge commit was used).

Run: `just lint-ci && uv run pytest -q`
Expected: green on `main`.

Run: `wc -l semvertag/_settings.py`
Expected: ~130-140 LOC (down from 211).

---

## Success criteria

When all tasks above are done:

- `semvertag/_settings.py` no longer contains `_inject_token_aliases`, `_inject_top_level_aliases`, `_resolve_active_provider`, `_inject_token`, `_find_aliased_env`, `_find_env_value`.
- `_settings.py` no longer contains any of the 7 alias-map constants (`_GITLAB_TOKEN_ALIASES`, `_GITHUB_TOKEN_ALIASES`, `_PROJECT_ID_ALIASES`, `_TOKEN_ALIASES_BY_PATH`, `_TOP_LEVEL_FIELD_ALIASES`, `_PROVIDER_TO_NESTED_KEY`, `_PROVIDER_ENV_VAR`).
- `_settings.py` no longer imports `os`.
- `GitLabConfig` and `GitHubConfig` are `pydantic_settings.BaseSettings` subclasses with their own `env_prefix` and `validation_alias=AliasChoices(...)` on their `token` field.
- `Settings.project_id` has `validation_alias=pydantic.AliasChoices("SEMVERTAG_PROJECT_ID", "CI_PROJECT_ID")`.
- All 13 tests in `tests/unit/test_settings.py` pass with **no test changes**.
- `_settings.py` is ~75-85 LOC shorter (from 211 → ~130-140).
- The 6 smoke-test outputs from Task 4 Step 6 all match expected values.
- `just lint-ci`, `uv run pytest`, `mkdocs build --strict` all green.

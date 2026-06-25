# `apply_cli_overlay` Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `apply_cli_overlay` + `_split_overrides` + `_revalidate_nested` (~57 LOC) in `semvertag/_settings.py` with a single 14-line `apply_cli_overlay` that uses `pydantic.BaseModel.model_copy(update=...)` for nested partial updates. Drop the `(value, flag_detail)` tuple shape in `_collect_overrides` in `semvertag/__main__.py`. No behavior change; no test changes.

**Architecture:** Single atomic commit on one worktree. Both file changes are tightly coupled (the override-values type changes simultaneously in producer and consumer) — must land together. Net deletion ~-50 LOC.

**Tech Stack:** `pydantic`, `pydantic-settings`. No new deps.

**Spec:** `planning/specs/2026-05-31-cli-overlay-simplification-design.md`

---

## Task 1: Spawn worktree and verify baseline

**Files:** none in main checkout.

- [ ] **Step 1: Spawn the worktree**

Use the `superpowers:using-git-worktrees` skill. Suggested branch: `feat/cli-overlay-simplification`. Suggested path: `.worktrees/feat-cli-overlay-simplification`.

- [ ] **Step 2: Verify clean baseline inside the worktree**

Run (inside the worktree, after `cd` and `uv sync --all-extras --group lint`):

```bash
pwd
git branch --show-current
git status
```

Expected: cwd is `/Users/kevinsmith/src/pypi/autosemver/.worktrees/feat-cli-overlay-simplification`, branch is `feat/cli-overlay-simplification`, status clean.

Run: `just lint-ci`
Expected: PASS.

Run: `uv run pytest -q`
Expected: 330 passed, 1 skipped.

Run: `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

If any baseline check fails, stop and report.

---

## Task 2: Atomic refactor in one commit

The override-values type changes simultaneously in both producer (`_collect_overrides`) and consumer (`apply_cli_overlay`). They MUST land in one commit.

**Files:**
- Modify: `semvertag/_settings.py` (replace 3 functions with 1)
- Modify: `semvertag/__main__.py` (simplify `_collect_overrides`)

### CRITICAL: Verify cwd before any git operation

Before EVERY `git add` and `git commit`, run:

```bash
pwd
git branch --show-current
```

The output MUST show:
- pwd: `/Users/kevinsmith/src/pypi/autosemver/.worktrees/feat-cli-overlay-simplification`
- branch: `feat/cli-overlay-simplification`

If either is wrong, STOP. Use absolute paths (starting with the worktree path) for Edit operations. Previous plan executions had implementers accidentally edit files on main.

### Step 1: Replace `apply_cli_overlay` body and delete helpers in `semvertag/_settings.py`

Find the existing `apply_cli_overlay` function (currently lines 91-102), `_split_overrides` (lines 105-128), and `_revalidate_nested` (lines 131-147). Replace all three with the single function below.

Use a single Edit operation that replaces the block from `def apply_cli_overlay(` through the end of `_revalidate_nested`. The exact text to find:

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
    return new_settings


def _split_overrides(
    settings: Settings,
    overrides: dict[str, tuple[typing.Any, str]],
) -> tuple[dict[str, typing.Any], dict[str, dict[str, typing.Any]]]:
    update_top: dict[str, typing.Any] = {}
    nested_updates: dict[str, dict[str, typing.Any]] = {}
    settings_fields: typing.Final = type(settings).model_fields

    for dotted_key, (value, _flag_detail) in overrides.items():
        if "." in dotted_key:
            head, _, leaf = dotted_key.partition(".")
            if "." in leaf:
                msg = f"CLI overlay key '{dotted_key}' exceeds nesting depth 2."
                raise ValueError(msg)
            if head not in settings_fields:
                msg = f"Unknown CLI overlay target: {head!r}."
                raise ValueError(msg)
            nested_updates.setdefault(head, {})[leaf] = value
        else:
            if dotted_key not in settings_fields:
                msg = f"Unknown CLI overlay target: {dotted_key!r}."
                raise ValueError(msg)
            update_top[dotted_key] = value
    return update_top, nested_updates


def _revalidate_nested(
    settings: Settings,
    head: str,
    leaf_updates: dict[str, typing.Any],
) -> pydantic.BaseModel:
    nested: typing.Final = getattr(settings, head)
    if not isinstance(nested, pydantic.BaseModel):
        msg = f"CLI overlay target '{head}' is not a pydantic BaseModel."
        raise TypeError(msg)
    nested_fields: typing.Final = type(nested).model_fields
    for leaf in leaf_updates:
        if leaf not in nested_fields:
            msg = f"Unknown CLI overlay target: {head}.{leaf!r}."
            raise ValueError(msg)
    nested_data: typing.Final = {name: getattr(nested, name) for name in nested_fields}
    nested_data.update(leaf_updates)
    return type(nested).model_validate(nested_data)
```

Replace with:

```python
def apply_cli_overlay(settings: Settings, overrides: dict[str, typing.Any]) -> Settings:
    top_updates: dict[str, typing.Any] = {}
    nested_updates: dict[str, dict[str, typing.Any]] = {}
    for dotted_key, value in overrides.items():
        head, _, leaf = dotted_key.partition(".")
        if "." in leaf:
            msg = f"CLI overlay key '{dotted_key}' exceeds nesting depth 2."
            raise ValueError(msg)
        if leaf:
            nested_updates.setdefault(head, {})[leaf] = value
        else:
            top_updates[head] = value
    for head, leaves in nested_updates.items():
        top_updates[head] = getattr(settings, head).model_copy(update=leaves)
    copied = settings.model_copy(update=top_updates)
    # Re-validate to trigger field validators (e.g. _clamp_request_timeout).
    # getattr (not model_dump) preserves live SecretStr values.
    return type(settings).model_validate({name: getattr(copied, name) for name in type(copied).model_fields})
```

### Step 2: Verify imports in `_settings.py` are still all used

Run: `uv run ruff check semvertag/_settings.py`

Expected: PASS (or only style issues, not unused-import errors). The new `apply_cli_overlay` still uses `typing`, `pydantic` (via model_validate / model_copy on BaseModel subclasses). No imports become orphans.

If `pydantic` is flagged unused: don't act — pydantic is still imported because `Settings` uses `pydantic.Field` / `pydantic.SecretStr` / `pydantic.AliasChoices`. The lint check shouldn't fire; if it does, investigate before changing anything.

### Step 3: Simplify `_collect_overrides` in `semvertag/__main__.py`

Find `_collect_overrides` (currently lines 40-65). The current body wraps each value in a `(value, "--flag-name")` tuple. Replace the entire function with:

```python
def _collect_overrides(  # noqa: PLR0913
    *,
    project_id: int | None,
    strategy: str | None,
    provider: str | None,
    token: str | None,
    default_branch: str | None,
    gitlab_endpoint: str | None,
    request_timeout: float | None,
) -> dict[str, typing.Any]:
    overrides: dict[str, typing.Any] = {}
    if project_id is not None:
        overrides["project_id"] = project_id
    if strategy is not None:
        overrides["strategy"] = strategy
    if provider is not None:
        overrides["provider"] = provider
    if token is not None:
        overrides["gitlab.token"] = pydantic.SecretStr(token)
    if default_branch is not None:
        overrides["default_branch"] = default_branch
    if gitlab_endpoint is not None:
        overrides["gitlab.endpoint"] = gitlab_endpoint
    if request_timeout is not None:
        overrides["request_timeout"] = request_timeout
    return overrides
```

Two changes from the current version:
- Return type annotation: `dict[str, tuple[typing.Any, str]]` → `dict[str, typing.Any]`
- Each assignment drops the `(value, "--flag-name")` tuple wrapper

### Step 4: Run the full test suite

```bash
uv run pytest -q
```

Expected: **330 passed, 1 skipped** (unchanged from baseline; no test count change).

If any test fails, READ the failure. Common pitfalls:
- `TypeError: cannot unpack non-iterable` in `_collect_overrides` callers — but there's only one caller (`_main_callback`), so this shouldn't happen unless the caller wasn't updated. The caller passes the dict directly to `apply_cli_overlay`, no unpacking; no change needed there.
- `AttributeError` on a model_copy result — `model_copy(update=...)` on a `BaseSettings` subclass should return the same subclass; verify by running `tests/integration/test_cli_main_verb.py` specifically.
- `ValidationError` complaints about `SecretStr` masking — the `model_validate({name: getattr(copied, name) ...})` round-trip preserves live SecretStr objects; verify token still flows correctly via the CLI smoke test.

Do NOT silently mask bugs.

### Step 5: Lint check

```bash
just lint-ci
```

Expected: PASS. If ruff/ty flag unused imports we missed, fix them.

### Step 6: Targeted regression smoke tests

```bash
uv run semvertag --version
```
Expected: prints version. Exit 0.

```bash
uv run semvertag tag
```
Expected: fails with `Error: Project id missing. Set CI_PROJECT_ID or pass --project-id.` Exit code 2.

```bash
SEMVERTAG_PROJECT_ID=999 SEMVERTAG_TOKEN=fake-token uv run semvertag --project-id 1234 tag
```
Expected: fails with a network error or auth error (no real GitLab access). The `--project-id 1234` should override the env `999` — verify the error message references `1234`, not `999`, to confirm CLI overlay still works.

```bash
SEMVERTAG_PROJECT_ID=999 uv run semvertag --strategy conventional-commits tag
```
Expected: fails (no token), but the failure path should reach `_build_current_strategy` (which checks `settings.strategy == "conventional-commits"`). If the CLI overlay broke, the strategy would fall back to `branch-prefix`. Hard to verify without setting up full mocks, but the call should at least not throw a `ValidationError`.

### Step 7: Docs build

```bash
UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict
```
Expected: builds clean.

### Step 8: Verify cwd before committing

```bash
pwd
git branch --show-current
```

MUST show worktree path and `feat/cli-overlay-simplification`. If wrong, STOP.

### Step 9: Verify LOC delta

```bash
wc -l semvertag/_settings.py
```
Expected: ~106 LOC (down from 147).

```bash
git diff main --shortstat
```
Expected: ~50 LOC net deletion, 2 files changed.

### Step 10: Commit

```bash
git add semvertag/_settings.py semvertag/__main__.py
git commit -m "settings: collapse apply_cli_overlay into 14 LOC via pydantic model_copy

Replace apply_cli_overlay + _split_overrides + _revalidate_nested
(~57 LOC) with a single 14-line apply_cli_overlay that uses
pydantic.BaseModel.model_copy(update=...) for nested partial updates.

Drop the (value, flag_detail) tuple shape from overrides — flag_detail
was scaffolding for the _provenance tracking that drop-doctor removed.
Pyright was already flagging it as unused.

Drop the unknown-key validation; _collect_overrides hard-codes all
override keys, so misspellings are implementer bugs caught by
lint/tests, not user-facing concerns. Pydantic ValidationError covers
any drift.

_collect_overrides in __main__.py simplifies correspondingly: returns
dict[str, Any] instead of dict[str, tuple[Any, str]]; 8 if-blocks
drop the (value, '--flag') tuple wrapping.

Net: ~-50 LOC across two files. No behavior change; no test changes
(no test references the simplified internals; CLI integration tests
verify end-to-end behavior unchanged)."
```

---

## Task 3: Pre-merge verification gate

**Files:** none modified.

- [ ] **Step 1: Lint**

Run: `just lint-ci`
Expected: PASS.

- [ ] **Step 2: Full test suite**

Run: `uv run pytest`
Expected: 330 passed, 1 skipped (unchanged).

- [ ] **Step 3: Branch-coverage gates (unaffected by this work)**

Run: `just test-branch-strategies`
Expected: 100% on `semvertag.strategies.branch_prefix`.

Run: `just test-cc-strategies`
Expected: 100% on `semvertag.strategies.conventional_commits`.

- [ ] **Step 4: Docs build**

Run: `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

- [ ] **Step 5: LOC + commit sanity check**

Run: `git diff main --shortstat`
Expected: 2 files changed, ~50 LOC net deletion.

Run: `git log --oneline main..HEAD`
Expected: exactly 1 commit (`settings: collapse apply_cli_overlay...`).

---

## Task 4: Land the worktree

**Files:** none modified by hand.

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Use the skill to merge to `main` (fast-forward expected — main shouldn't have moved during this work) and clean up the worktree.

- [ ] **Step 2: Verify the work is on `main`**

Run (in the main checkout): `git log --oneline -3`
Expected: the `settings: collapse apply_cli_overlay…` commit is at HEAD.

Run: `just lint-ci && uv run pytest -q`
Expected: green on `main`; 330 passed, 1 skipped.

Run: `grep -n "_split_overrides\|_revalidate_nested" semvertag/`
Expected: NO matches (both helpers deleted).

Run: `grep -n "flag_detail\|tuple\[typing.Any, str\]" semvertag/`
Expected: NO matches.

Run: `wc -l semvertag/_settings.py`
Expected: ~106 LOC.

---

## Success criteria

When all tasks above are done:

- `semvertag/_settings.py` no longer contains `_split_overrides` or `_revalidate_nested` (deleted).
- `apply_cli_overlay` body is ~14 LOC and uses `model_copy(update=...)` on nested configs.
- `apply_cli_overlay` signature accepts `dict[str, typing.Any]` (no tuple wrapping).
- `_collect_overrides` in `semvertag/__main__.py` returns `dict[str, typing.Any]`; 7 if-blocks drop the `(value, "--flag")` tuple wrapping.
- All 330 tests pass; no test changes.
- `_settings.py` is meaningfully shorter (~106 LOC; was 147).
- 4 smoke tests produce expected output.
- `just lint-ci`, `uv run pytest`, `mkdocs build --strict` all green.

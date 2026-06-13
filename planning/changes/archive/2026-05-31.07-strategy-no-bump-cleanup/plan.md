---
status: shipped
date: 2026-05-31
slug: strategy-no-bump-cleanup
spec: strategy-no-bump-cleanup
pr: null
---

# Strategy No-Bump Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move strategy-specific "why I returned `Bump.NONE`" text from `_status_for_no_bump` / `_reason_for_no_bump` helpers in `_use_case.py` onto each strategy class as `ClassVar[str]`, paralleling the existing `name: ClassVar[str]` pattern. Each strategy that can return `Bump.NONE` declares its own status + reason.

**Architecture:** Single atomic commit on one worktree. The `BumpStrategy` Protocol gains 2 fields, both concrete strategies declare them as `ClassVar`, `_use_case.py` reads them directly (drops 2 helpers + 2 constants), and the test stub gains matching defaults. 5 files; the Protocol change must land with all conformers + the consumer + the test stub at once.

**Tech Stack:** Existing — `dataclasses`, `typing.Protocol`, `typing.ClassVar`. No new deps.

**Spec:** `planning/specs/2026-05-31-strategy-no-bump-cleanup-design.md`

---

## Task 1: Spawn worktree and verify baseline

**Files:** none in main checkout.

- [ ] **Step 1: Spawn the worktree**

Use the `superpowers:using-git-worktrees` skill. Suggested branch: `feat/strategy-no-bump-cleanup`. Suggested path: `.worktrees/feat-strategy-no-bump-cleanup`.

- [ ] **Step 2: Verify clean baseline inside the worktree**

Run (inside the worktree, after `cd` and `uv sync --all-extras --group lint`):

```bash
pwd
git branch --show-current
git status
```

Expected: cwd is `/Users/kevinsmith/src/pypi/autosemver/.worktrees/feat-strategy-no-bump-cleanup`, branch is `feat/strategy-no-bump-cleanup`, status clean.

Run: `just lint-ci`
Expected: PASS.

Run: `uv run pytest -q`
Expected: 330 passed, 1 skipped.

If any baseline check fails, stop and report.

---

## Task 2: Atomic refactor in one commit

The Protocol change must land with all conformers (both strategy classes + the test stub) and the consumer (`_use_case.py`) at once.

**Files:**
- Modify: `semvertag/strategies/_base.py` (add 2 Protocol fields)
- Modify: `semvertag/strategies/branch_prefix.py` (add 2 ClassVar declarations)
- Modify: `semvertag/strategies/conventional_commits.py` (add 2 ClassVar declarations)
- Modify: `semvertag/_use_case.py` (delete 2 helpers + 2 constants; update one branch)
- Modify: `tests/unit/test_use_case.py` (add 2 fields to `_StubStrategy`)

### CRITICAL: Verify cwd before any git operation

Before EVERY `git add` and `git commit`, run:

```bash
pwd
git branch --show-current
```

The output MUST show:
- pwd: `/Users/kevinsmith/src/pypi/autosemver/.worktrees/feat-strategy-no-bump-cleanup`
- branch: `feat/strategy-no-bump-cleanup`

If either is wrong, STOP. Use absolute paths (starting with the worktree path) for Edit operations.

### Step 1: Add 2 fields to the `BumpStrategy` Protocol

In `semvertag/strategies/_base.py`, find the current Protocol (currently 5 lines after imports):

```python
class BumpStrategy(typing.Protocol):
    name: str

    def decide(self, commit: Commit) -> Bump: ...
```

Replace with:

```python
class BumpStrategy(typing.Protocol):
    name: str
    no_bump_status: str
    no_bump_reason: str

    def decide(self, commit: Commit) -> Bump: ...
```

### Step 2: Add ClassVars to `BranchPrefixStrategy`

In `semvertag/strategies/branch_prefix.py`, find the `BranchPrefixStrategy` class (currently lines 21-24, before the `decide` method):

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class BranchPrefixStrategy:
    name: typing.ClassVar[str] = "branch-prefix"
    config: BranchPrefixConfig
```

Replace with:

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class BranchPrefixStrategy:
    name: typing.ClassVar[str] = "branch-prefix"
    no_bump_status: typing.ClassVar[str] = "no_merge_commit"
    no_bump_reason: typing.ClassVar[str] = "Latest commit on default branch is not a merge commit."
    config: BranchPrefixConfig
```

Don't touch the `decide` method or the rest of the file.

### Step 3: Add ClassVars to `ConventionalCommitsStrategy`

In `semvertag/strategies/conventional_commits.py`, find the `ConventionalCommitsStrategy` class (currently lines 32-35, before the `decide` method):

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class ConventionalCommitsStrategy:
    name: typing.ClassVar[str] = "conventional-commits"
    config: ConventionalCommitsConfig
```

Replace with:

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class ConventionalCommitsStrategy:
    name: typing.ClassVar[str] = "conventional-commits"
    no_bump_status: typing.ClassVar[str] = "no_conforming_commit"
    no_bump_reason: typing.ClassVar[str] = "No conforming Conventional Commits type found in commit message."
    config: ConventionalCommitsConfig
```

### Step 4: Update `_use_case.py` to read from the strategy + delete dead helpers/constants

In `semvertag/_use_case.py`:

**4a. Delete the 2 strategy-specific constants** (currently lines 12-13):

```python
_NO_MERGE_REASON: typing.Final = "Latest commit on default branch is not a merge commit."
_NO_CONFORMING_REASON: typing.Final = "No conforming Conventional Commits type found in commit message."
```

Keep `_NO_TAGS_REASON` and `_ALREADY_TAGGED_REASON` (they're strategy-independent — about repo state).

**4b. Update the `if bump is Bump.NONE:` branch** (currently lines 54-62 inside `__call__`):

```python
if bump is Bump.NONE:
    return self._emit(
        output=output,
        bump=Bump.NONE,
        status=_status_for_no_bump(self.strategy.name),
        tag=None,
        commit=commit.sha,
        reason=_reason_for_no_bump(self.strategy.name),
    )
```

Replace with:

```python
if bump is Bump.NONE:
    return self._emit(
        output=output,
        bump=Bump.NONE,
        status=self.strategy.no_bump_status,
        tag=None,
        commit=commit.sha,
        reason=self.strategy.no_bump_reason,
    )
```

**4c. Delete the 2 helper functions** (currently lines 132-141, at module level near the end):

```python
def _status_for_no_bump(strategy_name: str) -> str:
    if strategy_name == "branch-prefix":
        return "no_merge_commit"
    return "no_conforming_commit"


def _reason_for_no_bump(strategy_name: str) -> str:
    if strategy_name == "branch-prefix":
        return _NO_MERGE_REASON
    return _NO_CONFORMING_REASON
```

Delete both functions entirely.

### Step 5: Add defaults to `_StubStrategy` in `tests/unit/test_use_case.py`

In `tests/unit/test_use_case.py`, find `_StubStrategy` (currently lines 68-74):

```python
@dataclasses.dataclass(slots=True, kw_only=True)
class _StubStrategy:
    name: str
    bump_to_return: Bump

    def decide(self, commit: Commit) -> Bump:  # noqa: ARG002
        return self.bump_to_return
```

Replace with:

```python
@dataclasses.dataclass(slots=True, kw_only=True)
class _StubStrategy:
    name: str
    no_bump_status: str = "no_merge_commit"
    no_bump_reason: str = "Latest commit on default branch is not a merge commit."
    bump_to_return: Bump

    def decide(self, commit: Commit) -> Bump:  # noqa: ARG002
        return self.bump_to_return
```

Both new fields default to branch-prefix values (most existing tests use branch-prefix-shaped stubs).

### Step 6: Update the conventional-commits no-bump test to override the defaults

In the same file, find `test_skips_with_no_conforming_commit_under_conventional_commits_when_bump_is_none` (currently lines 141-151). The test currently uses `_make_use_case(..., strategy_name=_CONVENTIONAL_STRATEGY)` which creates a `_StubStrategy(name="conventional-commits", bump_to_return=Bump.NONE)` — with the new default fields, this stub would report `no_bump_status="no_merge_commit"` (wrong for conventional-commits).

The test asserts `result.status == "no_conforming_commit"`, which now requires the stub to have `no_bump_status="no_conforming_commit"`.

**Two ways to fix this:**

**Option A (recommended): make `_make_use_case` factory derive the no-bump fields from `strategy_name`** — preserves all test call sites unchanged. Edit `_make_use_case` (currently lines 77-95) to look up the no-bump values per strategy name:

```python
_NO_BUMP_STATUS_BY_STRATEGY: typing.Final = {
    _BRANCH_PREFIX_STRATEGY: "no_merge_commit",
    _CONVENTIONAL_STRATEGY: "no_conforming_commit",
}
_NO_BUMP_REASON_BY_STRATEGY: typing.Final = {
    _BRANCH_PREFIX_STRATEGY: "Latest commit on default branch is not a merge commit.",
    _CONVENTIONAL_STRATEGY: "No conforming Conventional Commits type found in commit message.",
}


def _make_use_case(
    *,
    commit_message: str = _MERGE_MESSAGE,
    commit_sha: str = _LATEST_SHA,
    tags: list[Tag] | None = None,
    bump: Bump = Bump.MINOR,
    strategy_name: str = _BRANCH_PREFIX_STRATEGY,
) -> tuple[SemvertagUseCase, _StubProvider, _RecordingOutput]:
    provider: typing.Final = _StubProvider(
        commit=Commit(sha=commit_sha, message=commit_message),
        tags=tags if tags is not None else [Tag(name=_LATEST_TAG_NAME, commit_sha=_PRIOR_SHA)],
    )
    strategy: typing.Final = _StubStrategy(
        name=strategy_name,
        no_bump_status=_NO_BUMP_STATUS_BY_STRATEGY[strategy_name],
        no_bump_reason=_NO_BUMP_REASON_BY_STRATEGY[strategy_name],
        bump_to_return=bump,
    )
    output: typing.Final = _RecordingOutput()
    use_case: typing.Final = SemvertagUseCase(
        provider=typing.cast("typing.Any", provider),
        strategy=typing.cast("typing.Any", strategy),
    )
    return use_case, provider, output
```

Place the two constants near the other module-level test constants (above `_make_use_case`). The factory now derives the stub's `no_bump_status` / `no_bump_reason` from `strategy_name`, so every existing test call site works unchanged. The defaults on `_StubStrategy` itself (set in Step 5) remain as safety nets but aren't exercised by `_make_use_case`.

This makes the test plumbing mirror the dispatch shape that the production code USED to have — but only in tests, where it's stipulation, not logic. Production code is free of the string-identity branch.

**Option B (alternative, more verbose): update only the CC test to pass the values explicitly.** Reject this if you can; option A is cleaner for the existing 5+ tests that go through the factory.

### Step 7: Run pytest

```bash
uv run pytest -q
```

Expected: **330 passed, 1 skipped** (unchanged from baseline; no tests added or removed).

If any test fails, READ the failure. Common pitfalls:
- `AttributeError: '_StubStrategy' object has no attribute 'no_bump_status'` — Step 5 wasn't applied
- `KeyError: 'unexpected-strategy-name'` — a test uses a `strategy_name` value not in `_NO_BUMP_STATUS_BY_STRATEGY`; add it to the map, OR (if the test only sets `name` for the `Detected strategy:` progress message and never triggers the Bump.NONE path) call `_make_use_case` differently
- `AssertionError: result.reason != ...` — the constant text values must match exactly between the strategy ClassVar and what tests assert on. Re-check the text in Step 2 / Step 3.

Do NOT silently mask bugs.

### Step 8: Lint check

```bash
just lint-ci
```

Expected: PASS. If ruff/ty flag unused imports we missed (e.g., the now-unused `_NO_MERGE_REASON`/`_NO_CONFORMING_REASON` references — but those should be gone from `_use_case.py` per Step 4a), fix them.

### Step 9: Branch-coverage gates (the strategy modules now have 2 more declared attributes)

```bash
just test-branch-strategies
just test-cc-strategies
```
Expected: both still 100% on their respective strategy modules. The new ClassVar declarations are statements that need execution at class-definition time, which happens during import — coverage should naturally hit them.

### Step 10: Smoke test the CLI

```bash
uv run semvertag tag
```
Expected: fails with `Error: Project id missing. Set CI_PROJECT_ID or pass --project-id.` Exit 2.

```bash
uv run semvertag --version
```
Expected: prints version (e.g., "0"). Exit 0.

If anything diverges from main, surface it.

### Step 11: Docs build

```bash
UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict
```
Expected: builds clean.

### Step 12: Verify file LOC + cwd

```bash
wc -l semvertag/_use_case.py
```
Expected: ~127 LOC (down from 142; ~-15 LOC from deleting 2 helpers + 2 constants).

```bash
pwd
git branch --show-current
```
MUST show worktree path and `feat/strategy-no-bump-cleanup`. If wrong, STOP.

### Step 13: Commit

```bash
git add semvertag/strategies/_base.py semvertag/strategies/branch_prefix.py semvertag/strategies/conventional_commits.py semvertag/_use_case.py tests/unit/test_use_case.py
git commit -m "strategies: hoist no-bump status/reason to strategy ClassVars

Move strategy-specific 'why I returned Bump.NONE' text from
_status_for_no_bump / _reason_for_no_bump helpers in _use_case.py
onto each strategy class as ClassVar[str], paralleling the existing
name: ClassVar[str] pattern. The BumpStrategy Protocol gains
no_bump_status and no_bump_reason fields.

_use_case.py drops the two helpers, the _NO_MERGE_REASON and
_NO_CONFORMING_REASON constants, and the string-identity branching.
The use case body now reads self.strategy.no_bump_status and
self.strategy.no_bump_reason directly.

_StubStrategy in test_use_case.py gains matching default fields.
The _make_use_case factory derives the stub's no-bump fields from
strategy_name via a small lookup map, keeping every existing test
call site unchanged.

Structural value: adding a third strategy in the future requires no
edit to _use_case.py."
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

- [ ] **Step 3: Branch-coverage gates**

Run: `just test-branch-strategies`
Expected: 100% on `semvertag.strategies.branch_prefix`.

Run: `just test-cc-strategies`
Expected: 100% on `semvertag.strategies.conventional_commits`.

- [ ] **Step 4: Docs build**

Run: `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

- [ ] **Step 5: LOC + commit sanity check**

Run: `git diff main --shortstat`
Expected: 5 files changed; ~5-10 LOC net change (small positive in strategies/test, larger negative in _use_case.py).

Run: `git log --oneline main..HEAD`
Expected: exactly 1 commit (`strategies: hoist no-bump status/reason...`).

Run: `grep -n "_status_for_no_bump\|_reason_for_no_bump\|_NO_MERGE_REASON\|_NO_CONFORMING_REASON" semvertag/`
Expected: NO matches.

Run: `grep -n "no_bump_status\|no_bump_reason" semvertag/strategies/`
Expected: 4 matches (2 per concrete strategy file: one ClassVar declaration, one in `BumpStrategy` Protocol).

---

## Task 4: Land the worktree

**Files:** none modified by hand.

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Use the skill to merge to `main` (fast-forward expected — main shouldn't have moved during this work) and clean up the worktree.

- [ ] **Step 2: Verify the work is on `main`**

Run (in the main checkout): `git log --oneline -3`
Expected: the `strategies: hoist no-bump status/reason...` commit is at HEAD.

Run: `just lint-ci && uv run pytest -q`
Expected: green on `main`; 330 passed, 1 skipped.

Run: `grep -n "_status_for_no_bump\|_reason_for_no_bump" semvertag/`
Expected: NO matches (modulo `_archive/`).

Run: `wc -l semvertag/_use_case.py`
Expected: ~127 LOC.

---

## Success criteria

When all tasks above are done:

- `BumpStrategy` Protocol in `semvertag/strategies/_base.py` has `no_bump_status: str` and `no_bump_reason: str` fields.
- `BranchPrefixStrategy` and `ConventionalCommitsStrategy` each declare `no_bump_status` and `no_bump_reason` as `ClassVar[str]` with the values that previously lived in `_use_case.py`.
- `semvertag/_use_case.py` no longer contains `_status_for_no_bump`, `_reason_for_no_bump`, `_NO_MERGE_REASON`, or `_NO_CONFORMING_REASON`.
- `_use_case.py`'s `if bump is Bump.NONE:` branch reads `self.strategy.no_bump_status` and `self.strategy.no_bump_reason` directly.
- `_StubStrategy` in `tests/unit/test_use_case.py` has matching default fields; `_make_use_case` derives them from `strategy_name` via a lookup map.
- All 330 tests pass; CLI behavior unchanged (smoke tests confirm).
- `_use_case.py` is meaningfully shorter (~127 LOC; was 142).
- `just lint-ci`, `uv run pytest`, `mkdocs build --strict` all green.

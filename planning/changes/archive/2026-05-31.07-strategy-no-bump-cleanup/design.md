---
status: shipped
date: 2026-05-31
slug: strategy-no-bump-cleanup
supersedes: null
superseded_by: null
pr: null
outcome: shipped in the pre-1.0 bootstrap (no-bump return path)
---

# Move strategy-specific no-bump explanation onto the strategy classes

**Date:** 2026-05-31
**Status:** Approved, ready for plan
**Author:** brainstorm session (Superpowers `brainstorming` skill)

## Context

`_use_case.py` contains two helper functions that branch on
`strategy.name` to look up strategy-specific text:

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

Each strategy already declares `name: typing.ClassVar[str]` as part of
the `BumpStrategy` protocol. The same pattern can carry the no-bump
explanation: every strategy that can return `Bump.NONE` knows *why* it
did, and that text should live with the strategy, not be looked up by
the use case via string matching.

Today this is a 2-strategy codebase, so the cost is minimal. But the
branching has two real costs:

1. **Adding a third strategy requires editing `_use_case.py`** — the
   helpers' implicit "else" assumes conventional-commits, which silently
   binds new strategies to the conventional-commits status/reason text.
2. **Strategy text is coupled to strategy identity by string** — a
   typo in `strategy.name` ("branch_prefix" vs "branch-prefix") would
   silently pick the wrong reason.

The fix: hoist `no_bump_status` and `no_bump_reason` to `ClassVar[str]`
on each strategy, expose them in the `BumpStrategy` Protocol, and have
the use case read them directly.

## Decisions

| Question | Decision |
| --- | --- |
| Where do strategy-specific texts live? | On the strategy class as `ClassVar[str]`, paralleling `name` |
| Add new fields to `BumpStrategy` Protocol? | Yes — `no_bump_status: str` and `no_bump_reason: str` |
| Refactor `decide()` to return richer data (`BumpDecision` type)? | No — overkill for static-per-strategy explanations; keep `decide()` returning `Bump` |
| Migrate strategy-independent constants too (`_NO_TAGS_REASON`, `_ALREADY_TAGGED_REASON`)? | No — they describe repo state, not strategy behavior; stay in `_use_case.py` |
| Test changes | Minimal — add 2 fields to `_StubStrategy` in `test_use_case.py` |

## Architecture

### `BumpStrategy` Protocol gains 2 attributes

`semvertag/strategies/_base.py`:

```python
class BumpStrategy(typing.Protocol):
    name: str
    no_bump_status: str
    no_bump_reason: str

    def decide(self, commit: Commit) -> Bump: ...
```

### Concrete strategies gain 2 `ClassVar[str]` declarations each

`semvertag/strategies/branch_prefix.py`:

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class BranchPrefixStrategy:
    name: typing.ClassVar[str] = "branch-prefix"
    no_bump_status: typing.ClassVar[str] = "no_merge_commit"
    no_bump_reason: typing.ClassVar[str] = "Latest commit on default branch is not a merge commit."
    config: BranchPrefixConfig

    def decide(self, commit: Commit) -> Bump:
        # ... unchanged ...
```

`semvertag/strategies/conventional_commits.py`:

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class ConventionalCommitsStrategy:
    name: typing.ClassVar[str] = "conventional-commits"
    no_bump_status: typing.ClassVar[str] = "no_conforming_commit"
    no_bump_reason: typing.ClassVar[str] = "No conforming Conventional Commits type found in commit message."
    config: ConventionalCommitsConfig

    def decide(self, commit: Commit) -> Bump:
        # ... unchanged ...
```

### `_use_case.py` reads strategy attributes directly

Replace:

```python
status=_status_for_no_bump(self.strategy.name),
# ...
reason=_reason_for_no_bump(self.strategy.name),
```

With:

```python
status=self.strategy.no_bump_status,
# ...
reason=self.strategy.no_bump_reason,
```

Delete:

- `_status_for_no_bump` function (5 LOC)
- `_reason_for_no_bump` function (5 LOC)
- `_NO_MERGE_REASON` constant (1 LOC, value migrated to `BranchPrefixStrategy`)
- `_NO_CONFORMING_REASON` constant (1 LOC, value migrated to `ConventionalCommitsStrategy`)

Keep:

- `_NO_TAGS_REASON` (repo state, not strategy)
- `_ALREADY_TAGGED_REASON` (repo state, not strategy)

### Test stub update

`tests/unit/test_use_case.py` defines `_StubStrategy` as a duck-typed
stand-in for `BumpStrategy`. It needs the 2 new fields:

```python
@dataclasses.dataclass(slots=True, kw_only=True)
class _StubStrategy:
    name: str = "stub"
    no_bump_status: str = "no_merge_commit"
    no_bump_reason: str = "Latest commit on default branch is not a merge commit."
    bump_to_return: Bump = Bump.MINOR
    # ... existing decide method ...
```

Defaults match the branch-prefix values because most existing tests
use branch-prefix-shaped stubs. Tests that exercise the
conventional-commits no-bump path need to override these defaults
explicitly — verify by running the suite after the change.

## What gets touched

| File | Change |
|---|---|
| `semvertag/strategies/_base.py` | Add 2 fields to `BumpStrategy` Protocol |
| `semvertag/strategies/branch_prefix.py` | Add 2 `ClassVar[str]` declarations to `BranchPrefixStrategy` |
| `semvertag/strategies/conventional_commits.py` | Add 2 `ClassVar[str]` declarations to `ConventionalCommitsStrategy` |
| `semvertag/_use_case.py` | Delete 2 helpers + 2 constants; update one `if bump is Bump.NONE:` branch |
| `tests/unit/test_use_case.py` | Add 2 fields to `_StubStrategy`; verify suite passes; explicitly override defaults in any test that exercises the conventional-commits no-bump path |

### Estimated delta

| File | Delta |
|---|---|
| `_base.py` | +2 LOC |
| `branch_prefix.py` | +2 LOC |
| `conventional_commits.py` | +2 LOC |
| `_use_case.py` | -14 LOC (delete 2 helpers + 2 constants; trim the branch body) |
| `test_use_case.py` | +2 to +6 LOC (depending on how many tests need explicit overrides) |
| **Net** | **~-4 to -6 LOC** |

Value isn't LOC — it's structural: adding a third strategy in the
future requires no edit to `_use_case.py`. The "branching on string
identity" smell is gone.

## What stays unchanged

- `decide(commit) -> Bump` signature on strategies
- `_NO_TAGS_REASON` and `_ALREADY_TAGGED_REASON` constants in `_use_case.py`
  (strategy-independent; about repo state, not bump decision)
- All test names and assertion strings — tests still verify the same
  `result.status` and `result.reason` values
- `BumpStrategy` Protocol's `decide` method
- The two strategy implementations' `decide()` logic

## Execution sequencing

Schema change (Protocol gains fields) must land with all conformers
(both strategy classes + the test stub) and the consumer (`_use_case.py`)
at once. **One atomic commit on one worktree.**

### Worktree setup

Spawn `feat/strategy-no-bump-cleanup` off `main`, path
`.worktrees/feat-strategy-no-bump-cleanup`. Baseline:
`just lint-ci && uv run pytest -q` should pass (330 / 1 skipped on
current main).

### Single wave — full refactor

Edits land in this order (for diff readability):

1. `semvertag/strategies/_base.py` — add 2 Protocol fields
2. `semvertag/strategies/branch_prefix.py` — add 2 ClassVar declarations
3. `semvertag/strategies/conventional_commits.py` — add 2 ClassVar declarations
4. `semvertag/_use_case.py` — replace 2 helper calls with direct attribute access; delete helpers + 2 constants
5. `tests/unit/test_use_case.py` — add 2 fields to `_StubStrategy`; adjust any tests that depend on conventional-commits defaults

### Gate after the wave

- `just lint-ci` — PASS
- `uv run pytest -q` — 330 passed, 1 skipped (unchanged)
- `just test-branch-strategies && just test-cc-strategies` — still 100% on
  the strategy modules (these now have 2 more declared attributes; verify
  coverage)
- `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict` —
  clean
- Smoke test: `uv run semvertag tag` (no creds) — same "Project id missing"
  error + exit 2 as on main

### Commit message

```
strategies: hoist no-bump status/reason to strategy ClassVars

Move strategy-specific "why I returned Bump.NONE" text from
_status_for_no_bump / _reason_for_no_bump helpers in _use_case.py
onto each strategy class as ClassVar[str], paralleling the existing
name: ClassVar[str] pattern. The BumpStrategy Protocol gains
no_bump_status and no_bump_reason fields.

_use_case.py drops the two helpers, the _NO_MERGE_REASON and
_NO_CONFORMING_REASON constants, and the string-identity branching.
The use case body now reads self.strategy.no_bump_status and
self.strategy.no_bump_reason directly.

_StubStrategy in test_use_case.py gains matching default fields.

Structural value: adding a third strategy in the future requires no
edit to _use_case.py.
```

### Code review

Skip the formal subagent code review — mechanical change, no behavior
change, the gate covers the contract.

### Land

`superpowers:finishing-a-development-branch` — fast-forward expected.

## Success criteria

When all of these hold, this spec is done:

- `BumpStrategy` Protocol has `no_bump_status: str` and `no_bump_reason: str`
- `BranchPrefixStrategy` and `ConventionalCommitsStrategy` each declare
  both as `ClassVar[str]` with the values previously hard-coded in
  `_use_case.py`
- `_use_case.py` no longer contains `_status_for_no_bump`,
  `_reason_for_no_bump`, `_NO_MERGE_REASON`, or `_NO_CONFORMING_REASON`
- `_use_case.py` no longer references `self.strategy.name` for picking
  status/reason text (only for the `output.progress(f"Detected strategy: ...")`
  message and the `RunResult(strategy=...)` field, both of which are
  legitimate)
- All 330 tests pass; test stub updated
- Smoke test confirms CLI behavior unchanged
- `just lint-ci`, `uv run pytest`, `mkdocs build --strict` all green

## Out of scope

- Generalizing `BumpStrategy` to a fuller "explain a decision" API
  (e.g., `BumpDecision` dataclass returned by `decide()`) — overkill for
  the static-per-strategy case
- Refactoring `_emit` or the rest of `_use_case.py`
- GitHub provider implementation
- Any other test or doc updates beyond what this refactor strictly
  requires

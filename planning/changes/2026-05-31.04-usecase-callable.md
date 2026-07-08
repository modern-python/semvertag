---
summary: "Make the use-case a callable."
---

# `SemvertagUseCase` as a callable: separate init from invocation

**Date:** 2026-05-31
**Status:** Approved, ready for plan
**Author:** brainstorm session (Superpowers `brainstorming` skill)

## Context

`SemvertagUseCase` currently takes `output: Output` as an `__init__`
dependency, baked into the dataclass at construction time. But `output`
isn't a dependency — it's a per-invocation rendering choice driven by
CLI flags (`--json`, `--quiet`). The current design tries to inject it
via DI (the `OutputsGroup` in `semvertag/ioc.py`), and then `__main__.py`
has to use `dataclasses.replace(use_case, output=output)` to swap it
post-construction because the `--json` flag wasn't known at container-
construction time.

The `_run_with_output_override` hack and the `json=` parameter to
`build_container` are scaffolding around a fundamentally wrong shape:
`output` doesn't belong in `__init__`.

This spec separates initialization (durable dependencies: `provider`,
`strategy`) from invocation (per-call state: `output`) by:

- Removing `output` from `SemvertagUseCase` fields
- Renaming `.run()` → `__call__()` and taking `output` as a parameter
- Deleting `OutputsGroup` and its factory wrappers from `ioc.py`
- Deleting `_run_with_output_override` from `__main__.py`

This is **Sub-project A** of the broader "make ioc.py an idiomatic
modern-di-typer showcase" effort. Sub-project A is a prerequisite for
Sub-project B (full idiomatic DI wiring) because the per-invocation
output override that A removes is what currently blocks adopting
`modern_di_typer.setup_di` + `@inject` + `FromDI`. After A lands, the
use case has a clean init that's amenable to module-level container
construction.

## Decisions

| Question | Decision |
| --- | --- |
| Should `output` be a field or a `__call__` parameter? | `__call__` parameter |
| Build output inside `__call__` from flags, or pass it in? | Pass it in (CLI owns the flag → output decision) |
| Rename `run()` → `__call__()`? | Yes — `use_case(output=...)` reads better and signals the object is the action |
| Bundle with Sub-project B (idiomatic DI)? | No — Sub-project A delivers value alone and unblocks B |
| `Output` protocol changes? | None |
| `RichOutput` / `JsonOutput` / `build_*_output` changes? | None — same shape, same signatures |

## New use case shape

Before:

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class SemvertagUseCase:
    provider: Provider
    strategy: BumpStrategy
    output: Output

    def run(self) -> RunResult:
        self.output.progress(f"Detected strategy: {self.strategy.name}")
        ...
```

After:

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class SemvertagUseCase:
    provider: Provider
    strategy: BumpStrategy

    def __call__(self, *, output: Output) -> RunResult:
        output.progress(f"Detected strategy: {self.strategy.name}")
        ...
```

Every `self.output.*` call site in the body becomes `output.*`. The
internal `_emit` helper that builds a `RunResult` + emits it gains an
`output` parameter to forward through.

## What gets touched

### Source files

**`semvertag/_use_case.py`** (~140 LOC):
- Drop `output: Output` field from `SemvertagUseCase` dataclass
- Rename `def run(self) -> RunResult:` → `def __call__(self, *, output: Output) -> RunResult:`
- Replace `self.output.progress(...)` and `self.output.emit(...)` with
  `output.progress(...)` and `output.emit(...)` (5 call sites)
- Update `_emit` helper to take `output` as a parameter and forward it
- `from semvertag._output import Output` stays (still needed for the
  parameter annotation)

**`semvertag/ioc.py`** (~192 LOC):
- Delete `OutputsGroup` class entirely
- Delete `_build_rich_output` and `_build_json_output` factory wrappers
- Drop `from semvertag._output import JsonOutput, RichOutput, build_json_output, build_rich_output`
- Drop `"output": OutputsGroup.rich_output` from `UseCasesGroup.semvertag_use_case` kwargs
- Remove `OutputsGroup` from `ALL_GROUPS` list and `__all__` tuple
- Drop `json: bool = False` parameter from `build_container`
- Delete the `if json: json_instance = ...; container.override(OutputsGroup.rich_output, json_instance)` block

**`semvertag/__main__.py`** (~295 LOC):
- Delete `_run_with_output_override` function (4 lines)
- Replace its single call site (`_run_with_output_override(use_case, output)`) with `use_case(output=output)`
- Drop `from semvertag._use_case import SemvertagUseCase` if no longer
  referenced after the deletion
- Drop `json=json_flag` from `ioc.build_container(settings, json=json_flag)` →
  `ioc.build_container(settings)`

### Test files

**`tests/unit/test_use_case.py`** (~220 LOC):
- `_make_use_case` factory drops `output` from its `SemvertagUseCase(...)` construction
- Call sites change from `use_case.run()` to `use_case(output=recording_output)`
- The `_RecordingOutput` stub is unchanged
- Assertions on `output.emitted_results` / `output.progress_messages` /
  `output.error_messages` work unchanged because `_RecordingOutput` is
  now passed in at call time instead of injected at construction

**`tests/integration/test_cli_*.py`** (3 files, 432 LOC combined):
- Exercise the CLI end-to-end via `typer.testing.CliRunner`; should
  pass unchanged because they go through `__main__.py` which handles
  all the wiring internally
- If any test directly instantiates `SemvertagUseCase` (grep first),
  apply the same factory migration as `test_use_case.py`

**`tests/integration/conftest.py`**:
- Verify it doesn't pass `json=` to `ioc.build_container(...)`. If it
  does, remove that argument. Likely a no-op.

### Estimated delta

| File | Delta |
|---|---|
| `_use_case.py` | -1 field, +1 param, 5 minor edits. Net ≈ 0 LOC |
| `__main__.py` | -8 to -10 LOC |
| `ioc.py` | -25 to -30 LOC |
| `test_use_case.py` | ≈ 0 LOC |
| **Total** | **≈ -35 LOC** plus a cleaner shape |

The value is conceptual clarity, not raw LOC reduction: surfacing the
hidden coupling between `output` and `__init__`, eliminating the
`dataclasses.replace` hack, and shrinking the DI surface so
Sub-project B can adopt idiomatic patterns.

## Execution sequencing

The use case shape change and the DI wiring change are **tightly
coupled** — touching one without the other breaks the build. Landed as
**one atomic commit on one worktree**.

### Worktree setup

Spawn `feat/usecase-callable` off `main`, path
`.worktrees/feat-usecase-callable`. Baseline:
`just lint-ci && uv run pytest -q` should pass (334 / 1 skipped on
current main).

### Single wave — the full refactor

Edits land in this order within the commit (for diff readability):

1. `semvertag/_use_case.py` — drop `output` field; rename `run` →
   `__call__`; add `output: Output` parameter; update `self.output.*`
   to `output.*` (5 sites); thread `output` through `_emit`.
2. `semvertag/ioc.py` — delete `OutputsGroup` class; delete
   `_build_rich_output` and `_build_json_output`; drop the four output-
   related imports; drop `"output": OutputsGroup.rich_output` from
   `UseCasesGroup.semvertag_use_case` kwargs; remove `OutputsGroup`
   from `ALL_GROUPS` and `__all__`; drop `json: bool = False` parameter
   from `build_container` and the corresponding `if json: ...` block.
3. `semvertag/__main__.py` — delete `_run_with_output_override`;
   replace its call site with `use_case(output=output)`; drop the
   stale `SemvertagUseCase` import if unused; drop `json=json_flag`
   from `ioc.build_container(...)`.
4. `tests/unit/test_use_case.py` — update `_make_use_case` factory to
   drop the `output` constructor arg; update all `use_case.run()` →
   `use_case(output=output)` call sites.
5. Verify `tests/integration/conftest.py` — grep for `json=` and
   `build_container`; remove `json=` if present.

### Gate after the wave

- `just lint-ci` — PASS
- `uv run pytest -q` — 334 passed, 1 skipped (same count; no tests
  added or removed)
- `uv run pytest tests/unit/test_use_case.py -v` — explicit run of the
  most affected file
- `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict` —
  clean
- Smoke test: `uv run semvertag --help` — output unchanged from main
  (no behavior change to CLI surface)
- Smoke test: a manual `uv run semvertag --json --project-id 1`
  against a stub doesn't have to succeed (no real GitLab access in
  this environment), but the error message shape should match what
  main produces

### Commit message

```
use_case: separate init from invocation; pass output to __call__

SemvertagUseCase becomes a callable whose dependencies (provider,
strategy) are bound at init and whose per-invocation state (output)
arrives via __call__(*, output: Output). The renamed __call__ replaces
the previous .run() method.

This eliminates _run_with_output_override in __main__.py (the
dataclasses.replace hack that swapped the use case's output post-
construction) and OutputsGroup in ioc.py (output is no longer a DI'd
dependency — it's a per-call helper built by the CLI from --json /
--quiet flags).

Sets up sub-project B (idiomatic modern-di-typer wiring) by removing
the per-invocation override that prevented adopting setup_di / @inject
/ FromDI.
```

### Code review

Skip the formal subagent code review for this small focused refactor
unless something surprises during the wave. The change is
mechanically simple, well-bounded, and the tests pin the behavioral
contract.

### Land

`superpowers:finishing-a-development-branch` — fast-forward expected.

## Success criteria

When all of these hold, this spec is done:

- `SemvertagUseCase` has no `output` field; its only callable is
  `__call__(*, output: Output) -> RunResult` (no `.run()` method
  remains)
- `_run_with_output_override` is deleted from `__main__.py`
- `OutputsGroup` is deleted from `ioc.py`; `ALL_GROUPS` has 4 groups
  (Settings, Providers, Strategies, UseCases)
- `build_container` no longer accepts a `json=` parameter
- All 334 tests pass; CLI behavior unchanged (smoke tests confirm)
- `_use_case.py`, `__main__.py`, and `ioc.py` are all slightly shorter
  and cleaner

## Out of scope (Sub-project B — separate brainstorm next)

- Move container construction to module level
  (`Container(groups=ALL_GROUPS)` at import time in `ioc.py`)
- Adopt `modern_di_typer.setup_di(MAIN_APP, container)` +
  `@modern_di_typer.inject` + `FromDI(SemvertagUseCase)` in
  `__main__.py`
- Drop `skip_creator_parsing=True` / `bound_type=None` / manual
  `kwargs={...}` workarounds in `ioc.py` in favor of auto-wiring from
  creator type hints
- Migrate testability scaffolding from `inner_transport=` parameter on
  `build_container` to `container.override(...)` at test setup time

## Out of scope (further future brainstorms)

- `apply_cli_overlay` / `_split_overrides` / `_revalidate_nested`
  simplification in `_settings.py`
- `__main__.py` residual cleanup (post-doctor + post-A)
- `_use_case.py` `strategy.name` branching in `_status_for_no_bump` /
  `_reason_for_no_bump` (very minor; arguably correct as-is)

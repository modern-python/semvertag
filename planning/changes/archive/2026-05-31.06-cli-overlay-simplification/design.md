---
status: shipped
date: 2026-05-31
slug: cli-overlay-simplification
supersedes: null
superseded_by: null
pr: null
outcome: shipped in the pre-1.0 bootstrap (model_copy CLI overlay)
---

# Simplify `apply_cli_overlay` in `_settings.py`

**Date:** 2026-05-31
**Status:** Approved, ready for plan
**Author:** brainstorm session (Superpowers `brainstorming` skill)

## Context

The `apply_cli_overlay` + `_split_overrides` + `_revalidate_nested`
machinery in `semvertag/_settings.py` is ~57 LOC of CLI-overlay logic.
Two of its complexity sources are dead weight:

- The `(value, flag_detail)` tuple shape for overrides — `flag_detail`
  was used by `_provenance` tracking (drop-doctor removed the consumer).
  Pyright already flags `_flag_detail` as unused in `_split_overrides`.
- The manual unknown-key validation (`if dotted_key not in settings_fields`)
  produces friendly "Unknown CLI overlay target" errors, but
  `_collect_overrides` in `__main__.py` is the only caller and it
  hard-codes the keys. Misspellings would be implementer bugs caught
  by lint/tests, not user-facing concerns.

The third source — manual merge-then-validate for nested configs in
`_revalidate_nested` — can be expressed natively using
`pydantic.BaseModel.model_copy(update=...)`.

This spec collapses the three functions into one ~14-LOC
`apply_cli_overlay`, and simplifies `_collect_overrides` correspondingly.
Net deletion ~-50 LOC across two files. No behavior change; no test
changes (no test references `apply_cli_overlay` or `flag_detail`
directly; CLI integration tests verify end-to-end behavior unchanged).

## Decisions

| Question | Decision |
| --- | --- |
| Drop `(value, flag_detail)` tuple shape | Yes — `flag_detail` is unused |
| Drop unknown-key validation | Yes — `_collect_overrides` is the only caller and hard-codes the keys; trust the caller |
| Keep depth-2 guard (`if "." in leaf: raise`) | Yes — covers a real implementer-error case |
| Test changes | None expected — no test references the simplified internals |
| Public API change | None — `apply_cli_overlay(settings, overrides)` signature stays; only the override values type tightens (was `tuple[Any, str]`, now `Any`) |
| `_collect_overrides` signature | Stays the same (same keyword args); only return type changes (`dict[str, tuple[Any, str]]` → `dict[str, Any]`) |

## New `apply_cli_overlay` (replaces 3 functions ~57 LOC)

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
    # Re-validate to trigger field validators (e.g. _clamp_request_timeout)
    return type(settings).model_validate({name: getattr(copied, name) for name in type(copied).model_fields})
```

Why each step:

1. Walk the overrides dict, splitting dotted keys (`"gitlab.token"`) from
   top-level keys (`"project_id"`).
2. For each nested config that has overrides, use
   `model_copy(update=leaves)` — pydantic's native partial-update API.
3. Merge all top-level updates plus the rebuilt nested models via
   `model_copy(update=top_updates)`.
4. Re-validate via `model_validate({field: getattr(copied, field) ...})`
   to trigger field validators like `_clamp_request_timeout`. Direct
   `Settings.model_validate(copied.model_dump())` would not work because
   `model_dump()` masks `SecretStr` as `"**********"` — losing token
   values during the round trip. Using `getattr` preserves the live
   `SecretStr` objects.

Deleted helpers:
- `_split_overrides` (~25 LOC)
- `_revalidate_nested` (~17 LOC)

## Simplified `_collect_overrides`

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

Drops `(value, "--flag")` tuple wrapping at every line. Same keys, same
values, no second tuple element.

## What gets touched

### Source files (2)

**`semvertag/_settings.py`** (~148 LOC currently):
- Replace `apply_cli_overlay` body with the new 14-line version
- Update `apply_cli_overlay` signature: `overrides: dict[str, tuple[typing.Any, str]]` → `dict[str, typing.Any]`
- Delete `_split_overrides` function
- Delete `_revalidate_nested` function

**`semvertag/__main__.py`** (~187 LOC currently):
- Update `_collect_overrides` return type: `dict[str, tuple[typing.Any, str]]` → `dict[str, typing.Any]`
- Drop `(value, "--flag")` tuple wrapping at 8 if-blocks inside `_collect_overrides`

### Test files

None. Verified via `grep -n "apply_cli_overlay\|flag_detail" tests/`:
zero matches. CLI integration tests verify end-to-end behavior; they
don't touch the internal tuple shape.

### Estimated delta

| File | Delta |
| --- | --- |
| `_settings.py` | -42 LOC (delete 2 helpers, shrink `apply_cli_overlay`) |
| `__main__.py` | -8 LOC (drop tuple wrapping in 8 if-blocks) |
| **Total** | **~-50 LOC** |

`_settings.py`: 148 → ~106 LOC.

## What stays unchanged

- The depth-2 guard (`if "." in leaf: raise`) — covers a real
  implementer-error case
- The `model_copy(update=...)` + manual `model_validate` two-step —
  necessary to trigger field validators (`_clamp_request_timeout`)
  because `model_copy` alone doesn't re-validate, and `model_dump`
  would mask SecretStr values
- The `apply_cli_overlay` public signature (the type of the second arg
  changes from `dict[str, tuple[Any, str]]` to `dict[str, Any]`, but
  the function name + first arg type stay; the only external caller is
  `_collect_overrides` which we update in the same commit)
- `_collect_overrides`'s keyword-arg signature
- All field validators (`_clamp_request_timeout`)
- All `pydantic_settings.BaseSettings` subclass configurations
  (`GitLabConfig`, `GitHubConfig`, `Settings`)

## Execution sequencing

Single atomic commit on one worktree. The two file changes are tightly
coupled (the override-values type changes simultaneously in both
producer and consumer) — must land together to keep the build green.

### Worktree setup

Spawn `feat/cli-overlay-simplification` off `main`, path
`.worktrees/feat-cli-overlay-simplification`. Baseline:
`just lint-ci && uv run pytest -q` should pass (330 / 1 skipped on
current main).

### Single wave — the full refactor

Edits land in this order within the commit (for diff readability):

1. `semvertag/_settings.py` — replace `apply_cli_overlay` body; delete
   `_split_overrides` and `_revalidate_nested`
2. `semvertag/__main__.py` — simplify `_collect_overrides` (drop tuple
   wrapping, update return type annotation)

### Gate after the wave

- `just lint-ci` — PASS
- `uv run pytest -q` — 330 passed, 1 skipped (unchanged)
- `just test-branch-strategies && just test-cc-strategies` — still 100%
- `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict` —
  clean
- Smoke tests:
  - `uv run semvertag tag` (no creds) — same `Project id missing` error
    + exit code 2 as on main
  - `uv run semvertag --version` — prints version, exit 0

### Commit message

```
settings: collapse apply_cli_overlay into 14 LOC via pydantic model_copy

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
drop the (value, "--flag") tuple wrapping.

Net: ~-50 LOC across two files. No behavior change; no test changes
(no test references the simplified internals; CLI integration tests
verify end-to-end behavior unchanged).
```

### Code review

Skip the formal subagent code review — well-bounded refactor, no
behavior change, the gate plus smoke tests cover behavior preservation.

### Land

`superpowers:finishing-a-development-branch` — fast-forward expected.

## Success criteria

When all of these hold, this spec is done:

- `semvertag/_settings.py` no longer contains `_split_overrides` or
  `_revalidate_nested`
- `apply_cli_overlay` body is ~14 LOC and uses `model_copy(update=...)`
  on nested configs
- `apply_cli_overlay` signature accepts `dict[str, typing.Any]`
  (no tuple wrapping)
- `_collect_overrides` in `semvertag/__main__.py` returns
  `dict[str, typing.Any]`; 8 if-blocks drop the `(value, "--flag")`
  tuple wrapping
- All 330 tests pass; no test changes
- `_settings.py` is ~106 LOC (down from 148)
- Smoke tests produce same output as `main`
- `just lint-ci`, `uv run pytest`, `mkdocs build --strict` all green

## Out of scope

Deferred or accepted as-is:

- `_use_case.py` `strategy.name` branching in `_status_for_no_bump` /
  `_reason_for_no_bump` (very minor; arguably correct as-is)
- Any remaining `__main__.py` cleanup beyond what `_collect_overrides`
  needs (the post-sub-project-B callback shape is fine)
- GitHub provider implementation

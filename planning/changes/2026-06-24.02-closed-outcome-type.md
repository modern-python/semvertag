---
summary: Replace the free-form run-status strings with a closed Outcome sum type the renderers dispatch over exhaustively.
---

# Design: Closed Outcome type

## Summary

The use-case describes "what happened" as a free-form `status: str` on
`RunResult` (`created`, `dry_run`, `no_tags`, `already_tagged`, plus the
strategy-supplied `no_merge_commit` / `no_conforming_commit`). That set is
enumerated nowhere — it is produced as string literals in `_use_case.py`, then
re-decoded by string equality in `RichOutput._format_result` and again by `jq`
in `action.yml`. Introduce a closed `Outcome` sum type that the use-case returns
and the renderers `match` over exhaustively (`assert_never`), so a new outcome is
a compile-time error in every renderer instead of a silent fallthrough.
`RunResult` is demoted to a pure JSON serialization DTO derived from `Outcome`;
the wire envelope and `schema_version: "1.0"` are byte-for-byte preserved.

## Motivation

`semvertag/_use_case.py` emits the status set as bare literals at five call
sites. `semvertag/_output.py:_format_result` decodes them with
`if result.status == "created"` / `== "dry_run"` / `else`, and `action.yml`'s
`jq` does `case "$(jq -r '.status')" in created) … *) no-bump`. No module owns
the enumeration — it survives only as a comment in `action.yml`. Surfaced as
candidate #3 in the 2026-06-23 architecture review: the outcome set leaks across
the seam, and `dry_run` already collapses into `no-bump` in the action by
accident. A closed sum makes the set explicit and the renderers exhaustive.

## Non-goals

- No change to the JSON wire envelope: field names, order, values, and
  `schema_version: "1.0"` stay identical, so `action.yml` and any consumer are
  untouched. (`test_output_json` is the guardrail.)
- No change to the strategy protocol: each strategy keeps its `no_bump_status` /
  `no_bump_reason` ClassVars; those strings flow into the `NoBump` variant as
  data.
- Not touching the vestigial `CheckResult` / `ConfigSource` in `_types.py`
  (used only by an over-built test stub) — out of scope.

## Design

### 1. The closed sum — `semvertag/_outcome.py` (new)

Five frozen/slotted/kw-only dataclasses + a union alias. Each carries only the
fields meaningful to it:

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Created:        tag: str; bump: Bump; commit: str
class DryRun:         tag: str; bump: Bump; commit: str
class NoTags:         commit: str
class AlreadyTagged:  tag: str; commit: str
class NoBump:         status: str; reason: str; commit: str   # strategy-supplied

Outcome: typing.TypeAlias = Created | DryRun | NoTags | AlreadyTagged | NoBump
```

`NoBump` carries the strategy's `status` + `reason` as data, so `Outcome` stays
closed (five variants) and decoupled from the open set of strategies — a new
strategy adds a status string, never a variant.

### 2. The wire mapping — `to_run_result(outcome) -> RunResult`

One exhaustive `match` in `_outcome.py` (imports `RunResult` from `_types`;
one-way dependency `_outcome → _types`). It is the single place the four fixed
wire tokens and fixed reasons live; `NoBump` passes its token/reason through;
no-bump-ish variants map to `bump="none"`:

```python
def to_run_result(outcome: Outcome) -> RunResult:
    match outcome:
        case Created(tag=t, bump=b, commit=c):
            return RunResult(strategy=..., bump=b.value, status="created", tag=t, commit=c, reason=None)
        case DryRun(...):        return RunResult(..., status="dry_run", ...)
        case NoTags(commit=c):   return RunResult(..., bump="none", status="no_tags", tag=None, commit=c, reason=_NO_TAGS_REASON)
        case AlreadyTagged(...): return RunResult(..., status="already_tagged", ...)
        case NoBump(status=s, reason=r, commit=c):
            return RunResult(..., bump="none", status=s, tag=None, commit=c, reason=r)
        case _:
            typing.assert_never(outcome)
```

`strategy` (the `RunResult.strategy` field) is still needed on the wire. It is
threaded through as a parameter — `to_run_result(outcome, *, strategy)` and
`Output.emit(outcome, *, strategy)` — rather than carried on each variant, so the
variants stay about the outcome, not the run config. The use-case supplies
`self.strategy.name`.

### 3. The seam — `Output.emit(outcome: Outcome)`

The protocol's `emit` takes `Outcome` (plus the `strategy` name) instead of
`RunResult`:

- `RichOutput.emit`: `match outcome` → a human sentence per variant. The
  no-bump-ish cases stop echoing the raw machine token (`status:
  no_merge_commit`) in favour of a clean sentence from the variant's data. JSON
  is unaffected; the `RichOutput` unit tests are updated to the new wording.
- `JsonOutput.emit`: `to_run_result(outcome)` → `dataclasses.asdict` → one JSON
  line. Byte-identical envelope.

Two exhaustive matches total (`RichOutput.emit`, `to_run_result`); both end in
`assert_never`, so a sixth variant fails `ty` in both until handled.

### 4. The use-case returns `Outcome`

`SemvertagUseCase.__call__` builds and returns the relevant variant and calls
`output.emit(outcome)`. The `_emit` helper, the `status="…"` literals, and the
`_NO_TAGS_REASON` / `_ALREADY_TAGGED_REASON` constants move out: the literals into
`to_run_result`, the variant construction inline. `__main__.py` already ignores
the return value, so only `test_use_case.py` is affected (it asserts on the
returned object — now `Outcome` variants instead of `RunResult`).

## Testing

- **`_outcome` (new unit):** `to_run_result` maps each of the five variants to
  the correct `RunResult` wire fields (status token, tag/None, reason, `bump`,
  `commit`), including `bump="none"` for the no-bump-ish three and `NoBump`
  token/reason passthrough.
- **`test_output_json` (wire guardrail):** inputs change from `RunResult(...)` to
  `Outcome` variants; the assertions (one line, `schema_version` first and
  `"1.0"`, exact `status`/`tag`/`reason`) stay identical — proving the envelope
  did not move.
- **`test_output_rich`:** updated to the new per-variant human wording.
- **`test_use_case`:** asserts on returned `Outcome` variants.
- **Exhaustiveness:** enforced by `ty` via `assert_never`; the verification gate
  runs `just lint-ci`. A deliberate red check (add a throwaway sixth variant,
  confirm `ty` fails both matches, revert) confirms the guard bites.
- **Gates:** `just lint-ci` and `just test` (100% branch) stay green.

## Risk

Low–moderate. The JSON path is byte-preserved and guarded by `test_output_json`;
the human path changes wording by design (tests updated). The main surface is the
`Output.emit` signature change, but `Output` is internal (two implementations,
both ours) and the use-case return-type change only touches tests. The
`assert_never` arms must be reachable-by-type-only (never at runtime); 100% branch
coverage with `# pragma: no cover` on the `assert_never` arms keeps the gate
honest.

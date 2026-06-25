# closed-outcome-type — implementation plan

**Goal:** Replace the free-form run-status strings with a closed `Outcome` sum
the renderers dispatch over exhaustively, keeping the JSON wire envelope
byte-identical.

**Spec:** [`design.md`](./design.md)

**Branch:** `refactor/closed-outcome-type`

**Commit strategy:** Per-task commits; squash on merge.

TDD throughout: red → green → refactor. Keep `just lint-ci` + `just test`
(100% branch) green at each task boundary.

---

### Task 1: `_outcome.py` — the closed sum + wire mapping

**Files:**
- Create: `semvertag/_outcome.py`
- Create: `tests/unit/test_outcome.py`

Define the 5 frozen/slotted/kw-only variants, the `Outcome` union alias, and
`to_run_result(outcome, *, strategy) -> RunResult` (single exhaustive `match`,
`assert_never` final arm). Move `_NO_TAGS_REASON` / `_ALREADY_TAGGED_REASON` here.

- [x] Red: `test_outcome.py` asserts each variant → expected `RunResult` wire
  fields (status token, `bump`, tag/None, reason, commit); `bump="none"` for
  NoTags/AlreadyTagged/NoBump; NoBump token+reason passthrough.
- [x] Green: implement `_outcome.py`. `# pragma: no cover` the `assert_never` arm.
- [x] `just lint-ci` clean (confirm `ty` accepts the match + alias).
- [x] Commit.

### Task 2: `Output.emit(outcome: Outcome)` — renderers dispatch

**Files:**
- Modify: `semvertag/_output.py`
- Modify: `tests/unit/test_output_rich.py`, `tests/unit/test_output_json.py`

`Output.emit` takes `Outcome`. `RichOutput.emit` matches → human sentence per
variant (new no-bump wording, no raw token). `JsonOutput.emit` calls
`to_run_result` → `asdict` → JSON. Drop `_format_result`.

- [x] Red/update: `test_output_json` inputs become `Outcome` variants; envelope
  assertions unchanged (guardrail). `test_output_rich` updated to new wording.
- [x] Green: implement; second `assert_never` arm in `RichOutput.emit`.
- [x] `just test` green; `test_output_json` proves byte-identical envelope.
- [x] Commit.

### Task 3: use-case returns `Outcome`

**Files:**
- Modify: `semvertag/_use_case.py`
- Modify: `tests/unit/test_use_case.py`

`__call__` builds + returns variants, calls `output.emit(outcome)`. Remove
`_emit`, the `status="…"` literals, and the reason constants (now in `_outcome`).

- [x] Update `test_use_case` to assert on returned `Outcome` variants.
- [x] Green: `just test` + `just lint-ci`.
- [x] Commit.

### Task 4: exhaustiveness proof + promote

- [x] Deliberate red: add a throwaway 6th variant, confirm `ty` fails BOTH
  matches (`to_run_result`, `RichOutput.emit`), then revert.
- [x] Promote `architecture/cli.md` (Output + use-case sections) to describe the
  `Outcome` seam and `to_run_result`.
- [x] `just index`; set `status: shipped`, fill `pr`/`outcome` at merge.

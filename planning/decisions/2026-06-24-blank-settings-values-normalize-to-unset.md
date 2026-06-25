---
status: accepted
summary: A blank (empty/whitespace) optional settings value normalizes to None (unset), it is not rejected.
supersedes: null
superseded_by: null
---

# Blank optional settings values normalize to unset, not reject

**Decision:** For an *optional* `Settings` field where blank means "no value,
use the fallback," a declared-but-empty or whitespace-only input normalizes to
`None` (unset) via a field validator. Do **not** guard such a field with
`min_length` / a hard `ValidationError`.

## Context

`Settings.default_branch` (PR #33) first shipped a draft guarded by
`pydantic.Field(default=None, min_length=1)`, intending to reject the degenerate
`--default-branch ""`. Code review caught that this is a regression: pydantic-
settings materializes a declared-but-empty env var (`SEMVERTAG_DEFAULT_BRANCH=`,
a common CI idiom where a variable is exported with no value) as the string
`""`, so `min_length=1` raised `ValidationError → ConfigError` and aborted
**every** invocation. Before the field was wired up that same empty var was a
harmless no-op. The fix replaced `min_length` with a validator that strips and
maps empty/whitespace to `None`.

## Decision & rationale

The distinction is **what blank means for this field**:

- When blank means "I'm not setting this; fall back to the default/derived
  value" (default_branch falls back to the forge API), the correct behavior is
  **normalize blank → `None`**. Rejecting it turns a no-op into a crash and
  punishes the CI idiom of declaring-but-not-populating a variable. Stripping
  also lets a stray-padded value (`"  main  "`) still resolve.
- Only when blank is **genuinely invalid** — there is no fallback and an empty
  value cannot mean anything sensible — is a hard `min_length` / required-field
  rejection correct.

`default_branch` is the first kind, so it normalizes. The canonical shape:

```python
@pydantic.field_validator("<field>")
@classmethod
def _blank_is_unset(cls, value: str | None) -> str | None:
    stripped = (value or "").strip()
    return stripped or None
```

This keeps `None` the single "unset" sentinel and downstream `is not None`
checks dead simple.

## Revisit trigger

Reopen for a specific field if blank input must be a **hard error** there — i.e.
the field has no fallback and an empty value is a configuration mistake the user
must see immediately (e.g. a required token where `""` should fail loudly rather
than silently behave as unset). For that field, prefer explicit rejection over
this normalize-to-unset default; this decision governs only the
blank-means-fallback case.

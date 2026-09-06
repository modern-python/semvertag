# Blank optional settings values normalize to unset, not reject

**Decision:** for an *optional* `Settings` field where blank means "no value, use the fallback", a
declared-but-empty or whitespace-only input normalizes to `None` through a field validator. Such a
field is **not** guarded with `min_length` or a hard `ValidationError`.

`Settings.default_branch` first shipped a draft guarded by `pydantic.Field(default=None,
min_length=1)`, intending to reject the degenerate `--default-branch ""`. Review caught that this is
a regression: pydantic-settings materializes a declared-but-empty environment variable
(`SEMVERTAG_DEFAULT_BRANCH=`, a common CI idiom where a variable is exported with no value) as the
string `""`, so `min_length=1` raised `ValidationError` → `ConfigError` and aborted **every**
invocation. Before the field was wired up, that same empty variable was a harmless no-op.

The distinction is what blank *means for this field*. When blank means "I am not setting this; fall
back to the default or derived value" — and `default_branch` falls back to the forge API — the
correct behavior is to normalize blank to `None`. Rejecting it turns a no-op into a crash and
punishes the CI idiom of declaring a variable without populating it. Stripping also lets a
stray-padded value (`"  main  "`) still resolve. Only when blank is *genuinely invalid* — there is no
fallback and an empty value cannot mean anything sensible — is a hard rejection correct.

The canonical shape is a `field_validator` that strips and returns `stripped or None`, which keeps
`None` the single "unset" sentinel and leaves every downstream reader a dead-simple `is not None`
check.

**Revisit trigger:** a specific field where blank input must be a **hard error** — the field has no
fallback and an empty value is a configuration mistake the user must see immediately, such as a
required token where `""` should fail loudly rather than silently behave as unset. Prefer explicit
rejection for that field; this decision governs only the blank-means-fallback case.

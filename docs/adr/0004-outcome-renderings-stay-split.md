# Outcome renderings stay split (wire vs human), not unified on the variant

**Decision:** `to_run_result` in `semvertag/_outcome.py` (Outcome → JSON wire DTO) and
`_format_outcome` in `semvertag/_output.py` (Outcome → human sentence) remain two independent `match`
statements over the closed `Outcome` sum. Both renderings are **not** moved onto the variants
themselves to co-locate them.

An architecture review flagged that two exhaustive matches walk the same five-variant sum, and that a
comment in `_outcome.py` instructs the maintainer that the two audiences are worded differently on
purpose and both must be edited together. The proposed deepening: give each variant both renderings,
so the two outputs ask the variant instead of re-matching it.

The same test as [ADR-0001](0001-forge-providers-not-unified.md) and
[ADR-0003](0003-error-translators-not-tabled.md) kills it. What is shared is the `match` skeleton,
and it is coincidental — the only common structure is the sum's cardinality, not duplicated content.
What varies is the bulk and cannot be deduped: the wire arm builds a stable machine contract with
fixed status tokens and fixed reasons; the human arm builds presentation — a `No tag created — …`
sentence, a short commit, a tag interpolated into the already-tagged case. No string is shared
between them, by design.

The drift the comment warns about is already type-enforced: both matches end in `assert_never`, so
adding a sixth variant is a type error in *both* arms until handled. There is no silent
forgot-to-update-the-other failure mode to prevent.

And unifying mixes two concerns. The wire contract is stable and machine-facing; the sentence is
mutable and human-facing. Co-locating them trades locality-of-concern — all wire tokens in one place,
all phrasing in one place, both already true — for locality-of-variant, and drags presentation
phrasing into a module that today depends only on `_types`.

**Revisit trigger:** the wire reason and the human sentence for a variant must become the
**identical** string — a genuine single fact rendered once — or a variant's two renderings must stay
byte-for-byte in lockstep by contract. At that point the single-source-of-truth value is real; until
then the structural similarity of the two matches is coincidental.

---
status: accepted
summary: Keep the wire and human renderings of Outcome as two separate exhaustive matches; do not collapse onto per-variant render methods.
supersedes: null
superseded_by: null
---

# Outcome renderings stay split (wire vs human), not unified on the variant

**Decision:** `to_run_result` (in `semvertag/_outcome.py`, Outcome → JSON wire
DTO) and `_format_outcome` (in `semvertag/_output.py`, Outcome → human sentence)
remain two independent `match` statements over the closed `Outcome` sum. We do
**not** move both renderings onto the variants (e.g. `variant.wire()` +
`variant.sentence()`) to "co-locate" them.

## Context

An architecture review flagged that two exhaustive `match outcome:` statements
walk the same five-variant `Outcome` sum — one in `_outcome.py` producing the
wire `RunResult`, one in `_output.py` producing the terminal sentence — and that
a code comment (`_outcome.py:7-9`) instructs the maintainer that the two audiences
are "worded differently on purpose, edit both if you change one." The proposed
deepening: give each `Outcome` variant both renderings so the two outputs ask the
variant instead of re-matching it, leaving one place per variant.

## Decision & rationale

The split between what is shared and what varies kills the candidate — the same
test as [forge-providers-not-unified] and [error-translators-not-tabled]:

- **What's shared is the `match` skeleton, and it's coincidental.** The only
  common structure is the `case Created … case DryRun … case NoTags …` shape,
  which is just the closed sum's cardinality. It is not duplicated *content*.
- **What varies is the bulk, and it can't be deduped.** The wire arm builds a
  stable machine contract (fixed `status` tokens `created`/`dry_run`/`no_tags`/
  `already_tagged`, fixed reasons); the human arm builds presentation (a
  `No tag created — …` sentence, a 7-char short commit, the tag interpolated into
  `AlreadyTagged`). No string is shared between the two — they are different
  strings for different audiences by design, not by accident.
- **The drift the comment warns about is already type-enforced.** Both matches
  end in `typing.assert_never`, so adding a sixth variant is a `ty` error in
  *both* arms until handled. There is no silent "forgot to update the other
  match" failure mode to prevent.
- **Unifying mixes two concerns.** The wire contract is stable and machine-facing;
  the sentence is mutable and human-facing. Co-locating them on the variant trades
  locality-of-concern (all wire tokens in one place — already true; all phrasing
  in one place — already true) for locality-of-variant, and drags presentation
  phrasing into the module that today depends only on `_types`.

So the deepening buys co-location of one variant's two renderings — weak,
non-type-enforced locality — at the cost of fusing a machine contract with a
presentation string. Net negative against the project's "shared by standard, not
by coincidence" lens.

## Revisit trigger

Reopen if the wire reason and the human sentence for a variant must become the
**identical** string (a genuine single fact rendered once), or if a variant's two
renderings must stay byte-for-byte in lockstep by contract. At that point the
single-source-of-truth value is real; until then, the structural similarity of
the two matches is coincidental and not worth unifying.

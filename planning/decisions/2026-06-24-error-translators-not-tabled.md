---
status: accepted
summary: Keep the two per-forge HTTP status→error ladders as explicit copies; do not table-drive them.
supersedes: null
superseded_by: null
---

# Error translators stay duplicated, not table-driven

**Decision:** `semvertag/providers/_errors.py` keeps `_translate_gitlab_status`
/ `_translate_github_status` (and the paired `_translate_*_auth` and the two
create-tag specials) as two explicit, mirrored functions. We do **not** extract
the shared status→exception-type ladder into one generic translator driven by a
per-forge message table.

## Context

An architecture review flagged that the two `_translate_*_status` functions
share a ladder shape — `401/403 → AuthError`, `404 → ConfigError`,
`422 → ConfigError`, `429 → ProviderAPIError`, `5xx → ProviderAPIError`,
`else → ProviderAPIError` — and proposed collapsing them into one
`_translate_status(exc, *, messages: ForgeErrorMessages)` parameterised by a
per-forge table of message strings, mirroring how `_translate_transport` is
already shared.

## Decision & rationale

The split between what is shared and what varies kills the candidate:

- **What's shared is small and stable.** Only the ~17-line ladder *skeleton*
  (which HTTP code maps to which domain exception) is common, and it is fixed
  HTTP/RFC-7231 semantics — it does not change and the two ladders have not
  drifted. It is the part least in need of a single source of truth.
- **What varies is the bulk, and it can't be deduped.** Every message string is
  genuinely per-forge: scope hints (`api`/`write_repository` vs
  `contents: write`/`public_repo`), the identifier and its env-var hint
  (`project_id` + `CI_PROJECT_ID` vs `repo` + `GITHUB_REPOSITORY`), and the
  tag-exists fragment (`already exists` vs `already_exists`). That text stays
  per-forge data whether or not the ladder is extracted.

So a table-drive trades two readable, linearly-readable ladders for a
message-table struct (~7 fields, some callables for the parameterised rungs) +
a generic function + indirection — roughly net-neutral on lines and worse on
locality (you can no longer read one forge's error handling top-to-bottom). It
also risks the exact failure mode the [forge-providers-not-unified] decision
named: the first time one forge gives a status a new meaning, the shared ladder
grows an `if forge == ...` conditional — the wrong abstraction *plus*
indirection.

`_translate_transport` is *correctly* shared because its messages are uniform
(only a `provider_label` token differs); the status ladder is not like that, so
the file already draws the line in the right place. This decision applies the
same "shared by standard, not by coincidence" lens as
`forge-providers-not-unified`: the ladder *type-mapping* is standard, but the
per-rung messages — the thing a table would have to carry — are forge-specific
content, so the table buys too little to justify itself.

## Revisit trigger

Reopen if **a third forge** is added (three copies of the ladder shifts the
balance toward a table), **or** if the two ladders **actually drift** — one forge
starts mapping a status to a different exception type, or grows a rung the other
lacks. At that point the single-source-of-truth value is real; until then,
duplication is cheaper than the abstraction.

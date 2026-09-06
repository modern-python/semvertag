# Error translators stay duplicated, not table-driven

**Decision:** `semvertag/providers/_errors.py` keeps its two per-forge status ladders — and the
paired auth translators and create-tag specials — as explicit, mirrored functions. The shared
status-to-exception ladder is **not** extracted into one generic translator driven by a per-forge
message table.

An architecture review flagged that the two functions share a ladder shape (401/403 → `AuthError`,
404 → `ConfigError`, 422 → `ConfigError`, 429 and 5xx → `ProviderAPIError`, else →
`ProviderAPIError`) and proposed collapsing them into one translator parameterised by a per-forge
table of message strings, mirroring how the transport translator is already shared.

The split between what is shared and what varies kills the candidate. What is shared is small and
stable: only the ladder *skeleton* — which HTTP code maps to which domain exception — and that is
fixed HTTP semantics. It does not change, and the two ladders have not drifted; it is the part least
in need of a single source of truth. What varies is the bulk, and it cannot be deduped: every message
string is genuinely per-forge — the scope hints (`api`/`write_repository` versus
`contents: write`/`public_repo`), the identifier and its environment-variable hint (`project_id` +
`CI_PROJECT_ID` versus `repo` + `GITHUB_REPOSITORY`), and the tag-exists fragment (`already exists`
versus `already_exists`). That text stays per-forge data whether or not the ladder is extracted.

So the table trades two linearly-readable ladders for a message-table struct of roughly seven fields
— some of them callables for the parameterised rungs — plus a generic function and the indirection
between them. Net-neutral on lines, worse on locality: one forge's error handling can no longer be
read top to bottom. It also risks exactly the failure mode
[ADR-0001](0001-forge-providers-not-unified.md) named: the first time one forge gives a status a new
meaning, the shared ladder grows an `if forge == …` conditional — the wrong abstraction *plus*
indirection.

The transport translator is *correctly* shared because its messages are uniform, differing only by a
provider label. The status ladder is not like that, so the file already draws the line in the right
place: the type-mapping is standard, but the per-rung messages — the thing a table would have to
carry — are forge-specific content.

**Revisit trigger:** a third forge is added, since three copies of the ladder shifts the balance
toward a table; or the two ladders **actually drift** — one forge starts mapping a status to a
different exception type, or grows a rung the other lacks. At that point the single-source-of-truth
value is real. Until then, duplication is cheaper than the abstraction.

# Forge providers stay separate; only what is shared by standard is extracted

`GitHubProvider` and `GitLabProvider` stay independent classes despite roughly 70% line-level
similarity, and the per-forge status ladders in `providers/_errors.py` stay as mirrored functions.
An architecture review proposed a descriptor-driven engine that would flatten `sha` against `id` and
nested against flat commit messages through pydantic validation aliases, and a generic translator
driven by a per-forge table of message strings; both were rejected. The two REST APIs are
independently versioned third-party contracts, so most of the similarity is coincidental rather than
essential, and a shared engine becomes a magnet for `if forge == ...` conditionals, which is worse
than two honest copies. What is shared by standard is extracted instead: RFC 8288 Link-header
pagination lives once in `_rest.collect_link_pages`, as does the transport translator, whose
messages differ only by a provider label. A third forge, or the first real drift between the two
ladders, would reprice this.

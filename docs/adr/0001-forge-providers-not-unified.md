# Forge providers stay separate; share only what is shared by standard

**Decision:** `GitHubProvider` and `GitLabProvider` remain independent classes. They are **not**
collapsed into a single descriptor-driven `RestForgeProvider` engine parameterised by a per-forge
spec. The only shared mechanism extracted is the RFC 8288 Link-header pagination loop behind
`list_tags`, which lives once in `semvertag/providers/_rest.py`.

An architecture review flagged roughly 70% line-level similarity between `providers/github.py` and
`providers/gitlab.py` — four methods, the tag pagination loop, the try/except-then-translate pattern
— and proposed a deep engine whose differing response shapes (`commit.message` nested vs flat
`message`, `sha` vs `id`) would be normalised through pydantic validation aliases into one uniform
attribute surface. Three options were on the table: keep the duplication and spend the effort on real
bugs; extract only the pagination driver; or go to the full descriptor engine.

GitHub's v4 REST API and GitLab's v4 REST API are **independently versioned third-party contracts**.
Most of the line-level similarity is *coincidental* — both are REST CRUD — not *essential*. Unifying
them behind one engine couples two contracts that will drift, and turns the shared engine into a
magnet for `if forge == "github"` conditionals: the wrong abstraction, which is strictly worse than
two honest copies. The pydantic-alias normalisation is the tell, because it pretends two different
API shapes are one.

The discriminating test adopted here, and reused by every later decision of this kind: **extract only
what is shared by *standard*, not by *coincidence*.** Link-header pagination is implemented the same
way by both forges because it is RFC 8288, not a coincidence — genuinely deep, stable, reused, so it
earns a shared home. Response shapes, URL paths, create-tag payloads, and conflict semantics (GitHub
422 vs GitLab 400) are where the two APIs are honestly independent and *will* diverge; those stay
separate by design. Keeping the duplication wholesale was defensible but left the one
genuinely-shared, standard mechanism copy-pasted.

**Revisit trigger:** a third forge that also paginates via RFC 8288 Link headers is added *and* its
commit/tag/default-branch operations turn out to be expressible as pure per-forge **data** with
**zero** forge-conditionals in the shared code. Two such forges plus a clean data-only third would
mean the descriptor engine is a real seam rather than a forced unification, and it is worth
re-pricing. Conversely, the moment the shared pagination helper needs its first forge-conditional,
narrow it back toward two independent copies.

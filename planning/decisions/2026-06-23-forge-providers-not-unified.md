---
status: accepted
summary: Keep one provider class per forge; share only the Link-pagination loop, not a unified engine.
supersedes: null
superseded_by: null
---

# Forge providers stay separate; share only what's shared by standard

**Decision:** `GitHubProvider` and `GitLabProvider` remain independent classes.
We do **not** collapse them into a single descriptor-driven `RestForgeProvider`
engine. The only shared mechanism we extract is the RFC 8288 Link-header
pagination loop behind `list_tags`.

## Context

An architecture review flagged ~70% line-level similarity between
`providers/github.py` and `providers/gitlab.py` (four methods, the tag
pagination loop, the try/except→translate pattern) and proposed a deep
`RestForgeProvider` engine parameterised by a per-forge `ForgeSpec` value, with
the differing response shapes (`commit.message` nested vs flat `message`,
`sha` vs `id`) normalised via pydantic validation aliases into a uniform
attribute surface.

Options on the table:

- **(a)** Keep the duplication; spend effort on the real bugs instead.
- **(b)** Extract only the tag-pagination driver loop into a shared helper;
  keep both provider classes owning their own paths, shapes, payloads, and
  error handling. *(chosen)*
- **(c)** Full descriptor engine — forges become data behind one class.

## Decision & rationale

GitHub's v4 REST API and GitLab's v4 REST API are **independently versioned
third-party contracts**. Most of the line-level similarity is *coincidental*
(both are REST CRUD), not *essential*. Unifying them behind one engine couples
two contracts that will drift, and turns the shared engine into a magnet for
`if forge == "github"` conditionals — the wrong abstraction, which is strictly
worse than two honest copies. The pydantic-alias normalisation is the tell: it
pretends two different API shapes are one.

The discriminating test we adopted: **extract only what is shared by *standard*,
not by *coincidence*.** Link-header pagination (RFC 8288) is implemented the
same way by GitHub and GitLab because it is a spec, not a coincidence — that is
genuinely deep, stable, and reused, so it earns a shared home. Response shapes,
URL paths, create-tag payloads, and conflict semantics (GitHub 422 vs GitLab
400) are where the two APIs are honestly independent and *will* diverge; those
stay duplicated/separate by design.

(c) is rejected for the coupling reason above. (a) is defensible but leaves the
one genuinely-shared, standard mechanism — the pagination loop — copy-pasted.
(b) deepens exactly that and nothing more.

## Revisit trigger

Reopen if **a third forge that also paginates via RFC 8288 Link headers** is
added *and* its commit/tag/default-branch operations turn out to be
expressible as pure per-forge **data** with **zero forge-conditionals** in the
shared code. Two such forges plus a clean data-only third would mean the
descriptor engine is no longer a forced unification but a real seam — at which
point (c) is worth re-pricing. Conversely, the moment the shared pagination
helper needs its first forge-conditional, narrow it back toward (a).

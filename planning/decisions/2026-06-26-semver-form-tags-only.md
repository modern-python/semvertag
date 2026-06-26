---
status: accepted
summary: The bump baseline is selected from SemVer-form tags only; PEP 440 prereleases and v-prefixed tags are skipped, and SemVer-form prereleases finalize via next_version.
---

# Bump baseline is SemVer-form only; prereleases finalize via `next_version`

**Decision:** `_select_latest_semver_tag` (in `semvertag/_use_case.py`) picks the
bump baseline from tags parseable by `semver.Version.parse` — i.e. **SemVer-form**
(`MAJOR.MINOR.PATCH`, optionally `-prerelease`/`+build`). Tags that are not valid
SemVer are skipped: **PEP 440 prereleases** (`0.9.0rc1`, `0.8.1a1`) and
**`v`-prefixed** tags (`v1.2.3`). When a SemVer-form *prerelease* (`1.0.0-rc.1`)
is the selected baseline, the new version is computed with `Version.next_version`
(which **finalizes** the prerelease — `1.0.0-rc.1` + patch → `1.0.0`), **not**
`bump_*` (which would jump to `1.0.1`).

## Context

A research-grade review of the tag-selection chain found that the chain's
*composed* behavior had untested, emergent semantics. `semver.Version.parse` is
strict: it rejects `v1.2.3` and PEP 440 prereleases, so both are silently skipped
from selection. Separately, the old `bump_*` arithmetic on a (SemVer-form)
prerelease baseline jumps past the finalization (`1.0.0-rc.1` patch → `1.0.1`)
instead of finalizing to `1.0.0`.

Options considered for prerelease/format recognition:

- **(a)** SemVer-form only + `next_version` to finalize. *(chosen)*
- **(b)** Recognize PEP 440 prereleases too (via the `packaging` library or a
  hand-rolled normalizer). *(rejected)*
- **(c)** Recognize `v`-prefixed tags (strip a leading `v`/`V` before parse).
  *(deferred)*

## Decision & rationale

semvertag is a **SemVer** tagger: it emits bare `X.Y.Z`, sorts by SemVer
precedence, and the format it should expect in a managed repo is SemVer-form. The
discriminating "shared by standard, not by coincidence" lens applies:

- **`next_version` (chosen) is feasible, dependency-free, and behavior-preserving
  for every current tag.** On a stable baseline **without build metadata**
  `next_version(part)` equals `bump_*` exactly; it differs only by finalizing a
  SemVer-form prerelease baseline — which is the correct release-ramp semantics
  and the bug the review found. The selector strips build metadata
  (`.replace(build=None)`) before carrying the `Version`, so a hand-pushed
  `1.0.0+build`-style tag (SemVer-valid, precedence-irrelevant) is carried as
  `1.0.0` and bumps correctly to `1.0.1`; semvertag never emits build metadata,
  so stripping is safe. A SemVer-form prerelease baseline also finalizes on
  major/minor/patch alike (e.g. `1.0.0-rc.1` + major → `1.0.0`, not `2.0.0`,
  because the lower parts are already zero) — defensible release-ramp semantics,
  dormant because semvertag never self-emits prereleases. No new dependency, no
  new version model.
- **(b) PEP 440 recognition is rejected** because `python-semver` has no PEP 440
  parser (the `coerce` recipe extracts only `major.minor.patch` and *discards* the
  `rc1`, making a prerelease masquerade as final — unusable). Real support needs
  the `packaging` library running *alongside* `semver` — two version models in one
  selection path — to recognize a form that a SemVer tool should not need to
  consume. PEP 440 is semvertag's own PyPI-publishing quirk (on its dry-run
  dogfood repo), not the form user repos managed by semvertag carry.
- **(c) `v`-prefix recognition is deferred,** not rejected: it is cheap
  (strip a leading `v`/`V`) but a distinct *policy* change — semvertag would then
  *consume* `v`-prefixed tags while still *emitting* bare semver, a mixed
  convention worth deciding deliberately. It is a real adoption footgun (a repo
  with `v`-prefixed history sees `NoTags`), tracked for its own change.

## Revisit trigger

- **(b)** Reopen if users need PEP 440 prerelease tags recognized as bump
  baselines in managed repos — at which point adding `packaging` (PEP 440-native
  ordering) for selection, kept separate from the `semver` bump, is worth pricing.
- **(c)** Reopen `v`-prefix recognition when adoption against `v`-prefixed repos
  is a goal; the fix is a leading-`v` strip before parse, plus a decision on
  whether semvertag should then also emit `v`-prefixed tags.

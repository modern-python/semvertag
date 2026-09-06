# Bump baseline is SemVer-form only; prereleases finalize via `next_version`

**Decision:** `_select_latest_semver_tag` picks the bump baseline from tags parseable by
`semver.Version.parse` — SemVer-form (`MAJOR.MINOR.PATCH`, optionally `-prerelease`/`+build`). Tags
that are not valid SemVer are skipped: **PEP 440 prereleases** (`0.9.0rc1`, `0.8.1a1`) and
**`v`-prefixed** tags (`v1.2.3`). When a SemVer-form *prerelease* (`1.0.0-rc.1`) is the selected
baseline, the new version is computed with `Version.next_version`, which **finalizes** it
(`1.0.0-rc.1` + patch → `1.0.0`), not with `bump_*`, which would jump to `1.0.1`.

A review of the tag-selection chain found that its *composed* behavior had untested, emergent
semantics. `semver.Version.parse` is strict, so `v1.2.3` and PEP 440 prereleases are silently skipped
from selection; and the old `bump_*` arithmetic on a SemVer-form prerelease baseline jumped past
finalization instead of reaching it. Three options were considered for what the selector should
recognize: SemVer-form only with `next_version` to finalize (chosen); PEP 440 prereleases too
(rejected); `v`-prefixed tags too (deferred).

semvertag is a **SemVer** tagger: it emits bare `X.Y.Z`, sorts by SemVer precedence, and SemVer-form
is the format it should expect in a repo it manages.

`next_version` is feasible, dependency-free, and behavior-preserving for every tag that exists today.
On a stable baseline without build metadata it equals `bump_*` exactly; it differs only by finalizing
a SemVer-form prerelease baseline, which is the correct release-ramp semantics and the bug the review
found. The selector strips build metadata before carrying the `Version`, so a hand-pushed
`1.0.0+build` tag — SemVer-valid, precedence-irrelevant — is carried as `1.0.0` and bumps to
`1.0.1`; semvertag never emits build metadata, so stripping is safe. A prerelease baseline also
finalizes on major and minor alike (`1.0.0-rc.1` + major → `1.0.0`, because the lower parts are
already zero) — defensible release-ramp semantics, and dormant because semvertag never self-emits
prereleases.

**PEP 440 recognition is rejected.** `python-semver` has no PEP 440 parser; its `coerce` recipe
extracts only `major.minor.patch` and *discards* the `rc1`, making a prerelease masquerade as final —
unusable. Real support needs the `packaging` library running *alongside* `semver`, two version models
in one selection path, to recognize a form a SemVer tool should not need to consume. PEP 440 is
semvertag's own PyPI-publishing quirk, not the form of the repos it manages.

**`v`-prefix recognition is deferred, not rejected.** It is cheap — strip a leading `v`/`V` before
parse — but a distinct *policy* change: semvertag would then *consume* `v`-prefixed tags while still
*emitting* bare semver, a mixed convention worth deciding deliberately. It is a real adoption
footgun, since a repo with `v`-prefixed history sees `NoTags` and never bumps.

**Revisit trigger:** for PEP 440, users need prerelease tags recognized as bump baselines in managed
repos — at which point adding `packaging` for selection, kept separate from the `semver` bump, is
worth pricing. For the `v` prefix, adoption against `v`-prefixed repos becomes a goal; the fix is a
leading-`v` strip before parse, plus a decision on whether semvertag should then also emit
`v`-prefixed tags.

---
summary: Folded the tag-selection chain into _select_latest_semver_tag, which carries the parsed Version to _compute_new_version; next_version finalizes SemVer-form prerelease baselines.
---

# Design: Deepen the semver-tag selection chain

## Summary

The "pick the bump baseline and bump it" step in `semvertag/_use_case.py` is four
shallow pure helpers: `_try_parse_semver` → `_parse_semver_tags` →
`_pick_latest_semver_tag` → `_compute_new_version`. Each is trivially correct in
isolation, but the *composed* behavior — skip-unparseable, sort by precedence,
pick-max, then bump — has emergent semantics that no helper test captures, and the
winning tag is **parsed twice** (the selector discards the parsed `Version`, then
`_compute_new_version` re-parses it). This change folds the three parse-helpers
into one `_select_latest_semver_tag(tags) -> tuple[Tag, semver.Version] | None`
that carries the parsed `Version` through, and switches the bump arithmetic from
`bump_*` to `Version.next_version` so a SemVer-form prerelease baseline finalizes
(`1.0.0-rc.1` + patch → `1.0.0`, not `1.0.1`). One interface becomes the real test
surface; the emergent edges get explicit tests. See
[`decisions/2026-06-26-semver-form-tags-only.md`](../../decisions/2026-06-26-semver-form-tags-only.md).

## Motivation

`semvertag/_use_case.py:54-85`:

- **Parse-twice.** `_pick_latest_semver_tag` parses every tag into a `Version`,
  sorts, returns only the `Tag` — discarding the `Version`. `_compute_new_version`
  then re-parses `last_tag.name`.
- **Untested emergent surface.** PEP 440 prereleases (`0.9.0rc1`) and `v`-prefixed
  tags (`v0` — a real tag in this repo) are silently skipped by strict
  `Version.parse`; build-metadata ties are input-order-dependent. None of this is
  tested at the seam where it lives — the only non-semver test uses
  `release-2024-Q1`/`latest`.
- **Latent prerelease bug.** `bump_patch` on a SemVer-form prerelease baseline
  (`1.0.0-rc.1`) jumps to `1.0.1` instead of finalizing to `1.0.0`.

The four helpers are the textbook "extracted for testability, but the real bug is
in how they're composed" shape — low locality. Deletion test: folding them
concentrates the selection logic in one interface rather than scattering a
four-hop chain.

## Non-goals

- **No PEP 440 recognition** and **no `v`-prefix recognition** — both decided in
  `decisions/2026-06-26-semver-form-tags-only.md` (rejected / deferred). Selection
  stays SemVer-form only.
- No change to the `Outcome` variants, the providers, strategies, output, or DI.
- No change for *stable* baselines **without build metadata**: `next_version(part)`
  equals `bump_*` there, so every existing bare-semver tag behaves identically. The
  selector strips build metadata (precedence-irrelevant; semvertag never emits it),
  so the carried `Version` is always build-free and `next_version` is never tripped
  by a `1.0.0+build`-style tag.

## Design

### 1. One selector carrying the parsed `Version`

Replace `_try_parse_semver` / `_parse_semver_tags` / `_pick_latest_semver_tag`
with:

```python
def _select_latest_semver_tag(tags: list[Tag]) -> tuple[Tag, semver.Version] | None:
    parsed: list[tuple[semver.Version, Tag]] = []
    for tag in tags:
        try:
            version = semver.Version.parse(tag.name).replace(build=None)
        except ValueError:
            continue
        parsed.append((version, tag))
    if not parsed:
        return None
    parsed.sort(key=lambda item: item[0])
    version, tag = parsed[-1]
    return tag, version
```

`sorted(...)[-1]` (not `max`) preserves the current **last-equal-wins** tie order
for versions that compare equal (build metadata is ignored in precedence). The
`.replace(build=None)` strips build metadata from the carried `Version` so that
`next_version` never treats a `1.0.0+build`-style baseline as already-finalized
and skips the bump. semvertag never emits build metadata; stripping it is
precedence-neutral.

### 2. Bump via `next_version`, on the carried `Version`

```python
_BUMP_PARTS: typing.Final[dict[Bump, str]] = {Bump.MAJOR: "major", Bump.MINOR: "minor", Bump.PATCH: "patch"}

def _compute_new_version(version: semver.Version, bump: Bump) -> str:
    return str(version.next_version(_BUMP_PARTS[bump]))
```

It takes the `Version` from the selector tuple — the winning tag is never parsed
twice. `next_version` is behavior-preserving on stable baselines and finalizes
SemVer-form prerelease baselines.

### 3. Use-case wiring

```python
tags = self.provider.list_tags()
selected = _select_latest_semver_tag(tags)
if selected is None:
    return self._emit(output, NoTags(commit=commit.sha))
latest_tag, latest_version = selected
if latest_tag.commit_sha == commit.sha:
    return self._emit(output, AlreadyTagged(tag=latest_tag.name, commit=commit.sha))
...
new_version = _compute_new_version(latest_version, bump)
```

Same `NoTags` / `AlreadyTagged` / no-bump logic; only the carried `Version` is new.

## Testing

TDD. Direct helper tests in `tests/unit/test_use_case.py` (helpers stay in
`_use_case.py`):

- `_select_latest_semver_tag`: empty → `None`; all-unparseable
  (`release-2024-Q1`, `latest`, `v0`) → `None`; PEP 440 skip (`[0.8.1, 0.9.0rc1]`
  → `0.8.1`); SemVer-form prerelease participates/orders (`[1.0.0-rc.1, 0.9.0]` →
  `1.0.0-rc.1`); tie last-wins (`[1.0.0+a (x), 1.0.0+b (y)]` → `1.0.0+b`); returns
  the parsed `Version` alongside the `Tag`.
- `_compute_new_version`: finalize (`Version.parse("1.0.0-rc.1")`, `Bump.PATCH`) →
  `"1.0.0"`; stable cases unchanged.

Keep all existing use-case integration tests (behavior-preservation proof; they
stay green). Gates: `just test` (100% branch), `just lint-ci`, `just docs-build`.

## Risk

- **`next_version` behavior change (medium × low).** Mitigated: it equals `bump_*`
  on every stable baseline (so all existing tests pass unchanged), and differs only
  by finalizing prerelease baselines, which is the intended fix. The existing
  parametrized bump test (`1.4.2` → major/minor/patch) is the guardrail.
- **Tie-order regression (low × low).** `sorted(...)[-1]` preserves last-equal-wins;
  a new test pins it.
- **Coverage (low × low).** The folded selector's branches (parse ok/skip, empty,
  sort) and the `_BUMP_PARTS` lookups are covered by the direct tests plus the
  existing suite.
- **`architecture/cli.md` drift (low × low).** The Use-case section names
  `_pick_latest_semver_tag` and `bump_*`; promote it in the same PR.

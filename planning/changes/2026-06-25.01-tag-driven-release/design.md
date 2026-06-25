---
status: shipped
date: 2026-06-25
slug: tag-driven-release
summary: Tag-driven release.yml (PyPI + Release + v0); dogfood goes dry-run; publish.yml/tag-major.yml deleted.
supersedes: null
superseded_by: null
pr: 35
outcome: |
  Shipped a tag-driven release.yml (PyPI -> GitHub Release -> v0 float) replacing
  publish.yml + tag-major.yml; semvertag.yml dogfood runs dry-run so a hand-pushed
  bare semver tag is the sole release entry point. Maintainer runbook moved to
  CLAUDE.md; stale docs/contributing/release.md removed.
---

# Design: Tag-driven release for semvertag

## Summary

Replace the manual GitHub-Release-creation gate with a single tag-driven
`release.yml`, adapting the change `modern-di` shipped in #233/#235. Pushing a
bare semver tag publishes to PyPI (version from the tag), creates the matching
GitHub Release (body from `planning/releases/<tag>.md` when present), and floats
the `v0` action tag — all in one job, PyPI first. To keep the tag the *sole,
deliberate* release entry point, the self-dogfooding auto-tagger
(`semvertag.yml`) switches to dry-run so it stops pushing tags. `publish.yml`
and `tag-major.yml` are deleted (the latter folded into `release.yml`), and the
maintainer-only release runbook moves out of the user-facing docs site into
`CLAUDE.md`.

## Motivation

`modern-di` collapsed its two-step release (push tag → manually draft a GitHub
Release to trigger publish) into one tag-driven workflow. We want the same
ergonomics here. But the adaptation is non-trivial, because semvertag
**dogfoods its own auto-tagger**: `semvertag.yml` auto-creates and pushes the
version tag on every qualifying merge to `main`, and today the *manual GitHub
Release* — not the tag — is the deliberate publish gate.

Two facts force the design:

1. **GitHub suppresses workflow triggers from `GITHUB_TOKEN`-pushed refs**
   (anti-recursion). The dogfood pushes tags with `GITHUB_TOKEN`, so a naïve
   `on: push: tags` trigger would never fire on auto-tags — releases would
   silently never publish. The same rule is why the existing `tag-major.yml`
   (`on: release: published`) would stop firing once `release.yml` creates the
   Release with `GITHUB_TOKEN`.
2. A human `git push` of a tag is **not** suppressed. So a maintainer-pushed
   tag is a clean, reliable entry point — *if* nothing else is pushing tags.

The chosen model makes the manual tag the only tag: the dogfood goes dry-run
(it still exercises `action.yml` on every push via `--dry-run`, just stops
pushing), and the maintainer pushes the release tag by hand.

Separately, `docs/contributing/release.md` is already stale — it documents OIDC
trusted-publishing, a tag-guard, `workflow_dispatch`, and `v`-prefixed tags,
none of which match the real `publish.yml` (which uses a `PYPI_TOKEN` secret and
bare semver). It centers on `publish.yml`, the file this change deletes.

## Non-goals

- Continuous/auto release on every merge (rejected: release history is
  deliberate, each with a hand-written `planning/releases/<v>.md`).
- Migrating PyPI auth to OIDC trusted publishing — the repo uses a `PYPI_TOKEN`
  secret and that is unchanged here.
- Rewriting historical `planning/releases/*.md` — they record how past releases
  actually happened and stay as-is.
- Changing the `just publish` recipe — it already derives the version from
  `$GITHUB_REF_NAME` and works unchanged on a tag push.

## Design

### 1. `.github/workflows/release.yml` (new)

Adapted verbatim from `modern-di`'s canonical `release.yml`, plus a folded-in
`Float major tag` step replacing `tag-major.yml`.

- **Trigger**: `on: push: tags` with two patterns — stable
  `[0-9]+.[0-9]+.[0-9]+` (e.g. `0.9.0`) and PEP 440 pre-release
  `[0-9]+.[0-9]+.[0-9]+[a-z]+[0-9]+` (e.g. `0.9.0rc1`). Bare semver, matching
  this repo's release-tag convention.
- **`permissions: contents: write`** — needed for `action-gh-release` and the
  `v0` force-push.
- **Steps**:
  1. `actions/checkout@v6`, `extractions/setup-just@v4`, `astral-sh/setup-uv@v7`
     (the `@v7` pin matches the org canonical template adopted in `modern-di`
     #235).
  2. `just publish` with `PYPI_TOKEN` — **runs first** because PyPI is
     irreversible; a failed publish stops the job before any Release is created.
     `just publish` stamps the version from `$GITHUB_REF_NAME`.
  3. `meta` step: if `planning/releases/<tag>.md` exists, use it as `body_path`
     (verbatim, no auto-changelog) and set `generate_notes=false`; else
     `generate_notes=true`. `prerelease=true` when the tag contains a letter.
  4. `softprops/action-gh-release@v3` creates the Release
     (`body_path` / `generate_release_notes` / `prerelease` / `draft: false`).
  5. **`Float major tag`** (folded-in `tag-major`), `if:
     steps.meta.outputs.prerelease == 'false'`:

     ```bash
     major="v${GITHUB_REF_NAME%%.*}"        # 0.9.0 -> v0
     git config user.name  'github-actions[bot]'
     git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
     git tag -fa "$major" -m "Update $major to $GITHUB_REF_NAME"
     git push -f origin "$major"
     ```

     References `HEAD` (the tag commit), so no `fetch-depth: 0` is required, and
     reuses the `meta` prerelease flag instead of `tag-major`'s old
     `github.event.release.prerelease`.

Ordering rationale: PyPI (irreversible) → GitHub Release (user-facing artifact)
→ `v0` (a convenience floating tag, last because it depends on nothing).

### 2. Deletions

- **Delete `.github/workflows/publish.yml`** — replaced by `release.yml`. Its
  `on: release: published` trigger is removed so the Release that `release.yml`
  now creates cannot re-fire a publish (double-publish).
- **Delete `.github/workflows/tag-major.yml`** — folded into `release.yml`
  step 5. (Keeping it separate on `release: published` would break: a Release
  created by `release.yml` with `GITHUB_TOKEN` does not fire it.)

### 3. `.github/workflows/semvertag.yml` — dogfood to dry-run

- Add `with: { dry-run: true }` to the `uses: ./` step. `action.yml` already
  supports the `dry-run` input (`--dry-run`), so the dogfood still exercises the
  action on every push to `main` but never pushes a tag.
- Rewrite the header comment: it no longer "creates a tag"; it computes the
  planned bump only. Releases are cut by a manual tag push that triggers
  `release.yml`.
- Downgrade `permissions:` from `contents: write` to `contents: read` — dry-run
  never writes.

### 4. Docs & maintainer guide

- **Delete `docs/contributing/release.md`** and remove its mkdocs nav entry (the
  whole `Contributing:` section — it is the only page under that node). The
  release process is maintainer-only and does not belong in the user-facing
  docs site (mirrors `modern-di`, which keeps it out of contributor docs). This
  also retires the file's pre-existing OIDC/tag-guard staleness.
- **`CLAUDE.md`**:
  - Add a "Cutting a release (maintainers)" note to the Workflow section: write
    `planning/releases/<version>.md`, push a bare semver tag off green `main`
    (`git tag 0.9.0 && git push origin 0.9.0`); `release.yml` publishes to PyPI
    (version from the tag), creates the GitHub Release, and floats `v0`.
    Pre-releases use PEP 440 (`0.9.0rc1`). PyPI is irreversible; the tag is the
    commitment point (no CI gate — a tag is cut off green `main`). Note the
    dogfood is dry-run, so no auto-tags are created.
  - Update the "Tag and release naming" section: the `v0` paragraph currently
    points at `.github/workflows/tag-major.yml`; repoint it at `release.yml`'s
    `Float major tag` step.

## Operations

None out-of-repo. The `PYPI_TOKEN` secret already exists (used by the current
`publish.yml`); `release.yml` reuses it under the same name.

## Out of scope

See Non-goals.

## Testing

These are CI YAML and docs changes; the 100%-branch pytest gate is Python-only
and does not apply. Verification gate before completion:

- `python -c "import yaml, sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]"`
  on `release.yml`, `semvertag.yml` — both parse.
- Confirm `publish.yml` and `tag-major.yml` are gone and nothing references them
  (`grep -rn` over `.github/`, `mkdocs.yml`, `CLAUDE.md`, `docs/`).
- `just lint-ci`.
- `just docs-build` (`mkdocs build --strict`) — proves the nav no longer
  references the deleted `contributing/release.md`.

The true integration test is the next real release (the maintainer pushes a tag
and watches `release.yml` go green: PyPI upload, Release created from the notes
file, `v0` repointed). Called out as the post-merge step in `plan.md`.

## Risk

- **Auto-tags silently stop (intended), but a maintainer forgets the dogfood is
  now dry-run** and waits for an auto-tag that never comes. *Likelihood: low ·
  Impact: low.* Mitigated by the `CLAUDE.md` release note and the rewritten
  `semvertag.yml` header comment.
- **A future change re-points the dogfood push at a PAT**, resurrecting
  auto-tags that would then auto-publish. *Likelihood: low · Impact: high.* The
  header comment documents the dry-run-is-load-bearing invariant; the
  `release.yml` trigger comment notes the manual-tag-only contract.
- **First post-migration release double-publishes** if the old
  `release: published` path somehow lingers. *Likelihood: very low · Impact:
  high.* Mitigated by deleting `publish.yml` outright (no overlap window).
- **`planning/releases/<tag>.md` missing at release time** → `release.yml`
  falls back to GitHub generated notes (graceful, not a failure).

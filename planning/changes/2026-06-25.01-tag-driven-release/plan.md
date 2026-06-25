---
status: shipped
date: 2026-06-25
slug: tag-driven-release
spec: tag-driven-release
pr: 35
---

# tag-driven-release — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a hand-pushed bare semver tag the sole release entry point —
one `release.yml` publishes to PyPI, creates the GitHub Release, and floats
`v0` — and stop the dogfood from auto-tagging.

**Spec:** [`design.md`](./design.md)

**Branch:** `ci/tag-driven-release`

**Commit strategy:** Per-task commits; single PR; squash on merge.

## Global constraints (copy verbatim, every task)

- **Release tags are bare semver, no `v` prefix** (`0.9.0`, not `v0.9.0`).
  `$GITHUB_REF_NAME` is the bare tag.
- **Action pins:** `actions/checkout@v6`, `extractions/setup-just@v4`,
  `astral-sh/setup-uv@v7` (the `@v7` pin matches the org canonical template).
- **PyPI is irreversible → it runs first.** Nothing user-facing (Release, `v0`)
  is created before `just publish` succeeds.
- **PyPI auth is the existing `PYPI_TOKEN` secret** (not OIDC). Reused under the
  same name.
- **Pre-release tags use PEP 440** (`0.9.0rc1`), detected by a letter in the tag.
- These are CI/docs YAML + Markdown changes; the 100%-branch pytest gate is
  Python-only and does not apply. Verification is YAML-parse + grep + lint +
  strict docs build.
- Commit messages: imperative, scoped (`ci:` / `docs:`), no story prefixes; end
  with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Add tag-driven `release.yml`; delete `publish.yml` and `tag-major.yml`

**Files:**
- Create: `.github/workflows/release.yml`
- Delete: `.github/workflows/publish.yml`
- Delete: `.github/workflows/tag-major.yml`

Replace the manual `release: published` publish gate and the separate
`tag-major` workflow with one tag-driven workflow. The `v0` float logic from
`tag-major.yml` is folded into `release.yml`'s final step.

- [ ] **Step 1: Create `.github/workflows/release.yml`** with exactly this content:

  ```yaml
  name: Release

  # Tag-driven: pushing a bare semver tag publishes to PyPI, creates the matching
  # GitHub Release, and floats the `v0` action tag. Replaces the old
  # `release: published` publish.yml (deleted) and folds in tag-major.yml (deleted).
  #
  # The tag is the sole, deliberate entry point. semvertag.yml dogfoods in
  # DRY-RUN, so it never pushes a tag — only a maintainer's manual `git push` of
  # a tag reaches here (GitHub suppresses workflow triggers from
  # GITHUB_TOKEN-pushed refs, so even an auto-push would not fire this). By
  # convention a tag is cut only off green main, so there is no in-workflow CI gate.
  on:
    push:
      tags:
        - '[0-9]+.[0-9]+.[0-9]+'               # stable:      0.9.0
        - '[0-9]+.[0-9]+.[0-9]+[a-z]+[0-9]+'   # pre-release: 0.9.0rc1, 1.0.0a2

  # Needed for softprops/action-gh-release to create the Release and for the
  # v0 force-push.
  permissions:
    contents: write

  jobs:
    release:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v6
        - uses: extractions/setup-just@v4
        - uses: astral-sh/setup-uv@v7

        # PyPI is irreversible, so it runs FIRST: if it fails the job stops and no
        # GitHub Release or v0 move advertises a version that never reached PyPI.
        # `just publish` derives the version from $GITHUB_REF_NAME (the tag name).
        - run: just publish
          env:
            PYPI_TOKEN: ${{ secrets.PYPI_TOKEN }}

        # Description source: planning/releases/<tag>.md if present (verbatim, no
        # auto-changelog appended); otherwise GitHub's generated notes. A tag with
        # a letter (0.9.0rc1) is a pre-release -> flagged so GitHub won't mark it
        # "Latest" and so the v0 float below is skipped.
        - name: Resolve release metadata
          id: meta
          run: |
            set -euo pipefail
            notes="planning/releases/${GITHUB_REF_NAME}.md"
            if [ -f "$notes" ]; then
              echo "body_path=$notes" >> "$GITHUB_OUTPUT"
              echo "generate_notes=false" >> "$GITHUB_OUTPUT"
            else
              echo "generate_notes=true" >> "$GITHUB_OUTPUT"
            fi
            if [[ "$GITHUB_REF_NAME" =~ [a-z] ]]; then
              echo "prerelease=true" >> "$GITHUB_OUTPUT"
            else
              echo "prerelease=false" >> "$GITHUB_OUTPUT"
            fi

        - name: Publish GitHub Release
          uses: softprops/action-gh-release@v3
          with:
            body_path: ${{ steps.meta.outputs.body_path }}
            generate_release_notes: ${{ steps.meta.outputs.generate_notes }}
            prerelease: ${{ steps.meta.outputs.prerelease }}
            draft: false

        # Floating major tag (folded-in tag-major.yml): consumers pin
        # `uses: modern-python/semvertag@v0` and ride minor bumps. Skipped on
        # pre-releases so a 0.9.0rc1 doesn't drag v0 ahead of the latest stable.
        # References HEAD (the tag commit), so no fetch-depth: 0 is needed.
        - name: Float major tag
          if: steps.meta.outputs.prerelease == 'false'
          run: |
            set -euo pipefail
            major="v${GITHUB_REF_NAME%%.*}"      # 0.9.0 -> v0
            git config user.name  'github-actions[bot]'
            git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
            git tag -fa "$major" -m "Update $major to $GITHUB_REF_NAME"
            git push -f origin "$major"
  ```

- [ ] **Step 2: Delete the two superseded workflows**

  ```bash
  git rm .github/workflows/publish.yml .github/workflows/tag-major.yml
  ```

- [ ] **Step 3: Verify `release.yml` parses as YAML**

  Run:
  ```bash
  python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))" && echo OK
  ```
  Expected: `OK`

- [ ] **Step 4: Verify the deletions are clean and nothing references them**

  Run (scoped to live config — `planning/` keeps its historical references on purpose):
  ```bash
  ls .github/workflows/
  grep -rn 'publish\.yml\|tag-major' .github/ mkdocs.yml docs/ || echo CLEAN
  ```
  Expected: `publish.yml` and `tag-major.yml` absent from the listing. The grep
  still prints one line — `semvertag.yml`'s stale `does NOT trigger publish.yml`
  comment — which Task 2 rewrites. That single hit is expected here; do not fix
  it in this task. No `tag-major` hits, no hits in `mkdocs.yml`/`docs/`.

- [ ] **Step 5: Commit**

  ```bash
  git add .github/workflows/release.yml
  git commit -m "ci: replace publish.yml + tag-major.yml with tag-driven release.yml

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Switch the dogfood (`semvertag.yml`) to dry-run

**Files:**
- Modify: `.github/workflows/semvertag.yml`

The auto-tagger must stop pushing tags, so the only tags that reach the repo are
deliberate, maintainer-pushed release tags. It still exercises `action.yml` on
every push to `main` via `--dry-run`.

- [ ] **Step 1: Replace the entire contents of `.github/workflows/semvertag.yml`** with:

  ```yaml
  name: semvertag

  # Dogfood the local composite action against this repo in DRY-RUN: on every
  # push to main it computes the planned bump (exercising action.yml + the
  # published semvertag) but never pushes a tag. This keeps action.yml honest —
  # a breaking change fails the run before it can affect external users.
  #
  # Releases are NOT cut here. A release is a maintainer pushing a bare semver
  # tag by hand, which triggers .github/workflows/release.yml (PyPI + GitHub
  # Release + v0). Dry-run is load-bearing: it guarantees the only tags in the
  # repo are deliberate release tags — do not give this job a push token or
  # remove `dry-run: true`.
  #
  # This repo's branch convention uses `feat/...`, so SEMVERTAG_BRANCH_PREFIX__MINOR
  # overrides the default `feature/` mapping.

  on:
    push:
      branches: [main]

  permissions:
    contents: read

  concurrency:
    group: semvertag
    cancel-in-progress: false

  jobs:
    tag:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v6
          with:
            fetch-depth: 0
        - uses: ./
          with:
            dry-run: true
          env:
            SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'
  ```

- [ ] **Step 2: Verify it parses and the dry-run wiring is present**

  Run:
  ```bash
  python3 -c "import yaml; yaml.safe_load(open('.github/workflows/semvertag.yml'))" && echo OK
  grep -n 'dry-run: true\|contents: read' .github/workflows/semvertag.yml
  ```
  Expected: `OK`, and both `dry-run: true` and `contents: read` print.

- [ ] **Step 3: Commit**

  ```bash
  git add .github/workflows/semvertag.yml
  git commit -m "ci: run the semvertag dogfood in dry-run (stop auto-tagging)

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Move the release runbook out of user-facing docs

**Files:**
- Delete: `docs/contributing/release.md`
- Modify: `mkdocs.yml` (remove the `Contributing:` nav node)
- Modify: `CLAUDE.md` (add maintainer release note; repoint the `v0` paragraph)

The release process is maintainer-only and should not ship in the docs site. It
lives in `CLAUDE.md` instead. `release.md` is the only page under
`docs/contributing/`, so its whole nav node goes too.

- [ ] **Step 1: Delete the runbook page**

  ```bash
  git rm docs/contributing/release.md
  ```

- [ ] **Step 2: Remove the `Contributing:` nav node from `mkdocs.yml`**

  Delete these two lines (currently lines 14–15):
  ```yaml
    - Contributing:
      - Release runbook: contributing/release.md
  ```
  After the edit, the `nav:` block ends with the `Strategies:` node
  (`Conventional commits: strategies/conventional-commits.md`).

- [ ] **Step 3: Add the maintainer release note to `CLAUDE.md`**

  In the `## Workflow` section, immediately after the paragraph that ends
  "...use the change bundle under `planning/changes/` here instead." (the
  "Planning artifacts live under `planning/`..." paragraph), insert a blank line
  then this paragraph:

  ```markdown
  **Cutting a release (maintainers)** is tag-driven via
  [`.github/workflows/release.yml`](.github/workflows/release.yml): write the
  notes at `planning/releases/<version>.md` (used verbatim as the GitHub Release
  body), then push a bare semver tag off green `main` —
  `git tag 0.9.0 && git push origin 0.9.0`. The workflow runs `just publish` (the
  tag sets the version via `uv version $GITHUB_REF_NAME`; no `pyproject.toml`
  bump) to PyPI, then creates the GitHub Release, then floats the `v0` action tag
  — PyPI first, so a failed publish creates no Release. Pre-releases use the
  PEP 440 form (`0.9.0rc1`, not `0.9.0-rc1`). PyPI is irreversible; there is no
  CI gate (a tag is the commitment point). The dogfood (`semvertag.yml`) runs in
  dry-run and never auto-tags, so the tag you push is the only tag.
  ```

- [ ] **Step 4: Repoint the `v0` paragraph in the "Tag and release naming" section**

  In `CLAUDE.md`, replace the second bullet (currently referencing
  `.github/workflows/tag-major.yml`):

  ```markdown
  - **Action floating tag: `v`-prefixed** (`v0`). `.github/workflows/tag-major.yml`
    strips any leading `v` from the release tag then prepends `v` to the major
    segment (`0.4.0` → `v0`), so consumers can pin `uses: modern-python/semvertag@v0`
    per the GHA ecosystem convention. When touching `tag-major.yml` or
    action-consumer docs, think `v`-prefix.
  ```

  with:

  ```markdown
  - **Action floating tag: `v`-prefixed** (`v0`). The `Float major tag` step in
    [`.github/workflows/release.yml`](.github/workflows/release.yml) prepends `v`
    to the release tag's major segment (`0.4.0` → `v0`) and force-updates the
    floating tag, so consumers can pin `uses: modern-python/semvertag@v0` per the
    GHA ecosystem convention. Skipped on pre-releases. When touching that step or
    action-consumer docs, think `v`-prefix.
  ```

- [ ] **Step 5: Verify the docs build strictly and no stale refs remain**

  Run:
  ```bash
  grep -rn 'tag-major\|publish\.yml\|contributing/release' mkdocs.yml CLAUDE.md docs/ || echo CLEAN
  just docs-build
  ```
  Expected: grep prints `CLEAN`; `mkdocs build --strict` succeeds (proves the nav
  no longer points at the deleted page and there are no dead links to it).

- [ ] **Step 6: Commit**

  ```bash
  git add docs/contributing/release.md mkdocs.yml CLAUDE.md
  git commit -m "docs: move the release runbook into CLAUDE.md (maintainer-only)

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 4: Ship-time bookkeeping

**Files:**
- Modify: `planning/changes/2026-06-25.01-tag-driven-release/design.md` (frontmatter)
- Modify: `planning/changes/2026-06-25.01-tag-driven-release/plan.md` (frontmatter)

The implementing PR flips the bundle to `shipped` per the project convention.
No `architecture/` promotion — the release flow is not one of the capability
files (`strategies.md` / `providers.md` / `cli.md`).

- [ ] **Step 1: Run the full verification gate once more**

  Run:
  ```bash
  python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); yaml.safe_load(open('.github/workflows/semvertag.yml'))" && echo YAML-OK
  just lint-ci
  just docs-build
  ```
  Expected: `YAML-OK`, `lint-ci` clean, strict docs build succeeds.

- [ ] **Step 2: Set `status: shipped` and fill `pr` in both frontmatters**

  In `design.md`: `status: draft` → `status: shipped`, and set `pr:` to the PR
  number/URL. In `plan.md`: set `pr:` likewise. (Do this once the PR exists.)

- [ ] **Step 3: Regenerate the change index**

  ```bash
  just index
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add planning/changes/2026-06-25.01-tag-driven-release/
  git commit -m "planning: ship tag-driven release bundle

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## Post-merge (maintainer, not a code task)

The true integration test is the next real release. When this PR merges to
`main`, the merge commit already carries the dry-run `semvertag.yml`, so the
merge itself creates no auto-tag. To cut the first release on the new flow:

1. Ensure `planning/releases/<version>.md` exists for the target version.
2. Off green `main`: `git tag <version> && git push origin <version>`.
3. Watch `release.yml`: PyPI upload (version from the tag) → GitHub Release built
   from the notes file → `v0` repointed at the tag commit.

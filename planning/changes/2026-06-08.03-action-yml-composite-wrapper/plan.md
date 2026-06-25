# action.yml composite wrapper — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reintroduce `action.yml` at repo root as a composite GitHub Action so users can replace the 11-line install-and-run block with `uses: modern-python/semvertag@v0`. Ship a floating-major-tag workflow, migrate the dogfood + CI to consume the local action, rewrite docs, and produce a v0.4.0 release runbook including the manual Marketplace publication procedure.

**Architecture:** Pure-YAML + Markdown work. Two new workflow files (`action.yml`, `.github/workflows/tag-major.yml`), one modified workflow (`.github/workflows/semvertag.yml` dogfood), one modified workflow (`.github/workflows/ci.yml` adds an `action-smoke` job that runs `uses: ./` against the action being introduced — the chicken-and-egg is resolved by floor `'semvertag>=0.3.1,<1'` which is satisfiable from PyPI today). Docs rewrite touches README and `docs/providers/github.md`. Runbook captures the manual Marketplace publication procedure as five numbered steps for the maintainer to follow.

**Tech Stack:** GitHub Actions composite action syntax, `astral-sh/setup-uv@v7`, bash + `jq` (default on `ubuntu-latest`), MkDocs (`mkdocs build --strict` as the docs gate).

**Spec:** `planning/specs/2026-06-08-action-yml-composite-wrapper-design.md`

**Branch convention:** This is a `feat/` branch (the dogfood workflow's `SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'` maps it to a minor bump). Suggested branch: `feat/action-yml-composite-wrapper`.

---

## File structure

| File | Action | Purpose |
|---|---|---|
| `action.yml` | **create** | Composite action — `setup-uv` then `uvx 'semvertag>=0.3.1,<1' tag --json` with output parsing |
| `.github/workflows/tag-major.yml` | **create** | Force-update floating `v0` tag on each non-prerelease release |
| `.github/workflows/semvertag.yml` | **modify** | Collapse 4 install/run steps into `uses: ./` (dogfood the action) |
| `.github/workflows/ci.yml` | **modify** | Add `action-smoke` job that runs `uses: ./` and asserts outputs exist |
| `README.md` | **modify** | Replace 24-line "Use it in GitHub Actions" section (lines 42–69) with action-based snippet |
| `docs/providers/github.md` | **modify** | Delete pending callout, replace Quick Start, add Outputs section, add env-var passthrough note, add "Without the composite action" fallback |
| `planning/releases/0.4.0.md` | **create** | Release runbook with pre-flight + v0 bootstrap + Marketplace publication procedure |

---

## Verification commands referenced throughout

- **YAML parse check:** `python3 -c "import yaml; yaml.safe_load(open('PATH'))"`
- **Docs gate:** `mkdocs build --strict` (run from repo root with `.venv` active; if not active, `uv run mkdocs build --strict`)
- **Lint gate:** `just lint-ci`
- **Test gate (sanity, even though no Python changed):** `just test`

If a step says "verify" and the command exits 0 with no output, the check passed.

---

### Task 1: Create `action.yml`

**Files:**
- Create: `action.yml`

- [ ] **Step 1: Create the composite action file**

Write `action.yml` at the repo root with exactly this content:

```yaml
name: 'semvertag'
description: 'Auto-tag your GitHub repository with a SemVer git tag based on commits or branch prefixes.'
author: 'modern-python'

branding:
  icon: 'tag'
  color: 'blue'

inputs:
  strategy:
    description: 'Bump strategy: branch-prefix (default) or conventional-commits.'
    required: false
    default: 'branch-prefix'
  token:
    description: 'GitHub token with contents: write. Defaults to the workflow-issued github.token.'
    required: false
    default: ${{ github.token }}

outputs:
  tag:
    description: 'The created tag (e.g. v1.2.3), or empty string if no bump was warranted.'
    value: ${{ steps.run.outputs.tag }}
  bump:
    description: 'The computed bump: none | patch | minor | major.'
    value: ${{ steps.run.outputs.bump }}
  status:
    description: 'The run status: created (tag pushed) | no-bump (nothing to tag).'
    value: ${{ steps.run.outputs.status }}

runs:
  using: 'composite'
  steps:
    - uses: astral-sh/setup-uv@v7

    - name: Run semvertag
      id: run
      shell: bash
      env:
        GITHUB_TOKEN: ${{ inputs.token }}
        SEMVERTAG_STRATEGY: ${{ inputs.strategy }}
      run: |
        set -euo pipefail
        result=$(uvx 'semvertag>=0.3.1,<1' tag --json)
        printf '%s\n' "$result"
        # Normalize the CLI's internal status (`no_tags`, `already_tagged`,
        # `no_merge_commit`, `no_conforming_commit`, ...) to a stable
        # consumer-facing enum. `set -euo pipefail` ensures we never reach
        # here on CLI errors, so there is no `error` value to surface.
        case "$(jq -r '.status' <<<"$result")" in
          created) status='created' ;;
          *)       status='no-bump' ;;
        esac
        printf 'tag=%s\n'    "$(jq -r '.tag // ""' <<<"$result")" >> "$GITHUB_OUTPUT"
        printf 'bump=%s\n'   "$(jq -r '.bump'      <<<"$result")" >> "$GITHUB_OUTPUT"
        printf 'status=%s\n' "$status"                            >> "$GITHUB_OUTPUT"
```

- [ ] **Step 2: Verify YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('action.yml'))"`
Expected: exits 0, no output.

- [ ] **Step 3: Commit**

```bash
git add action.yml
git commit -m "feat: add action.yml composite GitHub Action"
```

---

### Task 2: Create `.github/workflows/tag-major.yml`

**Files:**
- Create: `.github/workflows/tag-major.yml`

- [ ] **Step 1: Create the workflow file**

Write `.github/workflows/tag-major.yml` with exactly this content:

```yaml
name: tag-major

# Maintains the floating `v0` major tag so users can pin `uses:
# modern-python/semvertag@v0` and ride minor bumps. Skipped on
# prereleases so an `v0.5.0-rc1` does not drag `v0` ahead of the latest
# stable. When v1.0.0 ships, this same job creates `v1` automatically
# from the tag name's leading segment.

on:
  release:
    types: [published]

permissions:
  contents: write

jobs:
  update-major-tag:
    if: ${{ !github.event.release.prerelease }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Update major tag
        env:
          RELEASE_TAG: ${{ github.event.release.tag_name }}
        run: |
          set -euo pipefail
          # RELEASE_TAG = 'v0.4.0' → major = 'v0'
          major="${RELEASE_TAG%%.*}"
          git config user.name  'github-actions[bot]'
          git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
          git tag -fa "$major" "$RELEASE_TAG" -m "Update $major to $RELEASE_TAG"
          git push -f origin "$major"
```

- [ ] **Step 2: Verify YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/tag-major.yml'))"`
Expected: exits 0, no output.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/tag-major.yml
git commit -m "ci: add tag-major workflow to maintain floating v0 tag"
```

---

### Task 3: Migrate `.github/workflows/semvertag.yml` to consume the local action

**Files:**
- Modify: `.github/workflows/semvertag.yml`

- [ ] **Step 1: Replace the file contents**

Overwrite `.github/workflows/semvertag.yml` with exactly this content:

```yaml
name: semvertag

# Dogfood the local composite action against this repo. Auto-tags on
# push to main when the latest commit is a merge from `feat/...` (minor
# bump) or `bugfix/`/`hotfix/...` (patch). This repo's branch
# convention uses `feat/...`, so SEMVERTAG_BRANCH_PREFIX__MINOR
# overrides the default `feature/` mapping.
#
# The workflow only creates a tag — it does NOT trigger publish.yml,
# which fires on GitHub release creation. To publish to PyPI, create a
# GitHub release pointed at the auto-tagged commit.
#
# `uses: ./` exercises the action.yml in the current checkout, so any
# breaking change to action.yml fails the dogfood run before it can
# affect external users.

on:
  push:
    branches: [main]

permissions:
  contents: write

concurrency:
  group: semvertag
  cancel-in-progress: false

jobs:
  tag:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: ./
        env:
          SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'
```

- [ ] **Step 2: Verify YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/semvertag.yml'))"`
Expected: exits 0, no output.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/semvertag.yml
git commit -m "ci: dogfood the composite action via uses: ./"
```

---

### Task 4: Add `action-smoke` job to `.github/workflows/ci.yml`

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Read current `ci.yml`**

Open `.github/workflows/ci.yml`. It currently has two jobs: `lint` and `pytest`. You will add a third job `action-smoke` at the end, preserving the existing two jobs unchanged.

- [ ] **Step 2: Append the `action-smoke` job**

Add this job to the `jobs:` block (after the `pytest:` job, with one blank line separating them):

```yaml
  action-smoke:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - id: semvertag
        uses: ./
        env:
          SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'
      - name: Verify outputs were emitted
        run: |
          test -n "${{ steps.semvertag.outputs.status }}"
          test -n "${{ steps.semvertag.outputs.bump }}"
```

After the edit, the full file should look like this (lint and pytest unchanged, action-smoke appended):

```yaml
name: main

on:
  push:
    branches:
      - main
  pull_request: {}

concurrency:
  group: ${{ github.head_ref || github.run_id }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: extractions/setup-just@v2
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
          cache-dependency-glob: "**/pyproject.toml"
      - run: uv python install 3.11
      - run: just install lint-ci

  pytest:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version:
          - "3.11"
          - "3.12"
          - "3.13"
          - "3.14"
    steps:
      - uses: actions/checkout@v4
      - uses: extractions/setup-just@v2
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
          cache-dependency-glob: "**/pyproject.toml"
      - run: uv python install ${{ matrix.python-version }}
      - run: just install
      - run: just test --cov-report xml

  action-smoke:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - id: semvertag
        uses: ./
        env:
          SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'
      - name: Verify outputs were emitted
        run: |
          test -n "${{ steps.semvertag.outputs.status }}"
          test -n "${{ steps.semvertag.outputs.bump }}"
```

- [ ] **Step 3: Verify YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: exits 0, no output.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add action-smoke job that exercises the composite action"
```

---

### Task 5: Rewrite README's "Use it in GitHub Actions" section

**Files:**
- Modify: `README.md` (lines 42–69, the "Use it in GitHub Actions" section)

- [ ] **Step 1: Read current `README.md`**

The current section spans lines 42–69 and contains an 11-step `steps:` block. You will replace it with an action-based snippet.

- [ ] **Step 2: Replace the section**

Replace the entire block from `## Use it in GitHub Actions` (line 42) through `> [GitHub Actions docs](docs/providers/github.md) for token scopes,` and the closing `> GitHub Enterprise setup, and troubleshooting.` (line 75, inclusive) with:

```markdown
## Use it in GitHub Actions

Paste this workflow into `.github/workflows/semvertag.yml`:

```yaml
name: semvertag
on:
  push:
    branches: [main]

permissions:
  contents: write

jobs:
  tag:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: modern-python/semvertag@v0
```

semvertag auto-detects GitHub Actions, picks the bump from the latest
commit, and creates the tag ref via the GitHub API. `fetch-depth: 0`
matters — the default `1` misses tag-relative history. See
[GitHub Actions docs](docs/providers/github.md) for token scopes,
GitHub Enterprise setup, outputs, and troubleshooting.
```

Note: the inner fenced ```yaml block must use triple-backticks, and the outer instruction must show those backticks literally. In the file, type three real backticks for both the opening and closing of the yaml block.

- [ ] **Step 3: Verify Markdown still renders (mkdocs gate)**

Run: `uv run mkdocs build --strict` from the repo root.
Expected: build succeeds with no warnings.

If mkdocs reports a strict warning, it most likely indicates a broken intra-repo link in the section you just edited. Verify the relative path `docs/providers/github.md` resolves from the repo root (it does).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README — advertise the composite action as the GHA recipe"
```

---

### Task 6: Rewrite `docs/providers/github.md`

**Files:**
- Modify: `docs/providers/github.md`

This task has several sub-edits. Do them in order. Each sub-edit's "verify" step is run at the end (Step 8) as one mkdocs build.

- [ ] **Step 1: Delete the "Composite wrapper pending" callout**

Remove lines 7–11 (the `> **GitHub Actions composite wrapper pending.** …` blockquote). The "## Quick Start" header on line 13 should be the next thing after the lead paragraph (lines 1–5).

After this edit, lines 1–13 should read:

```markdown
# GitHub Actions

Use semvertag in GitHub Actions via a small workflow that installs
`uv` and runs `uvx semvertag tag`. No composite action in your repo,
no maintained workflow YAML beyond the snippet below.

## Quick Start

The minimum useful workflow: auto-tag on every push to the default
branch.
```

Then update the lead paragraph (lines 1–5) to reflect that the action is now the recommended path. Replace lines 1–5 with:

```markdown
# GitHub Actions

Use semvertag in GitHub Actions via the published composite action
(`uses: modern-python/semvertag@v0`). The action installs `uv`, runs
`semvertag tag`, and surfaces the result as step outputs. A pure-CLI
fallback for environments that can't consume the action lives at the
bottom of this page.
```

- [ ] **Step 2: Replace the Quick Start workflow**

The current Quick Start workflow (the 11-step `steps:` block now around lines 21–44 after the prior edits) becomes:

````markdown
> **Required setup.** Either rely on the workflow-scoped
> `GITHUB_TOKEN` (which is auto-issued per job) — in which case the
> workflow MUST declare `permissions: contents: write` — OR provide a
> fine-grained PAT with `contents: write` (single repo) or a classic
> PAT with `repo` / `public_repo` scope. Store the PAT as a repo
> secret named `SEMVERTAG_TOKEN`; the alias chain picks it up ahead
> of `GITHUB_TOKEN`.

```yaml
name: semvertag
on:
  push:
    branches: [main]

permissions:
  contents: write

jobs:
  tag:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: modern-python/semvertag@v0
```
````

The auto-detection / `fetch-depth: 0` / token paragraphs that follow the snippet remain unchanged.

- [ ] **Step 3: Add an "Outputs" section**

Insert this section directly after "## Required permissions" (currently the section ending around line 87) and before "## Token scope":

````markdown
## Outputs

When you give the step an `id:`, downstream steps can read three outputs:

| Output | Value |
|---|---|
| `tag` | The created tag (e.g. `v1.2.3`), or empty string when `status` is `no-bump`. |
| `bump` | `none` \| `patch` \| `minor` \| `major`. |
| `status` | `created` (tag pushed) \| `no-bump` (nothing to tag — no prior tag, already tagged, no merge commit, or non-conforming commit). On CLI error the action itself exits non-zero and this output is not written. |

Example: trigger a downstream release-notes job only when a tag was
created.

```yaml
jobs:
  tag-and-release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - id: semvertag
        uses: modern-python/semvertag@v0
      - if: steps.semvertag.outputs.status == 'created'
        run: |
          echo "tagged ${{ steps.semvertag.outputs.tag }}"
          echo "bump=${{ steps.semvertag.outputs.bump }}"
```
````

- [ ] **Step 4: Update the Strategy section**

Replace the inline `uvx` snippet (currently around line 78 — the one-liner showing `--strategy conventional-commits`) with the action-input form:

```yaml
      - uses: modern-python/semvertag@v0
        with:
          strategy: conventional-commits
```

- [ ] **Step 5: Add an env-var passthrough note**

After the Strategy table (currently around lines 71–75), add this note:

````markdown
> **Strategy-specific env vars** (e.g. `SEMVERTAG_BRANCH_PREFIX__MINOR`)
> remain configured on the calling step. The composite action only
> explicitly sets `GITHUB_TOKEN` and `SEMVERTAG_STRATEGY`; every other
> env var on the calling step passes through to the action's run step.
>
> ```yaml
>       - uses: modern-python/semvertag@v0
>         env:
>           SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'
> ```
````

- [ ] **Step 6: Add a "Without the composite action" section**

Insert a new section immediately above "## Troubleshooting":

````markdown
## Without the composite action

If your environment can't consume the action — GitHub Enterprise
instances without Marketplace access, security-constrained orgs that
forbid third-party actions, or anyone who wants explicit control over
the uv install step — paste the pure-CLI recipe instead:

```yaml
jobs:
  tag:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install --quiet --no-cache-dir 'uv>=0.4,<1'
      - run: uvx 'semvertag>=0.3.1,<1' tag
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

The behavior matches the composite action exactly; only the install
shape differs. Strategy is set via env (`SEMVERTAG_STRATEGY`) or CLI
flag (`--strategy …`). No outputs are produced in this shape — read
the CLI stdout, or invoke `semvertag tag --json` and parse the
envelope yourself.
````

- [ ] **Step 7: Update Troubleshooting's `GITHUB_TOKEN` hint**

The current troubleshooting note (around line 153–155) says:

> For workflow-scoped tokens, this usually means `GITHUB_TOKEN` was not exported into the step's `env:` — add the `env: GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}` line shown in the Quick Start.

Replace that sentence with:

> When using the composite action, `GITHUB_TOKEN` is set automatically
> from the `token` input (which defaults to `${{ github.token }}`).
> When using the pure-CLI recipe in "Without the composite action",
> add `env: GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}` to the run
> step.

- [ ] **Step 8: Verify mkdocs gate**

Run: `uv run mkdocs build --strict` from the repo root.
Expected: build succeeds with no warnings.

Common pitfalls if it fails:
- A fenced code block left unclosed during the multi-step edit. Search for orphan ` ``` ` markers.
- A broken intra-repo link. The only links you should have introduced/touched are `[Branch-prefix strategy](../strategies/branch-prefix.md)` and `[Conventional Commits strategy](../strategies/conventional-commits.md)` — both exist; do not modify them.

- [ ] **Step 9: Commit**

```bash
git add docs/providers/github.md
git commit -m "docs(providers/github): rewrite Quick Start around the composite action"
```

---

### Task 7: Create `planning/releases/0.4.0.md` runbook

**Files:**
- Create: `planning/releases/0.4.0.md`

- [ ] **Step 1: Write the runbook**

Create `planning/releases/0.4.0.md` with this content:

```markdown
# semvertag 0.4.0 — composite GitHub Action

**Minor release shipping the `action.yml` composite wrapper that has been on the deferred list since 0.3.0.** Users can now write `uses: modern-python/semvertag@v0` instead of pasting an 11-line install-and-run block. No CLI changes; the action wraps the existing `semvertag tag --json` invocation and surfaces `tag` / `bump` / `status` as step outputs.

If you're already using the documented pure-CLI snippet and don't want to consume third-party actions, you can stay on it — `docs/providers/github.md` preserves it as the "Without the composite action" recipe.

## What landed

- `action.yml` at repo root — composite action: `astral-sh/setup-uv@v7`, then `uvx 'semvertag>=0.3.1,<1' tag --json`, then parses the envelope into `tag` / `bump` / `status` step outputs.
- `.github/workflows/tag-major.yml` — fires on release published (non-prerelease) and force-updates the floating `v0` major tag so consumers can pin `@v0` and ride minor bumps automatically.
- Dogfood workflow migration — `.github/workflows/semvertag.yml` now consumes `uses: ./`, exercising the action against the working tree on every push to main.
- `action-smoke` CI job — runs `uses: ./` on every PR and asserts that `status` and `bump` outputs are non-empty. Real tag creation against the GitHub API is covered by the post-merge dogfood run, not the PR-time job (forks can't have `contents: write`).
- README + `docs/providers/github.md` rewrite — Quick Start leads with the action; Outputs section documents the three step outputs; "Without the composite action" preserves the pure-CLI fallback for constrained environments.

## CLI version floor

`action.yml` pins `'semvertag>=0.3.1,<1'`. 0.3.1 is the minimum CLI version that ships every feature the action depends on (`--json` envelope, `GITHUB_ACTIONS=true` auto-detection, branch-prefix GitHub merge subject recognition). The floor only needs to bump when a future release breaks CLI contract — not on every minor.

## Release procedure (maintainer)

### Step 1: Pre-flight check

Before tagging:

- Search https://github.com/marketplace?type=actions for "semvertag" — the listing name `semvertag` must not be taken by another action.
  - **If it's taken:** edit `action.yml`'s `name:` field to `'semvertag tag'` (Marketplace permits spaces in display names) and re-PR before continuing. The `uses: modern-python/semvertag@v0` syntax depends on the repo slug, not the display name, so consumer-facing docs do not change.
- Confirm `branding.icon` is one of the Feather icon names GitHub accepts and `branding.color` is one of `white | yellow | blue | green | orange | red | purple | gray-dark`. (We ship `icon: tag`, `color: blue` — both valid.)
- Confirm CI is green on main, including the new `action-smoke` job.

### Step 2: Cut the v0.4.0 release

Follow the project's existing release flow: tag, push, create a GitHub release. `publish.yml` fires on release creation and pushes to PyPI via `just publish` (which uses `uv version $GITHUB_REF_NAME` to inject the version at build time).

### Step 3: Bootstrap the floating `v0` tag (one-time)

The `tag-major.yml` workflow handles the floating tag on every release from v0.4.1 forward. For v0.4.0 specifically — the first release after the workflow landed — the floating tag does not yet exist and must be bootstrapped manually:

```sh
git fetch --tags
git tag -fa v0 v0.4.0 -m 'Update v0 to v0.4.0'
git push -f origin v0
```

After this, `uses: modern-python/semvertag@v0` resolves successfully for consumers.

### Step 4: Publish to Marketplace (manual UI step)

1. Navigate to https://github.com/modern-python/semvertag/releases/tag/v0.4.0.
2. Click **Edit release**.
3. Check **Publish this Action to the GitHub Marketplace**.
4. Accept the Marketplace Terms of Service if prompted (one-time for the repo).
5. Select **Primary Category:** `Continuous integration`.
6. Select **Secondary Category** (optional): `Utilities`.
7. Save the release.

### Step 5: Post-publish smoke test

- Confirm the listing appears at https://github.com/marketplace/actions/semvertag (the slug derives from the `name:` field; if you renamed in Step 1 the slug will differ).
- In a sandbox repo, paste the README snippet (`uses: modern-python/semvertag@v0` after a `actions/checkout@v4` with `fetch-depth: 0`) and confirm the workflow runs end-to-end.

## Breaking changes

None. The action is additive; the pure-CLI recipe still works exactly as before (and remains documented as the fallback).

## See also

- Spec: `planning/specs/2026-06-08-action-yml-composite-wrapper-design.md`
- Implementation plan: `planning/plans/2026-06-08-action-yml-composite-wrapper.md`
```

- [ ] **Step 2: Verify mkdocs still passes**

Run: `uv run mkdocs build --strict` from the repo root.
Expected: build succeeds with no warnings.

(The file lives under `planning/`, which is not in the mkdocs nav, so it shouldn't affect the build — but run the gate to confirm nothing else regressed.)

- [ ] **Step 3: Commit**

```bash
git add planning/releases/0.4.0.md
git commit -m "docs(release): draft 0.4.0 notes (composite action + tag-major workflow)"
```

---

### Task 8: Final verification

**Files:** none modified

- [ ] **Step 1: Run the full lint gate**

Run: `just lint-ci`
Expected: exits 0. No Python source files changed, but this confirms the lint configuration still applies cleanly and we haven't accidentally introduced an EOF / formatting issue in the modified YAML/Markdown files via eof-fixer.

- [ ] **Step 2: Run the test gate (sanity)**

Run: `just test`
Expected: exits 0 with the existing test suite green. No tests were added or removed; this is a regression sanity check.

- [ ] **Step 3: Run the docs gate**

Run: `uv run mkdocs build --strict`
Expected: build succeeds with no warnings.

- [ ] **Step 4: Inspect git log on the branch**

Run: `git log --oneline main..HEAD`
Expected: seven commits, one per Task 1–7, in order:

```
<sha> docs(release): draft 0.4.0 notes (composite action + tag-major workflow)
<sha> docs(providers/github): rewrite Quick Start around the composite action
<sha> docs: README — advertise the composite action as the GHA recipe
<sha> ci: add action-smoke job that exercises the composite action
<sha> ci: dogfood the composite action via uses: ./
<sha> ci: add tag-major workflow to maintain floating v0 tag
<sha> feat: add action.yml composite GitHub Action
```

- [ ] **Step 5: Push the branch and open a PR**

```bash
git push -u origin feat/action-yml-composite-wrapper
gh pr create --title "feat: add action.yml composite wrapper + supporting workflows" --body "$(cat <<'EOF'
## Summary

- Add `action.yml` so users can write `uses: modern-python/semvertag@v0` instead of pasting the 11-line install-and-run block.
- Add `.github/workflows/tag-major.yml` to maintain the floating `v0` major tag on each non-prerelease release.
- Migrate the dogfood workflow to consume `uses: ./` and add a PR-time `action-smoke` CI job.
- Rewrite README + `docs/providers/github.md` around the action; preserve the pure-CLI recipe as the "Without the composite action" fallback.
- Add `planning/releases/0.4.0.md` runbook including the manual Marketplace publication procedure.

## Spec and plan

- Spec: `planning/specs/2026-06-08-action-yml-composite-wrapper-design.md`
- Plan: `planning/plans/2026-06-08-action-yml-composite-wrapper.md`

## Test plan

- [ ] CI green on this PR (lint, pytest matrix, action-smoke).
- [ ] After merge: dogfood workflow on main creates a tag (this PR is on a `feat/` branch, so branch-prefix maps it to a minor bump → v0.4.0).
- [ ] After v0.4.0 release: bootstrap the floating `v0` tag per the runbook.
- [ ] After Marketplace publish: smoke-test `uses: modern-python/semvertag@v0` in a sandbox repo.
EOF
)"
```

Expected: PR opens; the GH Actions run starts. Monitor it.

- [ ] **Step 6: Verify CI passes on the PR**

Wait for CI to complete on the PR. Expected:
- `lint` job: green (same as before this PR).
- `pytest` job (matrix of 4 Python versions): green (same as before this PR).
- `action-smoke` job: green. The new job will:
  - Check out the repo with `fetch-depth: 0`.
  - Run `uses: ./` which executes the action.yml: install uv via `setup-uv@v7`, then `uvx 'semvertag>=0.3.1,<1' tag --json`.
  - The CLI emits a JSON envelope. On a PR commit (not a merge commit), branch-prefix returns `status=no-bump` because no merge subject matches. `tag` is empty; `bump` is `none`; `status` is `no-bump`.
  - The verify step asserts that `status` and `bump` outputs are non-empty. Both are (`"no-bump"` and `"none"`), so the assertion passes.

If `action-smoke` fails:
- **`Required module unavailable: jq`** — jq missing from the runner. Unexpected on `ubuntu-latest`; if this happens, add `sudo apt-get install -y jq` before the `uses: ./` step in `ci.yml` (and document the dependency in `docs/providers/github.md`).
- **`semvertag` resolution error** — verify PyPI has 0.3.1; run `uvx 'semvertag>=0.3.1,<1' --version` locally to reproduce.
- **`Token rejected: 401`** — the action-smoke job declared `permissions: contents: write` but the runner still issued a read-only token. This can happen on PRs from forks; CI from a branch in the same repo is fine. The job's verify step does not require write to succeed (branch-prefix returns no-bump before any write would occur), so the actual API write path is never exercised in PR CI.

- [ ] **Step 7: Hand off to the maintainer for the release**

Once the PR is reviewed and merged, post a comment linking to the runbook (`planning/releases/0.4.0.md`) so the maintainer can follow the manual Marketplace publication procedure. No further plan steps after this — the runbook drives the rest.

---

## Acceptance against the spec

| Spec acceptance criterion | Task that covers it |
|---|---|
| `action.yml` exists at repo root with the shape in §`action.yml` | Task 1 |
| `.github/workflows/tag-major.yml` exists with the shape in §`tag-major.yml` | Task 2 |
| `.github/workflows/semvertag.yml` consumes `uses: ./` | Task 3 |
| `.github/workflows/ci.yml` has an `action-smoke` job that asserts on `status` and `bump` outputs | Task 4 |
| `README.md` advertises `uses: modern-python/semvertag@v0` | Task 5 |
| `docs/providers/github.md` Quick Start uses the action; pending callout gone; Outputs section exists; "Without the composite action" fallback section preserves the inline-CLI recipe | Task 6 |
| `planning/releases/0.4.0.md` exists with the five-step Marketplace publication procedure | Task 7 |
| CI green on a PR that introduces all of the above; the dogfood workflow runs to completion on main after the PR merges | Task 8 (CI green) + post-merge dogfood (out of plan scope, observed in the release runbook) |

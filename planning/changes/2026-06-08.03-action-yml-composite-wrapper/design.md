---
status: shipped
date: 2026-06-08
slug: action-yml-composite-wrapper
summary: "`action.yml` composite GitHub Action wrapping the CLI."
supersedes: null
superseded_by: null
pr: null
outcome: shipped (#10)
---

# action.yml composite wrapper — design spec

**Date:** 2026-06-08
**Status:** Approved, ready for implementation planning
**Topic slug:** `action-yml-composite-wrapper`
**Predecessor:** `2026-05-31-v0-1-0-release-prep-design.md` (deleted the prior stub `action.yml`; this spec reintroduces it now that the GitHub provider has shipped in 0.3.0)

## Goal

Ship a composite `action.yml` at the repo root so GitHub Actions users can replace the current 11-line install-and-run block in `docs/providers/github.md` with two lines:

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- uses: modern-python/semvertag@v0
```

Pair it with a small release-time workflow that maintains a floating `v0` major tag, so consumers can pin to `@v0` and ride minor releases automatically. Migrate the existing dogfood workflow to consume the local action (`uses: ./`) so any breakage surfaces on the repo's own CI before it reaches users.

## Background

`semvertag` ships as a Python CLI plus a GitLab CI Catalog template (`templates/semvertag.yml`). The GitHub Actions story is currently a documented inline snippet: install Python, install uv, run `uvx semvertag tag`. That works but it's verbose (11 lines of `steps:`), couples consumer workflows to implementation details (Python version, uv install method, version pin), and forces every consumer to keep those details in sync as upstream evolves.

A composite `action.yml` existed at v0 (pre-0.1.0) but was deleted during the v0.1.0 release prep because the GitHub provider was a stub at the time. The GitHub provider shipped in 0.3.0 (`f118670`) and was patched in 0.3.1 to recognise GitHub PR merge subjects (`c40a0da`). Both `docs/providers/github.md` (the "Composite wrapper pending" callout) and `planning/releases/0.3.0.md` (the "deferred" entry) explicitly flag this work as the remaining gap.

## Non-goals

- **Marketplace publication** — the spec produces the artifacts that make publication possible and a step-by-step runbook for the manual UI click, but does not perform the publication itself.
- **CLI changes** — `action.yml` is a wrapper. No edits to `semvertag/` source code, `--json` envelope shape, exit codes, or auto-detection logic.
- **GitLab Catalog work** — `templates/semvertag.yml` remains untouched. Catalog publication is blocked on the `modern-python` GitLab namespace not existing and is tracked separately from this spec.
- **`action.yml` inputs beyond `strategy` and `token`** — every other knob (GHE endpoint, repo override, branch-prefix lists) already works by setting `env:` at the workflow or step level. Adding them as first-class inputs would duplicate the env-var contract and create drift risk. Documented in §Decision log.
- **Outputs beyond `tag`, `bump`, `status`** — `commit` and `reason` are present in the `RunResult` JSON envelope but not exposed; they can be added without a breaking change if a real consumer demand emerges.

## Target shape

```
.github/workflows/
├── ci.yml              ← add `action-smoke` job that runs `uses: ./`
├── semvertag.yml       ← dogfood: drop 4 install/run steps, replace with `uses: ./`
└── tag-major.yml       ← NEW: on release published, force-update `v0` floating tag
action.yml              ← NEW: composite — setup-uv → run --json → expose outputs
README.md               ← rewrite "Use it in GitHub Actions" section
docs/providers/github.md ← rewrite Quick Start; add Outputs section; keep inline snippet as fallback
planning/releases/0.4.0.md ← NEW: release runbook including Marketplace publication procedure
```

## `action.yml`

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

### Key choices

- **No `SEMVERTAG_PROVIDER` forced.** Auto-detection from `GITHUB_ACTIONS=true` (shipped in 0.3.0) makes that unnecessary. Forcing it would suppress useful errors when someone runs `act` or otherwise exercises the action outside a real GHA environment.
- **`set -euo pipefail`.** If `uvx` fails, the step fails fast and jq never sees empty/garbage stdin. Avoids ambiguous half-states in `$GITHUB_OUTPUT`.
- **Echo the JSON before parsing.** Humans reading the job log see the full envelope; no second CLI invocation is needed for diagnostics.
- **`jq -r '.tag // ""'`.** Guards the no-bump case (where `tag` is JSON `null`) so the output becomes an empty string — predictable for downstream `if:` gates. `.bump` is always present per `RunResult` schema_version 1.0; no fallback. `.status` is normalized via a bash `case` to a stable consumer-facing enum (`created | no-bump`), encapsulating the CLI's internal status strings (`no_tags`, `already_tagged`, `no_merge_commit`, `no_conforming_commit`, ...) so future CLI additions don't break action consumers.
- **CLI version floor `>=0.3.1,<1`.** Locks to the minimum CLI version that ships every feature the action depends on (`--json` envelope, `GITHUB_ACTIONS=true` auto-detection, branch-prefix GitHub merge subject recognition). The floor only needs to bump when a future release breaks CLI contract — not on every minor. Upper bound `<1` defers the 1.0 question. This also resolves a chicken-and-egg: the floor is satisfiable from PyPI today, so the PR landing this work passes its own `action-smoke` CI on the first run.
- **`astral-sh/setup-uv@v7`.** The official Astral installer; one step, prebuilt binary, automatic cache. Used by every modern uv-in-CI project. `v7` is the highest major astral publishes as a floating tag — specific `v8.x.y` releases exist (v8.0.0–v8.2.0) but no floating `v8` ref has been tagged upstream, so `@v8` resolves to nothing. Trade-off accepted: this adds a third-party action dependency we trust via major-version pin (v7.x.y).
- **`SEMVERTAG_STRATEGY` always exported.** Mirrors the GitLab Catalog template (`templates/semvertag.yml`). Trade-off: a workflow-level `env: SEMVERTAG_STRATEGY: ...` is overridden by the action's step-env. The fix in that rare case is to use the `with: strategy:` input, which is the documented path.
- **Internal step id `run`.** Lets the top-level `outputs:` mapping reference `steps.run.outputs.*`. Users wire their own `id:` on the calling `uses:` block to read the exposed outputs.
- **No checkout inside the action.** Established tag/release actions (mathieudutour/github-tag-action, googleapis/release-please-action, cycjimmy/semantic-release-action) uniformly skip it. Callers have heterogeneous checkout needs (refs, submodules, LFS, sparse, monorepo paths, custom tokens); a composite that silently re-checks out fights those needs.

## `.github/workflows/tag-major.yml`

```yaml
name: tag-major

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
          major="${RELEASE_TAG%%.*}"
          git config user.name  'github-actions[bot]'
          git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
          git tag -fa "$major" "$RELEASE_TAG" -m "Update $major to $RELEASE_TAG"
          git push -f origin "$major"
```

### Key choices

- **`release.types: [published]`.** Fires once per release, not on draft/edit/delete. Avoids spurious `v0` updates while a release is being composed.
- **`!github.event.release.prerelease`.** Protects the floating tag during RC cycles — a `v0.5.0-rc1` should not drag `v0` ahead of the latest stable.
- **`${RELEASE_TAG%%.*}` parameter expansion.** Pure bash; no awk/sed/jq dependency. Extracts `v0` from `v0.4.0`.
- **Force-push the tag.** `-f` is required to move a floating tag. If branch protection rules cover tags (uncommon but possible) the job fails loudly with a clear permissions error — operator can adjust rules and re-run.
- **First-time bootstrap is manual.** When v0.4.0 ships, `v0` does not yet exist (this workflow only runs on subsequent releases). The v0.4.0 release runbook includes the one-time `git tag -fa v0 v0.4.0 && git push -f origin v0` step. From v0.4.1 onward the workflow handles it.

## Dogfood workflow migration

`.github/workflows/semvertag.yml` collapses to:

```yaml
name: semvertag

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

### Key choices

- **`uses: ./`.** Exercises the action.yml in the current checkout. Any PR that breaks `action.yml` fails its own dogfood-shaped sanity check on the next push to main.
- **`SEMVERTAG_BRANCH_PREFIX__MINOR` stays at step level.** The action's step-env only sets `GITHUB_TOKEN` and `SEMVERTAG_STRATEGY`; other env vars on the calling step pass through to the composite's run step.
- **Drop explicit `GITHUB_TOKEN`.** The action's `token` input defaults to `${{ github.token }}`; `permissions: contents: write` is what makes that writable.
- **No `with: strategy:`.** `branch-prefix` is the input default.

## CI smoke test

Add a third job to `.github/workflows/ci.yml`:

```yaml
action-smoke:
  runs-on: ubuntu-latest
  permissions:
    contents: write
  steps:
    - uses: actions/checkout@v4
      with: { fetch-depth: 0 }
    - id: semvertag
      uses: ./
      env:
        SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'
    - name: Verify outputs were emitted
      run: |
        test -n "${{ steps.semvertag.outputs.status }}"
        test -n "${{ steps.semvertag.outputs.bump }}"
```

### What it covers

| Check | Layer |
|---|---|
| YAML parses, inputs/outputs declared correctly | `astral-sh/setup-uv@v7` + GHA composite loader (failure shows up as a runtime parse error) |
| `astral-sh/setup-uv@v7` resolves and installs | Step 1 of the composite |
| `uvx 'semvertag>=0.3.1,<1' tag --json` runs to completion | Step 2 (failure → `set -euo pipefail` exits non-zero) |
| JSON parsing emits non-empty `status`/`bump` | The verify step |

### What it does NOT cover

- **Real tag creation against the GitHub API.** A PR-time job from a fork cannot have `contents: write` without footguns. Branch-prefix on a PR commit returns `status=no-bump` (no merge-commit shape on a feature branch), so the job lands in the no-tag-created path and the verify step still confirms output emission.
- **GitHub Enterprise endpoint resolution.** Out of scope; users configure `SEMVERTAG_GITHUB__ENDPOINT` themselves and the action passes it through.
- **End-to-end real-API tag push.** Covered by the dogfood workflow on `main` after merge.

## Docs rewrite

### `README.md`

Replace the "Use it in GitHub Actions" block (lines 42–69) with:

````markdown
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
````

### `docs/providers/github.md`

1. **Delete the "Composite wrapper pending" callout** (lines 7–11).
2. **Replace the Quick Start workflow** (lines 27–50) with the action-based one above.
3. **Add an "Outputs" section** after "Required permissions":

   ````markdown
   ## Outputs

   When you set `id: semvertag` on the step, downstream steps can read:

   | Output | Value |
   |---|---|
   | `tag` | The created tag (e.g. `v1.2.3`), or empty string on `no-bump`. |
   | `bump` | `none` \| `patch` \| `minor` \| `major`. |
   | `status` | `created` \| `no-bump` \| `error`. |

   ```yaml
   jobs:
     tag-and-release:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
           with: { fetch-depth: 0 }
         - id: semvertag
           uses: modern-python/semvertag@v0
         - if: steps.semvertag.outputs.status == 'created'
           run: echo "tagged ${{ steps.semvertag.outputs.tag }}"
   ```
   ````

4. **Swap the Strategy section's inline `uvx ...` snippet** for the action-input form:

   ```yaml
   - uses: modern-python/semvertag@v0
     with:
       strategy: conventional-commits
   ```

5. **Show strategy-specific env vars** as `env:` siblings of the `uses:` step:

   ```yaml
   - uses: modern-python/semvertag@v0
     env:
       SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'
   ```

   With a note: the action only explicitly sets `GITHUB_TOKEN` and `SEMVERTAG_STRATEGY`; every other env var on the calling step passes through to the composite's run step.

6. **Add a "Without the composite action" section** above Troubleshooting, preserving the existing 11-line install-and-run snippet for users on private GHE instances without Marketplace access, security-constrained orgs that forbid third-party actions, or anyone who wants explicit control over the uv install step.

## Release runbook (`planning/releases/0.4.0.md`)

New file capturing both the release process and the Marketplace publication procedure as a manual step the maintainer follows.

Structure:

1. **Pre-flight check.**
   - `name: 'semvertag'` not already taken on Marketplace (search at https://github.com/marketplace?type=actions before publishing).
   - `branding.icon` is a valid Feather icon name; `branding.color` is one of `white | yellow | blue | green | orange | red | purple | gray-dark`.
   - `action.yml` parses (`actionlint ./action.yml` if available locally).
   - CI green on the PR introducing the action.
2. **Cut the v0.4.0 release.**
   - Tag and push `v0.4.0` per the project's existing release flow (PyPI publishing via `publish.yml` fires on GitHub release creation).
3. **Bootstrap the floating `v0` tag (one-time).**
   ```sh
   git fetch --tags
   git tag -fa v0 v0.4.0 -m 'Update v0 to v0.4.0'
   git push -f origin v0
   ```
   Subsequent releases are handled automatically by `tag-major.yml`.
4. **Publish to Marketplace (manual UI step).**
   - Navigate to https://github.com/modern-python/semvertag/releases/tag/v0.4.0.
   - Click "Edit release".
   - Check "Publish this Action to the GitHub Marketplace".
   - Accept the Marketplace Terms of Service if prompted.
   - Select **Primary Category**: `Continuous integration`.
   - Select **Secondary Category** (optional): `Utilities`.
   - Save the release.
5. **Post-publish smoke test.**
   - Confirm listing appears at https://github.com/marketplace/actions/semvertag.
   - In a sandbox repo, paste the README's snippet (`uses: modern-python/semvertag@v0`) and confirm the workflow runs end-to-end.

## Decision log

| Decision | Choice | Why not the alternative |
|---|---|---|
| Checkout in the action? | No | Every published tag/release action skips it; callers have heterogeneous checkout needs (refs, submodules, LFS, sparse, monorepo paths). |
| uv installer? | `astral-sh/setup-uv@v7` | Faster than `pip install uv` (prebuilt binary, automatic cache). The third-party-action dependency is the ecosystem norm. `v7` is the highest major astral publishes as a floating tag today; `@v8` resolves to nothing. |
| Inputs? | `strategy` + `token` only | Every other knob (GHE endpoint, repo override, branch-prefix lists) already works via `env:`. Duplicating the env-var contract as inputs creates drift risk. |
| Outputs? | `tag`, `bump`, `status` | CLI already emits `--json`; cost is ~10 YAML lines. Matches release-please / github-tag-action convention. `commit` and `reason` deferred; can be added non-breaking. |
| Always export `SEMVERTAG_STRATEGY`? | Yes | Matches the GitLab Catalog template. Trade-off: workflow-level env `SEMVERTAG_STRATEGY` is overridden — use the `with: strategy:` input instead. |
| Floating major tag? | Yes, automated workflow | Lets users pin `@v0` and ride minor releases. Manual-per-release is easy to forget; deferring forces every user to bump pins on every minor. |
| Marketplace publication? | Manual UI step in the runbook | Maintainer-only action; not automatable from a workflow. Pre-flight + post-publish checks documented in the runbook. |

## Risks

- **`astral-sh/setup-uv@v7` major bump.** When astral publishes a floating `v8` (or later) tag, that becomes a candidate upgrade. Re-evaluate the pin on each minor semvertag release; bump only if the new major brings features we want and has stable floating-tag support.
- **`name: 'semvertag'` Marketplace collision.** If the name is taken when we publish, the listing fails to create. Mitigation: pre-flight check in the runbook. If the name is taken, change `name:` in `action.yml` to `'semvertag tag'` (Marketplace permits spaces in display names) before re-attempting publication; the listing slug and the `uses: modern-python/semvertag@v0` syntax are unaffected. Low likelihood — "semvertag" is distinctive.
- **`jq` not on self-hosted runners.** Default on every GitHub-hosted runner; self-hosted runners may strip it. Mitigation: document the assumption in `docs/providers/github.md` as a known requirement.
- **`SEMVERTAG_STRATEGY` step-env override surprise.** Users setting it at workflow level may be confused when the action's input default `branch-prefix` wins. Mitigation: documented in the new "Strategy-specific env vars" docs section; the `with: strategy:` input is presented as the canonical knob.
- **First-time `v0` bootstrap forgotten.** If the maintainer skips the bootstrap step in the v0.4.0 runbook, `uses: …@v0` fails for early adopters until the next release fires `tag-major.yml`. Mitigation: bold callout in the runbook.

## Acceptance

- `action.yml` exists at repo root with the shape in §`action.yml`.
- `.github/workflows/tag-major.yml` exists with the shape in §`tag-major.yml`.
- `.github/workflows/semvertag.yml` consumes `uses: ./`.
- `.github/workflows/ci.yml` has an `action-smoke` job that asserts on `status` and `bump` outputs.
- `README.md` advertises `uses: modern-python/semvertag@v0`.
- `docs/providers/github.md` Quick Start uses the action; the "Composite wrapper pending" callout is gone; Outputs section exists; "Without the composite action" fallback section preserves the inline-CLI recipe.
- `planning/releases/0.4.0.md` exists with the five-step Marketplace publication procedure.
- CI green on a PR that introduces all of the above; the dogfood workflow runs to completion on main after the PR merges.

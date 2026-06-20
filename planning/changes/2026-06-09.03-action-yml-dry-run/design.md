---
status: shipped
date: 2026-06-09
slug: action-yml-dry-run
summary: "Composite action `dry-run` input wired to the CLI flag."
supersedes: null
superseded_by: null
pr: null
outcome: shipped (#16)
---

# action.yml `dry-run` input + side-effect-free action-smoke — design

**Status:** approved
**Date:** 2026-06-09
**Depends on:** semvertag `0.5.0` (now on PyPI; ships `tag --dry-run`).
**Predecessor spec:** `planning/specs/2026-06-09-dry-run-flag-design.md` (PR A — landed in PR #15)

## Goal

Expose `--dry-run` through the composite action and switch `ci.yml`'s `action-smoke` job to use it. Eliminates the structural side-effect smell that lets any PR's smoke run mint a real release tag on the remote.

## Why

PR #14 surfaced the smell: `action-smoke` ran with `permissions: contents: write`, calling the composite action against main HEAD via the GitHub API. When main HEAD wasn't already tagged and was a `feat/`/`bugfix/` merge, semvertag dutifully bumped, pushed `0.4.1` (and later `0.5.0`), and the assertion `status == no-bump` failed because `status` was `created`. The current PR-only gate avoids most of the blast radius but doesn't fix the underlying problem: a smoke test that mutates production.

PR A landed `semvertag tag --dry-run` and the `dry_run` status (`0.5.0` now on PyPI). This PR wires the flag through the composite action and updates the smoke job to use it. After this PR, `action-smoke`:
- cannot push a tag (composite passes `--dry-run` → semvertag short-circuits before `provider.create_tag`),
- doesn't need `contents: write` (so even a future regression that bypassed dry-run couldn't push — GitHub would 403),
- asserts the dry-run wiring is intact (`status == no-bump` is guaranteed under dry-run, so any deviation indicates a wiring break).

## Scope

In scope:
1. `action.yml`: add a `dry-run` boolean input (default `'false'`); shell-conditionally pass `--dry-run` to the CLI invocation; update the comment block to list `dry_run` as a known internal status; bump version floor from `>=0.3.1,<1` to `>=0.5.0,<1`.
2. `ci.yml`'s `action-smoke` job: drop `permissions: contents: write`; pass `with: { dry-run: 'true' }`; replace the two-line assertion with a single `status == no-bump` check; update the comment block to reflect the dry-run mechanism.
3. `docs/providers/github.md`: add a "Preview the next bump" subsection covering both the action input and the equivalent local `uvx semvertag tag --dry-run`.
4. `README.md` + `pyproject.toml`: fix the docs URL from `readthedocs.io` to `modern-python.org` (a leftover from PR #14's subdomain switch, currently uncommitted in the working tree).

Out of scope:
- No change to `.github/workflows/semvertag.yml` (dogfood) — it MUST push real tags on push-to-main; that's its purpose.
- No change to `publish.yml` or `tag-major.yml` (release-triggered, unrelated).
- No new Python tests — the CLI behavior was tested in PR A. This PR is YAML + Markdown only.
- No refactor of `action-smoke` to use a fixture repo — dry-run removes the need.

## Design

### 1. `action.yml`: new `dry-run` input

Insert after the existing `token` input (around line 17):

```yaml
inputs:
  ...
  token:
    description: 'GitHub token with contents: write. Defaults to the workflow-issued github.token.'
    required: false
    default: ${{ github.token }}
  dry-run:
    description: 'If true, compute the bump and emit the planned tag/bump but do not push a tag.'
    required: false
    default: 'false'
```

Notes:
- Default is the literal string `'false'` — GitHub Actions input values are always strings; the workflow `with: { dry-run: true }` is also stringified before the action sees it.
- `description` is concise but complete; ties to the `dry_run` status in the CLI.

### 2. `action.yml`: pass `--dry-run` to the CLI

Modify the `Run semvertag` step's run script. Current (after PR A is in place via 0.5.0):

```yaml
run: |
  set -euo pipefail
  result=$(uvx 'semvertag>=0.3.1,<1' tag --json)
  ...
```

New:

```yaml
run: |
  set -euo pipefail
  dry_run_flag=''
  if [ "${{ inputs.dry-run }}" = "true" ]; then dry_run_flag='--dry-run'; fi
  result=$(uvx 'semvertag>=0.5.0,<1' tag --json $dry_run_flag)
  printf '%s\n' "$result"
  # Normalize the CLI's internal status (`no_tags`, `already_tagged`,
  # `no_merge_commit`, `no_conforming_commit`, `dry_run`, ...) to a stable
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

Three concrete changes:
1. **`dry_run_flag` shell variable** holds either `''` or `'--dry-run'`; deliberately unquoted in the `uvx` invocation so the empty value expands to nothing rather than passing a literal `''` argument. Safe because the only possible values are the empty string or the literal flag — no user-controlled content reaches that position.
2. **Version floor bump** from `>=0.3.1,<1` to `>=0.5.0,<1`. The `<1` upper bound stays in place — we don't want consumers auto-upgrading across a future 1.x breaking change.
3. **Comment block** lists `dry_run` as a known internal status.

The `case` block itself is unchanged: `dry_run` already fell into the `*) status='no-bump'` wildcard arm before this PR (PR A confirmed this). The comment is updated to make that explicit.

### 3. `ci.yml`: side-effect-free action-smoke

Current job (lines 47-74):

```yaml
action-smoke:
  if: github.event_name == 'pull_request'
  runs-on: ubuntu-latest
  permissions:
    contents: write
  steps:
    - uses: actions/checkout@v6
      with:
        fetch-depth: 0
    - id: semvertag
      uses: ./
      env:
        SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'
    - name: Verify outputs match the no-bump contract
      run: |
        test "${{ steps.semvertag.outputs.status }}" = "no-bump"
        test "${{ steps.semvertag.outputs.bump }}"   = "none"
```

New:

```yaml
action-smoke:
  # PR-only: action-smoke has no value on push-to-main where the dogfood
  # workflow (`.github/workflows/semvertag.yml`) exercises the real
  # composite action against the merge commit. Under `dry-run: true`,
  # this job is side-effect-free regardless of main's tag state.
  if: github.event_name == 'pull_request'
  runs-on: ubuntu-latest
  # No `permissions:` block: `contents: read` is sufficient because
  # dry-run guarantees no tag-push attempt. Even a future regression
  # that bypassed dry-run would be denied by the API.
  steps:
    - uses: actions/checkout@v6
      with:
        fetch-depth: 0
    - id: semvertag
      uses: ./
      with:
        dry-run: 'true'
      env:
        SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'
    - name: Verify the composite normalized dry-run to no-bump
      # Under `dry-run: true`, the CLI's status is one of `dry_run`,
      # `no_tags`, `already_tagged`, `no_merge_commit`, `no_conforming_commit` —
      # all normalized to `no-bump` by action.yml. If action.yml's
      # dry-run wiring regresses, the CLI would push a tag, status would
      # be `created`, and this assertion would fail loudly. `bump` is
      # intentionally NOT asserted: under dry-run it reflects the would-be
      # value (`patch`/`minor`/`major` for an untagged merge, `none`
      # otherwise) — not a stable smoke value.
      run: |
        test "${{ steps.semvertag.outputs.status }}" = "no-bump"
```

Four concrete changes:
1. **`permissions: contents: write` removed.** The job inherits `contents: read` from the workflow default.
2. **`with: { dry-run: 'true' }` added** to the `uses: ./` step.
3. **Assertion reduced to one line** (`status == no-bump`). The old `bump == none` check is dropped — under dry-run, `bump` reflects the would-be value, so this check would fail on every PR where main HEAD is an untagged `feat/`/`bugfix/` merge.
4. **Comment blocks rewritten** to explain the dry-run mechanism instead of the stale "PR-only because main HEAD might not be tagged" rationale.

### 4. `docs/providers/github.md`: document dry-run

Add a new `## Preview the next bump` section. Insertion point: between `## Outputs` (line 91) and `## Token scope: GITHUB_TOKEN vs Personal Access Tokens` (line 127). The new section is h2, matching the surrounding section levels. Suggested content:

```markdown
## Preview the next bump

Pass `dry-run: true` to compute the bump without pushing a tag — useful in
CI smoke tests, in PR previews, or to see what the next release would be:

​```yaml
- uses: modern-python/semvertag@v0
  with:
    dry-run: true
​```

When `dry-run: true`, the action's `status` output is `no-bump` (no real
tag was pushed) and `bump` / `tag` reflect what *would* have happened.

You can also run this locally without the action:

​```bash
uvx 'semvertag>=0.5.0' tag --dry-run --json
​```

Output (example):

​```json
{"schema_version":"1.0","strategy":"branch-prefix","bump":"minor","status":"dry_run","tag":"0.6.0","commit":"abc1234..."}
​```
```

The exact placement (file path, subsection level) follows whatever the current `docs/providers/github.md` structure dictates. The implementer should match the file's existing heading levels and code-fence conventions.

### 5. `README.md` + `pyproject.toml`: docs URL fix

The local working tree already contains these edits (uncommitted):

```diff
README.md:78
- ...See [docs](https://semvertag.readthedocs.io) for the full configuration surface.
+ ...See [docs](https://semvertag.modern-python.org) for the full configuration surface.

pyproject.toml:30
- docs = "https://semvertag.readthedocs.io"
+ docs = "https://semvertag.modern-python.org"
```

Bundle these into PR B as the first commit on the branch: `docs: update URL to new subdomain in README and pyproject`. Closes the docs-subdomain rollout loop started in PR #14.

### 6. Branch + commit shape

Branch: `feat/action-yml-dry-run` (already created from `main`).

Commit sequence (6 commits, all small):

1. `docs: update URL to new subdomain in README and pyproject`
2. `docs: add design spec for action.yml dry-run`
3. `docs: add implementation plan for action.yml dry-run`
4. `feat(action): add dry-run input and bump version floor to >=0.5.0`
5. `ci(action-smoke): use dry-run and drop contents: write`
6. `docs(providers/github): document dry-run usage`

All `feat/`-prefixed work, so dogfood will produce `0.6.0` on merge.

## Risks

- **Quoting of `dry_run_flag`** in the `uvx` invocation is unquoted by design (so empty value collapses cleanly). Safe given the only two possible values (`''` and the literal `'--dry-run'`), but reviewers may flag it as a shellcheck-style anti-pattern. The alternative (quoted) would pass a literal empty argument to uvx in the default case, which fails. The shell pattern in use is the standard "POSIX-portable optional flag injection" idiom.
- **`status == no-bump` is tautologically true under dry-run** by construction (every CLI status path normalizes to `no-bump`). The value is in detecting wiring regressions: if action.yml stops passing `--dry-run`, the CLI's `status` becomes `created` and the assertion fails loudly. Reviewers may suggest "stronger" assertions (asserting on `bump`, asserting on the JSON envelope) — those add brittleness without catching anything `status == no-bump` doesn't already catch, given the contract.
- **`contents: write` removal could surprise a future maintainer** who restores it without realizing dry-run obviates the need. The comment block in `ci.yml` explicitly explains why no permissions block exists; that documentation is the mitigation.
- **`>=0.5.0,<1` floor change forks behavior** for any consumer pinning to an older action ref that uses `>=0.3.1`. None today (this repo's `v0` is the only consumer pattern), but worth noting.

## Testing

Manual (the PR's own CI run is the test):
- The action-smoke job in this PR's CI must pass on the first try. If it doesn't, the dry-run wiring is broken.
- `lint` and `pytest` matrix should continue to pass — they're unaffected by YAML/Markdown changes.

No new automated tests; the CLI behavior was covered in PR A.

## Follow-ups (NOT in this PR)

- Update `docs/index.md` quick-start section to mention `--dry-run` (low-priority).
- Consider migrating action-smoke entirely to use a fixture repo so it doesn't depend on the GitHub API at all. Probably overkill once dry-run is in place; revisit only if dry-run-based smoke proves flaky.

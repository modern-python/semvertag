# action.yml `dry-run` + side-effect-free action-smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose `--dry-run` through the composite action, switch the `action-smoke` job to use it, and drop `contents: write` from that job so it cannot mint real tags even under regression.

**Architecture:** Pure YAML + Markdown + small git plumbing. No Python source changes — the CLI side landed in PR #15 (semvertag 0.5.0, now on PyPI). action.yml gains a `dry-run` boolean input that shell-conditionally appends `--dry-run` to the `uvx semvertag tag --json` call. The composite's existing status-normalization case block already routes `dry_run` to the public `no-bump` value (PR A confirmed this is the default-arm behavior). action-smoke passes `dry-run: 'true'`, drops `permissions: contents: write`, and reduces its assertion to `status == no-bump` — the strongest signal that the dry-run wiring is intact (under dry-run, `created` is structurally unreachable; a `created` would prove a regression).

**Tech Stack:** GitHub Actions composite (`action.yml`), `bash`, `uvx`, `jq`, MkDocs (for the docs build check), `just`.

**Spec:** `planning/specs/2026-06-09-action-yml-dry-run-design.md`

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `README.md` | Modify | Fix one docs URL (`readthedocs.io` → `modern-python.org`) — already edited in working tree |
| `pyproject.toml` | Modify | Fix the same URL in the project's `urls.docs` field — already edited in working tree |
| `action.yml` | Modify | Add `dry-run` input; conditionally append `--dry-run` to the CLI call; bump version floor to `>=0.5.0,<1`; mention `dry_run` in the status-normalization comment |
| `.github/workflows/ci.yml` | Modify | `action-smoke` job: drop `permissions: contents: write`; pass `with: { dry-run: 'true' }`; reduce assertion to one line; rewrite comment blocks |
| `docs/providers/github.md` | Modify | Insert a `## Preview the next bump` h2 section between line 91 (`## Outputs`) and line 127 (`## Token scope: ...`) |

## Branch

Already on `feat/action-yml-dry-run` (branched from updated `main` after PR #14 + PR #15 landed). The spec commit (`72e3830`) is currently HEAD; the URL fixes are uncommitted in the working tree. The plan you're reading is about to land as the second commit.

After this plan commit, the remaining task commits are:
1. (next) URL fix from working tree
2. action.yml: dry-run input + version floor
3. ci.yml: action-smoke uses dry-run + drops contents: write
4. docs/providers/github.md: Preview the next bump section
5. Verification + PR

---

### Task 1: Commit the working-tree URL fixes

**Files:**
- Modify: `README.md` (already edited; line 78)
- Modify: `pyproject.toml` (already edited; line 30)

- [ ] **Step 1: Confirm the working-tree changes are still present**

```bash
git status --short README.md pyproject.toml
```

Expected:

```
 M README.md
 M pyproject.toml
```

If either file is missing from the output, the local changes were stashed or lost. Stop and ask the user to restore them.

- [ ] **Step 2: Re-verify the diff matches the spec**

```bash
git diff README.md pyproject.toml
```

Expected: the only changes are `readthedocs.io` → `modern-python.org` in one line of each file. Specifically:

```
README.md:
- Both are configurable via env vars. See [docs](https://semvertag.readthedocs.io)
+ Both are configurable via env vars. See [docs](https://semvertag.modern-python.org)

pyproject.toml:
- docs = "https://semvertag.readthedocs.io"
+ docs = "https://semvertag.modern-python.org"
```

If the diff contains anything else, STOP — the working tree has unrelated changes that should not land in this commit.

- [ ] **Step 3: Run lint to confirm the edits don't break anything**

```bash
just lint-ci
```

Expected: passes. README/pyproject changes are pure URL text — lint should be untouched.

- [ ] **Step 4: Commit**

```bash
git add README.md pyproject.toml
git commit -m "docs: update URL to new subdomain in README and pyproject"
```

---

### Task 2: action.yml — dry-run input, conditional CLI flag, version floor bump

**Files:**
- Modify: `action.yml` (currently 56 lines)

- [ ] **Step 1: Add the `dry-run` input**

Open `action.yml`. Find the existing `inputs:` block (lines 9-17). Append a new `dry-run` input after `token` so the block reads:

```yaml
inputs:
  strategy:
    description: 'Bump strategy: branch-prefix (default) or conventional-commits.'
    required: false
    default: 'branch-prefix'
  token:
    description: 'GitHub token with contents: write. Defaults to the workflow-issued github.token.'
    required: false
    default: ${{ github.token }}
  dry-run:
    description: 'If true, compute the bump and emit the planned tag/bump but do not push a tag.'
    required: false
    default: 'false'
```

The default `'false'` is a quoted string — GitHub Actions input values are always strings, and the explicit quoting makes that obvious.

- [ ] **Step 2: Rewrite the `Run semvertag` step's run script**

Find the `run: |` block (lines 41-55). Replace it with this version (adds the `dry_run_flag` shell variable, bumps the version floor, updates the normalization comment):

```yaml
    - name: Run semvertag
      id: run
      shell: bash
      env:
        GITHUB_TOKEN: ${{ inputs.token }}
        SEMVERTAG_STRATEGY: ${{ inputs.strategy }}
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

Three concrete changes from the previous version:
- New `dry_run_flag=''` line + the conditional `if` line that sets it to `'--dry-run'` when the input is true.
- `$dry_run_flag` injected (deliberately unquoted) into the `uvx` invocation — empty value expands to nothing, non-empty expands to the literal `--dry-run`.
- Version constraint changed from `>=0.3.1,<1` to `>=0.5.0,<1`.
- Comment block now lists `dry_run` among the known internal statuses.

- [ ] **Step 3: Validate the YAML parses**

```bash
python3 -c "import yaml; yaml.safe_load(open('action.yml'))"
```

Expected: no output, exit code 0.

If parse fails, the most likely culprit is indentation around the new `dry-run` input or inside the `run: |` block. action.yml uses 2-space YAML indent (not tabs).

- [ ] **Step 4: Diff sanity check**

```bash
git diff action.yml
```

Expected diff stat: ~13 added, ~2 removed (one new input block, one new shell-variable assignment + conditional, the version constraint change, the comment update).

No changes to: the `name`, `description`, `branding`, `outputs`, the `setup-uv` step, the `jq` invocations, the `GITHUB_OUTPUT` writes.

- [ ] **Step 5: Commit**

```bash
git add action.yml
git commit -m "feat(action): add dry-run input and bump version floor to >=0.5.0"
```

---

### Task 3: ci.yml action-smoke — use dry-run, drop contents: write

**Files:**
- Modify: `.github/workflows/ci.yml` (`action-smoke` job, lines 47-74)

- [ ] **Step 1: Replace the action-smoke job**

Open `.github/workflows/ci.yml`. Replace the existing `action-smoke` job (lines 47-74) with this version:

```yaml
  action-smoke:
    # PR-only: action-smoke has no value on push-to-main, where the dogfood
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

Four concrete changes from the previous version:
1. The `permissions: contents: write` block (old lines 55-56) is GONE.
2. The `uses: ./` step now has `with: { dry-run: 'true' }`.
3. The assertion shrinks from 2 lines (`status` + `bump` checks) to 1 line (`status` only).
4. Comment blocks rewritten — the old "PR-only because main HEAD might not be tagged" rationale is replaced with the new "PR-only because action-smoke has no value on push-to-main" rationale, and a new comment explains why no `permissions:` block exists.

- [ ] **Step 2: Validate YAML parses**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Expected: no output, exit code 0.

- [ ] **Step 3: Diff sanity check**

```bash
git diff .github/workflows/ci.yml
```

Expected: only the `action-smoke` job changed. The `lint` and `pytest` jobs above must remain identical.

Spot-check `git diff --stat .github/workflows/ci.yml`: somewhere around 18-20 lines added, 14-15 removed (the block was 28 lines, the new block is ~30 lines, plus comment changes).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(action-smoke): use dry-run and drop contents: write"
```

---

### Task 4: docs/providers/github.md — Preview the next bump

**Files:**
- Modify: `docs/providers/github.md` (insertion between line 91 `## Outputs` section's end and line 127 `## Token scope: ...`)

- [ ] **Step 1: Find the exact insertion point**

```bash
grep -n "^## Token scope" docs/providers/github.md
```

Expected: a single line like `127:## Token scope: \`GITHUB_TOKEN\` vs Personal Access Tokens`.

That line is the anchor. The new section goes immediately ABOVE it, separated by a blank line.

- [ ] **Step 2: Insert the new section**

Open `docs/providers/github.md`. Before the `## Token scope:` heading (line 127), insert this block (note: the new section is its own h2; preserve a blank line before and after it):

```markdown
## Preview the next bump

Pass `dry-run: true` to compute the bump without pushing a tag — useful in
CI smoke tests, in PR previews, or to see what the next release would be:

​```yaml
- uses: modern-python/semvertag@v0
  with:
    dry-run: true
​```

When `dry-run: true`, the action's `status` output is `no-bump` (no real tag
was pushed) and `bump` / `tag` reflect what *would* have happened.

You can also run this locally without the action:

​```bash
uvx 'semvertag>=0.5.0' tag --dry-run --json
​```

Output (example):

​```json
{"schema_version":"1.0","strategy":"branch-prefix","bump":"minor","status":"dry_run","tag":"0.6.0","commit":"abc1234..."}
​```

```

Important: in the actual file, the code-fence markers are three backticks each (` ``` `). The leading zero-width-marker (​) above is only present in this plan to keep the markdown nested correctly — the file should have plain triple-backticks.

- [ ] **Step 3: Verify the docs still build**

```bash
uvx --with-requirements docs/requirements.txt mkdocs build --strict 2>&1 | tail -5
```

Expected: ends with `INFO    -  Documentation built in <N>.<NN> seconds`. No WARNING or ERROR lines from the strict check.

If `--strict` flags a link or anchor issue from the new section, fix it. Common culprits: orphaned heading anchor, missing blank line around a fenced block.

Clean up afterwards:

```bash
rm -rf site/
```

- [ ] **Step 4: Diff sanity check**

```bash
git diff docs/providers/github.md | head -50
```

Expected: pure addition of the new `## Preview the next bump` section. No other lines changed.

```bash
git diff --stat docs/providers/github.md
```

Expected: around 20-25 lines added, 0 removed.

- [ ] **Step 5: Commit**

```bash
git add docs/providers/github.md
git commit -m "docs(providers/github): document dry-run usage"
```

---

### Task 5: Final verification + PR

- [ ] **Step 1: Skim the branch diff**

```bash
git log origin/main..HEAD --oneline
```

Expected: 6 commits, in this order (newest first):

```
<sha> docs(providers/github): document dry-run usage
<sha> ci(action-smoke): use dry-run and drop contents: write
<sha> feat(action): add dry-run input and bump version floor to >=0.5.0
<sha> docs: update URL to new subdomain in README and pyproject
<sha> docs: add implementation plan for action.yml dry-run
<sha> docs: add design spec for action.yml dry-run
```

```bash
git diff origin/main..HEAD --stat
```

Expected files: `README.md`, `pyproject.toml`, `action.yml`, `.github/workflows/ci.yml`, `docs/providers/github.md`, `planning/specs/2026-06-09-action-yml-dry-run-design.md`, `planning/plans/2026-06-09-action-yml-dry-run.md`.

- [ ] **Step 2: Run lint + tests**

```bash
just lint-ci
```

Expected: passes.

```bash
just test
```

Expected: 428 tests pass, 100% branch coverage. (No Python source changes in this PR, so the suite should be unaffected.)

- [ ] **Step 3: Run mkdocs build one more time**

```bash
uvx --with-requirements docs/requirements.txt mkdocs build --strict 2>&1 | tail -5
rm -rf site/
```

Expected: `Documentation built in ...`.

- [ ] **Step 4: Push the branch**

```bash
git push -u origin feat/action-yml-dry-run
```

- [ ] **Step 5: Open the PR**

```bash
cat > /tmp/pr-b-body.md <<'EOF'
## Summary

- Adds `dry-run` boolean input to `action.yml` (default `'false'`). When true, the composite passes `--dry-run` to `semvertag tag`; semvertag skips `provider.create_tag` and emits `status="dry_run"`, which the existing case block normalizes to public `status="no-bump"`.
- Switches `ci.yml`'s `action-smoke` job to use `dry-run: 'true'` and drops `permissions: contents: write`. The job can no longer push real tags even under regression — GitHub would 403 first.
- Reduces the action-smoke assertion to a single line: `status == no-bump`. Under dry-run this is guaranteed true; if action.yml's dry-run wiring breaks, status becomes `created` and the assertion fails loudly.
- Bumps semvertag version floor in `action.yml` from `>=0.3.1,<1` to `>=0.5.0,<1` (the release that ships `--dry-run`).
- Documents the new input under a `## Preview the next bump` section in `docs/providers/github.md`.
- Drive-by: README + pyproject docs URL fix to the new `modern-python.org` subdomain (a leftover from PR #14).

Spec: `planning/specs/2026-06-09-action-yml-dry-run-design.md`. Predecessor: PR #15 (semvertag CLI `--dry-run` flag; shipped as `0.5.0`).

## Motivation

PR #14 surfaced the underlying smell: `action-smoke` ran with `contents: write` against main HEAD via the GitHub API, so whenever main HEAD was an untagged `feat/`/`bugfix/` merge, the smoke test minted and pushed a real release tag from a PR's CI run. PR A landed the CLI half (`semvertag tag --dry-run`); this PR wires it through the composite action and switches `action-smoke` to use it. After merge, `action-smoke` is structurally side-effect-free.

## Test plan

- [x] `just lint-ci` passes
- [x] `just test` passes (428 tests, 100% coverage — no Python source changed)
- [x] `mkdocs build --strict` passes
- [x] PR's own `action-smoke` job passes — confirms end-to-end wiring of the new `dry-run` input
- [x] After merge: confirm `action-smoke` on the NEXT PR (whatever it is) still passes — verifies the contract holds across consecutive PRs

## Post-merge follow-ups (NOT in this PR)

- Cut `0.6.0` (this is a `feat/` merge under the convention → minor bump). PR B's CLI behavior is unchanged from 0.5.0, but the action.yml's contract grew, so a minor bump is the right communication. Optional — could wait until the next user-visible CLI change.
- Consider mentioning `--dry-run` in `docs/index.md`'s quick-start. Low priority.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
gh pr create --title "feat(action): add dry-run input + make action-smoke side-effect-free" --body-file /tmp/pr-b-body.md
```

Expected: a GitHub PR URL is printed. Report it verbatim — do NOT fabricate.

- [ ] **Step 6: Watch PR CI**

The action-smoke job in this PR's CI must pass on the first try. If it doesn't:

- **`action-smoke` failed, output says "uvx: error: no matching distribution":** semvertag `0.5.0` is not on PyPI (or hasn't propagated). Check `pip index versions semvertag` from outside the runner. If 0.5.0 isn't there, this PR can't merge until the release process completes.
- **`action-smoke` failed, output shows `status=created`:** the dry-run wiring is broken in `action.yml`. Re-examine the `dry_run_flag` shell construction in Task 2 Step 2.
- **`action-smoke` failed, output shows `status=no-bump` but the assertion still failed:** this is impossible given the assertion is `test "$status" = "no-bump"`. If it happens, capture the raw CI log and STOP.
- **`lint` or `pytest` failed:** these jobs are not touched by this PR, so any failure is a pre-existing flake or an unrelated regression. Investigate before merging.

---

## Post-merge follow-ups (NOT part of this plan)

1. The dogfood workflow will run on the merge commit. Since this is a `feat/`-prefixed branch, branch-prefix bumps minor → `0.6.0` (next minor after the current `0.5.0`).
2. Optionally cut a `0.6.0` release pointing at the merge commit to publish to PyPI. The CLI behavior is unchanged from 0.5.0; only the composite action's contract grew (new input). A `0.6.0` PyPI release isn't strictly needed unless a consumer relies on `uvx semvertag` (not the action) for dry-run — and `0.5.0` already supports that.

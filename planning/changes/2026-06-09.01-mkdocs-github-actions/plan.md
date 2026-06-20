---
status: shipped
date: 2026-06-09
slug: mkdocs-github-actions
spec: mkdocs-github-actions
pr: null
---

# mkdocs deploy via GitHub Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up mkdocs auto-deploy on push to `main` (mirroring `modern-di`'s setup) and bump action pins across existing workflows to match.

**Architecture:** Pure CI/configuration change. Adds a `docs-deploy` Justfile recipe, a `Deploy Docs` GitHub Actions workflow, a `site_url` + `docs/CNAME` for the `semvertag.modern-python.org` custom subdomain, and mechanical action-version bumps in four existing workflow files. No application code changes. No automated tests — verification is observational (local `mkdocs build --strict`, YAML validation, post-merge `workflow_dispatch` trigger).

**Tech Stack:** GitHub Actions, mkdocs + mkdocs-material (already in `docs/requirements.txt`), `uv`/`uvx`, `just`.

**Spec:** `planning/specs/2026-06-09-mkdocs-github-actions-design.md`

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `Justfile` | Modify (append) | Add `docs-deploy` recipe |
| `.github/workflows/docs.yml` | Create | Auto-deploy on push to `main` when docs change |
| `mkdocs.yml` | Modify | Add `site_url` for custom subdomain |
| `docs/CNAME` | Create | One-line file containing the custom subdomain hostname |
| `.github/workflows/ci.yml` | Modify | Bump action pins (3x checkout, 2x setup-just, 2x setup-uv) |
| `.github/workflows/publish.yml` | Modify | Bump action pins (1x each) |
| `.github/workflows/semvertag.yml` | Modify | Bump `checkout@v4` → `@v6` |
| `.github/workflows/tag-major.yml` | Modify | Bump `checkout@v4` → `@v6` |

## Branch

Work happens on a single feature branch. Per `CLAUDE.md` + the repo's branch-prefix strategy (`SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'`), `feat/...` maps to a minor bump on merge — which is what this change deserves.

Branch name: `feat/docs-github-actions`

Run before Task 1:

```bash
git checkout -b feat/docs-github-actions
```

---

### Task 1: Add `docs-deploy` recipe to `Justfile`

**Files:**
- Modify: `Justfile` (append at end)

- [ ] **Step 1: Append the recipe to `Justfile`**

Open `Justfile` and append at the end (after the existing `publish` recipe). Keep the foot-gun comment verbatim — it's load-bearing for anyone who runs this locally:

```make

# Force-pushes built site to gh-pages; CI runs this on push to main.
# Manual invocation from a stale checkout will roll the live site back.
docs-deploy:
    uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force
```

Note the leading blank line — `Justfile` recipes are separated by blank lines.

- [ ] **Step 2: Verify just sees the recipe**

Run: `just --list`

Expected output includes a line like:

```
    docs-deploy    # Force-pushes built site to gh-pages; CI runs this on push to main.
```

If the recipe doesn't appear, check that the indentation under `docs-deploy:` is a literal tab (Justfile, like Make, requires tabs for recipe bodies).

- [ ] **Step 3: Verify the diff**

Run: `git diff Justfile`

Expected: only the addition of the `docs-deploy` recipe (3 added lines: comment, comment, recipe header) + 1 indented body line. No other changes.

- [ ] **Step 4: Commit**

```bash
git add Justfile
git commit -m "ci: add docs-deploy recipe to Justfile"
```

---

### Task 2: Add `.github/workflows/docs.yml`

**Files:**
- Create: `.github/workflows/docs.yml`

- [ ] **Step 1: Create the workflow file**

Write `.github/workflows/docs.yml` with this exact content:

```yaml
name: Deploy Docs

on:
  push:
    branches: [main]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - ".github/workflows/docs.yml"
  workflow_dispatch:

concurrency:
  group: docs-deploy
  cancel-in-progress: true

permissions:
  contents: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: extractions/setup-just@v4
      - uses: astral-sh/setup-uv@v8.2.0
      - run: just docs-deploy
```

- [ ] **Step 2: Validate YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docs.yml'))"`

Expected: no output, exit code 0. Any YAML parse error means a typo (most commonly: bad indentation under `on:`, or accidentally tabs instead of spaces — workflows must use spaces).

- [ ] **Step 3: Sanity-check the file structurally**

Run: `git diff --stat .github/workflows/docs.yml`

Expected: shows the file as added with ~25 lines.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "ci(docs): add Deploy Docs workflow"
```

---

### Task 3: Add `site_url` to `mkdocs.yml` and create `docs/CNAME`

**Files:**
- Modify: `mkdocs.yml` (insert after line 1, `site_name: semvertag`)
- Create: `docs/CNAME`

- [ ] **Step 1: Add `site_url` to `mkdocs.yml`**

Open `mkdocs.yml`. After the `site_name: semvertag` line (current line 1), insert:

```yaml
site_url: https://semvertag.modern-python.org
```

The top of the file should now read:

```yaml
site_name: semvertag
site_url: https://semvertag.modern-python.org
repo_url: https://github.com/modern-python/semvertag
docs_dir: docs
edit_uri: edit/main/docs/
```

- [ ] **Step 2: Create `docs/CNAME`**

Create `docs/CNAME` with this single line (no trailing blank line beyond the single newline at EOF — `eof-fixer` will normalize, but only if there's exactly one):

```
semvertag.modern-python.org
```

- [ ] **Step 3: Verify the docs still build locally**

Run: `uvx --with-requirements docs/requirements.txt mkdocs build --strict 2>&1 | tail -20`

Expected: ends with a line like `INFO    -  Documentation built in <N>.<NN> seconds`. No `WARNING` or `ERROR` lines.

If `--strict` flags a warning about `site_url` not matching `repo_url`, ignore — that's expected; they're intentionally different.

If `--strict` fails for an unrelated reason (e.g. a broken link in an existing page), that's a pre-existing issue out of scope — stash the local build and proceed; surface it in the final review.

Clean up the build artifact:

```bash
rm -rf site/
```

- [ ] **Step 4: Verify the diff**

Run: `git status --short docs/ mkdocs.yml`

Expected:

```
 M mkdocs.yml
?? docs/CNAME
```

Run: `git diff mkdocs.yml`

Expected: a single line addition — the `site_url:` line under `site_name:`.

- [ ] **Step 5: Commit**

```bash
git add mkdocs.yml docs/CNAME
git commit -m "docs: configure custom subdomain semvertag.modern-python.org"
```

---

### Task 4: Bump action pins across existing workflows

This task touches four files in one commit. The bumps are mechanical and consistent; bundling them is more readable than four single-line commits.

**Files:**
- Modify: `.github/workflows/ci.yml` (3x checkout, 2x setup-just, 2x setup-uv)
- Modify: `.github/workflows/publish.yml` (1x each)
- Modify: `.github/workflows/semvertag.yml` (1x checkout)
- Modify: `.github/workflows/tag-major.yml` (1x checkout)

- [ ] **Step 1: Bump pins in `ci.yml`**

In `.github/workflows/ci.yml`, replace every occurrence:
- `uses: actions/checkout@v4` → `uses: actions/checkout@v6` (3 occurrences: lint job, pytest job, action-smoke job)
- `uses: extractions/setup-just@v2` → `uses: extractions/setup-just@v4` (2 occurrences: lint job, pytest job)
- `uses: astral-sh/setup-uv@v3` → `uses: astral-sh/setup-uv@v8.2.0` (2 occurrences: lint job, pytest job)

A safe way to do this is with `sed`:

```bash
sed -i.bak \
  -e 's|actions/checkout@v4|actions/checkout@v6|g' \
  -e 's|extractions/setup-just@v2|extractions/setup-just@v4|g' \
  -e 's|astral-sh/setup-uv@v3|astral-sh/setup-uv@v8.2.0|g' \
  .github/workflows/ci.yml && rm .github/workflows/ci.yml.bak
```

- [ ] **Step 2: Verify `ci.yml` diff**

Run: `git diff --stat .github/workflows/ci.yml`

Expected: `7 +++++++ 7 -------` (3 + 2 + 2 = 7 lines changed).

Run: `git diff .github/workflows/ci.yml | grep -c '^+[^+]'` — should print `7`.
Run: `git diff .github/workflows/ci.yml | grep -c '^-[^-]'` — should print `7`.

Run: `grep -E '@(v4|v2|v3)$' .github/workflows/ci.yml` — should print nothing (no old pins left).

- [ ] **Step 3: Bump pins in `publish.yml`**

Same sed pattern:

```bash
sed -i.bak \
  -e 's|actions/checkout@v4|actions/checkout@v6|g' \
  -e 's|extractions/setup-just@v2|extractions/setup-just@v4|g' \
  -e 's|astral-sh/setup-uv@v3|astral-sh/setup-uv@v8.2.0|g' \
  .github/workflows/publish.yml && rm .github/workflows/publish.yml.bak
```

- [ ] **Step 4: Verify `publish.yml` diff**

Run: `git diff --stat .github/workflows/publish.yml`

Expected: `3 +++ 3 ---`.

- [ ] **Step 5: Bump pins in `semvertag.yml`**

Only `checkout` needs bumping here (no `setup-just`/`setup-uv` in this file):

```bash
sed -i.bak 's|actions/checkout@v4|actions/checkout@v6|g' \
  .github/workflows/semvertag.yml && rm .github/workflows/semvertag.yml.bak
```

- [ ] **Step 6: Verify `semvertag.yml` diff**

Run: `git diff --stat .github/workflows/semvertag.yml`

Expected: `1 + 1 -`.

- [ ] **Step 7: Bump pins in `tag-major.yml`**

```bash
sed -i.bak 's|actions/checkout@v4|actions/checkout@v6|g' \
  .github/workflows/tag-major.yml && rm .github/workflows/tag-major.yml.bak
```

- [ ] **Step 8: Verify `tag-major.yml` diff**

Run: `git diff --stat .github/workflows/tag-major.yml`

Expected: `1 + 1 -`.

- [ ] **Step 9: Verify no stale `.bak` files were left behind**

Run: `find .github/workflows -name '*.bak'`

Expected: no output. If any `.bak` file is listed, delete it: `rm .github/workflows/*.bak`.

- [ ] **Step 10: Validate every workflow file still parses as YAML**

Run:

```bash
for f in .github/workflows/*.yml; do
  python3 -c "import sys, yaml; yaml.safe_load(open('$f'))" || { echo "FAIL: $f"; exit 1; }
done
echo "all workflows parse OK"
```

Expected: `all workflows parse OK`.

- [ ] **Step 11: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/publish.yml \
        .github/workflows/semvertag.yml .github/workflows/tag-major.yml
git commit -m "ci: bump action pins (checkout v6, setup-just v4, setup-uv v8.2.0)"
```

---

### Task 5: Final verification and PR

- [ ] **Step 1: Skim the full branch diff**

Run: `git log main..HEAD --oneline`

Expected: four commits in order:

```
<sha> ci: bump action pins (checkout v6, setup-just v4, setup-uv v8.2.0)
<sha> docs: configure custom subdomain semvertag.modern-python.org
<sha> ci(docs): add Deploy Docs workflow
<sha> ci: add docs-deploy recipe to Justfile
```

Run: `git diff main..HEAD --stat`

Expected: 8 files touched (Justfile, mkdocs.yml, docs/CNAME, and the 5 workflow files).

- [ ] **Step 2: Run the repo's lint-ci gate**

Run: `just lint-ci`

Expected: passes. This validates `eof-fixer`, `ruff format`, `ruff check`, and `ty check` — none of which should be affected by this change, but they're the standard gate.

If `eof-fixer` complains about `docs/CNAME` missing/extra trailing newline, that's the file-format expectation; `eof-fixer` will tell you to either run `just lint` (which auto-fixes) or fix manually. Fix and re-stage:

```bash
just lint  # auto-fix
git add docs/CNAME
git commit --amend --no-edit  # only if this is the most recent commit on the branch
```

If the file with the bad EOF is not in the most recent commit, make a tiny follow-up commit rather than amending an earlier commit:

```bash
git add docs/CNAME
git commit -m "docs: fix CNAME trailing newline"
```

- [ ] **Step 3: Push the branch**

```bash
git push -u origin feat/docs-github-actions
```

- [ ] **Step 4: Open the PR**

Run:

```bash
gh pr create --title "ci: deploy mkdocs via GitHub Actions" --body "$(cat <<'EOF'
## Summary

- Adds a `Deploy Docs` workflow that auto-deploys `mkdocs` to `gh-pages` on push to `main` when `docs/**` or `mkdocs.yml` changes.
- Adds a `docs-deploy` recipe to `Justfile` (`uvx mkdocs gh-deploy --force`), mirroring `modern-di`.
- Configures the custom subdomain `semvertag.modern-python.org` via `site_url` in `mkdocs.yml` and `docs/CNAME`.
- Bumps action pins across `ci.yml`, `publish.yml`, `semvertag.yml`, `tag-major.yml` to match `modern-di` parity: `checkout@v6`, `setup-just@v4`, `setup-uv@v8.2.0`.

Spec: `planning/specs/2026-06-09-mkdocs-github-actions-design.md`

## Test plan

- [ ] CI lint job passes under bumped action pins
- [ ] CI pytest matrix passes under bumped action pins
- [ ] `action-smoke` job passes under `checkout@v6` (this is the one job where the bump could surface a difference — composite action exercised via `uses: ./`)
- [ ] After merge: trigger `Deploy Docs` via `workflow_dispatch` from the Actions UI — workflow succeeds, creates `gh-pages` branch
- [ ] After merge: enable GitHub Pages on the `gh-pages` branch in repo Settings → Pages
- [ ] After merge: configure DNS for `semvertag.modern-python.org` (CNAME → `modern-python.github.io.`) and verify the site serves

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed. Return it to the user.

- [ ] **Step 5: Confirm the PR's own CI run passes**

Watch the PR's checks. Two jobs are the bump's load-bearing tests:

- `lint` — sanity-check that `setup-just@v4` + `setup-uv@v8.2.0` still expose the same interfaces
- `action-smoke` — the one job where `checkout@v6` could surface a real difference, since it exercises the composite action via `uses: ./`

If `action-smoke` fails *only* due to the `checkout@v6` bump (and not a pre-existing flake), the rollback per the spec's Risks section is: revert that one pin in `ci.yml` (the action-smoke job's `actions/checkout@v6` back to `@v4`) and keep the rest. Commit and push.

If everything passes, the PR is ready for review.

---

## Post-merge follow-ups (NOT part of this plan)

These steps are outside the code change and the user (maintainer) will run them after the PR merges. Listed here so they're not forgotten:

1. From the Actions UI, manually trigger the `Deploy Docs` workflow via `workflow_dispatch`. First run creates the `gh-pages` branch.
2. Repo Settings → Pages: set source = "Deploy from a branch", branch = `gh-pages`, folder = `/ (root)`.
3. DNS: add CNAME record `semvertag.modern-python.org` → `modern-python.github.io.` in the `modern-python.org` zone.
4. Verify `https://semvertag.modern-python.org` serves the docs.
5. Repo Settings → Pages: enable "Enforce HTTPS" once the cert provisions.

If DNS for `modern-python.org` can't be configured, the fallback is to revert the `docs/CNAME` addition + the `site_url` line; the site will then serve at `https://modern-python.github.io/semvertag/`.

---
summary: "Docs hosting via MkDocs + GitHub Actions + Pages."
---

# mkdocs deploy via GitHub Actions — design

**Status:** approved
**Date:** 2026-06-09
**Reference:** `modern-python/modern-di` (sibling repo, same maintainer pattern)

## Goal

Wire `semvertag`'s mkdocs site to deploy automatically on push to `main`, mirroring `modern-di`'s setup. The docs source already exists (`docs/`, `mkdocs.yml`); only the deployment plumbing is missing.

## Why

- The site never updates today — there's no `docs-deploy` recipe and no docs workflow.
- `modern-di` is the maintainer's established template for this; staying close to it keeps both repos easy to reason about.
- Bumping the action pins across all workflows at the same time avoids a second drive-by churn PR later.

## Scope

In scope:
1. Add `docs-deploy` recipe to `Justfile`.
2. Add `.github/workflows/docs.yml` for auto-deploy on push to `main`.
3. Add `site_url` to `mkdocs.yml` and `docs/CNAME` for the custom subdomain `semvertag.modern-python.org`.
4. Bump action pins across all existing workflows to match `modern-di`:
   - `actions/checkout@v4` → `@v6`
   - `extractions/setup-just@v2` → `@v4`
   - `astral-sh/setup-uv@v3` → `@v8.2.0`
   - Files touched: `ci.yml`, `publish.yml`, `semvertag.yml`, `tag-major.yml`.

Out of scope (explicit):
- No `_checks.yml` reusable-workflow refactor (modern-di did this; we're not).
- No `mkdocs build --strict` PR gate (modern-di doesn't have one either).
- DNS configuration on `modern-python.org` — manual follow-up, not code.
- GitHub Pages repo-settings change — manual follow-up, not code.

## Design

### 1. Justfile recipe

Copy verbatim from `modern-di`, keeping the foot-gun comment:

```make
# Force-pushes built site to gh-pages; CI runs this on push to main.
# Manual invocation from a stale checkout will roll the live site back.
docs-deploy:
    uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force
```

`uvx` resolves `mkdocs` + `mkdocs-material` from `docs/requirements.txt` (which already exists and matches modern-di's). `gh-deploy --force` is mkdocs' built-in command; it builds the site and force-pushes to the `gh-pages` branch.

### 2. Deploy workflow

New file `.github/workflows/docs.yml`, byte-for-byte from modern-di:

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

Notes:
- `paths:` filter means non-docs commits to `main` don't redeploy.
- `workflow_dispatch:` is what we'll use for the first-deploy bootstrap.
- `concurrency` prevents racing deploys; `cancel-in-progress: true` matches modern-di.
- `permissions: contents: write` is required for force-pushing to `gh-pages`.
- `fetch-depth: 0` gives mkdocs the full history (needed for `git-revision-date`-style plugins if added later; modern-di carries it, we mirror).

### 3. mkdocs.yml + CNAME

Add `site_url` near the top of `mkdocs.yml`:

```yaml
site_url: https://semvertag.modern-python.org
```

Add new file `docs/CNAME`:

```
semvertag.modern-python.org
```

GitHub Pages reads `docs/CNAME` during the build (mkdocs ships it as-is to `gh-pages`) and uses it as the configured custom domain.

### 4. Action-version bumps

Mechanical edit across four workflow files. No semantic change expected — same actions, newer major versions. Bump every occurrence; if `action-smoke` breaks under `checkout@v6`, address per the Risks section.

| File | `checkout@v4` → `@v6` | `setup-just@v2` → `@v4` | `setup-uv@v3` → `@v8.2.0` |
|---|---|---|---|
| `ci.yml` | 3 (lint, pytest, action-smoke) | 2 (lint, pytest) | 2 (lint, pytest) |
| `publish.yml` | 1 | 1 | 1 |
| `semvertag.yml` | 1 | — | — |
| `tag-major.yml` | 1 | — | — |

### 5. First-deploy bootstrap (manual, post-merge)

Order of operations after this lands on `main`:

1. Trigger `Deploy Docs` via `workflow_dispatch` from the Actions UI. This creates the `gh-pages` branch as a side effect of `gh-deploy --force`.
2. In repo Settings → Pages, set source = "Deploy from a branch", branch = `gh-pages`, folder = `/ (root)`.
3. Configure DNS for `semvertag.modern-python.org`: CNAME → `modern-python.github.io.` (matches modern-di's setup; verify against existing modern-di DNS records).
4. Wait for DNS propagation; verify `https://semvertag.modern-python.org` resolves and serves the docs.
5. In Settings → Pages, enable "Enforce HTTPS" once the certificate provisions.

These steps are intentionally outside the spec because they're either GitHub UI clicks or DNS-zone changes. The spec will be considered complete once the workflow runs green and the maintainer can complete these steps without further code changes.

## Risks

- **action-smoke job interaction with `checkout@v6`:** `ci.yml`'s `action-smoke` job uses `uses: ./` to run the composite action under test. Composite actions with `checkout@v6` should be fine, but it's the one job where a version bump could surface a real difference. Mitigation: test on a PR before merging; if `action-smoke` fails on v6, revert just that pin and keep the rest of the bump.
- **`gh-deploy --force` foot-gun:** Anyone running `just docs-deploy` from a stale local checkout will roll the live site back. The comment in the Justfile is the only mitigation; we accept this since modern-di accepts it.
- **DNS misconfiguration locks out the site:** If the `CNAME` file is committed before DNS is configured, the GitHub Pages domain check will fail and the site will 404 on the custom domain. This is recoverable (remove the `CNAME` file or fix DNS), but the bootstrap order in §5 puts DNS as step 3 to minimize the window.
- **`modern-python.org` zone may not be owned by the maintainer:** If the subdomain can't be assigned, fall back to `<user>.github.io/semvertag/` by skipping the `CNAME` file and `site_url`. This is a recoverable revert, not a blocker for the workflow.

## Testing

No automated tests — this is infrastructure. Verification is observational:
- After merge: `workflow_dispatch` succeeds; `gh-pages` branch exists; site builds.
- After Pages enabled: `https://<user>.github.io/semvertag/` serves the docs.
- After DNS: `https://semvertag.modern-python.org` serves the docs.
- Subsequent push to `main` touching `docs/` triggers a redeploy; non-docs pushes don't.

## Follow-ups (not in this spec)

- Consider adding `mkdocs build --strict` as a PR-time gate in `ci.yml`. Defer until the deploy is stable.
- Consider the `_checks.yml` reusable-workflow refactor as a separate parity pass. Defer.
- Consider migrating to GitHub's newer Pages deployment model (`actions/deploy-pages@v4` + `actions/upload-pages-artifact`) instead of `gh-deploy --force`. modern-di hasn't done this; we mirror.

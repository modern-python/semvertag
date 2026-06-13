---
status: shipped
date: 2026-05-31
slug: v0-1-0-release-prep
spec: v0-1-0-release-prep
pr: null
---

# v0.1.0 Release Prep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land all v0.1.0 release blockers in one atomic commit on main, then tag `v0.1.0` and let the publish workflow handle PyPI upload.

**Architecture:** Single bundled commit touching ~12 files. Source-side changes (drop `--provider` + `Settings.provider`), test updates, file deletions (`action.yml`, `docs/providers/github.md`), `mkdocs.yml` nav cleanup, `pyproject.toml` metadata, `publish.yml` switch to `uv version $TAG` pattern, real README, real `docs/index.md`, `<org>` → `modern-python` sweep across docs.

**Tech Stack:** Existing — pydantic-settings, typer, modern-di-typer, mkdocs, uv. No new deps.

**Spec:** `planning/specs/2026-05-31-v0-1-0-release-prep-design.md`

---

## Task 1: Spawn worktree and verify baseline

**Files:** none in main checkout.

- [ ] **Step 1: Spawn the worktree**

Use the `superpowers:using-git-worktrees` skill. Suggested branch: `feat/v0-1-0-release-prep`. Suggested path: `.worktrees/feat-v0-1-0-release-prep`.

- [ ] **Step 2: Verify clean baseline inside the worktree**

Run (inside the worktree, after `cd` and `uv sync --all-extras --group lint`):

```bash
pwd
git branch --show-current
git status
```

Expected: cwd is `/Users/kevinsmith/src/pypi/autosemver/.worktrees/feat-v0-1-0-release-prep`, branch is `feat/v0-1-0-release-prep`, status clean.

Run: `just lint-ci`
Expected: PASS.

Run: `uv run pytest -q`
Expected: 330 passed, 1 skipped.

Run: `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

If any baseline check fails, stop and report.

---

## Task 2: Atomic release-prep commit

The 12-ish file changes are independent in their effects but bundled for diff coherence as a "release prep" commit.

### CRITICAL: Verify cwd before any git operation

Before EVERY `git rm`, `git add`, and `git commit`, run:

```bash
pwd
git branch --show-current
```

The output MUST show:
- pwd: `/Users/kevinsmith/src/pypi/autosemver/.worktrees/feat-v0-1-0-release-prep`
- branch: `feat/v0-1-0-release-prep`

If either is wrong, STOP. Use absolute paths (starting with the worktree path) for Edit operations.

### Step 1: Drop `provider` field from `Settings` in `semvertag/_settings.py`

Find the `provider` field (currently line 65 in the `Settings` class):

```python
    provider: typing.Literal["gitlab", "github", "bitbucket"] = "gitlab"
```

Delete this line. The `Settings` class loses the `provider` field entirely.

### Step 2: Drop `--provider` flag + related plumbing in `semvertag/__main__.py`

**2a.** In `_collect_overrides` (around lines 40-65), remove the `provider` keyword from the signature and the corresponding if-block. The new signature:

```python
def _collect_overrides(  # noqa: PLR0913
    *,
    project_id: int | None,
    strategy: str | None,
    token: str | None,
    default_branch: str | None,
    gitlab_endpoint: str | None,
    request_timeout: float | None,
) -> dict[str, typing.Any]:
```

And remove the body block:

```python
    if provider is not None:
        overrides["provider"] = provider
```

If the function is now under 6 keyword args (currently 7 → 6), check whether `# noqa: PLR0913` (>5 args) is still needed. Ruff's PLR0913 default is 5; with 6 args it still applies. Keep the noqa.

**2b.** In `_main_callback` (around lines 83-150), remove the `--provider` typer Option from the parameter list. Currently:

```python
    provider: typing.Annotated[
        str | None,
        typer.Option("--provider", help="Provider: gitlab | github | bitbucket."),
    ] = None,
```

Delete those four lines.

**2c.** In `_main_callback`'s body, remove the `provider=provider,` argument from the `_collect_overrides(...)` call.

**2d.** In `_main_callback`'s body, remove the provider-not-supported check:

```python
        if settings.provider != "gitlab":
            msg = f"Provider {settings.provider!r} not yet supported; v1.0 supports gitlab only."
            raise ConfigError(msg)
```

There IS no other provider in v0.1.0, so the check is dead.

### Step 3: Delete provider-related test fixtures and assertions

**3a.** In `tests/integration/conftest.py`, find `_CLEAN_ENV_KEYS` (around line 28-39). Remove the `"SEMVERTAG_PROVIDER",` entry.

**3b.** In `tests/unit/test_settings.py`, find `assert settings.provider == "gitlab"` (line 29). Delete this assertion. The surrounding test (`test_uses_defaults_when_no_env_set`) keeps its other assertions; just drop this one line.

**3c.** In `tests/unit/test_settings.py`, find the function `test_prefers_semvertag_token_over_provider_native` (line 49). Read the whole function — if it relies on `provider=...` in Settings construction, update or delete. If it only relies on env-var precedence (likely), no change needed. Run the test before deciding.

**3d.** In `tests/unit/test_ioc.py`, find `_ProviderName` (line 13) and `_settings(... provider=...)` (lines 16-18). Drop both the `_ProviderName` alias and the `provider` parameter. The new helper:

```python
def _settings(
    *,
    strategy: _StrategyName = "branch-prefix",
) -> Settings:
    return Settings(project_id=999, strategy=strategy)
```

If any test in `test_ioc.py` calls `_settings(provider=...)`, drop the `provider=` argument from those calls.

**3e.** Verify no CLI integration test passes `--provider` to `cli_runner.invoke(MAIN_APP, [...])`:

```bash
grep -n "provider" tests/integration/test_cli_*.py
```

If any matches with `--provider`, remove the flag from the args list.

### Step 4: Delete the GitHub-specific files

```bash
git rm action.yml docs/providers/github.md
```

Both files are deleted entirely.

### Step 5: Update `mkdocs.yml` — drop GitHub provider nav entry + replace `<org>`

In `mkdocs.yml`:

**5a.** Update `repo_url` (line 2):

```yaml
repo_url: https://github.com/modern-python/semvertag
```

(was `https://github.com/<org>/semvertag`)

**5b.** Remove the GitHub Actions entry from the `Providers` nav (line 10):

```yaml
# Before:
  - Providers:
    - GitHub Actions: providers/github.md
    - GitLab CI: providers/gitlab.md
# After:
  - Providers:
    - GitLab CI: providers/gitlab.md
```

**5c.** Update the social GitHub link (line 71):

```yaml
extra:
  social:
    - icon: fontawesome/brands/github
      link: https://github.com/modern-python/semvertag
      name: GitHub
```

(was `link: https://github.com/<org>/semvertag`)

### Step 6: Update `pyproject.toml` — `<org>` + description

**6a.** Replace `<org>` (line 32):

```toml
[project.urls]
repository = "https://github.com/modern-python/semvertag"
docs = "https://semvertag.readthedocs.io"
```

**6b.** Tighten the description (line 3):

```toml
description = "Auto-tag GitLab repos with semantic version tags — one tool, two strategies."
```

(was `"Auto-tag GitLab/GitHub/Bitbucket repos with semantic version tags — one tool, two strategies."`)

Keywords stay as-is (`["semver", "gitlab", "ci", "auto-tag", "conventional-commits"]` — no github/bitbucket to remove).

### Step 7: Update `.github/workflows/publish.yml` — drop tag-guard, add `uv version` step

In `.github/workflows/publish.yml`, find the `tag_guard` step (lines 80-121). The step currently does:
1. Compute `EFFECTIVE_TAG` from `release.tag_name` or `inputs.tag`
2. Strip leading `v`
3. Validate SemVer 2.0 regex
4. Read `[project.version]` from pyproject.toml
5. Assert `EFFECTIVE_TAG == PROJECT_VERSION`
6. Set `effective_tag` step output

Replace the entire step block with this simpler version that keeps the tag computation + SemVer validation, drops the assertion, and writes the step output (still needed for the artifact-upload step):

```yaml
      - id: tag_guard
        name: Resolve and validate release tag
        run: |
          # Resolve effective tag from the triggering event.
          if [ "${{ github.event_name }}" = "release" ]; then
            EFFECTIVE_TAG="${{ github.event.release.tag_name }}"
          elif [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            EFFECTIVE_TAG="${{ inputs.tag }}"
          else
            echo "::error::Unexpected event_name ${{ github.event_name }} — publish.yml expects 'release' or 'workflow_dispatch'."
            exit 1
          fi

          # Strip a single leading 'v' (the SemVer-style 'v1.0.0' tag prefix).
          EFFECTIVE_TAG="${EFFECTIVE_TAG#v}"

          # Re-assert strict SemVer 2.0 form post-strip. Catches typos like
          # 'v1.0' or empty pre-release identifiers before the tag reaches
          # PyPI. See SemVer 2.0 §2 (no leading zeros), §9 (pre-release
          # identifier rules), §10 (build-metadata identifier rules).
          if ! echo "$EFFECTIVE_TAG" | grep -Eq '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9A-Za-z-]*)(\.(0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9A-Za-z-]*))*))?(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$'; then
            echo "::error::Effective tag '${EFFECTIVE_TAG}' is not strict SemVer 2.0 (expected MAJOR.MINOR.PATCH with optional dot-separated -prerelease and +build identifiers; no leading zeros in numeric identifiers; no empty identifiers)."
            exit 1
          fi
          echo "effective_tag=${EFFECTIVE_TAG}" >> "$GITHUB_OUTPUT"

      - name: Inject version from tag
        if: success()
        # pyproject.toml ships with version = "0" as a placeholder
        # (matches the modern-di convention). The publish workflow sets
        # the real version from the tag at build time, so main never
        # carries a version that requires bumping per release.
        run: uv version "${{ steps.tag_guard.outputs.effective_tag }}"
```

Keep everything else in `publish.yml` unchanged (concurrency, release-from-main check, setup-uv, build, upload artifact, publish).

### Step 8: Rewrite `README.md`

Replace the entire contents of `README.md` with:

````markdown
# semvertag

[![CI](https://github.com/modern-python/semvertag/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/semvertag/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/modern-python/semvertag/branch/main/graph/badge.svg)](https://codecov.io/gh/modern-python/semvertag)

Auto-tag your GitLab repository with semantic version tags from CI — one tool, two strategies.

## Install

```sh
uvx semvertag tag
```

## Use it in GitLab CI

Include the Catalog component in your `.gitlab-ci.yml`:

```yaml
include:
  - component: gitlab.com/modern-python/semvertag/semvertag@v0.1.0
    inputs:
      strategy: branch-prefix  # or: conventional-commits
```

The component runs `uvx semvertag tag` against your repo on the
default branch. semvertag inspects the latest commit + tag history,
decides the appropriate semver bump, and creates the new tag via the
GitLab API.

## Strategies

- **branch-prefix** (default): the latest commit on the default branch
  must be a merge commit whose source branch starts with `feature/`
  (minor), `bugfix/`, or `hotfix/` (patch).
- **conventional-commits**: parses the latest commit's
  [Conventional Commits](https://www.conventionalcommits.org/)
  header (`feat:` minor, `fix:`/`perf:` patch, `!` or `BREAKING
  CHANGE:` major).

Both are configurable via env vars. See [docs](https://semvertag.readthedocs.io)
for the full configuration surface.

## License

MIT
````

### Step 9: Rewrite `docs/index.md`

Replace the entire contents of `docs/index.md` (currently `# semvertag — coming soon`) with:

```markdown
# semvertag

Auto-tag your GitLab repository with semantic version tags from CI —
one tool, two strategies.

semvertag reads the latest commit and tag history from your GitLab
project via the API, decides the appropriate semver bump based on the
strategy you've configured, and creates the new git tag — all from a
single command in your CI pipeline.

## Quick start

The recommended way to use semvertag in CI is via the
[GitLab CI Catalog component](providers/gitlab.md):

```yaml
include:
  - component: gitlab.com/modern-python/semvertag/semvertag@v0.1.0
    inputs:
      strategy: branch-prefix  # or: conventional-commits
```

For local testing or one-off invocations:

```sh
SEMVERTAG_TOKEN=<your-gitlab-token> \
SEMVERTAG_PROJECT_ID=<your-project-id> \
  uvx semvertag tag
```

## Strategies

semvertag ships with two bump-decision strategies:

- [**branch-prefix**](strategies/branch-prefix.md) — bump based on the
  source branch of the latest merge commit (`feature/` → minor,
  `bugfix/` / `hotfix/` → patch). The default.
- [**conventional-commits**](strategies/conventional-commits.md) —
  bump based on the latest commit's Conventional Commits header
  (`feat:` → minor, `fix:` / `perf:` → patch, `!` or
  `BREAKING CHANGE:` → major).

Both strategies are configurable via environment variables — see the
strategy pages for the full configuration surface.

## Contributing

- [Release runbook](contributing/release.md) — for maintainers cutting
  a new release of semvertag itself.
```

### Step 10: Update `docs/providers/gitlab.md` — replace `<org>` and update version pin

In `docs/providers/gitlab.md`, replace every occurrence of `<org>` with `modern-python`. Use the editor's find/replace or:

```bash
sed -i '' 's/<org>/modern-python/g' docs/providers/gitlab.md
```

(On Linux: `sed -i 's/<org>/modern-python/g' docs/providers/gitlab.md` — drop the `''`.)

Verify with:

```bash
grep -n "<org>" docs/providers/gitlab.md
```
Expected: no matches.

Also update the version pin in the Catalog component examples. The file currently uses `@v1`; update to `@v0.1.0` to match the first release. Find with:

```bash
grep -n "@v1" docs/providers/gitlab.md
```

There are typically 3 occurrences. Replace each `@v1` with `@v0.1.0`.

### Step 11: Update `docs/contributing/release.md` — replace `<org>`

```bash
sed -i '' 's/<org>/modern-python/g' docs/contributing/release.md
```

Verify with `grep -n "<org>" docs/contributing/release.md` (expected: no matches).

The release runbook also has 2-3 NOTE blocks that explain `<org>` is a placeholder. After the find/replace those notes become stale ("Replace `modern-python` below with the actual..."). Read the file and delete or rewrite those NOTE blocks; they served only to flag the placeholder.

### Step 12: Update `templates/semvertag.yml` — version pin

Open `templates/semvertag.yml`. Find the `script:` section. The current script line is:

```yaml
  script:
    - uvx 'semvertag>=1,<2' tag
```

Update the version pin to allow v0.x as the first published release:

```yaml
  script:
    - uvx 'semvertag>=0.1,<1' tag
```

(`>=0.1,<1` permits any 0.1.x or 0.x release; tighten to `>=0.1,<0.2` if you want to pin more strictly. The wider range is more forgiving for early adopters.)

### Step 13: Run the full test suite

```bash
uv run pytest -q
```

Expected: a count near 330, possibly slightly lower because:
- The `provider == "gitlab"` assertion in `test_uses_defaults_when_no_env_set` is removed (1 fewer assertion, same test count)
- The `test_prefers_semvertag_token_over_provider_native` test might still pass without modification
- `test_ioc.py`'s parametrize-on-provider tests might lose variants if they tested provider rejection

If a test fails, READ the failure:
- `AttributeError: 'Settings' object has no attribute 'provider'` — Step 1 incomplete, OR Step 3a/3b/3d missed a reference
- `TypeError: _collect_overrides() got an unexpected keyword argument 'provider'` — Step 2c missed a caller
- `TypeError: Settings.__init__() got an unexpected keyword argument 'provider'` — Step 3d missed a test fixture

Do NOT silently mask bugs.

### Step 14: Lint check

```bash
just lint-ci
```

Expected: PASS. If ruff/ty flag unused imports (e.g., a `typing.Literal` import that became unused), fix them.

### Step 15: Branch-coverage gates

```bash
just test-branch-strategies
just test-cc-strategies
```

Expected: both still 100% on their respective strategy modules (unaffected by this work).

### Step 16: Docs build

```bash
UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict
```

Expected: builds clean. If `--strict` complains about a missing nav entry, verify `mkdocs.yml` correctly dropped the GitHub Actions line (Step 5b).

### Step 17: Sdist verification

```bash
uv build
tar -tzf dist/semvertag-0.tar.gz | sort
```

Expected: 27-ish files, all under `semvertag-0/semvertag/` or top-level (`README.md`, `pyproject.toml`, `PKG-INFO`). NO `action.yml`, NO `docs/`, NO `tests/`.

### Step 18: CLI smoke tests

```bash
uv run semvertag --help
```
Expected: top-level help shows the `tag` subcommand. The `--provider` flag is NOT listed.

```bash
uv run semvertag tag --help
```
Expected: tag subcommand help. Shows `--quiet` and `--json` only.

```bash
uv run semvertag tag
```
Expected: fails with `Error: Project id missing. Set CI_PROJECT_ID or pass --project-id.` Exit code 2.

```bash
uv run semvertag --version
```
Expected: prints version (e.g. "0", because pyproject still has version = "0"; the real version is set only at publish-workflow time). Exit 0.

### Step 19: `<org>` sweep

```bash
grep -rn "<org>" . 2>&1 | grep -vE "_archive/|\.worktrees/|_autosemver_reference/|\.git/"
```

Expected: NO matches. If any line is still there, address it.

### Step 20: Verify cwd before committing

```bash
pwd
git branch --show-current
```

MUST show worktree path and `feat/v0-1-0-release-prep`. If wrong, STOP.

### Step 21: Commit

```bash
git add -A
git commit -m "release: prep for v0.1.0

- Drop --provider CLI flag + Settings.provider field (only gitlab works)
- Delete action.yml + docs/providers/github.md (github provider not
  implemented; ship clean v0.1.0; restore both when github provider lands)
- publish.yml: adopt modern-di pattern of \`uv version \$TAG\` at build time;
  drop the strict tag↔[project.version] guard
- README.md + docs/index.md: replace stubs with real content
- <org> → modern-python everywhere (pyproject URL, doc examples, mkdocs
  repo_url + social link, GitLab template version pin)
- mkdocs.yml: drop GitHub provider nav entry
- templates/semvertag.yml: update version pin to >=0.1,<1

[project.version] stays \"0\" as a placeholder per the modern-di convention;
the publish workflow injects the real version from the git tag."
```

---

## Task 3: Pre-merge verification gate

**Files:** none modified.

- [ ] **Step 1: Lint**

Run: `just lint-ci`
Expected: PASS.

- [ ] **Step 2: Full test suite**

Run: `uv run pytest`
Expected: count near 330 (small reduction from deleted provider tests, see Step 13 for likely diff).

- [ ] **Step 3: Branch-coverage gates**

Run: `just test-branch-strategies && just test-cc-strategies`
Expected: both still 100% on strategy modules.

- [ ] **Step 4: Docs build**

Run: `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

- [ ] **Step 5: Sdist sanity check**

Run: `uv build && tar -tzf dist/semvertag-0.tar.gz`
Expected: 27 entries, all `semvertag/` source or top-level (README, pyproject, PKG-INFO).

- [ ] **Step 6: LOC + commit sanity check**

Run: `git diff main --shortstat`
Expected: 12+ files changed, ~-200 to -300 LOC net deletion.

Run: `git log --oneline main..HEAD`
Expected: exactly 1 commit (`release: prep for v0.1.0`).

- [ ] **Step 7: `<org>` sweep on main + worktree files**

Run: `grep -rn "<org>" . 2>&1 | grep -vE "_archive/|\.worktrees/|_autosemver_reference/|\.git/"`
Expected: NO matches.

---

## Task 4: Land the worktree + tag the release

**Files:** none modified by hand.

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Use the skill to merge to `main` (fast-forward expected — main shouldn't have moved during this work) and clean up the worktree.

- [ ] **Step 2: Verify the work is on `main`**

Run (in the main checkout): `git log --oneline -3`
Expected: the `release: prep for v0.1.0` commit is at HEAD.

Run: `just lint-ci && uv run pytest -q`
Expected: green on `main`.

Run: `ls action.yml docs/providers/github.md 2>&1 | head -2`
Expected: both files report "No such file or directory".

- [ ] **Step 3: Tag v0.1.0**

```bash
git tag v0.1.0
```

Note: do NOT push the tag yet. The tag must align with the GitHub Release creation, which fires the publish workflow.

- [ ] **Step 4: Push the tag**

```bash
git push origin v0.1.0
```

- [ ] **Step 5: Create the GitHub Release**

This is a manual step in the GitHub UI:
1. Navigate to `https://github.com/modern-python/semvertag/releases/new`
2. Select tag: `v0.1.0`
3. Title: `v0.1.0 — initial release`
4. Body: free-form release notes (this IS the changelog; mention the strategies, that gitlab is the only supported provider in this release)
5. Click "Publish release"

This fires the `release: published` event, which triggers `.github/workflows/publish.yml`. The workflow validates the tag, runs `uv version 0.1.0`, builds the sdist + wheel with the injected version, and publishes to PyPI via trusted publishing.

- [ ] **Step 6: Verify the publish workflow ran**

Watch the workflow run at `https://github.com/modern-python/semvertag/actions/workflows/publish.yml`. Expected: green run on `v0.1.0`.

If the workflow fails (e.g., trusted-publishing not configured on PyPI, or a SemVer validation issue), use the `workflow_dispatch` retry path:

```
GitHub Actions → publish workflow → Run workflow → tag: v0.1.0 → Run
```

- [ ] **Step 7: Verify the package on PyPI**

```bash
uvx --refresh semvertag==0.1.0 tag --help
```

Expected: downloads from PyPI, prints the tag subcommand help.

Or visit `https://pypi.org/project/semvertag/0.1.0/` to confirm the release page.

---

## Success criteria

When all tasks above are done:

- `semvertag/_settings.py` has no `provider` field
- `semvertag/__main__.py` has no `--provider` typer Option; `_collect_overrides` has no `provider` kwarg; the `if settings.provider != "gitlab"` check is gone
- `action.yml` and `docs/providers/github.md` are deleted
- `mkdocs.yml` nav has no GitHub provider entry; `repo_url` and social link use `modern-python`
- `pyproject.toml` `[project.urls].repository` is `https://github.com/modern-python/semvertag`; description mentions gitlab only
- `publish.yml` uses `uv version "${EFFECTIVE_TAG}"` instead of the tag-guard shell script
- `README.md` has install + usage + strategies + license sections
- `docs/index.md` is a real landing page (not "coming soon")
- `templates/semvertag.yml` uses `>=0.1,<1` version pin
- `grep -rn "<org>" .` (excluding `_archive/`, `.worktrees/`, `_autosemver_reference/`, `.git/`) returns no matches
- All tests pass (count near 330)
- `just lint-ci`, `uv run pytest`, `mkdocs build --strict`, `uv build` all green
- Sdist contents are clean (only `semvertag/` source + README + pyproject + PKG-INFO)
- v0.1.0 is published on PyPI: `https://pypi.org/project/semvertag/0.1.0/`

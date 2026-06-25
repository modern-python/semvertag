---
summary: "Pre-1.0 release preparation."
---

# v0.1.0 release prep

**Date:** 2026-05-31
**Status:** Approved, ready for plan
**Author:** brainstorm session (Superpowers `brainstorming` skill)

## Context

`semvertag` is functionally ready for its first PyPI release after a
session of refactor work (BMad → Superpowers migration, httpx2
wrapper, doctor removal, AliasChoices, callable use case, idiomatic
modern-di-typer wiring, CLI overlay simplification, strategy no-bump
cleanup). 330 tests pass. CI workflow, publish workflow (trusted
publishing via PyPI OIDC, SHA-pinned actions), dependency-update
workflow, MIT license, full pyproject metadata, mkdocs docs — all in
place.

The publish-blocking gaps are content/scope-honesty issues, not code
issues:

- `version = "0"` in `pyproject.toml` is fine as a placeholder (matches
  modern-di's convention), but `publish.yml` currently asserts
  `tag == [project.version]` — incompatible with the version-from-tag
  pattern. Workflow needs adjusting.
- `<org>` placeholder appears in URLs across `pyproject.toml`, `README.md`,
  `action.yml`, and 3 doc files. Needs replacing with `modern-python`.
- `README.md` is a 5-line stub (title + 2 broken badges + 1 sentence).
- `docs/index.md` is literally `# semvertag — coming soon`.
- The CLI advertises `--provider gitlab | github | bitbucket` but only
  gitlab works. `action.yml` (the GitHub Actions wrapper) sets
  `SEMVERTAG_PROVIDER: github` and would fail at runtime. Misleading.

This spec bundles all blockers into one atomic commit, then the maintainer
tags `v0.1.0` on GitHub and the existing publish workflow handles the
rest.

## Decisions

| Question | Decision |
| --- | --- |
| Version | `v0.1.0` (first PyPI release, pre-1.0 signals early-access) |
| `[project.version]` in `pyproject.toml` | Stays `"0"`; publish workflow injects real version from tag via `uv version $EFFECTIVE_TAG` (matches modern-di) |
| GitHub org | `modern-python` (sibling to `modern-di`) |
| `--provider` CLI flag + `Settings.provider` field | Drop entirely. Only gitlab works; no choice means no flag |
| `action.yml` (GitHub Actions wrapper) | Delete. Would fail at runtime; add back when github provider is real |
| `docs/providers/github.md` | Delete. Same reasoning |
| `CHANGELOG.md` | Skip. GitHub Releases are the changelog |
| Spec shape | One bundled spec, single atomic commit |

## What gets touched

### Source

| File | Change |
|---|---|
| `semvertag/_settings.py` | Drop `provider` field from `Settings` (the `typing.Literal["gitlab", "github", "bitbucket"]`) |
| `semvertag/__main__.py` | Drop `--provider` typer Option from `_main_callback`; drop `provider` param from `_collect_overrides`; drop the `if settings.provider != "gitlab"` ConfigError raise |
| `semvertag/ioc.py` | (No change — already builds gitlab unconditionally) |

### Build / CI

| File | Change |
|---|---|
| `.github/workflows/publish.yml` | Replace the long shell `tag == [project.version]` guard (~40 LOC) with a `uv version "${EFFECTIVE_TAG}"` step inserted before `uv build`. Keep tag SemVer 2.0 validation, release-from-main check, SHA-pinned actions, trusted publishing, artifact upload |
| `pyproject.toml` | Replace `<org>` in `[project.urls].repository` with `modern-python`. Tighten `description` to mention gitlab only |
| `action.yml` | **Delete** |

### Docs

| File | Change |
|---|---|
| `README.md` | Replace 5-line stub with ~30 lines: badges (fixed `<org>`), install via `uvx`, GitLab CI Catalog include example, strategies summary, license. Point at mkdocs docs for full content |
| `docs/index.md` | Replace `# semvertag — coming soon` with a landing page (~30-50 lines): what it does, quick start (link to provider/strategy pages), link to contributing/release runbook |
| `docs/providers/github.md` | **Delete** |
| `docs/providers/gitlab.md` | Replace `<org>` → `modern-python` (~6 occurrences); update version pin in component example to `@v0.1.0` |
| `docs/contributing/release.md` | Replace `<org>` → `modern-python` (~3 occurrences) |
| `mkdocs.yml` | Drop the `Providers > GitHub Actions` nav entry (the file is gone) |

### Tests

| File | Change |
|---|---|
| `tests/integration/conftest.py` | Drop `"SEMVERTAG_PROVIDER"` from `_CLEAN_ENV_KEYS` (no longer a setting) |
| `tests/unit/test_settings.py` | Drop any test that asserts on `settings.provider` (or its default). Check by grep |
| `tests/integration/test_cli_*.py` | Verify no test passes `--provider` flag. If so, drop the flag from those invocations |
| `tests/unit/test_ioc.py` | The `_settings(provider=...)` helper takes a `_ProviderName` Literal — narrow or drop the parameter |

## Architecture changes

### `publish.yml` — modern-di version-from-tag pattern

Current shape (around lines 80-121):

```bash
# ... compute EFFECTIVE_TAG, strip leading 'v', validate SemVer 2.0 ...

# Read [project.version] from pyproject.toml
PROJECT_VERSION=$(uv run --no-project python -c \
    "import tomllib, pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")

if [ "$EFFECTIVE_TAG" != "$PROJECT_VERSION" ]; then
    echo "::error::Release tag (${EFFECTIVE_TAG}) does not match pyproject.toml [project.version] (${PROJECT_VERSION}). Refusing to publish..."
    exit 1
fi
```

New shape:

```bash
# ... compute EFFECTIVE_TAG, strip leading 'v', validate SemVer 2.0 ...

# Inject the version from the tag (pyproject.toml keeps version = "0" as a placeholder).
# Matches the modern-di convention.
uv version "${EFFECTIVE_TAG}"
```

The `PROJECT_VERSION` shell var, the `tomllib`-based read, the assertion,
and the error message all go away. The `uv version` step replaces them.

`uv version <X>` sets `[project.version]` to `<X>` in the working
directory's pyproject.toml; the subsequent `uv build` reads that
in-memory pyproject. The change is not committed (the working-dir-only
edit happens inside the publish job; the `main` branch's pyproject
still reads `version = "0"` after the workflow finishes).

Keep everything else in `publish.yml`:
- `concurrency:` group
- release-from-main `target_commitish` check (when triggered by release event)
- SHA-pinned actions, OIDC trusted publishing, artifact upload
- SemVer 2.0 regex validation (catches typos like `v1.0` or empty pre-release identifiers)

### `Settings.provider` removal

Before:

```python
class Settings(pydantic_settings.BaseSettings):
    # ...
    strategy: typing.Literal["branch-prefix", "conventional-commits"] = "branch-prefix"
    provider: typing.Literal["gitlab", "github", "bitbucket"] = "gitlab"
    # ...
```

After: drop the `provider` line. The field, the Literal, and any
downstream branching disappear.

### `_main_callback` simplification

Drop the `--provider` typer Option (currently around lines 93-96 in
`__main__.py`):

```python
provider: typing.Annotated[
    str | None,
    typer.Option("--provider", help="Provider: gitlab | github | bitbucket."),
] = None,
```

Drop the corresponding line in `_collect_overrides` call (~line 124):

```python
provider=provider,
```

Drop the `provider` keyword from `_collect_overrides`'s signature
(~lines 41) and its `if provider is not None:` block (~lines 86-87).

Drop the runtime check (~lines 77-79):

```python
if settings.provider != "gitlab":
    msg = f"Provider {settings.provider!r} not yet supported; v1.0 supports gitlab only."
    raise ConfigError(msg)
```

(No replacement — there IS no other provider in v0.1.0.)

### README.md content (verbatim)

```markdown
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

Both can be customized via env vars. See [docs](https://semvertag.readthedocs.io)
for the full configuration surface.

## License

MIT
```

### docs/index.md content (rough sketch)

A landing page roughly:

```markdown
# semvertag

Auto-tag your GitLab repository with semantic version tags from CI — one
tool, two strategies.

## Quick start

Pick your CI:

- **GitLab CI** → [GitLab CI Catalog component](providers/gitlab.md)

## Strategies

- [branch-prefix](strategies/branch-prefix.md) — bump based on
  feature/bugfix/hotfix merge-commit prefixes
- [conventional-commits](strategies/conventional-commits.md) — bump
  based on Conventional Commits headers

## Contributing

- [Release runbook](contributing/release.md) — for maintainers cutting
  a new release
```

(The implementer can flesh out the prose; this is the structural
intent.)

## Estimated delta

- Source: ~-30 LOC (drop provider field + CLI flag + collect_overrides param + ConfigError check)
- CI: ~-30 LOC (drop the publish.yml tag-guard shell script, add one `uv version` step)
- Files deleted: `action.yml` (~85 LOC) + `docs/providers/github.md` (~140 LOC) = ~-225 LOC
- README + docs/index.md: net +50 LOC (content)
- `<org>` replacements: ~zero LOC delta
- Tests: ~-10 LOC (drop provider-related assertions/fixtures)

**Net: ~-250 LOC across the codebase, plus a much cleaner public surface.**

## Execution sequencing

One atomic commit on one worktree. Changes are independent but bundling
them keeps the "release-prep" diff coherent in git history.

### Worktree setup

Spawn `feat/v0-1-0-release-prep` off `main`, path
`.worktrees/feat-v0-1-0-release-prep`. Baseline:
`just lint-ci && uv run pytest -q` should pass (330 / 1 skipped on
current main).

### Single wave — all changes

Edits land in this order within the commit (for diff readability):

1. **Source changes** — drop `provider` field from `_settings.py`; drop `--provider` flag + the related callback logic in `__main__.py`; verify `ioc.py` doesn't reference it
2. **Test updates** — drop provider-related assertions in `test_settings.py`, `test_ioc.py`, `tests/integration/conftest.py`'s `_CLEAN_ENV_KEYS`; verify CLI tests still pass
3. **Delete files** — `git rm action.yml docs/providers/github.md`
4. **`mkdocs.yml`** — drop the GitHub provider nav entry
5. **`pyproject.toml`** — replace `<org>` with `modern-python` in `[project.urls]`; tighten description
6. **`publish.yml`** — drop the shell tag-guard; add `uv version` step
7. **`README.md`** — replace with the content above
8. **`docs/index.md`** — replace with the landing page sketch
9. **`<org>` → `modern-python`** in `docs/providers/gitlab.md`, `docs/contributing/release.md`, and the GitLab template version pin (`@v1` → `@v0.1.0` where applicable)

### Gate after the wave

- `just lint-ci` — PASS
- `uv run pytest -q` — expect a smaller count than 330 (some provider tests deleted; how many depends on what's in `test_settings.py`/`test_ioc.py`)
- `just test-branch-strategies && just test-cc-strategies` — still 100%
- `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict` — clean (with the github.md gone and nav updated)
- `uv build` — succeeds (sdist + wheel)
- Smoke tests:
  - `uv run semvertag --help` — `--provider` flag NOT listed
  - `uv run semvertag tag` — same `Project id missing` error + exit 2
  - `grep -rn "<org>" .` (excluding `_archive/` and `.worktrees/`) — NO matches
  - `tar -tzf dist/semvertag-0.tar.gz` — only `semvertag/` source + manifest, NO `action.yml`

### Commit message

```
release: prep for v0.1.0

- Drop --provider CLI flag + Settings.provider field (only gitlab works)
- Delete action.yml + docs/providers/github.md (github provider not
  implemented; ship clean v0.1.0; restore both when github provider lands)
- publish.yml: adopt modern-di pattern of `uv version $TAG` at build time;
  drop the strict tag↔[project.version] guard
- README.md + docs/index.md: replace stubs with real content
- <org> → modern-python everywhere (pyproject URL, doc examples, GitLab
  template version pin)
- mkdocs.yml: drop GitHub provider nav entry

[project.version] stays "0" as a placeholder per the modern-di convention;
the publish workflow injects the real version from the git tag.
```

### Tag and release

After the commit lands on `main`:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Then on GitHub:
1. Navigate to Releases → "Draft a new release"
2. Choose tag `v0.1.0`
3. Title: `v0.1.0 — initial release`
4. Body: free-form release notes (this IS the changelog)
5. Click "Publish release" — fires `release: published` event → `publish.yml` runs → PyPI receives the package

If `publish.yml` fails for any reason, the `workflow_dispatch` retry path
exists (workflow input takes the tag explicitly).

## Success criteria

When all of these hold, this spec is done and the release is publishable:

- `Settings` has no `provider` field
- `--provider` flag is gone from the CLI
- `action.yml` and `docs/providers/github.md` are deleted
- `mkdocs.yml` nav has no GitHub provider entry
- `publish.yml` uses `uv version "${EFFECTIVE_TAG}"` instead of the tag-guard shell script
- `pyproject.toml` `[project.urls].repository` points at `modern-python/semvertag`
- `README.md` has install + usage + strategies + license sections
- `docs/index.md` has a landing page (not "coming soon")
- `grep -rn "<org>" .` (excluding `_archive/`, `.worktrees/`, `_autosemver_reference/`) returns no matches
- All tests pass (count adjusted for deleted provider tests)
- `just lint-ci`, `mkdocs build --strict`, `uv build` all green
- Sdist contents are clean (only `semvertag/` source + README + pyproject + PKG-INFO)

## Out of scope

- Implementing the GitHub provider (separate future work; restore
  `action.yml` + `docs/providers/github.md` when it lands)
- Implementing the Bitbucket provider
- `_use_case.py` `strategy.name` cleanup (already done)
- CHANGELOG.md (using GitHub Releases instead)
- Any architecture work — the code is ready

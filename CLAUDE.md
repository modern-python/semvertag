# semvertag — Claude project guide

## Architecture

> Quick orientation. The authoritative, code-current account of each capability
> lives in [`architecture/`](architecture/). **When a change alters a
> capability's behavior, update the matching `architecture/<capability>.md` in
> the same PR** — that promotion is what keeps `architecture/` true.

`semvertag` funnels everything through one process: a human at a shell, the
GitHub Action, and the GitLab CI component all invoke `semvertag tag`, which
parses flags + environment into validated `Settings`, wires a **provider** and a
**strategy** through a modern-di container, and runs the use-case. Invariants
that must not break: the CLI is the single entry point all wrappers share;
providers expose a forge-neutral contract (read commits/tags, create a tag)
independent of GitLab-vs-GitHub REST differences; strategies answer only "given
this repo signal, what bump level" with no network and no tag-history reads.

| Capability | File |
|---|---|
| CLI entry point, `Settings`, DI wiring, Action / CI wrappers | [`architecture/cli.md`](architecture/cli.md) |
| Forge adapters (GitLab, GitHub) and their neutral contract | [`architecture/providers.md`](architecture/providers.md) |
| Bump-level strategies (`branch-prefix`, `conventional-commits`) | [`architecture/strategies.md`](architecture/strategies.md) |

## Workflow

This project uses **Superpowers** (brainstorm → plan → TDD → review) with the
portable two-axis planning convention. `architecture/` (repo root) is the living
truth home; `planning/` records *how it got there*. **Start at the
[Quick path](planning/README.md#quick-path-start-here)** in
[`planning/README.md`](planning/README.md) to choose a lane (Full / Lightweight /
Tiny), create a bundle, and ship — that file is the authoritative spec. Run
`just check-planning` to validate bundles and `just index` to print the change
listing.

Per feature: brainstorming → `design.md` → writing-plans → `plan.md` →
executing-plans / subagent-driven-development → requesting-code-review →
finishing-a-development-branch. Use TDD by default (red, green, refactor), git
worktrees for isolation (`superpowers:using-git-worktrees`), the verification
gate before claiming completion (`superpowers:verification-before-completion`),
and a subagent code review before landing (`superpowers:requesting-code-review`).

Planning artifacts live under `planning/` (not `docs/`, so they're excluded from
the mkdocs site automatically). When superpowers skills default to
`docs/superpowers/specs/` or `docs/superpowers/plans/`, use the change bundle
under `planning/changes/` here instead.

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
dry-run and never auto-tags, so the tag you push is the only tag. If `just
publish` succeeds but a later step fails (Release or `v0`), do **not** re-push
the tag — PyPI rejects re-uploading an existing version. Create the GitHub
Release and move `v0` by hand, or cut a new patch tag.

## Commit messages

Imperative present-tense, scoped where helpful:

- `providers: add HttpClient wrapper`
- `docs: update README hero section`
- `fix: handle empty default branch in GitLab provider`

No story-numbered prefixes (`land story X.Y`, `contextualise story X.Y`). Those
belong to the retired BMad workflow.

## Reference directories (do not edit)

- `_archive/bmad/` — retired BMad workspace. Historical specs, PRD,
  architecture, retrospectives, and 14 dense story files. Read for context;
  do not extend, do not delete.
- `_autosemver_reference/` — the original Raiffeisen-internal `autosemver`
  package. Behavioral reference only — port logic and test shapes from it
  but never `git mv` files in or take it as a starter.

## Commands

`just --list` is the source of truth. Non-obvious "which to use when":

- `just lint` autofixes; `just lint-ci` is check-only and also runs the
  planning validator (`planning/index.py --check`, also `just check-planning`).
- `just test` runs pytest with `--cov-branch` and a project-wide
  `fail_under = 100` gate (set in `pyproject.toml` addopts), so every branch
  must be covered. Pass args through:
  `just test tests/unit/test_branch_prefix_strategy.py -q`.
- `just docs-build` — strict mkdocs build (`mkdocs build --strict`), the docs
  gate.

## What the codebase ships

`semvertag` is a public-OSS auto-tagger for GitLab/GitHub/Bitbucket
repositories. Two strategies (`branch-prefix`, `conventional-commits`), two
providers implemented today (GitLab, GitHub), distributed as a Python CLI plus
a GitHub Actions wrapper (`action.yml`) and a GitLab CI Catalog component
(`templates/semvertag.yml`).

## Tag and release naming

Two distinct tag conventions coexist — confusing them is easy:

- **Release tags: bare semver, no `v` prefix** (`0.3.1`, `0.4.0`). `just publish`
  runs `uv version $GITHUB_REF_NAME` expecting bare semver; the branch-prefix
  strategy emits bare-semver tags by default; release URLs are
  `releases/tag/0.4.0`. When touching the CLI / `Justfile` / publish flow, think
  bare semver — `$GITHUB_REF_NAME` is `0.4.0`, not `v0.4.0`.
- **Action floating tag: `v`-prefixed** (`v0`). The `Float major tag` step in
  [`.github/workflows/release.yml`](.github/workflows/release.yml) prepends `v`
  to the release tag's major segment (`0.4.0` → `v0`) and force-updates the
  floating tag, so consumers can pin `uses: modern-python/semvertag@v0` per the
  GHA ecosystem convention. Skipped on pre-releases. When touching that step or
  action-consumer docs, think `v`-prefix.

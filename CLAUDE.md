# semvertag — Claude project guide

## Workflow

This project uses **Superpowers** (brainstorm → plan → TDD → review) with the
portable two-axis planning convention. The living truth about *what the system
does now* lives in [`architecture/`](architecture/) at the repo root (one file
per capability: `strategies.md`, `providers.md`, `cli.md`); `planning/` records
*how it got there*. See [`planning/README.md`](planning/README.md) for the full
conventions and the change Index, and [`planning/_templates/`](planning/_templates/)
for copy-and-fill starters.

Per feature: brainstorming → spec in
`planning/changes/YYYY-MM-DD.NN-<slug>/design.md` → writing-plans → plan
in the same bundle's `plan.md` → executing-plans / subagent-driven-development →
requesting-code-review → finishing-a-development-branch. `<slug>` is a
kebab-case description, not a story ID; `.NN` is a zero-padded intra-day counter
that breaks same-date ties. The implementing PR sets `status: shipped` and fills
`pr` / `outcome` in the branch, alongside the code and the
`architecture/<capability>.md` promotion — that hand-edit is the only ship-time
step; there is no folder move. The change listing is generated — run `just index`
(no committed Index). A design decision taken **without** a code change —
especially a candidate **rejected** with a load-bearing reason — is recorded as
`planning/decisions/YYYY-MM-DD-<slug>.md` (the `decision.md` template, frontmatter
`status: accepted|superseded`), each with a **Revisit trigger** so future reviews
don't re-litigate it; listed by `just index`.

**Three lanes.** Scale the artifact to the change. **Full** — a `design.md` +
`plan.md` bundle — for real design judgment, a new file/module, a public-API
change, cross-cutting/multi-file work, or non-trivial test design.
**Lightweight** — a single `change.md` — for small-but-real changes (≲30 LOC
net, ≤2 files, no new file, no public-API change, a single straightforward
test). **Tiny** — no bundle, just a conventional commit — for a typo, dep bump,
linter/formatter/CI tweak, a mechanical rename, or a single-line config change.
Heavier lane wins on ambiguity.

Use TDD by default: red, green, refactor. Tests before implementation. Use git
worktrees for feature isolation (`superpowers:using-git-worktrees`). Use the
verification gate before claiming work complete
(`superpowers:verification-before-completion`). Request code review via a
subagent before landing (`superpowers:requesting-code-review`).

Planning artifacts live under `planning/` (not under `docs/`, so they're
excluded from the mkdocs site automatically). When superpowers skills default to
`docs/superpowers/specs/` or `docs/superpowers/plans/`, use the change bundle
under `planning/changes/` here instead.

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

## Test stack and lint

See `Justfile` for the canonical commands. Quick reference:

- `just lint-ci` — eof-fixer, ruff format check, ruff check, ty check
  (check-only; `just lint` is the autofixing variant)
- `just test` — pytest. The `addopts` in `pyproject.toml` add `--cov-branch`
  with a project-wide `fail_under = 100` gate, so every branch (strategy
  modules included) must be covered. Pass args through, e.g.
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
- **Action floating tag: `v`-prefixed** (`v0`). `.github/workflows/tag-major.yml`
  strips any leading `v` from the release tag then prepends `v` to the major
  segment (`0.4.0` → `v0`), so consumers can pin `uses: modern-python/semvertag@v0`
  per the GHA ecosystem convention. When touching `tag-major.yml` or
  action-consumer docs, think `v`-prefix.

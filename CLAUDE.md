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
`planning/changes/active/YYYY-MM-DD.NN-<slug>/design.md` → writing-plans → plan
in the same bundle's `plan.md` → executing-plans / subagent-driven-development →
requesting-code-review → finishing-a-development-branch. `<slug>` is a
kebab-case description, not a story ID; `.NN` is a zero-padded intra-day counter
that breaks same-date ties. On merge the bundle moves to
`planning/changes/archive/` with `status: shipped`, `pr:`, and `outcome:`
filled, **and the change promotes its conclusions into the affected
`architecture/<capability>.md`** — that hand-edit is what keeps `architecture/`
true.

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
under `planning/changes/active/` here instead.

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
- `just test` — pytest with coverage
- `just test-branch` — pytest with branch coverage
- `just test-branch-strategies` / `just test-cc-strategies`
  — 100% branch coverage gates on specific modules
- `mkdocs build --strict` — docs build gate

## What the codebase ships

`semvertag` is a public-OSS auto-tagger for GitLab/GitHub/Bitbucket
repositories. Two strategies (`branch-prefix`, `conventional-commits`), two
providers implemented today (GitLab, GitHub), distributed as a Python CLI plus
a GitHub Actions wrapper (`action.yml`) and a GitLab CI Catalog component
(`templates/semvertag.yml`).

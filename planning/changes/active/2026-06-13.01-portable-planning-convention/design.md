---
status: draft
date: 2026-06-13
slug: portable-planning-convention
supersedes: null
superseded_by: null
pr: null
outcome: null
---

# Design: Adopt the portable two-axis planning convention

## Summary

Port the planning convention from `lite-bootstrap` (its #120, itself from
`faststream-outbox` #77) into `semvertag`. It splits planning into two axes: an
`architecture/` truth home at the repo root (one living-prose file per
capability, the promotion target on every ship) and `planning/changes/`
bundles (one frozen folder per change). The existing 15 `planning/specs/` +
`planning/plans/` pairs migrate into dated `changes/archive/` bundles; the
portable `## Conventions` block, `_templates/`, and `deferred.md` are copied
byte-identical. **Docs and file-moves only — no runtime code, tests, or public
API touched.**

## Motivation

`semvertag` currently keeps design docs in `planning/specs/` and plans in
`planning/plans/` as two parallel flat directories keyed by
`YYYY-MM-DD-<topic>`. This has two gaps the sibling repos already solved:

- **No truth home.** There is no single place that states *what the system
  does now*. That knowledge is scattered across `CLAUDE.md` and the code, and
  drifts as changes land. `architecture/` fixes this with a promote-on-merge
  discipline.
- **Spec and plan drift apart.** A spec and its plan for the same change live
  in two directories with no folder binding them; nothing co-locates the
  *thinking* with the *sequencing*. Change bundles co-locate them.

Adopting the same convention as `lite-bootstrap` and `faststream-outbox` also
makes the three modern-python repos navigable the same way — the `##
Conventions` block and `_templates/` are deliberately byte-identical so the
convention is learned once.

A latent bug also gets fixed: `.gitignore` carries a bare `plan.md` rule that
would silently swallow every bundle's `plan.md` once the convention lands.

## Non-goals

- No runtime code, test, or public-API change. The published `semvertag`
  package is untouched.
- No `audits/` or `retros/` directories — this repo has produced neither;
  YAGNI. The README still documents them for when they first appear.
- No rewrite of the migrated specs/plans' bodies — they move verbatim (via
  `git mv`) and gain only YAML frontmatter.
- No GitLab Catalog or release work; unrelated to this change.

## Design

### 1. Two-axis model

- **`architecture/` (repo root) — the present.** One file per capability,
  living prose, **no frontmatter** (dated by git). Updated whenever a change
  ships. The truth home.
- **`planning/changes/` — the past-and-pending.** One folder per change,
  frozen once shipped.

Shipping a change **promotes** its conclusions into the affected
`architecture/<capability>.md` by hand, then archives the bundle. The hand-edit
is what keeps `architecture/` true; the archived bundle carries the *why*.

### 2. `architecture/` seeded with three capability files

Mirroring lite-bootstrap's three-file carving, seeded from `CLAUDE.md` and the
code:

- **`strategies.md`** — the `Strategy` base (`strategies/_base.py`) and the two
  bump strategies, `branch-prefix` and `conventional-commits`
  (`strategies/branch_prefix.py`, `strategies/conventional_commits.py`), plus
  commit-message parsing (`_commit_parse.py`).
- **`providers.md`** — the provider abstraction (`providers/_base.py`), the
  GitLab and GitHub providers (`providers/gitlab.py`, `providers/github.py`),
  link-header pagination (`_link_pagination.py`), the httpware HTTP client, and
  secret redaction (`_redact.py`).
- **`cli.md`** — the CLI surface (`__main__.py`), IoC wiring (`ioc.py`),
  settings + CLI overlay (`_settings.py`), use-case orchestration
  (`_use_case.py`), and output formatting (`_output.py`).

### 3. Migrate the 15 spec/plan pairs into archived bundles

Each `planning/specs/<date>-<slug>-design.md` + `planning/plans/<date>-<slug>.md`
pair becomes `planning/changes/archive/<date>.NN-<slug>/{design.md,plan.md}`.
The `.NN` intra-day counter is taken from git first-commit order so the timeline
sorts stably:

| Bundle |
|--------|
| `2026-05-31.01-bmad-to-superpowers-migration-and-httpx2-wrapper` |
| `2026-05-31.02-drop-doctor` |
| `2026-05-31.03-settings-aliaschoices` |
| `2026-05-31.04-usecase-callable` |
| `2026-05-31.05-ioc-idiomatic-modern-di-typer` |
| `2026-05-31.06-cli-overlay-simplification` |
| `2026-05-31.07-strategy-no-bump-cleanup` |
| `2026-05-31.08-v0-1-0-release-prep` |
| `2026-06-07.01-httpware-migration` |
| `2026-06-08.01-httpware-decoder-adoption` |
| `2026-06-08.02-github-provider` |
| `2026-06-08.03-action-yml-composite-wrapper` |
| `2026-06-09.01-mkdocs-github-actions` |
| `2026-06-09.02-dry-run-flag` |
| `2026-06-09.03-action-yml-dry-run` |

Migration mechanics per pair:

- `git mv` both files into the bundle folder, renaming to `design.md` /
  `plan.md` (preserves history).
- Prepend YAML frontmatter. `design.md`: `status: shipped`, `date`, `slug`,
  `supersedes: null`, `superseded_by: null`, `pr`, `outcome`. `plan.md`:
  `status: shipped`, `date`, `slug`, `spec: <slug>`, `pr`. The existing
  header-style `**Date:**` / `**Status:**` lines stay in the body untouched.
- `planning/specs/` and `planning/plans/` are removed once empty (their
  `.gitkeep` files go too).

**Frontmatter `pr` / `outcome` completeness.** `pr` and a one-line factual
`outcome` are backfilled where git/GitHub merge history maps a bundle cleanly to
a single PR. Where a bundle does not map to one PR (e.g. early pre-release work
landed across several commits), `pr` is left `null` and `outcome` carries a
short factual note instead of a guessed PR number. Accuracy over completeness:
no invented PR links.

### 4. Supporting files copied byte-identical

- **`planning/README.md`** — the portable `## Conventions` block byte-identical
  to lite-bootstrap, plus a fresh semvertag-specific `## Index` (Active: this
  convention change until merge; Archived: the 15 migrated bundles).
- **`planning/_templates/{design,plan,change}.md`** — byte-identical.
- **`planning/deferred.md`** — added, seeded empty (no genuinely-deferred items
  on hand).
- `planning/releases/` (0.2.0–0.6.0) is left as-is.

### 5. `CLAUDE.md`, `Justfile`, `.gitignore`

- **`CLAUDE.md`** — rewrite the `## Workflow` section to the bundle convention,
  naming `architecture/` as the promotion target and pointing at
  `planning/changes/active/YYYY-MM-DD.NN-<slug>/` (replacing the current
  `planning/specs/` + `planning/plans/` references). Keep `## Reference
  directories` and `## What the codebase ships` intact. The three-lanes
  guidance (Full / Lightweight / Tiny) is added.
- **`Justfile`** — add a `docs-build` recipe
  (`uvx --with-requirements docs/requirements.txt mkdocs build --strict`) as a
  local strict gate alongside the existing `docs-deploy`.
- **`.gitignore`** — remove the bare `plan.md` line so bundle `plan.md` files
  are tracked.

### 6. Dogfood

This change is its own bundle:
`planning/changes/active/2026-06-13.01-portable-planning-convention/`. On merge
it moves to `archive/` with `status: shipped`, `pr:`, and `outcome:` filled, and
its Index line shifts from Active to Archived. No `architecture/` promotion —
this change defines the convention, not a library capability.

## Testing

- `just lint-ci` — eof-fixer, ruff format/check, ty all clean.
- `just test` — full suite green, coverage unchanged (no runtime code touched).
- `mkdocs build --strict` (via the new `just docs-build`) — exits 0;
  `architecture/` and `planning/` are outside `docs_dir`, so the site is
  unchanged.
- Frontmatter parses as valid YAML on every migrated `design.md` / `plan.md`;
  any `outcome` value containing `#` is quoted (YAML comment trap).
- Stale-pointer sweep: no remaining references to `planning/specs/` or
  `planning/plans/`; README Index links and the migrated `Spec:` links all
  resolve.
- `## Conventions` block and `_templates/` are byte-identical to lite-bootstrap.

## Risk

- **`.gitignore` plan.md trap (high likelihood if missed, high impact).** Until
  the rule is removed, `git add` silently skips every bundle's `plan.md`.
  Mitigation: remove it in the same change and verify with `git status` /
  `git check-ignore` that no bundle `plan.md` is ignored.
- **Lost git history on migrated files (medium / medium).** Using `cp`+`rm`
  instead of `git mv` would break `--follow`. Mitigation: `git mv` only;
  spot-check `git log --follow` on a migrated file.
- **Inaccurate frontmatter `pr` (low / medium).** Guessing PR numbers would
  mislead. Mitigation: backfill only when merge history is unambiguous;
  otherwise `null` (see §3).
- **Stale references in `CLAUDE.md` / docs (low / low).** Mitigation: grep sweep
  for `planning/specs` and `planning/plans` after migration.

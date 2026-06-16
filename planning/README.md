# Planning

Specs, plans, and change history for `semvertag`. The living truth
about *what the system does now* lives in [`architecture/`](../architecture/)
at the repo root; this directory records *how it got there*.

## Conventions

> This section is the portable convention — identical across the
> modern-python repos. The Index below is repo-specific. To adopt elsewhere,
> copy this section plus [`_templates/`](_templates/) and point that repo's
> `CLAUDE.md` Workflow + truth home at it.

### Two axes, never mixed

- **`architecture/` (repo root) — the present.** One file per capability,
  living prose, updated whenever a change ships. The truth home.
- **`planning/changes/` — the past-and-pending.** One folder per change,
  frozen once shipped.

Shipping a change **promotes** its conclusions into the affected
`architecture/<capability>.md` by hand, then archives the bundle. That
hand-edit is what keeps `architecture/` true; the archived bundle carries the
*why*.

### Change bundles

A change is a folder `changes/active/YYYY-MM-DD.NN-<slug>/`:

- `YYYY-MM-DD` — proposal date; `.NN` — zero-padded intra-day counter
  (`.01`, `.02`, …) that breaks same-date ties so the timeline sorts stably.
- `<slug>` — kebab-case description, not a story ID.

On merge the folder moves to `changes/archive/` with `status: shipped`, `pr:`,
and `outcome:` filled, and its line moves from **Active** to **Archived** in
the Index below.

### Three lanes

| Lane | Artifacts | Use when |
|------|-----------|----------|
| **Full** | `design.md` + `plan.md` | design judgment; new file/module; public-API change; cross-cutting/multi-file; non-trivial test design |
| **Lightweight** | `change.md` | small-but-real: ≲30 LOC net, ≤2 files, no new file, no public-API change, single straightforward test |
| **Tiny** | none — conventional commit | typo, dep bump, linter/formatter/CI tweak, mechanical rename, single-line config |

Heavier lane wins on ambiguity. A `change.md` that outgrows its lane splits
into `design.md` + `plan.md`.

### Artifacts at a glance

- **`design.md`** — the spec: the *thinking* (why, design, trade-offs, scope).
- **`plan.md`** — the plan: the *sequencing* (the executor's task checklist).
- **`change.md`** — both, condensed, for the lightweight lane.
- **`releases/<semver>.md`** — per-release user-facing notes.
- **`audits/<date>-<slug>.md`** — findings from a code/docs/bug-hunt sweep;
  spawns fix changes.
- **`retros/<date>-<slug>.md`** — what we learned after a body of work.
- **`deferred.md`** — real-but-unscheduled items, each with a revisit trigger.

Templates live in [`_templates/`](_templates/).

### Frontmatter

`design.md` / `change.md`: `status` (draft|approved|shipped|superseded),
`date`, `slug`, `supersedes`, `superseded_by`, `pr`, `outcome`.
`plan.md`: `status`, `date`, `slug`, `spec`, `pr`. Files in `architecture/`
carry **no** frontmatter — living prose, dated by git.

## Index

### Active

_None._

### Archived (shipped)

- **[httpware-max-error-body-bytes](changes/archive/2026-06-16.03-httpware-max-error-body-bytes/design.md)**
  (#26, 2026-06-16) — Cap provider error-body reads at 1 MiB; translate
  `ResponseTooLargeError` to `ProviderAPIError`.
- **[branch-prefix-patch-on-non-merge](changes/archive/2026-06-16.02-branch-prefix-patch-on-non-merge/design.md)**
  (#24, 2026-06-16) — Opt-in `patch_on_non_merge_commit` flag: a non-merge HEAD
  commit bumps patch instead of nothing.
- **[httpware-0.12-get-with-response](changes/archive/2026-06-16.01-httpware-0.12-get-with-response/change.md)**
  (#24, 2026-06-16) — Bump httpware to 0.12.0; adopt `get_with_response` at the
  pagination call sites.
- **[portable-planning-convention](changes/archive/2026-06-13.01-portable-planning-convention/design.md)**
  (#21, 2026-06-13) — Adopt the portable two-axis convention: `architecture/`
  truth home + `changes/` bundles, migrate the 15 spec/plan pairs, fresh Index.
- **[action-yml-dry-run](changes/archive/2026-06-09.03-action-yml-dry-run/design.md)**
  (#16, 2026-06-09) — Composite action `dry-run` input wired to the CLI flag.
- **[dry-run-flag](changes/archive/2026-06-09.02-dry-run-flag/design.md)**
  (#15, 2026-06-09) — `--dry-run` CLI flag: compute the next tag without
  creating it.
- **[mkdocs-github-actions](changes/archive/2026-06-09.01-mkdocs-github-actions/design.md)**
  (#14, 2026-06-09) — Docs hosting via MkDocs + GitHub Actions + Pages.
- **[action-yml-composite-wrapper](changes/archive/2026-06-08.03-action-yml-composite-wrapper/design.md)**
  (#10, 2026-06-08) — `action.yml` composite GitHub Action wrapping the CLI.
- **[github-provider](changes/archive/2026-06-08.02-github-provider/design.md)**
  (#4, 2026-06-08) — GitHub provider alongside GitLab.
- **[httpware-decoder-adoption](changes/archive/2026-06-08.01-httpware-decoder-adoption/design.md)**
  (#3, 2026-06-08) — Adopt the httpware response decoder in the providers.
- **[httpware-migration](changes/archive/2026-06-07.01-httpware-migration/design.md)**
  (#2, 2026-06-07) — Migrate the HTTP client onto httpware.
- **[v0-1-0-release-prep](changes/archive/2026-05-31.08-v0-1-0-release-prep/design.md)**
  (2026-05-31) — Pre-1.0 release preparation.
- **[strategy-no-bump-cleanup](changes/archive/2026-05-31.07-strategy-no-bump-cleanup/design.md)**
  (2026-05-31) — Clean up the strategies' no-bump return path.
- **[cli-overlay-simplification](changes/archive/2026-05-31.06-cli-overlay-simplification/design.md)**
  (2026-05-31) — Replace the CLI-overlay machinery with `model_copy`.
- **[ioc-idiomatic-modern-di-typer](changes/archive/2026-05-31.05-ioc-idiomatic-modern-di-typer/design.md)**
  (2026-05-31) — Idiomatic modern-di + Typer IoC wiring.
- **[usecase-callable](changes/archive/2026-05-31.04-usecase-callable/design.md)**
  (2026-05-31) — Make the use-case a callable.
- **[settings-aliaschoices](changes/archive/2026-05-31.03-settings-aliaschoices/design.md)**
  (2026-05-31) — pydantic-settings `AliasChoices` for env/CLI names.
- **[drop-doctor](changes/archive/2026-05-31.02-drop-doctor/design.md)**
  (2026-05-31) — Remove the `doctor` command.
- **[bmad-to-superpowers-migration-and-httpx2-wrapper](changes/archive/2026-05-31.01-bmad-to-superpowers-migration-and-httpx2-wrapper/design.md)**
  (2026-05-31) — Retire BMad for Superpowers; add the HTTP-client wrapper.

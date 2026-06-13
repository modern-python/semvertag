---
status: shipped
date: 2026-06-13
slug: portable-planning-convention
spec: portable-planning-convention
pr: 21
---

# Portable Planning Convention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt the portable two-axis planning convention in `semvertag` —
seed an `architecture/` truth home, migrate the 15 spec/plan pairs into dated
`planning/changes/` bundles, and copy the byte-identical convention scaffolding
(`README.md` `## Conventions`, `_templates/`, `deferred.md`).

**Architecture:** Pure docs / file-moves. No runtime code, tests, or public API
touched, so there is no TDD loop — each task's "test" is a structural check
(file exists, frontmatter parses, grep sweep clean) plus the standing gates
`just lint-ci`, `just test`, and `mkdocs build --strict`. Existing specs/plans
move via `git mv` (history preserved) and gain only YAML frontmatter.

**Tech Stack:** Markdown, YAML frontmatter, `git mv`, `just`, `mkdocs`.

**Spec:** [`design.md`](./design.md)

**Branch:** `docs/portable-planning-convention` (already created; the spec is
committed there).

**Commit strategy:** Per-task commits.

---

### Task 1: Scaffold the portable convention files

**Files:**
- Create: `planning/_templates/design.md`
- Create: `planning/_templates/plan.md`
- Create: `planning/_templates/change.md`
- Create: `planning/deferred.md`
- Create: `planning/changes/active/.gitkeep`
- Create: `planning/changes/archive/.gitkeep`

These four content files are copied **byte-identical** from `lite-bootstrap`
(the portable convention). Reproduce them exactly.

- [ ] **Step 1: Write `planning/_templates/design.md`**

```markdown
---
status: draft
date: YYYY-MM-DD
slug: my-change
supersedes: null
superseded_by: null
pr: null
outcome: null
---

# Design: One-line capitalized title

## Summary

One paragraph. What changes, at the level a reader needs to decide if this
spec is worth reading in full.

## Motivation

Why now. What is broken or missing. Concrete observations / numbers, not
abstract complaints. Link to memory entries or earlier specs when relevant.

## Non-goals

What is deliberately out of scope and (when nontrivial) why. Each item is
a sentence; one line each.

## Design

### 1. <First piece>

What changes, in enough detail that a reader who has not seen the codebase
can follow. Code samples / diagrams welcome.

### 2. <Second piece>

...

## Operations

Out-of-repo steps (DNS, infra, external account changes). Omit if none.

## Out of scope

Already covered above under Non-goals if appropriate. Repeat-list of
explicitly-excluded follow-ups belongs here when the list is long.

## Testing

How we know it landed correctly. New pytest? Smoke check on live URL?
Lint pass? Be specific.

## Risk

What could go wrong, ranked by likelihood × impact. Mitigations.
```

- [ ] **Step 2: Write `planning/_templates/plan.md`**

```markdown
---
status: draft
date: YYYY-MM-DD
slug: my-change
spec: my-change
pr: null
---

# <slug> — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One sentence — what shipping this plan achieves. No design
rationale; link to the spec for that.

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/my-change` (or `fix/`, `chore/`, etc.)

**Commit strategy:** Per-task commits / single commit / squash on merge.
Whichever fits.

---

### Task 1: <imperative description>

**Files:**
- Modify: `path/to/file.py`
- Create: `path/to/new.py`

One sentence on what this task accomplishes. No deeper reasoning — that's
in the spec.

- [ ] **Step 1: <action>**

  Run / edit / verify command. Expected output.

- [ ] **Step 2: <action>**

  ...

- [ ] **Step 3: Commit**

  ```bash
  git add path/to/file.py
  git commit -m "<type>: <subject>

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: ...
```

- [ ] **Step 3: Write `planning/_templates/change.md`**

```markdown
---
status: draft
date: YYYY-MM-DD
slug: my-change
supersedes: null
superseded_by: null
pr: null
outcome: null
---

# Change: One-line capitalized title

**Lane:** lightweight — ≲30 LOC net, ≤2 files, no new file, no public-API
change, a single straightforward test. If it outgrows this, split into
`design.md` + `plan.md`.

## Goal

One or two sentences: what changes and why.

## Approach

The shape of the change in brief — enough that a reviewer sees the design
without a full spec. Link the truth home (`architecture/<capability>.md`) if a
capability contract moves.

## Files

- `path/to/file.py` — what changes
- `tests/test_x.py` — test added / updated

## Verification

- [ ] Failing test first — command + expected error.
- [ ] Apply the change.
- [ ] Test passes — command.
- [ ] `just test` — full suite green.
- [ ] `just lint` — clean.
```

- [ ] **Step 4: Write `planning/deferred.md`**

```markdown
# Deferred Work

Items raised in reviews or audits that are real but not actionable now.
Each is parked here with the reason it's deferred and the concrete trigger
that should bring it back. This is the long-tail register — not a backlog
of planned work. When an item is picked up it graduates to a spec/plan
bundle in [`changes/active/`](changes/active/); see [CLAUDE.md](../CLAUDE.md#workflow).

## Open

_None._
```

- [ ] **Step 5: Create the `changes/` directory keepers**

```bash
mkdir -p planning/changes/active planning/changes/archive
touch planning/changes/active/.gitkeep planning/changes/archive/.gitkeep
```

- [ ] **Step 6: Verify the templates are byte-identical to lite-bootstrap**

```bash
for f in design plan change; do
  diff <(gh api "repos/modern-python/lite-bootstrap/contents/planning/_templates/$f.md?ref=main" --jq '.content' | base64 -d) \
       planning/_templates/$f.md && echo "$f.md: identical"
done
diff <(gh api "repos/modern-python/lite-bootstrap/contents/planning/deferred.md?ref=main" --jq '.content' | base64 -d) \
     planning/deferred.md && echo "deferred.md: identical"
```
Expected: four `identical` lines, no diff output.

- [ ] **Step 7: Commit**

```bash
git add planning/_templates planning/deferred.md planning/changes/active/.gitkeep planning/changes/archive/.gitkeep
git commit -m "docs(planning): add portable templates, deferred register, changes/ skeleton

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Fix the `.gitignore` trap and add the `docs-build` gate

**Files:**
- Modify: `.gitignore`
- Modify: `Justfile`

The bare `plan.md` rule in `.gitignore` would silently exclude every bundle's
`plan.md`. Remove it. Add a strict local docs build recipe mirroring CI.

- [ ] **Step 1: Remove the `plan.md` line from `.gitignore`**

Delete the line containing exactly `plan.md` (between `.python-version`/`.venv`
and `/site/`). Leave every other line untouched.

- [ ] **Step 2: Verify no bundle plan.md is ignored**

```bash
git check-ignore planning/changes/active/2026-06-13.01-portable-planning-convention/plan.md; echo "exit=$?"
```
Expected: no output, `exit=1` (not ignored).

- [ ] **Step 3: Add the `docs-build` recipe to `Justfile`**

Insert this recipe immediately before the existing `docs-deploy` recipe:

```makefile
# Strict local docs build (no deploy). Mirrors CI's link/strict checks.
docs-build:
    uvx --with-requirements docs/requirements.txt mkdocs build --strict
```

- [ ] **Step 4: Verify the recipe runs**

```bash
just docs-build
```
Expected: `mkdocs build --strict` exits 0 (site builds, no warnings-as-errors).

- [ ] **Step 5: Commit**

```bash
git add .gitignore Justfile
git commit -m "chore: untrack bundle plan.md and add docs-build gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Migrate the 15 spec/plan pairs into archived bundles

**Files (per pair):**
- Move: `planning/specs/<date>-<slug>-design.md` → `planning/changes/archive/<date>.NN-<slug>/design.md`
- Move: `planning/plans/<date>-<slug>.md` → `planning/changes/archive/<date>.NN-<slug>/plan.md`
- Delete: `planning/specs/.gitkeep`, `planning/plans/.gitkeep` (after dirs are empty)

This is the bundle table. `.NN` is the git first-commit order. `pr` stays
`null`; the PR reference (where one exists) goes in `outcome` per the
lite-bootstrap house style. The eight `2026-05-31` items predate PR numbering
(direct pre-1.0 merges), so they carry a factual bootstrap note.

| Bundle dir (`<date>.NN-<slug>`) | Source slug (`<date>-<slug>`) | `outcome` value |
|---|---|---|
| `2026-05-31.01-bmad-to-superpowers-migration-and-httpx2-wrapper` | `2026-05-31-bmad-to-superpowers-migration-and-httpx2-wrapper` | shipped in the pre-1.0 bootstrap (retired BMad; added the httpx HTTP-client wrapper) |
| `2026-05-31.02-drop-doctor` | `2026-05-31-drop-doctor` | shipped in the pre-1.0 bootstrap (removed the doctor command) |
| `2026-05-31.03-settings-aliaschoices` | `2026-05-31-settings-aliaschoices` | shipped in the pre-1.0 bootstrap (pydantic-settings AliasChoices) |
| `2026-05-31.04-usecase-callable` | `2026-05-31-usecase-callable` | shipped in the pre-1.0 bootstrap (callable use-case) |
| `2026-05-31.05-ioc-idiomatic-modern-di-typer` | `2026-05-31-ioc-idiomatic-modern-di-typer` | shipped in the pre-1.0 bootstrap (modern-di + Typer IoC) |
| `2026-05-31.06-cli-overlay-simplification` | `2026-05-31-cli-overlay-simplification` | shipped in the pre-1.0 bootstrap (model_copy CLI overlay) |
| `2026-05-31.07-strategy-no-bump-cleanup` | `2026-05-31-strategy-no-bump-cleanup` | shipped in the pre-1.0 bootstrap (no-bump return path) |
| `2026-05-31.08-v0-1-0-release-prep` | `2026-05-31-v0-1-0-release-prep` | shipped in the pre-1.0 bootstrap (0.1.0 release prep) |
| `2026-06-07.01-httpware-migration` | `2026-06-07-httpware-migration` | shipped (#2) |
| `2026-06-08.01-httpware-decoder-adoption` | `2026-06-08-httpware-decoder-adoption` | shipped (#3) |
| `2026-06-08.02-github-provider` | `2026-06-08-github-provider` | shipped (#4) |
| `2026-06-08.03-action-yml-composite-wrapper` | `2026-06-08-action-yml-composite-wrapper` | shipped (#10) |
| `2026-06-09.01-mkdocs-github-actions` | `2026-06-09-mkdocs-github-actions` | shipped (#14) |
| `2026-06-09.02-dry-run-flag` | `2026-06-09-dry-run-flag` | shipped (#15) |
| `2026-06-09.03-action-yml-dry-run` | `2026-06-09-action-yml-dry-run` | shipped (#16) |

- [ ] **Step 1: `git mv` every pair into its bundle folder**

For each row, derive `<date>` and `<slug>` from the bundle dir, then:

```bash
mkdir -p "planning/changes/archive/<date>.NN-<slug>"
git mv "planning/specs/<date>-<slug>-design.md" "planning/changes/archive/<date>.NN-<slug>/design.md"
git mv "planning/plans/<date>-<slug>.md"        "planning/changes/archive/<date>.NN-<slug>/plan.md"
```

Concretely, the 30 moves are (note `2026-05-31.01`'s plan keeps its full
descriptive source name):

```bash
B=planning/changes/archive
S=planning/specs
P=planning/plans
for row in \
  "2026-05-31.01-bmad-to-superpowers-migration-and-httpx2-wrapper|2026-05-31-bmad-to-superpowers-migration-and-httpx2-wrapper" \
  "2026-05-31.02-drop-doctor|2026-05-31-drop-doctor" \
  "2026-05-31.03-settings-aliaschoices|2026-05-31-settings-aliaschoices" \
  "2026-05-31.04-usecase-callable|2026-05-31-usecase-callable" \
  "2026-05-31.05-ioc-idiomatic-modern-di-typer|2026-05-31-ioc-idiomatic-modern-di-typer" \
  "2026-05-31.06-cli-overlay-simplification|2026-05-31-cli-overlay-simplification" \
  "2026-05-31.07-strategy-no-bump-cleanup|2026-05-31-strategy-no-bump-cleanup" \
  "2026-05-31.08-v0-1-0-release-prep|2026-05-31-v0-1-0-release-prep" \
  "2026-06-07.01-httpware-migration|2026-06-07-httpware-migration" \
  "2026-06-08.01-httpware-decoder-adoption|2026-06-08-httpware-decoder-adoption" \
  "2026-06-08.02-github-provider|2026-06-08-github-provider" \
  "2026-06-08.03-action-yml-composite-wrapper|2026-06-08-action-yml-composite-wrapper" \
  "2026-06-09.01-mkdocs-github-actions|2026-06-09-mkdocs-github-actions" \
  "2026-06-09.02-dry-run-flag|2026-06-09-dry-run-flag" \
  "2026-06-09.03-action-yml-dry-run|2026-06-09-action-yml-dry-run" \
; do
  dir="${row%%|*}"; src="${row##*|}"
  mkdir -p "$B/$dir"
  git mv "$S/$src-design.md" "$B/$dir/design.md"
  git mv "$P/$src.md"        "$B/$dir/plan.md"
done
```

- [ ] **Step 2: Verify all 15 source pairs moved and dirs are empty**

```bash
ls planning/specs planning/plans   # expect only .gitkeep in each
find planning/changes/archive -name design.md | wc -l   # expect 15
find planning/changes/archive -name plan.md   | wc -l   # expect 15
```

- [ ] **Step 3: Prepend frontmatter to each `design.md`**

For every bundle, insert this block at the very top of `design.md`, filling
`date`, `slug`, and `outcome` from the table above (slug = the bundle slug
without the `<date>.NN-` prefix):

```yaml
---
status: shipped
date: <date>
slug: <slug>
supersedes: null
superseded_by: null
pr: null
outcome: <outcome from table>
---

```

The existing `# Title` / `**Date:**` / `**Status:**` body stays unchanged below
the block. None of the `outcome` values has a space-preceded `#`, so none needs
quoting.

- [ ] **Step 4: Prepend frontmatter to each `plan.md`**

For every bundle, insert this block at the very top of `plan.md`:

```yaml
---
status: shipped
date: <date>
slug: <slug>
spec: <slug>
pr: null
---

```

- [ ] **Step 5: Verify frontmatter parses as YAML on all 30 files**

```bash
python3 - <<'PY'
import pathlib, yaml, sys
bad = 0
for f in pathlib.Path("planning/changes/archive").rglob("*.md"):
    text = f.read_text()
    if not text.startswith("---\n"):
        print("NO FRONTMATTER:", f); bad += 1; continue
    fm = text.split("---\n", 2)[1]
    try:
        d = yaml.safe_load(fm)
        assert d["status"] == "shipped" and d["slug"] and d["date"]
    except Exception as e:
        print("BAD:", f, e); bad += 1
print("checked", len(list(pathlib.Path('planning/changes/archive').rglob('*.md'))), "files, bad =", bad)
sys.exit(1 if bad else 0)
PY
```
Expected: `bad = 0`, exit 0.

- [ ] **Step 6: Verify `git mv` preserved history on a sample file**

```bash
git log --follow --oneline -- planning/changes/archive/2026-06-08.02-github-provider/design.md | tail -1
```
Expected: a commit predating this branch (history followed through the rename).

- [ ] **Step 7: Remove the now-empty source dirs**

```bash
git rm planning/specs/.gitkeep planning/plans/.gitkeep
rmdir planning/specs planning/plans 2>/dev/null || true
```

- [ ] **Step 8: Commit**

```bash
git add -A planning/changes planning/specs planning/plans
git commit -m "docs(planning): migrate 15 spec/plan pairs into archived change bundles

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Write `planning/README.md`

**Files:**
- Create: `planning/README.md`

The `## Conventions` block is byte-identical to lite-bootstrap; the `## Index`
is semvertag-specific.

- [ ] **Step 1: Write the file**

```markdown
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

- **[portable-planning-convention](changes/active/2026-06-13.01-portable-planning-convention/design.md)**
  (2026-06-13) — Adopt the portable two-axis convention: `architecture/` truth
  home + `changes/` bundles, migrate the 15 spec/plan pairs, fresh Index.

### Archived (shipped)

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
```

- [ ] **Step 2: Verify the Conventions block is byte-identical to lite-bootstrap**

```bash
diff <(gh api "repos/modern-python/lite-bootstrap/contents/planning/README.md?ref=main" --jq '.content' | base64 -d | sed -n '/^## Conventions$/,/^## Index$/p' | sed '$d') \
     <(sed -n '/^## Conventions$/,/^## Index$/p' planning/README.md | sed '$d') \
  && echo "Conventions block: identical"
```
Expected: `Conventions block: identical`, no diff output.

- [ ] **Step 3: Verify every Index link resolves**

```bash
grep -oE '\(changes/[^)]+\)' planning/README.md | tr -d '()' | while read p; do
  test -f "planning/$p" || echo "BROKEN: $p"
done; echo "link check done"
```
Expected: only `link check done` (no `BROKEN` lines).

- [ ] **Step 4: Commit**

```bash
git add planning/README.md
git commit -m "docs(planning): add README with portable conventions and index

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Seed `architecture/` with three capability files

**Files:**
- Create: `architecture/strategies.md`
- Create: `architecture/providers.md`
- Create: `architecture/cli.md`

Each file is **living prose, no frontmatter** (dated by git). Write it by
**reading the listed source files first**, then stating the invariants below as
dense, factual prose — match the tone of lite-bootstrap's `architecture/*.md`
(present-tense, names the symbols and files, states the *why* of each
invariant). Do not copy code; describe contracts. Every bullet below is a fact
the file must capture; expand each into prose, correcting any detail the source
contradicts.

- [ ] **Step 1: Write `architecture/strategies.md`**

Read first: `semvertag/strategies/_base.py`, `semvertag/strategies/branch_prefix.py`,
`semvertag/strategies/conventional_commits.py`, `semvertag/strategies/__init__.py`,
`semvertag/_commit_parse.py`.

Capture, with a `# Strategies` H1 and one section per topic:

- **What a strategy is.** A strategy decides the next semver tag from the
  current tags plus repository signal (branch name or commit messages). The
  base contract lives in `strategies/_base.py`; name the base type and the
  method(s) every strategy implements and what they receive/return.
- **`branch-prefix`** (`branch_prefix.py`) — maps a branch-name prefix to a
  bump level; state the default prefix→level mapping and that it recognizes a
  GitHub PR merge-commit subject under the defaults (the `#7` fix). Note the
  configured-prefix source.
- **`conventional-commits`** (`conventional_commits.py`) — derives the bump
  from Conventional Commits parsed by `_commit_parse.py`; state the
  type→level mapping (`feat`→minor, `fix`→patch, breaking→major) and how a
  commit range is scanned.
- **No-bump path** — when no signal warrants a bump the strategy yields a
  no-bump result rather than a forced increment (the `strategy-no-bump-cleanup`
  change). State exactly what is returned and how callers detect it.
- **`_commit_parse.py`** — the single place commit subjects/bodies are parsed;
  note what it extracts (type, scope, breaking marker).

- [ ] **Step 2: Write `architecture/providers.md`**

Read first: `semvertag/providers/_base.py`, `semvertag/providers/gitlab.py`,
`semvertag/providers/github.py`, `semvertag/providers/_errors.py`,
`semvertag/_link_pagination.py`, `semvertag/_redact.py`, `semvertag/_errors.py`.

Capture, with a `# Providers` H1 and one section per topic:

- **What a provider is.** A provider is the API adapter for one forge; the base
  contract is `providers/_base.py`. Name the abstract operations (list tags,
  read commits/branch, create tag) and their signatures.
- **GitLab** (`gitlab.py`) and **GitHub** (`github.py`) — one section each:
  the endpoints used, how tags are created, and any auth/header handling.
- **HTTP client (httpware).** Requests go through the httpware-based client
  (the `httpware-migration` + `httpware-decoder-adoption` changes); state how
  the client is constructed and that responses are decoded via the httpware
  decoder.
- **Link-header pagination** (`_link_pagination.py`) — how `Link` headers are
  followed to page through tags/commits; name the function and where providers
  call it.
- **Secret redaction** (`_redact.py`) — tokens are redacted from errors/log
  output; state what is redacted and where it is applied.
- **Errors** (`providers/_errors.py`, `_errors.py`) — the provider error types
  and what maps to them (auth failure, not-found, rate-limit, etc.).

- [ ] **Step 3: Write `architecture/cli.md`**

Read first: `semvertag/__main__.py`, `semvertag/ioc.py`, `semvertag/_settings.py`,
`semvertag/_use_case.py`, `semvertag/_output.py`, `semvertag/_types.py`,
`action.yml`, `templates/semvertag.yml`.

Capture, with a `# CLI` H1 and one section per topic:

- **Entry point** (`__main__.py`) — the Typer app, the command(s) it exposes,
  and the `--dry-run` flag (compute the next tag without creating it; the
  `dry-run-flag` change). State what `--dry-run` short-circuits.
- **IoC wiring** (`ioc.py`) — the modern-di container; what it provides
  (settings, provider, strategy, use-case) and how the CLI resolves the
  use-case (the `ioc-idiomatic-modern-di-typer` change). Note the eager-DI
  None-field guard if present.
- **Settings** (`_settings.py`) — pydantic-settings model; env + CLI sources,
  `AliasChoices` for alternate names (the `settings-aliaschoices` change), and
  the `apply_cli_overlay` overlay built on `model_copy(update=...)` (the
  `cli-overlay-simplification` change). State precedence (CLI over env over
  default).
- **Use-case** (`_use_case.py`) — the callable that wires provider + strategy
  to produce/create the tag (the `usecase-callable` change); state its inputs
  and return.
- **Output** (`_output.py`) — how results are rendered (human vs machine
  output, if both).
- **Distribution wrappers** — `action.yml` is the composite GitHub Action
  wrapping the CLI (the `action-yml-composite-wrapper` + `action-yml-dry-run`
  changes); `templates/semvertag.yml` is the GitLab CI component. State that
  both shell out to the same CLI and pass `--dry-run` through.

- [ ] **Step 4: Verify the files exist, are non-empty, and carry no frontmatter**

```bash
for f in strategies providers cli; do
  test -s "architecture/$f.md" || echo "MISSING/EMPTY: $f.md"
  head -1 "architecture/$f.md" | grep -q '^---$' && echo "HAS FRONTMATTER (remove): $f.md"
done; echo "architecture check done"
```
Expected: only `architecture check done`.

- [ ] **Step 5: Verify `mkdocs build --strict` still passes (architecture/ is outside docs_dir)**

```bash
just docs-build
```
Expected: exit 0; the published site is unchanged.

- [ ] **Step 6: Commit**

```bash
git add architecture
git commit -m "docs(architecture): seed strategies, providers, and cli truth files

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Rewrite the `CLAUDE.md` Workflow section

**Files:**
- Modify: `CLAUDE.md`

Replace the current `## Workflow` section (the Superpowers/brainstorm→plan→TDD
list that points at `planning/specs/` + `planning/plans/`) with the
bundle-convention text below. Leave `## Commit messages`, `## Reference
directories`, and `## What the codebase ships` untouched.

- [ ] **Step 1: Replace the `## Workflow` section body**

Use this text (between the `## Workflow` heading and the next `##` heading):

```markdown
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
```

- [ ] **Step 2: Verify no stale references remain**

```bash
grep -rn 'planning/specs\|planning/plans' CLAUDE.md README.md mkdocs.yml docs/ 2>/dev/null && echo "STALE FOUND" || echo "no stale references"
```
Expected: `no stale references`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: rewrite CLAUDE.md workflow for the two-axis convention

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Final verification sweep

**Files:** none (verification only).

- [ ] **Step 1: Repo-wide stale-pointer sweep**

```bash
grep -rn 'planning/specs\|planning/plans' . --include='*.md' --include='*.yml' --include='*.toml' \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=_archive --exclude-dir=_autosemver_reference \
  && echo "STALE FOUND" || echo "no stale references"
```
Expected: `no stale references`. (The `_archive/` and `_autosemver_reference/`
trees are excluded — do not edit them.)

- [ ] **Step 2: Lint**

```bash
just lint-ci
```
Expected: eof-fixer, ruff format check, ruff check, ty — all clean.

- [ ] **Step 3: Tests**

```bash
just test
```
Expected: full suite passes, coverage unchanged from `main` (no runtime code
touched).

- [ ] **Step 4: Docs build**

```bash
just docs-build
```
Expected: `mkdocs build --strict` exits 0.

- [ ] **Step 5: Confirm final tree shape**

```bash
test ! -d planning/specs && test ! -d planning/plans && echo "old dirs gone"
find architecture -name '*.md' | wc -l        # expect 3
find planning/changes/archive -name design.md | wc -l   # expect 15
ls planning/changes/active                    # expect the convention bundle + .gitkeep
```
Expected: `old dirs gone`, `3`, `15`, and the active bundle present.

---

## On merge

Move `planning/changes/active/2026-06-13.01-portable-planning-convention/` →
`planning/changes/archive/`, fill its `design.md` frontmatter (`status:
shipped`, `pr:` = this PR's number, `outcome:`) and `plan.md` (`status:
shipped`, `pr:`), and shift its README Index line from **Active** to
**Archived**. No `architecture/` promotion — this change defines the
convention, not a library capability.

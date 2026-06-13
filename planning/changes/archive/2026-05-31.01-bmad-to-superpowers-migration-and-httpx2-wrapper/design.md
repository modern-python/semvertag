---
status: shipped
date: 2026-05-31
slug: bmad-to-superpowers-migration-and-httpx2-wrapper
supersedes: null
superseded_by: null
pr: null
outcome: shipped in the pre-1.0 bootstrap (retired BMad; added the httpx HTTP-client wrapper)
---

# BMad → Superpowers migration + httpx2 wrapper pilot

**Date:** 2026-05-31
**Status:** Approved, ready for plan
**Author:** brainstorm session (Superpowers `brainstorming` skill)

## Context

semvertag is mid-Epic 4 (4/8 stories done; 4.4–4.8 in backlog) under the BMad
workflow. BMad has produced 14 dense story files (60–90 KB each), a PRD, an
architecture document, three retrospectives, and a `sprint-status.yaml` tracker
inside `_bmad/`.

Two pains drive the switch:

1. **Process is too slow.** The contextualise → implement → code-review loop
   per story carries too much ceremony for the remaining work.
2. **Resulting code feels overengineered and complex.** Concrete example: every
   method in `semvertag/providers/gitlab.py` repeats a 6-step defensive dance
   (build URL, catch `RequestError`, translate status, catch `DecodingError`,
   validate shape, extract with `KeyError` handling). A base wrapper around
   `httpx2` would erase most of it.

This spec covers two bundled sub-projects:

- **Migration mechanics:** hard cutover from BMad to Superpowers.
- **httpx2 wrapper pilot:** first real piece of work executed under the new
  flow — small enough to learn the rhythm, directly addresses one
  overengineering complaint.

A broader simplification pass on the rest of the codebase (`_settings.py`,
`ioc.py`, `doctor/`, `_use_case.py`) is **deferred to a follow-up brainstorm**
once the wrapper has validated the new workflow.

## Decisions

| Question | Decision |
| --- | --- |
| Disposition of BMad workspace | Hard cutover, archive everything |
| Scope of this spec | Migration mechanics + httpx2 wrapper pilot bundled |
| Superpowers stack depth | Full stack from day one (TDD, worktrees, code-review subagents, verification gates) |
| Remaining 4.4–4.8 backlog | Dropped. Re-decide each item fresh later, individually, only if still needed |
| GitHub provider as part of wrapper work | No. YAGNI. Wrapper is justified by what it deletes today in `gitlab.py` |

## Section 1 — Workspace cutover

### File moves

- `_bmad/` → `_archive/bmad/` (via `git mv`). Joins `_autosemver_reference/`
  as a read-only sibling. Nothing inside is deleted.
- No retro extraction, no PRD distillation, no "what we still believe" summary.
  If past decisions are needed, open the archive.
- `.claude/settings.local.json` stays untouched.

### New directories

```
planning/specs/   — brainstorm outputs (one per piece of work)
planning/plans/   — writing-plans outputs (one per spec)
```

`specs/` is created as part of writing this spec (it lives there). `plans/` is
created at the same time and remains empty until the writing-plans step runs;
it gets a `.gitkeep` so the empty dir tracks in git.

### `CLAUDE.md` (new, repo-root)

There is no repo-level `CLAUDE.md` today (only the user-global one). Add one,
30–50 lines, covering:

- Workflow is Superpowers: brainstorm → writing-plans → executing-plans (or
  subagent-driven-development), with TDD by default, worktrees for feature
  isolation, code-review subagents, verification-before-completion gates.
- Spec/plan locations: `planning/specs/` and `planning/plans/`.
- `_archive/bmad/` is reference-only — historical decisions, do not edit, do
  not extend.
- `_autosemver_reference/` is behavioral reference only (existing convention).
- Commit-message convention: imperative present-tense scoped messages
  (`providers: add HttpClient base`). No more `land story X.Y …` or
  `contextualise story X.Y` prefixes.
- Test stack and lint commands (mirror what `Justfile` already documents).

### Artefacts with no replacement in the new workflow

These move to `_archive/bmad/` with everything else (nothing is deleted), but
nothing in the Superpowers flow takes their place:

- `_bmad/sprint-status.yaml` — Superpowers uses in-session `TaskList` plus git
  log between sessions. No standing tracker file.
- `implementation-readiness-report-*.md`, `prd-validation-report.md`,
  `deferred-work.md` — ceremony artefacts.

### Verification gate before Phase 2

`just lint-ci`, `uv run pytest`, `mkdocs build --strict` all green. None should
care about doc moves, but verify rather than assume.

## Section 2 — httpx2 wrapper design

### Goal

Erase the 6-step defensive dance from every method in `gitlab.py` so call
sites read like "GET this path → here's a typed object", with status / JSON
/ shape errors handled once in one place. The wrapper takes a Pydantic
schema per call and returns a validated, typed instance; raw dict/list
handling and `KeyError`/`TypeError` field-extraction guards disappear from
provider code.

Pydantic is already a transitive dependency via `pydantic-settings`; no new
package required.

### Shape — composition, not inheritance

Today `GitLabProvider` is a frozen dataclass holding `client: httpx2.Client`.
Replace that field with `http: HttpClient`, where `HttpClient` is a small
class wrapping `httpx2.Client` plus two injected callables: one for
auth-header construction, one for status-code translation. Both are provider-
specific; the wrapper itself stays generic.

The provider stays a flat dataclass with no base class. Reasons:

- No MRO surprises.
- DI wiring (`semvertag/ioc.py`) stays one-shot.
- A future GitHub provider just composes the same `HttpClient` with a
  different auth callable.

### `HttpClient` API (approximate)

```python
T = TypeVar("T", bound=pydantic.BaseModel)

class HttpClient:
    client: httpx2.Client
    auth_headers: Callable[[], dict[str, str]]
    status_translator: Callable[[int], None]  # raises typed errors; no-op on success

    def request(self, method: str, url: str, *, schema: type[T], **kwargs) -> T: ...
    def request_many(self, method: str, url: str, *, schema: type[T], **kwargs) -> list[T]: ...
    def request_raw(self, method: str, url: str, **kwargs) -> httpx2.Response: ...
```

Final API surface is decided at planning time; treat this as illustrative.

- `request` runs the request with auth headers, catches `httpx2.RequestError`
  → `ProviderAPIError`, calls `status_translator`, decodes JSON, validates
  via `schema.model_validate(payload)`, returns the typed instance. Pydantic
  validation errors → `ProviderAPIError` with the field-level message
  preserved.
- `request_many` is the same but expects a JSON list and returns
  `list[T]` (used by `list_tags`). Separated from `request` because Python
  generics make `schema=list[Model]` clunky to type-check; an explicit method
  is clearer than overloading on the schema parameter.
- `request_raw` is an escape hatch for `create_tag` (needs raw status for the
  "already exists" 400 branch) and `list_tags` pagination (needs the `Link`
  header). It applies auth headers and translates `RequestError` →
  `ProviderAPIError`, but does **not** call `status_translator` and does
  **not** decode the body — the caller takes responsibility for both
  (typically by invoking the module-level translator explicitly after their
  special-case branch).
- `status_translator` is injected at construction — `_translate_status` keeps
  living at module level in `gitlab.py`. The wrapper never knows GitLab's
  specific error messages.
- Status translation runs **before** body decoding, so a 401 raises `AuthError`
  rather than trying to validate the error-body shape against the success
  schema.

### Schemas

Per-endpoint Pydantic models live near the methods that use them, in
`gitlab.py` itself (private, leading-underscore names like `_ProjectResponse`,
`_TagItem`, `_CommitItem`). They are not shared across providers — they
describe GitLab's response shapes, not domain concepts. Domain types
(`Tag`, `Commit`, `CheckResult` in `semvertag/_types.py`) stay unchanged;
the provider translates from response schema to domain type at the boundary.

Use Pydantic's `extra="ignore"` (the default) — GitLab adds fields we don't
care about and we shouldn't break on them. Use `extra="forbid"` only if a
specific endpoint's stability matters more than forward-compatibility (none
do today).

### What stays in `providers/gitlab.py`

- URL building (`_url`).
- `_translate_status` and all GitLab-specific error messages.
- The four `check_*` methods (provider-semantic).
- Pagination helpers (`_next_page_url`, `_same_origin`, `_LINK_ENTRY_RE`).
- The `create_tag` "already exists" 400 branch (uses `request_raw`).

### Explicit non-goals

- **No retry logic in the wrapper** — `RetryingTransport` already handles
  retries one level below.
- **No redaction logic in the wrapper** — `_redact.py` handles that at output
  time.
- **No async surface** — semvertag is sync. Adding async is hypothetical.
- **No `ProviderBase` abstract class.** The `Provider` Protocol stays the
  only shared shape.
- **No GitHub provider built preemptively.** Wrapper is built for GitLab.
  GitHub validates the design later when actually needed.

### Expected delta

- `gitlab.py`: ~380 LOC → ~180 LOC estimated (schemas + their definitions
  add some LOC, but the elimination of both the shape-validation layer AND
  the field-extraction layer wins back more). Not a hard gate.
- Tests stay structurally similar; per-method tests get shorter because
  malformed-JSON, `RequestError`, missing-field, and wrong-field-type cases
  all live in one shared `HttpClient` test file. The per-method tests focus
  on URL construction, schema choice, and domain translation.
- `ioc.py`: one new node for `HttpClient`, GitLab group field renames
  `client` → `http`.

## Section 3 — Execution sequencing

### Phase 1 — Migration scaffolding

Direct-to-`main`, no worktree, no PR. Mechanical, low-risk, not subject to TDD.

1. `chore: archive _bmad/ as reference` — `git mv _bmad _archive/bmad`.
2. `chore: track empty planning/plans/` — `plans/` was created during
   this brainstorm but is empty; add a `.gitkeep` so it tracks. (`specs/`
   already tracks because this spec lives in it.)
3. `docs: add project CLAUDE.md` — the 30–50 line file described in Section 1.

**Gate:** `just lint-ci`, `uv run pytest`, `mkdocs build --strict` all green.

### Phase 2 — Wrapper pilot

Spawn a worktree (`using-git-worktrees` skill). Inside the worktree:

1. **`HttpClient` red → green, alone.** Write
   `tests/test_providers/test_http_client.py` covering:
   - `request`: happy path returns validated schema instance.
   - `request_many`: happy path returns `list[schema]`.
   - `request`: `RequestError` → `ProviderAPIError`.
   - `request`: malformed JSON → `ProviderAPIError`.
   - `request`: payload is a list when schema is single → `ProviderAPIError`.
   - `request`: missing required field → `ProviderAPIError` carrying the
     pydantic field path in the message.
   - `request`: wrong field type (e.g. int where str expected) →
     `ProviderAPIError`.
   - `request_many`: payload is a dict when list expected →
     `ProviderAPIError`.
   - `status_translator` hook fires before JSON decode + schema validation
     (so a 401 raises `AuthError` rather than trying to validate the error
     body against the success schema).
   - Auth-header callable is invoked per request and the result merged into
     request headers.
   - `request_raw` returns the `httpx2.Response` with auth headers applied
     and `RequestError` translated, but without `status_translator` or body
     decoding (caller takes responsibility for those).

   Build `HttpClient` minimally to make each test green. Commit when the new
   file is self-contained.

2. **Refactor `GitLabProvider` method-by-method.** For each of
   `get_default_branch`, `get_latest_commit_on_default_branch`, `list_tags`,
   `create_tag`, and the four `check_*` methods: rewrite the body to use
   `HttpClient`. Run `uv run pytest tests/test_providers/test_gitlab.py` —
   existing tests stay green (the parity guarantee, no test changes needed).
   Commit per-method or in 2–3 logical batches.

3. **DI wiring** (`semvertag/ioc.py`) — add an `HttpClient` provider node,
   wire it into the GitLab group, drop the raw `client` field from
   `GitLabProvider`. Single commit.

4. **Cleanup** — delete dead helpers (e.g. `_safe_get` if no longer needed),
   trim `_translate_status` if call sites changed.

5. **Pre-review verification gate** (`verification-before-completion` skill):
   - `just lint-ci`
   - `uv run pytest`
   - branch coverage at 100% on `providers/` (existing standard)
   - `mkdocs build --strict`

   No "all tests pass" claims without showing the command output.

6. **Code review** — invoke `requesting-code-review` skill to spawn a review
   subagent against the worktree branch. Address findings via
   `receiving-code-review` (which forces verification rather than blind
   acceptance).

7. **Land** — `finishing-a-development-branch` skill to merge back to `main`.
   PR or fast-forward, developer's call.

## Success criteria

This spec is "done" when **all** of the following hold:

- `_bmad/` is gone from the working tree (lives at `_archive/bmad/`).
- `planning/specs/` contains this spec and the implementation plan
  derived from it.
- Repo-root `CLAUDE.md` exists and points at the Superpowers flow.
- `HttpClient` exists in `semvertag/providers/` (or chosen location) and is
  used by every method in `gitlab.py`.
- All existing tests still pass; no behavioral changes to the GitLab provider.
- `gitlab.py` is meaningfully shorter (target ~40–50% LOC reduction; soft
  signal — if the wrapper doesn't shrink it, the wrapper isn't pulling
  weight).
- Branch coverage on `providers/` remains at 100%.

## Out of scope

Deferred to separate later brainstorms:

- Simplification pass on `_settings.py`, `ioc.py`, `doctor/`, `_use_case.py`,
  and other "overengineered code" complaints.
- Any of the dropped Epic 4 backlog items (4.4 mkdocs site content, 4.5
  migration guides, 4.6 trust-surface markdown, 4.7 README hero + issue
  templates, 4.8 shadow-mode parity validation). Each gets re-decided
  individually, only if still needed.
- GitHub provider implementation.
- Async support.
- Migration of CI workflow conventions (Justfile, GitHub Actions) to anything
  Superpowers-specific — they stay as-is.

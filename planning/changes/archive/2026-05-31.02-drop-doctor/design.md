---
status: shipped
date: 2026-05-31
slug: drop-doctor
supersedes: null
superseded_by: null
pr: null
outcome: shipped in the pre-1.0 bootstrap (removed the doctor command)
---

# Drop `semvertag doctor` subcommand

**Date:** 2026-05-31
**Status:** Approved, ready for plan
**Author:** brainstorm session (Superpowers `brainstorming` skill)

## Context

semvertag's `doctor` subcommand is a pre-flight diagnostic: it runs four
checks against the configured provider (`check_token`, `check_scopes`,
`check_project_access`, `check_protected_tags`) and exits with a category-
specific code (auth / config / provider / generic). It was the entire
output of BMad Epic 3.

The subsystem is overengineered for the value it provides:

- **~400 LOC of source** plus ~38 KB of tests across `semvertag/doctor/`,
  the `check_*` methods in `gitlab.py`, the `_doctor_command` in
  `__main__.py`, and the `_provenance` tracking in `_settings.py`.
- **String-fragment matching** in `doctor/_checks.py` to pick an exit code
  from `result.cause`, with an explicit comment that the fragments "shadow
  GitLabProvider's cause vocabulary; update in lockstep when wording
  changes there." Brittle.
- **Pads the `Provider` Protocol** — every future provider (GitHub,
  Bitbucket) must implement four `check_*` methods.
- The four diagnostics duplicate what the main command's error paths
  already report. The main command's `_translate_status` already raises
  the right typed errors (`AuthError`/`ConfigError`/`ProviderAPIError`)
  with the same exit codes for the same failure modes.

The pattern of bundling a `doctor` command into a focused CLI is rare —
`kubectl`, `git`, `aws`, `gh` don't have one. It's more common in
framework CLIs with many config sources (Flutter, Homebrew, Hugo).
For an auto-tagger with two strategies and one provider implemented,
the cost is well above the value.

This spec removes the `doctor` subsystem entirely. Pre-1.0 (no public
release yet), so no users to break.

## Decisions

| Question | Decision |
| --- | --- |
| Keep `doctor`? | No — remove entirely |
| Remove `check_*` from `Provider` Protocol? | Yes |
| Remove `_provenance` from `Settings`? | Yes — only consumer was doctor's render |
| Improve main command error paths to compensate? | No code changes needed; main command already produces equivalent typed errors with the same exit codes |
| Migration / deprecation path? | None — pre-1.0, drop directly |

## What gets deleted

### Source files (entire deletion)

- `semvertag/doctor/__init__.py`
- `semvertag/doctor/_checks.py`
- `semvertag/doctor/_render.py`

### Test files (entire deletion)

- `tests/unit/test_doctor_checks.py`
- `tests/unit/test_doctor_render.py`
- `tests/unit/test_provenance.py` (only consumer of `_provenance`)
- `tests/integration/test_cli_doctor.py`

### Source files (surgical removal)

**`semvertag/providers/_base.py`** — drop the four `check_*` lines from the
`Provider` Protocol. Resulting Protocol has 5 members: `name`,
`get_default_branch`, `get_latest_commit_on_default_branch`, `list_tags`,
`create_tag`.

**`semvertag/providers/gitlab.py`** — drop:
- The four `check_*` methods
- `_safe_get` (sole consumer was `check_*`)
- `_evaluate_scopes_payload` (sole consumer was `check_scopes`)
- Module-level constants that become unused: likely `_USER_PATH`,
  `_TOKEN_INTROSPECTION_PATH`, `_API_SCOPE` (verify with `ruff check`
  after deletion, do not pre-judge)

**`semvertag/_settings.py`** — drop:
- The `_provenance` `PrivateAttr` field
- `_record_env_provenance` model_validator
- `_scan_model`, `_resolve_source`, `_candidate_env_names` helpers
- The provenance-tracking block at the end of `apply_cli_overlay`
  (lines ~202–205: the `new_provenance = dict(...); ... ; new_settings._provenance = new_provenance` block)
- Keep `_find_aliased_env`, `_find_env_value`, the env-alias maps and
  the `_inject_token_aliases` / `_inject_top_level_aliases` validators
  — they are used by the main settings construction, not by doctor

**`semvertag/__main__.py`** — drop:
- `_doctor_command` function
- `_collect_doctor_overrides` function
- The two `from semvertag.doctor._checks import …` and
  `from semvertag.doctor._render import …` imports at the top

### Test files (surgical removal)

**`tests/integration/test_gitlab_provider.py`** — drop:
- All tests in the `check_*` section (search for `check_token`,
  `check_scopes`, `check_project_access`, `check_protected_tags`)
- The protocol-conformance test's expectation that those four members
  exist (`test_gitlab_provider_exposes_every_member_required_by_protocol`
  — shrink the `expected_members` tuple from 9 to 5)

**`tests/conftest.py`** — likely no change required. The `gitlab_provider`
fixture doesn't care about `check_*`. Verify by running the suite after
the surgery; adjust only if something breaks.

### Build and docs

**`Justfile`** — delete the `test-doctor` recipe (last 2 lines).

**`CLAUDE.md`** — remove the `test-doctor` bullet from the Justfile
quick-reference section.

**`docs/providers/gitlab.md`** — find and remove any doctor mentions
(grep first; likely a sentence or short section in the Troubleshooting
or Quick Start area).

## Why the main command covers the gap

The load-bearing assumption: every failure mode `doctor` currently
diagnoses is already producible by the main `semvertag` command with the
correct typed error and exit code. Walk-through:

| Failure mode | doctor today | Main command today | Exit code |
| --- | --- | --- | --- |
| Token invalid | `check_token` → 401 → "Token rejected by GitLab" | `get_default_branch` → 401 → `_translate_status` raises `AuthError` ("Token rejected: 401. Verify SEMVERTAG_TOKEN…") | 3 (both) |
| Token missing 'api' scope | `check_scopes` → "Token missing 'api' scope" | First scoped API call → 403 → `AuthError` ("Token missing scope or insufficient permission: 403. Add 'api' or 'write_repository' to scopes") | 3 (both) |
| Project not accessible | `check_project_access` → 404 → "GitLab project not found: project_id=…" | `get_default_branch` → 404 → `ConfigError` ("GitLab project not found: project_id=… Verify CI_PROJECT_ID or --project-id") | 2 (both) |
| Network unreachable | `check_token` → no response → "GitLab unreachable (ConnectError)" | `get_default_branch` → `RequestError` → `HttpClient` wraps → `ProviderAPIError` ("request failed: ConnectError") | 4 (both) |
| Rate limit (429) | `check_*` → 429 → "Unexpected GitLab response" | Any method → 429 → `ProviderAPIError` ("GitLab rate limit: 429. Retries exhausted…") | 4 (both) |
| Server error (5xx) | `check_*` → 5xx → "Unexpected GitLab response" | Any method → 5xx → `ProviderAPIError` ("GitLab API failure: …") | 4 (both) |
| Protected tags misconfigured | `check_protected_tags` → "Token cannot read protected_tags" | `create_tag` → 403 → `AuthError` ("Token missing scope or insufficient permission: 403. Add 'api' or 'write_repository' to scopes") | 3 (both); failure discovered later in the run |

**One accepted loss:** the protected-tags case fails fast under `doctor`
but only at `create_tag` time under the main command — after `list_tags`
and bump computation already ran. Costs ~1 extra HTTP round-trip and one
strategy decision per misconfigured run. The exit code and the
actionable fix instruction are identical. The cost of preserving
fail-fast for one rare misconfiguration scenario is keeping ~400 LOC and
the string-fragment exit-code matching — not worth it.

**No new code** required in the main command. Its error paths are already
structurally complete.

## Execution sequencing

Single worktree off `main`. Three commits, each leaving the suite green.

### Worktree setup

Spawn a worktree (suggested: `feat/drop-doctor`). Baseline:
`just lint-ci && uv run pytest` should pass (438 / 1 skipped at time of
writing).

### Wave A — drop the doctor subsystem

Files in one commit:
- Delete `semvertag/doctor/` directory entirely
- Edit `semvertag/__main__.py`: remove `_doctor_command`,
  `_collect_doctor_overrides`, the two `from semvertag.doctor …` imports
- Delete `tests/integration/test_cli_doctor.py`
- Delete `tests/unit/test_doctor_checks.py`
- Delete `tests/unit/test_doctor_render.py`

After this wave:
- `semvertag --help` no longer lists `doctor` subcommand
- Provider `check_*` methods still exist (`tests/integration/test_gitlab_provider.py`
  still calls them — that's the next wave)
- `_provenance` machinery still exists (its own test file still covers it
  — that's the wave after)
- `just lint-ci` clean; `uv run pytest` green (test count drops by however
  many doctor tests existed)

Commit message: `feat: drop doctor subcommand and its package`

### Wave B — drop provider `check_*` surface

Files in one commit:
- `semvertag/providers/_base.py` — drop four `check_*` lines from `Provider`
  Protocol
- `semvertag/providers/gitlab.py` — drop the four `check_*` methods,
  `_safe_get`, `_evaluate_scopes_payload`, plus any module-level constants
  that `ruff check` flags as unused after the deletion
- `tests/integration/test_gitlab_provider.py` — drop the `check_*` tests
  and shrink `expected_members` in the protocol-conformance test

After this wave:
- `Provider` Protocol surface is 5 methods
- `just lint-ci` clean; `uv run pytest` green

Commit message: `providers: drop check_* methods after doctor removal`

### Wave C — drop `_provenance` and remaining references

Files in one commit:
- `semvertag/_settings.py` — drop `_provenance` field, `_record_env_provenance`,
  `_scan_model`, `_resolve_source`, `_candidate_env_names`, and the
  provenance-tracking block in `apply_cli_overlay`
- Delete `tests/unit/test_provenance.py`
- `Justfile` — delete the `test-doctor` recipe
- `CLAUDE.md` — remove `test-doctor` bullet
- `docs/providers/gitlab.md` — remove any doctor mentions found by grep

After this wave:
- `Settings` has no `_provenance` field
- `Justfile` and docs are clean
- `just lint-ci` clean; `uv run pytest` green;
  `mkdocs build --strict` clean

Commit message: `chore: drop _provenance tracking and remaining doctor references`

### Pre-merge verification gate

- `just lint-ci`
- `uv run pytest` — expect a much smaller test count than 438, but no
  failures (the drop reflects deleted tests, not regressions)
- `just test-branch-strategies` and `just test-cc-strategies` — must
  still be 100% (these are unrelated)
- `uv run --with-requirements docs/requirements.txt mkdocs build --strict`
- `git diff main --stat` — net negative ~400+ LOC across the source files

### Code review and land

Invoke `superpowers:requesting-code-review` for a final review pass, then
`superpowers:finishing-a-development-branch` to merge to `main`.

## Success criteria

When all of these hold, this spec is done:

- `semvertag/doctor/` no longer exists
- `Provider` Protocol has 5 methods (was 9)
- `Settings` has no `_provenance` field, no provenance-related helpers
- `gitlab.py` is meaningfully shorter (target ~120 LOC reduction)
- `_settings.py` is meaningfully shorter (target ~50 LOC reduction)
- `__main__.py` is meaningfully shorter (target ~100 LOC reduction)
- The main `semvertag` command still raises `AuthError`/`ConfigError`/
  `ProviderAPIError` with the correct exit codes (3/2/4) for every
  failure mode listed in the table above
- `just lint-ci`, `uv run pytest`, and `mkdocs build --strict` all green

## Out of scope (deferred to future brainstorms)

- `_settings.py` env-alias hand-coding migration to Pydantic
  `AliasChoices` (still ~140 LOC after this spec lands)
- `ioc.py` modern-di overhead reduction (192 LOC, untouched)
- `__main__.py` residual cleanup after `_doctor_command` is gone (likely
  small now)
- `_use_case.py` `strategy.name` branching in `_status_for_no_bump` /
  `_reason_for_no_bump`
- GitHub provider work (the smaller Provider Protocol surface makes this
  cheaper to add later)

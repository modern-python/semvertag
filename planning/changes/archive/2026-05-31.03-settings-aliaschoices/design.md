---
status: shipped
date: 2026-05-31
slug: settings-aliaschoices
supersedes: null
superseded_by: null
pr: null
outcome: shipped in the pre-1.0 bootstrap (pydantic-settings AliasChoices)
---

# Adopt Pydantic `AliasChoices` in `_settings.py`

**Date:** 2026-05-31
**Status:** Approved, ready for plan
**Author:** brainstorm session (Superpowers `brainstorming` skill)

## Context

`semvertag/_settings.py` hand-codes env-var alias resolution that
Pydantic's native `AliasChoices` already handles. Four pieces of
machinery exist to work around what looks like a Pydantic limitation
but is actually solvable with the right base-class choice:

- ~30 LOC of alias-map module constants
  (`_GITLAB_TOKEN_ALIASES`, `_GITHUB_TOKEN_ALIASES`, `_PROJECT_ID_ALIASES`,
  `_TOKEN_ALIASES_BY_PATH`, `_TOP_LEVEL_FIELD_ALIASES`,
  `_PROVIDER_TO_NESTED_KEY`, `_PROVIDER_ENV_VAR`)
- `_inject_token_aliases` `model_validator(mode="before")` (~14 LOC) that
  dispatches on the active provider and merges the matching alias chain
  into the nested config
- `_inject_top_level_aliases` `model_validator(mode="before")` (~14 LOC)
  that iterates `_TOP_LEVEL_FIELD_ALIASES` and populates aliased
  top-level fields
- Module helpers `_resolve_active_provider`, `_inject_token`,
  `_find_aliased_env`, `_find_env_value` (~30 LOC) that read
  `os.environ` directly

The hand-coded approach exists because **`AliasChoices` on fields inside
a nested `pydantic.BaseModel` is silently ignored by pydantic-settings**.
Only top-level `BaseSettings` fields honor `validation_alias`. A
60-second smoke test confirmed this (4/7 cases failed — the token
chain on a nested `BaseModel` never resolved any env vars).

The fix is to **promote the nested configs (`GitLabConfig`,
`GitHubConfig`) from `BaseModel` to `BaseSettings`**. Each gets its own
`env_prefix` and reads `AliasChoices` on its `token` field natively. A
second smoke test confirmed this works for all 7 alias-precedence
scenarios that the current code supports.

This spec replaces all four pieces of machinery with three small
additions to the field definitions. Net deletion is ~75-85 LOC.

## Decisions

| Question | Decision |
| --- | --- |
| Replace alias-machinery with `AliasChoices`? | Yes |
| `GitLabConfig` / `GitHubConfig` base class | Promote to `pydantic_settings.BaseSettings` |
| `apply_cli_overlay` and CLI overlay helpers in scope? | No — separate concern, can't use `AliasChoices` |
| Public API breakage? | None — `Settings`, `GitLabConfig`, `GitHubConfig` keep the same field names and types |
| Test changes? | None expected — existing 13 tests in `tests/unit/test_settings.py` pin the alias precedence and should pass unchanged |

## Architecture change

### `GitLabConfig` (and `GitHubConfig` analogously)

Before:

```python
class GitLabConfig(pydantic.BaseModel):
    endpoint: str = "https://gitlab.com"
    token: pydantic.SecretStr = pydantic.Field(default=pydantic.SecretStr(""))
```

After:

```python
class GitLabConfig(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="SEMVERTAG_GITLAB__",
        case_sensitive=False,
        extra="ignore",
    )
    endpoint: str = "https://gitlab.com"
    token: pydantic.SecretStr = pydantic.Field(
        default=pydantic.SecretStr(""),
        validation_alias=pydantic.AliasChoices(
            "SEMVERTAG_GITLAB__TOKEN",
            "SEMVERTAG_TOKEN",
            "CI_JOB_TOKEN",
            "GITLAB_TOKEN",
        ),
    )
```

`GitHubConfig` mirrors the shape with its own prefix
(`SEMVERTAG_GITHUB__`) and chain
(`SEMVERTAG_GITHUB__TOKEN`, `SEMVERTAG_TOKEN`, `GITHUB_TOKEN`).

`AliasChoices` evaluates left-to-right, first-match-wins, exactly
matching the current precedence semantics.

### `Settings.project_id`

Before:

```python
project_id: int | None = pydantic.Field(default=None)
```

After:

```python
project_id: int | None = pydantic.Field(
    default=None,
    validation_alias=pydantic.AliasChoices("SEMVERTAG_PROJECT_ID", "CI_PROJECT_ID"),
)
```

## What gets deleted vs preserved

### Deleted from `_settings.py`

- `import os` (no longer used)
- All alias-map module constants:
  - `_GITLAB_TOKEN_ALIASES`
  - `_GITHUB_TOKEN_ALIASES`
  - `_PROJECT_ID_ALIASES`
  - `_TOKEN_ALIASES_BY_PATH`
  - `_TOP_LEVEL_FIELD_ALIASES`
  - `_PROVIDER_TO_NESTED_KEY`
  - `_PROVIDER_ENV_VAR`
- `_inject_token_aliases` model_validator on `Settings`
- `_inject_top_level_aliases` model_validator on `Settings`
- Module helpers:
  - `_resolve_active_provider`
  - `_inject_token`
  - `_find_aliased_env`
  - `_find_env_value`

### Preserved

- `Settings` class shape — same fields, same defaults, same nested-config
  field names. Callers don't change.
- `GitLabConfig` and `GitHubConfig` keep `endpoint` (where applicable)
  and `token` field names and types. They become `BaseSettings` but the
  surface seen by callers is unchanged.
- `_clamp_request_timeout` field validator + `_REQUEST_TIMEOUT_CEILING`
  constant — legitimate behavior, not related to aliasing.
- `_logger` — used by `_clamp_request_timeout`.
- `apply_cli_overlay`, `_split_overrides`, `_revalidate_nested` — CLI
  overlay machinery, out of scope per Decisions.
- `_ENV_PREFIX`, `_ENV_NESTED_DELIMITER` — still in `Settings.model_config`.

### Estimated delta

`_settings.py`: 211 LOC → ~134 LOC (target ~75-85 LOC reduction). Not a
hard gate; if the actual delta diverges meaningfully, surface and
reconsider, but the design's deletion list is exhaustive.

## Semantic shift to be aware of

The current `_inject_token_aliases` dispatcher only populates the
**active** provider's token (selected via the `provider` field). The
new design populates **both** providers' tokens independently — each
nested config reads its own alias chain.

| Env state | Today | After |
| --- | --- | --- |
| `SEMVERTAG_TOKEN=X`, `provider=gitlab` | `gitlab.token=X`, `github.token=""` | `gitlab.token=X`, `github.token=X` |
| `CI_JOB_TOKEN=X`, `provider=gitlab` | `gitlab.token=X`, `github.token=""` | `gitlab.token=X`, `github.token=""` (CI_JOB_TOKEN not in github's chain — unchanged) |
| `GITHUB_TOKEN=X`, `provider=gitlab` | `gitlab.token=""`, `github.token=""` (dispatcher only routes gitlab) | `gitlab.token=""`, `github.token=X` |

**Why this is acceptable:** only the active provider's config is
consumed (by `_construct_gitlab_provider` in `semvertag/ioc.py`). The
inactive provider's config object exists in memory but nothing reads
from it. The stray token on the inactive provider is invisible to
user-facing behavior.

**Where it could surface:** `repr(settings)` would show both configs
populated where today only one would be. SecretStr redaction (`'**********'`)
means the actual token isn't disclosed. No real user-facing diff.

This shift is arguably more honest than the old behavior — the env var
is set, the alias chain matches it, so populating the field is the
straightforward reading.

## Test impact

Existing tests in `tests/unit/test_settings.py` (13 functions, 157 LOC)
all assert on `settings.gitlab.token`, `settings.project_id`,
`settings.gitlab.endpoint`, `settings.quiet`, or `settings.request_timeout`.
None assert on `settings.github.token` being empty when `provider=gitlab`
(which would be the only test the semantic shift could break).

**Expectation:** all 13 tests pass after the refactor with no test
changes needed. If a test does break unexpectedly, surface it; do not
quietly adjust the assertion.

## Execution sequencing

Single worktree off `main`. Two commits, each leaving the suite green.

### Worktree setup

Spawn a worktree (suggested: `feat/settings-aliaschoices`, path
`.worktrees/feat-settings-aliaschoices`). Baseline:
`just lint-ci && uv run pytest -q` should pass (expect 334 / 1 skipped
on current `main`).

### Wave A — Adopt `AliasChoices` and drop the validators

Files in one commit:
- `semvertag/_settings.py`:
  - Change `GitLabConfig` from `pydantic.BaseModel` to `pydantic_settings.BaseSettings`
  - Add `model_config = pydantic_settings.SettingsConfigDict(env_prefix="SEMVERTAG_GITLAB__", case_sensitive=False, extra="ignore")`
  - Wrap `token` field with `validation_alias=pydantic.AliasChoices("SEMVERTAG_GITLAB__TOKEN", "SEMVERTAG_TOKEN", "CI_JOB_TOKEN", "GITLAB_TOKEN")`
  - Same migration for `GitHubConfig` with its own prefix and chain (`"SEMVERTAG_GITHUB__TOKEN", "SEMVERTAG_TOKEN", "GITHUB_TOKEN"`)
  - Add `validation_alias=pydantic.AliasChoices("SEMVERTAG_PROJECT_ID", "CI_PROJECT_ID")` to `Settings.project_id`
  - Delete `_inject_token_aliases` and `_inject_top_level_aliases` model_validators

Keep the alias-map constants and helper functions for now — Wave B
deletes them. Splitting in two commits makes the diff easier to follow.

Gate after Wave A:
- `just lint-ci` — expect PASS, but ruff will flag the now-unused
  helpers and constants (don't act on those yet)
- `uv run pytest -q` — expect 334 / 1 skipped, no failures
- Verify all 13 `test_settings.py` tests pass without modification

Commit message: `settings: route nested token aliases through pydantic AliasChoices`

### Wave B — Drop the dead alias machinery

Files in one commit (`semvertag/_settings.py` only):
- Delete `import os`
- Delete all 7 alias-map constants
  (`_GITLAB_TOKEN_ALIASES`, `_GITHUB_TOKEN_ALIASES`, `_PROJECT_ID_ALIASES`,
  `_TOKEN_ALIASES_BY_PATH`, `_TOP_LEVEL_FIELD_ALIASES`,
  `_PROVIDER_TO_NESTED_KEY`, `_PROVIDER_ENV_VAR`)
- Delete the 4 helper functions
  (`_resolve_active_provider`, `_inject_token`, `_find_aliased_env`,
  `_find_env_value`)

Keep `_ENV_PREFIX`, `_ENV_NESTED_DELIMITER`, `_REQUEST_TIMEOUT_CEILING`,
`_clamp_request_timeout`, `_logger`, and the CLI-overlay machinery
(`apply_cli_overlay`, `_split_overrides`, `_revalidate_nested`).

Gate after Wave B:
- `just lint-ci` — PASS (no more ruff warnings about unused symbols)
- `uv run pytest -q` — 334 / 1 skipped
- `uv run --with-requirements docs/requirements.txt mkdocs build --strict` — clean

Commit message: `settings: drop hand-coded env-alias machinery superseded by AliasChoices`

### Pre-merge verification gate

- `just lint-ci`
- `uv run pytest` (expect 334 / 1 skipped — no test changes)
- `just test-branch-strategies` and `just test-cc-strategies` (still 100%)
- `uv run --with-requirements docs/requirements.txt mkdocs build --strict`
- `git diff main --stat -- semvertag/_settings.py` should show net
  negative ~75-85 LOC

### Code review and land

Invoke `superpowers:requesting-code-review` for a final pass, then
`superpowers:finishing-a-development-branch` to merge to `main`.

**Subagent prompt requirement:** explicitly require `pwd` verification
before any `git commit` (to avoid the on-main-commit issue that
happened during the previous plan's Wave A).

## Success criteria

When all of these hold, this spec is done:

- `_settings.py` no longer contains `_inject_token_aliases`,
  `_inject_top_level_aliases`, `_resolve_active_provider`, `_inject_token`,
  `_find_aliased_env`, `_find_env_value`
- `_settings.py` no longer contains any of the 7 alias-map constants
- `_settings.py` no longer imports `os`
- `GitLabConfig` and `GitHubConfig` are `pydantic_settings.BaseSettings`
  subclasses with their own `env_prefix` and `validation_alias` on their
  `token` field
- `Settings.project_id` has `validation_alias=AliasChoices(...)`
- All 13 tests in `tests/unit/test_settings.py` pass with **no test
  changes**
- `_settings.py` is meaningfully shorter (target ~75-85 LOC reduction)
- `just lint-ci`, `uv run pytest`, and `mkdocs build --strict` all green

## Out of scope (future brainstorms)

- `apply_cli_overlay` / `_split_overrides` / `_revalidate_nested`
  simplification — separate concern, ~60 LOC, can't use `AliasChoices`
- `ioc.py` modern-di overhead reduction
- `__main__.py` residual cleanup (post-doctor)
- `_use_case.py` `strategy.name` branching
- GitHub provider implementation (still pending; the smaller `Provider`
  Protocol after drop-doctor makes this cheaper to add)

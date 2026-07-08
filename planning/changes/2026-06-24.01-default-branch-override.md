---
summary: Make the advertised --default-branch / SEMVERTAG_DEFAULT_BRANCH override actually take effect.
---

# Design: Honor the default-branch override

## Summary

`--default-branch` (and `SEMVERTAG_DEFAULT_BRANCH`) is parsed, validated, and
stored on `Settings.default_branch`, then read by nobody. Both providers always
resolve the branch by calling `get_default_branch()` against the forge API, so
the documented override is silently ignored. Give each provider an optional
`default_branch` and have `get_default_branch()` short-circuit to it when set —
the override lands on a real seam, and the default-branch API round-trip is
skipped when the branch is already known.

## Motivation

`semvertag/_settings.py:86` declares `default_branch: str | None = None`;
`semvertag/__main__.py` exposes `--default-branch` and routes it into
`overrides["default_branch"]`. Grepping the source shows the only reader of the
*concept* "default branch" is each provider's own `get_default_branch()` API
call — the **setting** is never consulted. A user who sets it sees no effect and
no error: the tool quietly queries the API for the branch anyway. This was
surfaced as candidate #4 in the 2026-06-23 architecture review (dead override +
an always-paid API call).

## Non-goals

- No change to auto-detection of the default branch when the override is unset —
  that path (API query) stays exactly as is.
- No change to the `Provider` protocol method signatures; only the concrete
  provider constructors gain a field.
- Not adding a per-forge default-branch setting; the existing top-level
  `Settings.default_branch` is the single source.

## Design

### 1. Treat a blank override as unset at the settings edge

A field validator on `Settings.default_branch` strips the value and maps an
empty or whitespace-only string to `None`. A declared-but-empty
`SEMVERTAG_DEFAULT_BRANCH=` (a common CI idiom, materialized by pydantic-settings
as `""`) therefore means "no override" — the tool falls back to the forge API
rather than aborting. (An earlier draft used `min_length=1`, which turned that
previously-harmless empty env var into a hard `ValidationError`; normalizing
blank-to-`None` avoids that regression.) Stripping also means a stray-padded
name still resolves. This keeps the provider's short-circuit a dead-simple
`is not None` check, since blank never reaches it.

### 2. Providers gain an optional `default_branch`

Both `GitHubProvider` and `GitLabProvider` (frozen/slotted/kw-only dataclasses)
gain `default_branch: str | None = None`. `get_default_branch()` short-circuits:

```python
def get_default_branch(self) -> str:
    if self.default_branch is not None:
        return self.default_branch
    # ... existing API path unchanged
```

Because `get_latest_commit_on_default_branch()` already calls
`get_default_branch()`, the override flows through to the commit lookup for free,
and the default-branch GET is skipped entirely when the override is set.

### 3. Wire the setting through IoC

`ioc._build_current_provider` passes `default_branch=settings.default_branch`
into whichever provider it constructs.

## Testing

- **Providers (integration, both forges):** with `default_branch="develop"`,
  `get_default_branch()` returns `"develop"` and the repo/project endpoint is
  never called; `get_latest_commit_on_default_branch()` issues the commits query
  with the override as the branch param and skips the default-branch GET.
  Existing tests (no override → `None`) prove the API path is unchanged.
- **IoC (unit):** `_build_current_provider` propagates `settings.default_branch`
  to the constructed provider for both providers.
- **Settings (unit):** a blank `default_branch` (empty or whitespace) becomes
  `None`; a padded name is stripped.
- **Gates:** `just lint-ci` and `just test` (100% branch) stay green; the new
  `is not None` branch is covered both ways.

## Risk

Low. When the override is unset (the overwhelmingly common case) the field is
`None` and every code path is byte-identical to today. The only new behavior is
gated behind a non-`None` override. Blank values normalize to `None` (unset), so
a declared-but-empty env var keeps working as a no-op rather than aborting; no
existing test exercises an empty branch.

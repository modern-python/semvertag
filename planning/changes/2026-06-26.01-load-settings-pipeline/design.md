---
summary: Consolidated the env→CLI→validate→token settings pipeline behind one load_settings entry point raising only ConfigError; the CLI callback shrank to collect→load→map→stash and the overlay went private.
---

# Design: Consolidate the settings pipeline behind `load_settings`

## Summary

The flow that turns environment variables and CLI flags into a validated
`Settings` is spread across three places — `_main_callback` in
`semvertag/__main__.py`, `apply_cli_overlay` in `semvertag/_settings.py`, and the
`Settings` validators — and the "a dotted key is nested" rule is computed twice.
The bug-prone orchestration (CLI-over-env precedence, `--token` routing to the
*resolved* provider, error translation) has **no unit test seam**; it is only
exercised through the typer callback in integration tests. This change introduces
one public entry point, `load_settings`, in `semvertag/_settings.py` that owns the
whole pipeline and raises only the domain `ConfigError`. The CLI shrinks to:
collect flags → `load_settings(...)` → map `ConfigError` to an exit code → stash
in DI. Observable behavior and the `Provider` protocol are unchanged.

## Motivation

Concrete friction in the current code:

- **Scattered pipeline.** To understand how config is built a reader must hold
  `__main__.py:125-155` (collect, split, construct, two overlay passes, error
  handling) **and** `_settings.py:136-153` (`apply_cli_overlay`: re-partition,
  `model_copy`, re-validate) **and** the `Settings` validators in mind at once.
- **Duplicated rule.** The "dotted = nested" distinction is computed in
  `__main__.py:140` / `:143` (`if "." in k`) and again inside `apply_cli_overlay`
  (`_settings.py:139-147`, partition on `.`).
- **No unit seam for the risky part.** `test_settings.py` unit-tests `Settings`
  construction and `apply_cli_overlay` in isolation, but precedence,
  token-routing to the resolved provider, and `ValidationError`→`ConfigError`
  translation are only proven via `cli_runner.invoke` integration tests. That
  orchestration is exactly where a precedence bug would hide.
- **pydantic leaks into the CLI.** `_main_callback` catches
  `pydantic.ValidationError` directly and owns `_config_error_from_validation`;
  the CLI must know pydantic is underneath.

This was grilled against the project's "extract only what is shared by *standard*,
not by *coincidence*" lens (`decisions/2026-06-23-forge-providers-not-unified.md`,
`decisions/2026-06-24-error-translators-not-tabled.md`). Unlike those rejected
unifications, this consolidates a *single genuine responsibility* (produce a
validated `Settings` from env + CLI) that is currently split — the deletion test
passes: delete `load_settings` and its logic reappears in `__main__`.

## Non-goals

- The `ioc._build_current_provider` asserts (`ioc.py:64,68`) stay. They are
  load-bearing `ty` type-narrowing (`settings.repo` is `str | None`, the provider
  wants `str`) plus a documented defensive backstop (`architecture/cli.md`), not
  duplicated user-input validation. Removing them was explicitly scoped out.
- No change to `Settings` fields, validators, env aliases, or precedence
  semantics. This is behavior-preserving restructuring.
- No change to the `Provider` / `BumpStrategy` protocols, the use-case, or output.

## Design

### 1. New public entry point: `load_settings`

In `semvertag/_settings.py`:

```python
def load_settings(cli_overrides: dict[str, typing.Any], *, token: str | None = None) -> Settings:
    """Build a validated Settings from environment + CLI overrides.

    cli_overrides is the dotted-key dict produced at the CLI boundary
    (e.g. {"provider": "github", "repo": "o/r", "gitlab.endpoint": "..."}).
    Owns the whole pipeline and raises only ConfigError on any invalid input.
    """
```

Internally, in order:

1. Split `cli_overrides` once into top-level (no `.`) and nested (dotted) maps.
2. `Settings(**top_level)` — so `--provider github --repo o/r` satisfies the
   model validator even when the environment alone would fail. pydantic reads the
   environment here.
3. Overlay the nested map via the now-private `_apply_cli_overlay`.
4. If `token is not None`, overlay `{f"{settings.provider}.token":
   pydantic.SecretStr(token)}` — *after* step 2/3 so `settings.provider` is the
   resolved (possibly auto-detected) value.
5. Return the validated `Settings`.

All failure modes are translated to `ConfigError` inside `load_settings`:
`pydantic.ValidationError` (from step 2 and the overlay's re-validate) via the
relocated `_config_error_from_validation`, and the overlay's `ValueError` (the
nesting-depth-2 guard) wrapped with `ConfigError(str(exc))`.

### 2. `apply_cli_overlay` becomes a private internal seam

Rename `apply_cli_overlay` → `_apply_cli_overlay`. It keeps its current body
(top/nested `model_copy`, re-validate, `SecretStr` preservation) and its focused
tests as an **internal seam** (the depth-2 guard and `SecretStr`-through-`model_copy`
behavior). It is no longer imported by `__main__`; `load_settings` is the only
public way to build settings from overrides.

### 3. `_config_error_from_validation` moves into `_settings.py`

It is an implementation detail of translating pydantic failures to the domain
error, so it lives with the loader. `__main__` no longer references
`pydantic.ValidationError`.

### 4. `__main__._main_callback` shrinks

After collecting overrides (via the unchanged `_collect_overrides`, which stays at
the CLI boundary as the flag→key adapter), the callback becomes:

```python
overrides = _collect_overrides(...)
try:
    settings = load_settings(overrides, token=token)
except ConfigError as err:
    typer.echo(f"Error: {err}", err=True)
    raise typer.Exit(code=err.exit_code) from err
app_container = modern_di_typer.fetch_di_container(ctx)
app_container.set_context(Settings, settings)
```

The `pydantic` import in `__main__.py` is dropped if no longer used elsewhere
(the `--token` `SecretStr` wrap moves into `load_settings`).

## Testing

TDD, characterize-first — write the `load_settings` tests against current
behavior, get them green against a thin shim that calls the existing pieces, then
move the logic so the tests stay green (provably behavior-preserving).

New unit tests in `tests/unit/test_settings.py` against `load_settings`:

- **Precedence:** env value overridden by a CLI override; default used when
  neither is set.
- **Token routing — explicit provider:** `provider=github` + `token=...` →
  `settings.github.token` set, `settings.gitlab.token` untouched (and the gitlab
  mirror case).
- **Token routing — auto-detected provider:** provider unset, `GITHUB_ACTIONS=true`
  in env + `token=...` → routed to `github.token`.
- **Error translation:** an invalid value (e.g. non-numeric `project_id`, or
  `provider=gitlab` with no `project_id`) raises `ConfigError`, never a leaked
  `pydantic.ValidationError`.
- **Depth-2 guard:** an override key like `gitlab.endpoint.extra` raises
  `ConfigError`.

Keep the existing `_apply_cli_overlay` internal-seam tests (renamed). Keep one
integration test that the CLI wires `load_settings` → DI correctly; remove
integration assertions that only existed to prove precedence (now unit-covered).

Gates: `just test` (100% branch coverage), `just lint-ci` (includes
`just check-planning`), `just docs-build`.

## Risk

- **Behavior drift during the move (medium × low).** Mitigated by characterize-first
  TDD: the precedence/token/error tests are written and green *before* the logic
  moves, so any drift fails a test.
- **Coverage gate (low × low).** `fail_under = 100` with `--cov-branch`: every new
  branch in `load_settings` (token present/absent, top/nested split, each error
  translation arm) needs a test. The test list above is written to cover each
  branch.
- **`architecture/cli.md` drift (low × low).** The "Settings" section describes
  `apply_cli_overlay` and the two-pass token routing by name; promote it in the
  same PR to describe `load_settings` as the single entry point.

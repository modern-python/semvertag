---
status: shipped
date: 2026-05-31
slug: ioc-idiomatic-modern-di-typer
supersedes: null
superseded_by: null
pr: null
outcome: shipped in the pre-1.0 bootstrap (modern-di + Typer IoC)
---

# Idiomatic `modern-di-typer` wiring in `ioc.py` + `__main__.py`

**Date:** 2026-05-31
**Status:** Approved, ready for plan
**Author:** brainstorm session (Superpowers `brainstorming` skill)

## Context

`semvertag` depends on `modern-di-typer` (the user is its maintainer) and
`ioc.py` is intended as a teaching artifact showing how to wire a Typer
CLI with `modern-di`. The current implementation **bypasses the library's
main features**: it uses `modern_di.Group`/`Factory` machinery but
manually fights every form of automatic wiring:

- `skip_creator_parsing=True` on every `providers.Factory` (disables
  type-hint-based dependency resolution)
- `bound_type=None` on every `providers.Factory` (disables type-based
  `FromDI` resolution)
- Manual `kwargs={"settings": SettingsGroup.settings}` on every Factory
  whose creator takes Settings (redundant with what creator parsing would
  generate)
- Container constructed per-CLI-invocation via `build_container(settings)`
  rather than at module level
- No `modern_di_typer.setup_di`, no `@modern_di_typer.inject`, no
  `FromDI` — the CLI manually calls `container.resolve_provider(...)`
- `_construct_gitlab_provider` + `_build_gitlab_provider` pair exists
  only for testability (the `inner_transport=` parameter)
- Testability scaffolding is on `build_container(settings, inner_transport=...)`
  rather than via `container.override(...)` (the documented test pattern)

As a showcase, this currently demonstrates "manually wiring a DI graph
with extra boilerplate." After this spec, it demonstrates **the
canonical `modern-di-typer` pattern**: module-level container,
`setup_di`, `@inject`-decorated command, `FromDI` resolution,
auto-wiring from creator type hints, and test overrides via
`container.override`.

A smoke test (run during brainstorming) verified the load-bearing
mechanic: **`container.set_context(Settings, settings)` called from
inside the callback AFTER `with container:` has entered APP scope
successfully late-binds the Settings context.** Factories with
type-hinted parameters (`def _build_x(settings: Settings)`) then
auto-resolve from that context when `@inject` fires on a subsequent
command.

## Decisions

| Question | Decision |
| --- | --- |
| Container lifecycle | Module-level singleton (`container = Container(groups=ALL_GROUPS)` in `ioc.py`) |
| `setup_di` integration | Module-level (`modern_di_typer.setup_di(MAIN_APP, ioc.container)` in `__main__.py`) |
| Settings flow | `container.set_context(Settings, settings)` from inside the callback, after `with container:` opens APP scope in `main()` |
| `@inject` / `FromDI` usage | Add explicit `semvertag tag` subcommand decorated with `@modern_di_typer.inject`, takes `use_case: Annotated[SemvertagUseCase, FromDI(SemvertagUseCase)]` |
| `quiet` / `json` flag location | On the `tag` subcommand (not the callback, not on Settings) — they're per-invocation display preferences, not configuration |
| `Settings.quiet` field | **Removed** — was supporting env-var-based quiet which doesn't fit the "display pref" framing |
| `Settings.json` field | **Not added** — same reasoning |
| Output construction | Inline in the tag command body (`build_json_output(...)` if `--json` else `build_rich_output(...)`); passed to `use_case(output=output)` |
| Setup-error redaction | None — use `typer.echo(err=True)` for callback-side setup errors (they happen before any tokens are parsed, so disclosure risk is minimal) |
| Tests' transport injection | `container.override(TransportsGroup.transport, mock_transport)` + `reset_override` (the canonical test pattern); `container.override` is **test-only**, never production |
| CLI surface change | Accepted — `semvertag tag` is the new invocation; bare `semvertag` shows help. Templates (`action.yml`, GitLab CI catalog) and docs update accordingly. Pre-1.0, no published users to break. |

## Architecture

### Module-level wiring

```python
# semvertag/ioc.py
container = Container(groups=ALL_GROUPS)
```

```python
# semvertag/__main__.py
modern_di_typer.setup_di(MAIN_APP, ioc.container)
```

### Callback (config + Settings context)

```python
@MAIN_APP.callback()
def _root(
    ctx: typer.Context,
    project_id: ..., strategy: ..., provider: ..., token: ...,
    default_branch: ..., gitlab_endpoint: ..., request_timeout: ...,
    _version: ...,
) -> None:
    try:
        settings = Settings()
        overrides = _collect_overrides(...)  # no quiet/json
        settings = apply_cli_overlay(settings, overrides)
    except (pydantic.ValidationError, ValueError, ConfigError) as err:
        typer.echo(f"Configuration error: {err}", err=True)
        raise typer.Exit(code=2)

    app_container = modern_di_typer.fetch_di_container(ctx)
    app_container.set_context(Settings, settings)
```

The callback's only job: parse CLI flags, build Settings, push it via
`set_context`. Setup errors emit via `typer.echo(err=True)` because
Output isn't constructed yet (it depends on per-call display prefs that
aren't known here).

### Tag subcommand (per-call flags + DI resolution)

```python
@MAIN_APP.command("tag")
@modern_di_typer.inject
def _tag(
    use_case: typing.Annotated[SemvertagUseCase, modern_di_typer.FromDI(SemvertagUseCase)],
    quiet: typing.Annotated[bool, typer.Option("--quiet", help="Suppress progress narrative.")] = False,
    json_flag: typing.Annotated[bool, typer.Option("--json", help="Emit JSON envelope instead of human-readable output.")] = False,
) -> None:
    output: Output = build_json_output(quiet=quiet) if json_flag else build_rich_output(quiet=quiet)
    try:
        use_case(output=output)
    except SemvertagError as err:
        output.error(str(err))
        raise typer.Exit(code=err.exit_code) from err
    except BrokenPipeError as exc:
        raise typer.Exit(code=0) from exc
    except OSError as exc:
        if exc.errno == errno.EPIPE:
            raise typer.Exit(code=0) from exc
        raise
```

The tag command:
- Takes `--quiet` / `--json` directly (per-call display prefs live where
  they're used)
- Receives `use_case` via `FromDI` (resolved from the late-bound Settings
  context)
- Builds `output` inline from CLI flags, passes to `use_case(output=output)`
- Handles runtime errors with proper exit codes

### Main entry

```python
def main() -> None:
    with ioc.container:
        MAIN_APP()
```

### Group definitions (declarative)

```python
class SettingsGroup(Group):
    settings = providers.ContextProvider(scope=Scope.APP, context_type=Settings)


class TransportsGroup(Group):
    transport = providers.Factory(scope=Scope.APP, creator=RetryingTransport)


class ProvidersGroup(Group):
    gitlab_provider = providers.Factory(
        scope=Scope.APP,
        creator=_build_gitlab_provider,  # signature: (settings: Settings, transport: httpx2.BaseTransport)
        cache_settings=providers.CacheSettings(finalizer=_close_provider_client),
    )


class StrategiesGroup(Group):
    branch_prefix_strategy = providers.Factory(scope=Scope.APP, creator=_build_branch_prefix_strategy)
    conventional_commits_strategy = providers.Factory(scope=Scope.APP, creator=_build_conventional_commits_strategy)
    current_strategy = providers.Factory(scope=Scope.APP, creator=_build_current_strategy)


class UseCasesGroup(Group):
    semvertag_use_case = providers.Factory(
        scope=Scope.APP,
        creator=SemvertagUseCase,
        kwargs={
            "provider": ProvidersGroup.gitlab_provider,
            "strategy": StrategiesGroup.current_strategy,
        },
    )
```

What's gone vs. today:
- `skip_creator_parsing=True` — removed everywhere (creator parsing
  enabled by default; auto-wires from type hints)
- `bound_type=None` — removed everywhere (defaults to the creator's
  return type, enabling `FromDI(Type)`)
- `kwargs={"settings": SettingsGroup.settings}` — removed where the
  creator only takes Settings (auto-wired); **kept** on
  `semvertag_use_case` because `provider: Provider` and
  `strategy: BumpStrategy` are Protocol types and modern-di can't
  disambiguate which Factory satisfies a Protocol — explicit reference
  is correct
- `OutputsGroup` — stays gone (sub-project A removed it)

What's new:
- `TransportsGroup` — wraps `RetryingTransport` as a Factory so tests
  can override it via `container.override`
- The `_construct_gitlab_provider` / `_build_gitlab_provider` pair
  collapses to one `_build_gitlab_provider(settings, transport)`
- Module-level `container` singleton

## What gets touched

### Source files

**`semvertag/_settings.py`** — small subtraction:
- Drop the `quiet: bool` field (was at line ~68)
- Justification: `quiet` is a per-call display pref, not stable
  configuration. It belongs on the `tag` subcommand, not in Settings.

**`semvertag/ioc.py`** — major restructure (see Architecture above):
- Drop `_construct_gitlab_provider` (collapse into `_build_gitlab_provider`)
- Drop `build_container()` function entirely
- Add `TransportsGroup`
- Drop `skip_creator_parsing=True`, `bound_type=None`, redundant `kwargs={"settings": ...}` across all Factories
- Add module-level `container = Container(groups=ALL_GROUPS)`
- Update `__all__`: drop `build_container`, add `TransportsGroup`
- Move inline imports (`from semvertag.providers._http import HttpClient` and friends) to module-level if circular-import-safe; if not, keep inline with the `# noqa: PLC0415`
- Drop the `if settings.provider != "gitlab"` runtime check from
  `build_container`; relocate it to `_build_gitlab_provider`'s body (or
  let it surface as a Factory construction error)

**`semvertag/__main__.py`** — restructure:
- Add `modern_di_typer.setup_di(MAIN_APP, ioc.container)` at module level
- Refactor `_main_callback` per the Architecture section: drop
  `--quiet`/`--json` typer Options, drop quiet from `_collect_overrides`
  call, replace Output construction + container building with
  `set_context`, replace try-blocks with `typer.echo`-based setup-error
  reporting
- Add new `@MAIN_APP.command("tag")` decorated with
  `@modern_di_typer.inject` (full body per Architecture)
- Update `main()` to `with ioc.container: MAIN_APP()`
- Drop `_build_output_for_flags` helper (unused after the refactor)
- `_collect_overrides` loses its `quiet` parameter

### Test files

**`tests/integration/conftest.py`** — `install_mock_transport` migrates:

```python
@pytest.fixture
def install_mock_transport() -> typing.Iterator[typing.Callable[[HandlerCallable], None]]:
    overridden: list[bool] = [False]

    def install(handler: HandlerCallable) -> None:
        mock_transport = httpx2.MockTransport(handler)
        ioc.container.override(ioc.TransportsGroup.transport, mock_transport)
        overridden[0] = True

    yield install

    if overridden[0]:
        ioc.container.reset_override(ioc.TransportsGroup.transport)
```

(The exact fixture shape may differ — the key is `container.override`
during install and `reset_override` on teardown.)

**`tests/integration/test_cli_*.py`** (3 files) — update CLI invocations:
- `cli_runner.invoke(MAIN_APP, [])` → `cli_runner.invoke(MAIN_APP, ["tag"])`
- `cli_runner.invoke(MAIN_APP, ["--json"])` → `cli_runner.invoke(MAIN_APP, ["tag", "--json"])`
- `cli_runner.invoke(MAIN_APP, ["--quiet"])` → `cli_runner.invoke(MAIN_APP, ["tag", "--quiet"])`
- All other flags stay before `"tag"` (they're callback flags): `cli_runner.invoke(MAIN_APP, ["--project-id", "123", "tag"])` or after if typer accepts mixed positions

**`tests/unit/test_settings.py`** — drop the `test_quiet_picks_up_semvertag_quiet_env_var` test (no more env-var support for quiet). Test count: 14 → 13.

**`tests/unit/test_ioc.py`** — review and update. Currently 47 LOC, likely tests `build_container`. Replace with tests that resolve providers from the module-level container with a stubbed Settings pushed via `set_context`.

**`tests/unit/test_use_case.py`** — likely unchanged (tests construct `SemvertagUseCase` directly).

### Build / docs

**`action.yml`** — GitHub Actions wrapper invokes `uvx semvertag`. Update
to `uvx semvertag tag`. Affects the `runs.steps[].run` field.

**`templates/semvertag.yml`** — GitLab CI catalog component's `script:`
section. Update to `uvx semvertag tag`.

**`docs/providers/github.md`** + **`docs/providers/gitlab.md`** — search
for `uvx semvertag` and `semvertag` invocations; update to `semvertag tag`.

**`CLAUDE.md`** — verify no `semvertag` invocations need updating. If
the file documents the CLI, update accordingly.

**`README.md`** — check for usage examples; update if needed.

### Estimated delta

| File | Delta |
|---|---|
| `_settings.py` | -3 LOC (drop quiet field) |
| `ioc.py` | ~-30 LOC (drop boilerplate + build_container + _construct/_build pair; add TransportsGroup + module-level container) |
| `__main__.py` | ~0 LOC (callback shrinks, tag command adds, error handling moves) |
| `tests/integration/conftest.py` | ~+5 LOC (new override-based fixture) |
| `tests/integration/test_cli_*.py` (3 files) | ~+10 LOC across files (add "tag" to invoke args) |
| `tests/unit/test_settings.py` | -8 LOC (drop quiet env-var test) |
| `tests/unit/test_ioc.py` | varies — likely shrinks |
| `action.yml`, `templates/semvertag.yml` | ~+2 LOC each |
| Docs | ~+5 LOC across files |
| **Net** | **roughly flat or slight reduction; value isn't LOC** |

The value of this refactor is **teaching clarity**, not code reduction.
After the refactor, every `ioc.py` line earns its place: the Factories
auto-wire, `FromDI` resolves by type, `setup_di` integrates with Typer,
`set_context` late-binds CLI-derived state, and `container.override` is
the test injection mechanism. Today's code shows what to write to bypass
all of that.

## Why the canonical pattern works for semvertag

The smoke test that unblocked this design:

```python
# Module-level: schema only
container = Container(groups=[AppGroup])
app = typer.Typer()
modern_di_typer.setup_di(app, container)


@app.callback()
def _root(ctx, name="world"):
    settings = Settings(name=name)
    app_container = modern_di_typer.fetch_di_container(ctx)
    app_container.set_context(Settings, settings)  # AFTER scope is entered


@app.command()
@modern_di_typer.inject
def hello(greeter: Annotated[Greeter, FromDI(Greeter)]):
    typer.echo(greeter.greet())  # prints "hello alice" with --name alice


if __name__ == "__main__":
    with container:  # enters APP scope
        app()
```

Output: `hello alice`. The `set_context` call on an already-entered
container successfully late-binds Settings; the auto-wired Greeter
Factory (from `_build_greeter(settings: Settings)`) resolves from the
late-bound context when `@inject` fires.

This is the core insight: **`ContextProvider` can be late-bound via
`set_context` from inside the callback**, which makes the canonical
module-level container + `@inject`/`FromDI` pattern work even when
dependencies depend on CLI-parsed state.

## Execution sequencing

Tightly coupled changes — must land as **one atomic commit on one
worktree** to keep the build green.

### Worktree setup

Spawn `feat/ioc-idiomatic-modern-di-typer` off `main`, path
`.worktrees/feat-ioc-idiomatic-modern-di-typer`. Baseline:
`just lint-ci && uv run pytest -q` should pass (334 / 1 skipped on
current main).

### Single wave — the full refactor

Edits land in this order (for diff readability):

1. `semvertag/_settings.py` — drop `quiet` field
2. `semvertag/ioc.py` — full restructure per Architecture section
3. `semvertag/__main__.py` — callback shrinks, tag command added,
   `setup_di` at module level, `main()` enters container scope
4. `tests/integration/conftest.py` — `install_mock_transport` migrates
   to `container.override`
5. `tests/integration/test_cli_*.py` (3 files) — invocations get `"tag"`
6. `tests/unit/test_settings.py` — drop quiet env-var test
7. `tests/unit/test_ioc.py` — review and update for module-level container
8. `tests/unit/test_use_case.py` — verify unchanged (should be)
9. `action.yml`, `templates/semvertag.yml` — invocations get `tag`
10. `docs/providers/*.md`, `CLAUDE.md`, `README.md` — search and replace
    invocation examples

### Gate after the wave

- `just lint-ci` — PASS
- `uv run pytest -q` — **333 passed, 1 skipped** (drops by 1 for the
  removed quiet env-var test; this is the only legitimate count change)
- `just test-branch-strategies && just test-cc-strategies` — still 100%
- `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict` —
  clean
- Smoke tests:
  - `uv run semvertag --help` — top-level help shows the `tag` subcommand
  - `uv run semvertag tag --help` — shows `--quiet`, `--json`, runtime help text
  - `uv run semvertag tag` (without credentials) — fails with the expected
    `ConfigError` from missing `project_id` or `token`; exit code 2

### Commit message

```
ioc: adopt idiomatic modern-di-typer wiring with setup_di + @inject + FromDI

Refactor ioc.py from manual container construction per CLI invocation
to module-level container + modern_di_typer.setup_di integration.
Settings flows in via container.set_context(Settings, settings) from
the callback after APP scope is entered. The new semvertag tag
subcommand is decorated with @modern_di_typer.inject and resolves the
use case via FromDI(SemvertagUseCase). All Factories drop
skip_creator_parsing=True, bound_type=None, and the redundant
kwargs={"settings": ...} entries — creator parsing auto-wires from type
hints.

Quiet and json move from Settings/callback flags to the tag subcommand
(per-call display preferences, not config). Settings.quiet field
removed.

Test transport injection migrates from the inner_transport= parameter
on build_container to container.override(TransportsGroup.transport,
mock_transport) — the documented test pattern; override is test-only.

CLI surface: semvertag tag is the invocation. Bare semvertag prints
help. action.yml, templates/semvertag.yml, and provider docs updated
to use the new subcommand.

Closes sub-project B of the ioc.py showcase brainstorm.
```

### Code review

Skip the formal subagent code review for this tightly-scoped refactor.
Surface anything that surprises during the wave.

### Land

`superpowers:finishing-a-development-branch` — fast-forward expected.

## Success criteria

When all of these hold, this spec is done:

- `semvertag/ioc.py` has module-level `container = Container(groups=ALL_GROUPS)`;
  no `build_container()` function; no `skip_creator_parsing=True`;
  no `bound_type=None`; `kwargs={"settings": ...}` only present on
  `semvertag_use_case` for Protocol disambiguation
- `semvertag/__main__.py` has `modern_di_typer.setup_di(MAIN_APP, ioc.container)`
  at module level; an `@MAIN_APP.command("tag")` decorated with
  `@modern_di_typer.inject` and `FromDI(SemvertagUseCase)`;
  `with ioc.container: MAIN_APP()` in `main()`
- `Settings` no longer has a `quiet` field
- All CLI tests invoke via `["tag", ...]`
- `install_mock_transport` uses `container.override(TransportsGroup.transport, ...)`
  (and resets on teardown)
- `action.yml`, `templates/semvertag.yml`, and provider docs invoke
  `semvertag tag`
- `just lint-ci`, `uv run pytest`, `mkdocs build --strict` all green
- 333 tests pass (vs 334 baseline; the dropped quiet-env-var test is
  the only intentional count change)

## Out of scope

Deferred to future brainstorms or accepted as-is:

- `apply_cli_overlay` / `_split_overrides` / `_revalidate_nested`
  simplification in `_settings.py` (still ~60 LOC of CLI-overlay
  machinery; functionally fine, no urgent need to touch)
- `_use_case.py` `strategy.name` branching in `_status_for_no_bump` /
  `_reason_for_no_bump` (very minor)
- `__main__.py` further cleanup beyond what the subcommand split
  requires
- GitHub provider implementation
- Library-side changes to `modern-di-typer` (the smoke-test pattern
  works; no library changes needed)

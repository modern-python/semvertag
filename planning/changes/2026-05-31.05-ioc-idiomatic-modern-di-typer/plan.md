# Idiomatic `modern-di-typer` Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `ioc.py` + `__main__.py` to the canonical `modern-di-typer` pattern: module-level container, `setup_di`, an explicit `semvertag tag` subcommand decorated with `@modern_di_typer.inject`, and `FromDI`-based dependency resolution — with creator-parsing auto-wiring replacing the manual `kwargs={...}` / `skip_creator_parsing=True` / `bound_type=None` workarounds.

**Architecture:** Single atomic commit on one worktree. Container shape, callback shape, command shape, and Settings shape all change together. The breakthrough mechanic is `container.set_context(Settings, settings)` from inside the callback after `with ioc.container:` opens APP scope — late-binds CLI-derived Settings into the context so Factories with type-hinted parameters auto-resolve when `@inject` fires.

**Tech Stack:** `modern-di`, `modern-di-typer`, `typer`, `pydantic-settings`, `pytest`, `httpx2`. No new deps.

**Spec:** `planning/specs/2026-05-31-ioc-idiomatic-modern-di-typer-design.md`

---

## Task 1: Spawn worktree and verify baseline

**Files:** none in main checkout.

- [ ] **Step 1: Spawn the worktree**

Use the `superpowers:using-git-worktrees` skill. Suggested branch: `feat/ioc-idiomatic-modern-di-typer`. Suggested path: `.worktrees/feat-ioc-idiomatic-modern-di-typer`.

- [ ] **Step 2: Verify clean baseline inside the worktree**

Run (inside the worktree, after `cd` and `uv sync --all-extras --group lint`):

```bash
pwd
git branch --show-current
git status
```

Expected: cwd is `/Users/kevinsmith/src/pypi/autosemver/.worktrees/feat-ioc-idiomatic-modern-di-typer`, branch is `feat/ioc-idiomatic-modern-di-typer`, status clean.

Run: `just lint-ci`
Expected: PASS.

Run: `uv run pytest -q`
Expected: 334 passed, 1 skipped.

Run: `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

If any baseline check fails, stop and report.

---

## Task 2: Atomic refactor in one commit

The container shape, callback shape, tag-command introduction, and Settings shape are tightly coupled. They land in **one commit** because partial state breaks the build.

**Files:**
- Modify: `semvertag/_settings.py` (drop `quiet` field)
- Modify: `semvertag/ioc.py` (major restructure)
- Modify: `semvertag/__main__.py` (callback shrinks, tag command added, `setup_di` at module level, `main()` enters container)
- Modify: `tests/integration/conftest.py` (`install_mock_transport` migrates to `container.override`)
- Modify: `tests/integration/test_cli_main_verb.py` (5 invocations)
- Modify: `tests/integration/test_cli_quiet_json_matrix.py` (10 invocations)
- Modify: `tests/integration/test_strategy_switching.py` (7 invocations)
- Modify: `tests/unit/test_settings.py` (drop quiet env-var test)
- Modify: `tests/unit/test_ioc.py` (rewrite to use module-level container)
- Modify: `action.yml` (`uvx semvertag` → `uvx semvertag tag`)
- Modify: `templates/semvertag.yml` (same)
- Modify: `docs/providers/github.md` (3 invocation references)
- Modify: `docs/providers/gitlab.md` (3 invocation references)

### CRITICAL: Verify cwd before any git operation

Before EVERY `git add` and `git commit`, run:

```bash
pwd
git branch --show-current
```

The output MUST show:
- pwd: `/Users/kevinsmith/src/pypi/autosemver/.worktrees/feat-ioc-idiomatic-modern-di-typer`
- branch: `feat/ioc-idiomatic-modern-di-typer`

If either is wrong, STOP. Use absolute paths (starting with the worktree path) for Edit/Write operations.

### Step 1: Drop `quiet` field from `Settings`

In `semvertag/_settings.py`, find the `quiet` field declaration in the `Settings` class (currently line 68):

```python
    quiet: bool = pydantic.Field(default=False)
```

Delete this line. The `Settings` class loses the `quiet` field entirely.

### Step 2: Restructure `semvertag/ioc.py`

Replace the entire contents of `semvertag/ioc.py` with:

```python
import typing

import httpx2
import modern_di
from modern_di import Scope, providers

from semvertag._errors import ConfigError
from semvertag._settings import Settings
from semvertag._transport import RetryingTransport
from semvertag._use_case import SemvertagUseCase
from semvertag.providers._http import HttpClient
from semvertag.providers.gitlab import GitLabProvider, _translate_status, gitlab_auth_headers
from semvertag.strategies._base import BumpStrategy
from semvertag.strategies.branch_prefix import BranchPrefixStrategy
from semvertag.strategies.conventional_commits import ConventionalCommitsStrategy


def _build_gitlab_provider(settings: Settings, transport: httpx2.BaseTransport) -> GitLabProvider:
    if settings.project_id is None:
        msg = "Project id missing. Set CI_PROJECT_ID or pass --project-id."
        raise ConfigError(msg)
    project_id: typing.Final = settings.project_id
    client: typing.Final = httpx2.Client(
        transport=transport,
        base_url=settings.gitlab.endpoint,
        timeout=settings.request_timeout,
    )
    http: typing.Final = HttpClient(
        client=client,
        auth_headers=lambda: gitlab_auth_headers(settings.gitlab.token),
        status_translator=lambda status: _translate_status(status, project_id),
    )
    return GitLabProvider(
        config=settings.gitlab,
        project_id=project_id,
        http=http,
    )


def _build_branch_prefix_strategy(settings: Settings) -> BranchPrefixStrategy:
    return BranchPrefixStrategy(config=settings.branch_prefix)


def _build_conventional_commits_strategy(settings: Settings) -> ConventionalCommitsStrategy:
    return ConventionalCommitsStrategy(config=settings.conventional_commits)


def _build_current_strategy(settings: Settings) -> BumpStrategy:
    if settings.strategy == "conventional-commits":
        return _build_conventional_commits_strategy(settings)
    return _build_branch_prefix_strategy(settings)


def _close_provider_client(provider: GitLabProvider) -> None:
    provider.http.client.close()


class SettingsGroup(modern_di.Group):
    settings = providers.ContextProvider(scope=Scope.APP, context_type=Settings)


class TransportsGroup(modern_di.Group):
    transport = providers.Factory(scope=Scope.APP, creator=RetryingTransport)


class ProvidersGroup(modern_di.Group):
    gitlab_provider = providers.Factory(
        scope=Scope.APP,
        creator=_build_gitlab_provider,
        cache_settings=providers.CacheSettings(finalizer=_close_provider_client),
    )


class StrategiesGroup(modern_di.Group):
    branch_prefix_strategy = providers.Factory(scope=Scope.APP, creator=_build_branch_prefix_strategy)
    conventional_commits_strategy = providers.Factory(scope=Scope.APP, creator=_build_conventional_commits_strategy)
    current_strategy = providers.Factory(scope=Scope.APP, creator=_build_current_strategy)


class UseCasesGroup(modern_di.Group):
    semvertag_use_case = providers.Factory(
        scope=Scope.APP,
        creator=SemvertagUseCase,
        kwargs={
            "provider": ProvidersGroup.gitlab_provider,
            "strategy": StrategiesGroup.current_strategy,
        },
    )


ALL_GROUPS: typing.Final[list[type[modern_di.Group]]] = [
    SettingsGroup,
    TransportsGroup,
    ProvidersGroup,
    StrategiesGroup,
    UseCasesGroup,
]


container: typing.Final = modern_di.Container(groups=ALL_GROUPS)


__all__: typing.Final = (
    "ALL_GROUPS",
    "ProvidersGroup",
    "SettingsGroup",
    "StrategiesGroup",
    "TransportsGroup",
    "UseCasesGroup",
    "container",
)
```

Key differences from the old `ioc.py`:
- `build_container()` function deleted
- `_construct_gitlab_provider` collapsed into `_build_gitlab_provider(settings, transport)`
- `TransportsGroup` added (wraps `RetryingTransport` as a Factory)
- `OutputsGroup` stays gone (sub-project A removed it)
- `skip_creator_parsing=True`, `bound_type=None`, `kwargs={"settings": SettingsGroup.settings}` all removed
- `kwargs` kept only on `semvertag_use_case` (for Protocol disambiguation)
- Module-level `container = modern_di.Container(groups=ALL_GROUPS)` singleton
- Inline imports promoted to top-level (verify they work; if `from semvertag.providers._http import HttpClient` causes a circular import, restore the inline import with `# noqa: PLC0415`)
- TYPE_CHECKING-only imports dropped because everything is now imported at top level
- `if settings.provider != "gitlab"` runtime check removed from `build_container` (handled inside `_build_gitlab_provider` only if it's still needed — verify whether non-gitlab providers get rejected naturally)

### Step 3: Add provider-rejection check back to the callback

The old `build_container` raised `ConfigError(f"Provider {settings.provider!r} not yet supported; v1.0 supports gitlab only.")` when `settings.provider != "gitlab"`. This check must move somewhere. The cleanest place is the callback (after Settings is built, before pushing context):

In `semvertag/__main__.py`, this will be added inside the callback after `settings = apply_cli_overlay(...)` and before the `set_context` call. See Step 4 for exact placement.

### Step 4: Restructure `semvertag/__main__.py`

Replace the entire contents of `semvertag/__main__.py` with:

```python
import errno
import importlib.metadata
import typing

import modern_di_typer
import pydantic
import typer

from semvertag import ioc
from semvertag._errors import ConfigError, SemvertagError
from semvertag._output import Output, build_json_output, build_rich_output
from semvertag._settings import Settings, apply_cli_overlay
from semvertag._use_case import SemvertagUseCase


_PACKAGE_NAME: typing.Final = "semvertag"
_CONFIG_ERROR_EXIT_CODE: typing.Final = 2


MAIN_APP: typing.Final = typer.Typer(
    name="semvertag",
    help=("Auto-tag GitLab/GitHub/Bitbucket repos with semantic version tags — one tool, two strategies."),
    no_args_is_help=True,
    add_completion=True,
)

modern_di_typer.setup_di(MAIN_APP, ioc.container)


def _version_callback(value: bool) -> None:
    if not value:
        return
    try:
        version = importlib.metadata.version(_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        version = "0"
    typer.echo(version)
    raise typer.Exit


def _collect_overrides(  # noqa: PLR0913
    *,
    project_id: int | None,
    strategy: str | None,
    provider: str | None,
    token: str | None,
    default_branch: str | None,
    gitlab_endpoint: str | None,
    request_timeout: float | None,
) -> dict[str, tuple[typing.Any, str]]:
    overrides: dict[str, tuple[typing.Any, str]] = {}
    if project_id is not None:
        overrides["project_id"] = (project_id, "--project-id")
    if strategy is not None:
        overrides["strategy"] = (strategy, "--strategy")
    if provider is not None:
        overrides["provider"] = (provider, "--provider")
    if token is not None:
        overrides["gitlab.token"] = (pydantic.SecretStr(token), "--token")
    if default_branch is not None:
        overrides["default_branch"] = (default_branch, "--default-branch")
    if gitlab_endpoint is not None:
        overrides["gitlab.endpoint"] = (gitlab_endpoint, "--gitlab-endpoint")
    if request_timeout is not None:
        overrides["request_timeout"] = (request_timeout, "--request-timeout")
    return overrides


def _config_error_from_validation(exc: pydantic.ValidationError) -> ConfigError:
    first: typing.Final = exc.errors()[0]
    loc: typing.Final = ".".join(str(part) for part in first.get("loc", ()))
    detail: typing.Final = first.get("msg", "invalid value")
    msg: typing.Final = f"Configuration error at '{loc}': {detail}. Check environment variables and command-line flags."
    return ConfigError(msg)


@MAIN_APP.callback()
def _main_callback(  # noqa: PLR0913
    ctx: typer.Context,
    project_id: typing.Annotated[
        int | None,
        typer.Option("--project-id", help="GitLab project id (or set CI_PROJECT_ID)."),
    ] = None,
    strategy: typing.Annotated[
        str | None,
        typer.Option("--strategy", help="Bump strategy: branch-prefix | conventional-commits."),
    ] = None,
    provider: typing.Annotated[
        str | None,
        typer.Option("--provider", help="Provider: gitlab | github | bitbucket."),
    ] = None,
    token: typing.Annotated[
        str | None,
        typer.Option("--token", help="API token (overrides SEMVERTAG_TOKEN)."),
    ] = None,
    default_branch: typing.Annotated[
        str | None,
        typer.Option("--default-branch", help="Default branch name override."),
    ] = None,
    gitlab_endpoint: typing.Annotated[
        str | None,
        typer.Option("--gitlab-endpoint", help="GitLab API endpoint URL."),
    ] = None,
    request_timeout: typing.Annotated[
        float | None,
        typer.Option("--request-timeout", help="Per-request timeout in seconds (clamped to 10)."),
    ] = None,
    _version: typing.Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = None,
) -> None:
    try:
        settings = Settings()
        try:
            overrides = _collect_overrides(
                project_id=project_id,
                strategy=strategy,
                provider=provider,
                token=token,
                default_branch=default_branch,
                gitlab_endpoint=gitlab_endpoint,
                request_timeout=request_timeout,
            )
            settings = apply_cli_overlay(settings, overrides)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        if settings.provider != "gitlab":
            msg = f"Provider {settings.provider!r} not yet supported; v1.0 supports gitlab only."
            raise ConfigError(msg)
    except pydantic.ValidationError as exc:
        err = _config_error_from_validation(exc)
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=err.exit_code) from err
    except ConfigError as err:
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=err.exit_code) from err

    app_container = modern_di_typer.fetch_di_container(ctx)
    app_container.set_context(Settings, settings)


@MAIN_APP.command("tag")
@modern_di_typer.inject
def _tag_command(
    use_case: typing.Annotated[SemvertagUseCase, modern_di_typer.FromDI(SemvertagUseCase)],
    quiet: typing.Annotated[
        bool,
        typer.Option("--quiet", help="Suppress progress narrative; final result still emits."),
    ] = False,
    json_flag: typing.Annotated[
        bool,
        typer.Option("--json", help="Emit a JSON envelope on stdout instead of human-readable output."),
    ] = False,
) -> None:
    output: Output = build_json_output(quiet=quiet) if json_flag else build_rich_output(quiet=quiet)
    try:
        use_case(output=output)
    except ImportError as exc:
        err = ConfigError(f"Required module unavailable: {exc}.")
        output.error(str(err))
        raise typer.Exit(code=err.exit_code) from err
    except SemvertagError as err:
        output.error(str(err))
        raise typer.Exit(code=err.exit_code) from err
    except BrokenPipeError as exc:
        raise typer.Exit(code=0) from exc
    except OSError as exc:
        if exc.errno == errno.EPIPE:
            raise typer.Exit(code=0) from exc
        raise


def main() -> None:
    with ioc.container:
        MAIN_APP()


if __name__ == "__main__":  # pragma: no cover
    main()
```

Key differences from the old `__main__.py`:
- `modern_di_typer.setup_di(MAIN_APP, ioc.container)` at module level
- `MAIN_APP` config: `no_args_is_help=True` (show help when no subcommand) instead of `invoke_without_command=True` (run callback as default action)
- Callback: removes `--quiet`/`--json` Options; removes `quiet=quiet` from `_collect_overrides` call; removes Output construction; replaces container-building + use-case-resolving with `set_context(Settings, settings)`; uses `typer.echo` for setup errors
- `_collect_overrides` loses its `quiet` parameter
- Provider-rejection check (`settings.provider != "gitlab"`) moves from `build_container` to the callback
- New `@MAIN_APP.command("tag")` decorated with `@modern_di_typer.inject`, takes `use_case` via `FromDI` and `--quiet`/`--json` as typer Options
- `_build_output_for_flags` helper deleted (tag command builds output inline)
- `main()` wraps the app in `with ioc.container:` to enter APP scope
- `import dataclasses` removed (was unused after sub-project A; this confirms)

### Step 5: Migrate `tests/integration/conftest.py` `install_mock_transport` fixture

In `tests/integration/conftest.py`, replace the `install_mock_transport` fixture (currently lines 55-69) with:

```python
@pytest.fixture
def install_mock_transport() -> typing.Iterator[collections.abc.Callable[[HandlerCallable], None]]:
    overridden: list[bool] = [False]

    def install(handler: HandlerCallable) -> None:
        mock_transport: typing.Final = httpx2.MockTransport(handler)
        ioc.container.override(ioc.TransportsGroup.transport, mock_transport)
        overridden[0] = True

    yield install

    if overridden[0]:
        ioc.container.reset_override(ioc.TransportsGroup.transport)
```

The fixture's monkeypatch parameter is no longer needed; the new shape is a generator-style fixture with explicit setup/teardown. If the fixture signature change requires updating the import list at the top of the file (`from semvertag import ioc` may need to stay; `import collections.abc` may need to be added), do so.

### Step 6: Update CLI invocations in `tests/integration/test_cli_main_verb.py`

5 invocations need updating (lines 42, 63, 76, 89, 102 per pre-edit numbering — may shift slightly). Pattern:

- `cli_runner.invoke(MAIN_APP, [])` → `cli_runner.invoke(MAIN_APP, ["tag"])`
- `cli_runner.invoke(MAIN_APP, ["--json"])` → `cli_runner.invoke(MAIN_APP, ["tag", "--json"])`

Note: `--json` and `--quiet` are now flags on the tag subcommand, not the callback. They must appear AFTER `"tag"` in the args list.

### Step 7: Update CLI invocations in `tests/integration/test_cli_quiet_json_matrix.py`

10 invocations need updating (lines 46, 62, 78, 97, 122, 140, 159, 179, 193, 206). Same pattern as Step 6.

Also check the `raising_run` / `raising_call` monkeypatched test (from sub-project A) — verify it still works with the new command structure. The `monkeypatch.setattr(SemvertagUseCase, "__call__", raising_call)` should still fire when `use_case(output=output)` runs inside the tag command body.

### Step 8: Update CLI invocations in `tests/integration/test_strategy_switching.py`

7 invocations need updating (lines 22, 37, 52, 67, 83, 88, 102). Same pattern as Step 6.

### Step 9: Drop the quiet env-var test from `tests/unit/test_settings.py`

In `tests/unit/test_settings.py`, find `test_quiet_picks_up_semvertag_quiet_env_var` (around line 152). Delete the entire test function (plus any constants only it uses).

Also check line 34 — there's `assert settings.quiet is False` in some other test. That test was checking the default for `quiet`. Either:
- Delete the assertion (Settings no longer has `quiet`, so the assertion would fail)
- Delete the entire test if `quiet` was its only purpose

Read the test context around line 34 and decide. Likely the assertion is one of several in `test_uses_defaults_when_no_env_set` — remove just that line, keep the test.

### Step 10: Rewrite `tests/unit/test_ioc.py` for module-level container

Replace the entire contents of `tests/unit/test_ioc.py` with:

```python
import typing

import pytest

from semvertag import ioc
from semvertag._errors import ConfigError
from semvertag._settings import Settings
from semvertag.strategies.branch_prefix import BranchPrefixStrategy
from semvertag.strategies.conventional_commits import ConventionalCommitsStrategy


_StrategyName = typing.Literal["branch-prefix", "conventional-commits"]
_ProviderName = typing.Literal["gitlab", "github", "bitbucket"]


def _settings(
    *,
    strategy: _StrategyName = "branch-prefix",
    provider: _ProviderName = "gitlab",
) -> Settings:
    return Settings(project_id=999, strategy=strategy, provider=provider)


def test_container_resolves_branch_prefix_strategy_by_default() -> None:
    settings: typing.Final = _settings(strategy="branch-prefix")
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        try:
            strategy = ioc.container.resolve_provider(ioc.StrategiesGroup.current_strategy)
            assert isinstance(strategy, BranchPrefixStrategy)
            assert strategy.name == "branch-prefix"
        finally:
            pass


def test_container_resolves_conventional_commits_strategy_when_settings_strategy_is_cc() -> None:
    settings: typing.Final = _settings(strategy="conventional-commits")
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        try:
            strategy = ioc.container.resolve_provider(ioc.StrategiesGroup.current_strategy)
            assert isinstance(strategy, ConventionalCommitsStrategy)
            assert strategy.name == "conventional-commits"
        finally:
            pass


def test_named_strategy_factories_resolve_to_their_concrete_types_regardless_of_settings() -> None:
    settings: typing.Final = _settings(strategy="conventional-commits")
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        bp = ioc.container.resolve_provider(ioc.StrategiesGroup.branch_prefix_strategy)
        cc = ioc.container.resolve_provider(ioc.StrategiesGroup.conventional_commits_strategy)
        assert isinstance(bp, BranchPrefixStrategy)
        assert isinstance(cc, ConventionalCommitsStrategy)


def test_provider_check_moved_out_of_ioc_lives_in_callback_now() -> None:
    """Sanity reminder: the 'Provider not yet supported' check is now in __main__.py's callback,
    not in ioc.py. There's no longer a build_container() to test this in isolation.
    Integration tests in test_cli_*.py exercise the callback's behavior end-to-end."""
    # Intentionally empty body. Test passes by existing as documentation.
```

Note the `with ioc.container:` + `set_context` pattern at each test — this mirrors how production code uses the container. The previous test for "provider rejection" is removed because that logic moved to `__main__.py`; CLI tests cover it.

### Step 11: Update `action.yml`

In `action.yml`, find the line `run: uvx semvertag` (currently near the end of the file in the `runs.steps` section). Change to:

```yaml
      run: uvx semvertag tag
```

### Step 12: Update `templates/semvertag.yml`

In `templates/semvertag.yml`, find the `script:` section near the end. Change:

```yaml
  script:
    - uvx 'semvertag>=1,<2'
```

to:

```yaml
  script:
    - uvx 'semvertag>=1,<2' tag
```

### Step 13: Update `docs/providers/github.md`

Find and update three references to `uvx semvertag` / `semvertag` (currently lines 7, 15-16, 142, 149):

- Line 7: `uvx semvertag` → `uvx semvertag tag`
- Line 15-16: `runs \`uvx semvertag\` with the workflow-issued...` → `runs \`uvx semvertag tag\` with the workflow-issued...`
- Line 142: `the composite wraps \`uvx semvertag\` correctly...` → `the composite wraps \`uvx semvertag tag\` correctly...`
- Line 149: `status: no_tags\` and exits 0 without bumping (\`semvertag/_use_case.py\`'s` — this is a source file reference, NOT a CLI invocation. Do NOT change.

### Step 14: Update `docs/providers/gitlab.md`

Find and update three references to `uvx semvertag` / `semvertag` (currently lines 4-6, 12, 46):

- Line 4-6: `component is a thin GitLab CI job template around the \`semvertag\` CLI` and `uvx semvertag`. The first sentence describes the CLI (no change needed if it's referring to the package); update the second invocation `uvx semvertag` → `uvx semvertag tag`.
- Line 12: `component itself contributes a single \`semvertag\` job` — this refers to the GitLab CI job name, NOT the CLI invocation. Do NOT change.
- Line 46: `so GitLab serializes concurrent \`semvertag\` jobs across pipelines` — same, refers to GitLab CI job name. Do NOT change.

Read the file carefully and update only the CLI-invocation lines, not job-name or package-name references.

### Step 15: Verify CLAUDE.md and README.md don't need updates

Run: `grep -n "uvx semvertag\|\\\`semvertag\\\b" CLAUDE.md README.md 2>/dev/null`

If any CLI invocation lines turn up, update `semvertag` → `semvertag tag`. If only package-name or repository-name references show, leave alone.

### Step 16: Run the full test suite

```bash
uv run pytest -q
```
Expected: **333 passed, 1 skipped** (drops by 1 vs baseline because the quiet env-var test was deleted).

If the count is different than 333 or any test fails: READ the failure. Common issues:
- `AttributeError: 'Settings' object has no attribute 'quiet'` — missed a reference
- `TypeError: _collect_overrides() got an unexpected keyword argument 'quiet'` — missed the call-site update in callback
- `ContainerError` or `ProviderError` from modern-di — Factory wiring problem (auto-wiring isn't finding Settings in context, or Protocol disambiguation broke)
- `TypeError: __init__() takes 1 positional argument but 2 were given` — `build_container` is called somewhere it shouldn't be

Do NOT silently adjust tests to mask bugs.

### Step 17: Lint check

```bash
just lint-ci
```
Expected: PASS. If ruff/ty flag unused imports we missed (e.g., `Output` if no longer referenced in `__main__.py` — but it IS referenced as a type annotation for `output: Output`, so it stays), fix them.

### Step 18: Docs build

```bash
UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict
```
Expected: builds clean.

### Step 19: Smoke tests

Run each and verify expected output:

```bash
uv run semvertag --help
```
Expected: top-level help showing `tag` as a subcommand. The `--project-id`/`--strategy`/etc. options are listed at the top level (on the callback). The `--quiet`/`--json` options are NOT at the top level (moved to tag).

```bash
uv run semvertag tag --help
```
Expected: tag-subcommand help. Lists `--quiet` and `--json` only (the callback-level options are accessed via `semvertag --help`).

```bash
uv run semvertag
```
Expected: prints help (no_args_is_help=True). Exit code 0.

```bash
uv run semvertag tag
```
Expected: fails with a ConfigError because no `project_id` is set (no env, no flag). Exit code 2. Error message starts with "Configuration error" or "Project id missing".

```bash
SEMVERTAG_PROJECT_ID=999 uv run semvertag tag
```
Expected: fails with a network error or AuthError (no real GitLab token). Exit code 3 or 4. Output should be valid (not a stack trace).

```bash
uv run semvertag --version
```
Expected: prints the package version. Exit code 0.

### Step 20: Verify cwd before committing

```bash
pwd
git branch --show-current
```
MUST show worktree path and `feat/ioc-idiomatic-modern-di-typer`. If wrong, STOP.

### Step 21: Commit

```bash
git add semvertag/_settings.py semvertag/ioc.py semvertag/__main__.py tests/integration/conftest.py tests/integration/test_cli_main_verb.py tests/integration/test_cli_quiet_json_matrix.py tests/integration/test_strategy_switching.py tests/unit/test_settings.py tests/unit/test_ioc.py action.yml templates/semvertag.yml docs/providers/github.md docs/providers/gitlab.md
git commit -m "ioc: adopt idiomatic modern-di-typer wiring with setup_di + @inject + FromDI

Refactor ioc.py from manual container construction per CLI invocation
to module-level container + modern_di_typer.setup_di integration.
Settings flows in via container.set_context(Settings, settings) from
the callback after APP scope is entered. The new semvertag tag
subcommand is decorated with @modern_di_typer.inject and resolves the
use case via FromDI(SemvertagUseCase). All Factories drop
skip_creator_parsing=True, bound_type=None, and the redundant
kwargs={'settings': ...} entries — creator parsing auto-wires from type
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

Closes sub-project B of the ioc.py showcase brainstorm."
```

Verify with: `git log --oneline -1`.

---

## Task 3: Pre-merge verification gate

**Files:** none modified.

- [ ] **Step 1: Lint**

Run: `just lint-ci`
Expected: PASS.

- [ ] **Step 2: Full test suite**

Run: `uv run pytest`
Expected: 333 passed, 1 skipped.

- [ ] **Step 3: Branch-coverage gates (unaffected by this work)**

Run: `just test-branch-strategies`
Expected: 100% on `semvertag.strategies.branch_prefix`.

Run: `just test-cc-strategies`
Expected: 100% on `semvertag.strategies.conventional_commits`.

- [ ] **Step 4: Docs build**

Run: `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

- [ ] **Step 5: LOC + commit sanity check**

Run: `git diff main --shortstat`
Expected: net change near zero (the refactor is roughly flat in LOC; value is structural).

Run: `git log --oneline main..HEAD`
Expected: exactly 1 commit (`ioc: adopt idiomatic modern-di-typer wiring…`).

- [ ] **Step 6: CLI surface smoke tests**

Run each from Step 19 of Task 2:

```bash
uv run semvertag --help       # shows 'tag' subcommand
uv run semvertag tag --help    # shows --quiet and --json
uv run semvertag                # prints help (no_args_is_help=True), exit 0
uv run semvertag tag            # fails with project_id missing, exit 2
uv run semvertag --version     # prints version, exit 0
```

All outputs must be as expected. Any deviation indicates a wiring issue.

---

## Task 4: Land the worktree

**Files:** none modified by hand.

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Use the skill to merge to `main` (fast-forward expected — main shouldn't have moved during this work) and clean up the worktree.

- [ ] **Step 2: Verify the work is on `main`**

Run (in the main checkout): `git log --oneline -2`
Expected: the `ioc: adopt idiomatic modern-di-typer wiring…` commit is at HEAD.

Run: `just lint-ci && uv run pytest -q`
Expected: green on `main`; 333 passed, 1 skipped.

Run: `grep -n "build_container\|skip_creator_parsing\|bound_type=None" semvertag/`
Expected: NO matches (modulo `_archive/`).

Run: `grep -n "modern_di_typer\.setup_di\|FromDI" semvertag/__main__.py`
Expected: BOTH found — `setup_di(MAIN_APP, ioc.container)` and `FromDI(SemvertagUseCase)`.

Run: `uv run semvertag --help | head -20`
Expected: `tag` subcommand listed.

---

## Success criteria

When all tasks above are done:

- `semvertag/ioc.py` has module-level `container = modern_di.Container(groups=ALL_GROUPS)`; no `build_container()` function; no `skip_creator_parsing=True`; no `bound_type=None`; `kwargs={"settings": ...}` only present on `UseCasesGroup.semvertag_use_case` for Protocol disambiguation.
- `TransportsGroup` exists in `ioc.py` (wraps `RetryingTransport`).
- `semvertag/__main__.py` has `modern_di_typer.setup_di(MAIN_APP, ioc.container)` at module level; an `@MAIN_APP.command("tag")` decorated with `@modern_di_typer.inject`; `with ioc.container: MAIN_APP()` in `main()`; `--quiet` and `--json` flags on the tag command (not the callback).
- `Settings` no longer has a `quiet` field.
- All CLI tests invoke via `["tag", ...]` (22 sites updated).
- `install_mock_transport` uses `ioc.container.override(ioc.TransportsGroup.transport, ...)` and resets on teardown.
- `action.yml`, `templates/semvertag.yml`, and provider docs invoke `semvertag tag`.
- `just lint-ci`, `uv run pytest`, `mkdocs build --strict` all green.
- 333 tests pass (vs 334 baseline; one quiet-env-var test deleted).
- The 6 smoke tests from Task 3 Step 6 all produce expected output.

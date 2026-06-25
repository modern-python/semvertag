# `SemvertagUseCase` Callable Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `SemvertagUseCase` a callable whose dependencies (`provider`, `strategy`) are bound at `__init__` and whose per-invocation state (`output`) arrives via `__call__(*, output: Output)`, eliminating the `_run_with_output_override` hack in `__main__.py` and `OutputsGroup` in `ioc.py`.

**Architecture:** Single atomic commit on one worktree. Use case shape change and DI wiring change are tightly coupled — they have to land together to keep the build green. ~6 file edits, ~-35 LOC net, no behavior change to the CLI surface.

**Tech Stack:** Existing — `pydantic`, `pydantic-settings`, `modern-di`, `typer`, `httpx2`, `pytest`. No new deps.

**Spec:** `planning/specs/2026-05-31-usecase-callable-design.md`

---

## Task 1: Spawn worktree and verify baseline

**Files:** none in main checkout.

- [ ] **Step 1: Spawn the worktree**

Use the `superpowers:using-git-worktrees` skill. Suggested branch: `feat/usecase-callable`. Suggested path: `.worktrees/feat-usecase-callable`.

- [ ] **Step 2: Verify clean baseline inside the worktree**

Run (inside the worktree, after `cd` and `uv sync --all-extras --group lint`):

```bash
pwd
git branch --show-current
git status
```

Expected: cwd is `/Users/kevinsmith/src/pypi/autosemver/.worktrees/feat-usecase-callable`, branch is `feat/usecase-callable`, status clean.

Run: `just lint-ci`
Expected: PASS.

Run: `uv run pytest -q`
Expected: 334 passed, 1 skipped.

Run: `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean. (`UV_OFFLINE=1` because PyPI may time out fetching mkdocs-material; the cached version works fine.)

If any baseline check fails, stop and report — main is not in the expected post-settings-aliaschoices state.

---

## Task 2: Atomic refactor in one commit

The use case shape change (drop `output` field, rename `run` → `__call__`, take `output` as param) and the DI wiring change (drop `OutputsGroup`, drop `json=` from `build_container`) are tightly coupled. They land in one commit because partial state would break the build.

**Files:**
- Modify: `semvertag/_use_case.py`
- Modify: `semvertag/ioc.py`
- Modify: `semvertag/__main__.py`
- Modify: `tests/unit/test_use_case.py`
- Modify: `tests/integration/conftest.py`
- Modify: `tests/integration/test_cli_quiet_json_matrix.py`

### CRITICAL: verify cwd before any git operation

Before EVERY `git rm`, `git add`, `git commit`, run:

```bash
pwd
git branch --show-current
```

The output MUST show:
- pwd: `/Users/kevinsmith/src/pypi/autosemver/.worktrees/feat-usecase-callable`
- branch: `feat/usecase-callable`

If either is wrong, STOP. Two previous plans had implementers accidentally commit to main; do not repeat that.

### Step 1: Refactor `semvertag/_use_case.py`

Edit `semvertag/_use_case.py`. The current `SemvertagUseCase` class body (around lines 18-91) needs three coordinated changes:

1. **Drop the `output: Output` field** (currently line 22):
   ```python
   # DELETE this line:
       output: Output
   ```

2. **Rename `def run(self) -> RunResult:` (line 24) to `def __call__(self, *, output: Output) -> RunResult:`**.

3. **Replace `self.output.*` with `output.*` throughout the method body**. There are 4 call sites in `run()`:
   - Line 25: `self.output.progress(f"Detected strategy: {self.strategy.name}")` → `output.progress(...)`
   - Line 26: `self.output.progress("Fetching latest commit on default branch...")` → `output.progress(...)`
   - Line 29: `self.output.progress("Fetching tag history...")` → `output.progress(...)`
   - Line 51: `self.output.progress("Computing bump...")` → `output.progress(...)`
   - Line 63: `self.output.progress(f"Creating tag {new_version}...")` → `output.progress(...)`

4. **Update `_emit` helper to take `output` as a parameter** (currently lines 73-91). The current signature:

   ```python
       def _emit(
           self,
           *,
           bump: Bump,
           status: str,
           tag: str | None,
           commit: str | None,
           reason: str | None,
       ) -> RunResult:
           result: typing.Final = RunResult(
               strategy=self.strategy.name,
               bump=bump.value,
               status=status,
               tag=tag,
               commit=commit,
               reason=reason,
           )
           self.output.emit(result)
           return result
   ```

   Change to:

   ```python
       def _emit(
           self,
           *,
           output: Output,
           bump: Bump,
           status: str,
           tag: str | None,
           commit: str | None,
           reason: str | None,
       ) -> RunResult:
           result: typing.Final = RunResult(
               strategy=self.strategy.name,
               bump=bump.value,
               status=status,
               tag=tag,
               commit=commit,
               reason=reason,
           )
           output.emit(result)
           return result
   ```

5. **Update the 5 `self._emit(...)` call sites in `__call__`** to pass `output=output`. Each call currently looks like:

   ```python
   return self._emit(
       bump=Bump.NONE,
       status="no_tags",
       tag=None,
       commit=commit.sha,
       reason=_NO_TAGS_REASON,
   )
   ```

   becomes:

   ```python
   return self._emit(
       output=output,
       bump=Bump.NONE,
       status="no_tags",
       tag=None,
       commit=commit.sha,
       reason=_NO_TAGS_REASON,
   )
   ```

   All 5 `self._emit(...)` calls in the body need this.

The final shape of `SemvertagUseCase` should look like:

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class SemvertagUseCase:
    provider: Provider
    strategy: BumpStrategy

    def __call__(self, *, output: Output) -> RunResult:
        output.progress(f"Detected strategy: {self.strategy.name}")
        output.progress("Fetching latest commit on default branch...")
        commit: typing.Final = self.provider.get_latest_commit_on_default_branch()

        output.progress("Fetching tag history...")
        tags: typing.Final = self.provider.list_tags()
        latest_semver_tag: typing.Final = _pick_latest_semver_tag(tags)

        if latest_semver_tag is None:
            return self._emit(
                output=output,
                bump=Bump.NONE,
                status="no_tags",
                tag=None,
                commit=commit.sha,
                reason=_NO_TAGS_REASON,
            )

        if latest_semver_tag.commit_sha == commit.sha:
            return self._emit(
                output=output,
                bump=Bump.NONE,
                status="already_tagged",
                tag=latest_semver_tag.name,
                commit=commit.sha,
                reason=_ALREADY_TAGGED_REASON,
            )

        output.progress("Computing bump...")
        bump: typing.Final = self.strategy.decide(commit)
        if bump is Bump.NONE:
            return self._emit(
                output=output,
                bump=Bump.NONE,
                status=_status_for_no_bump(self.strategy.name),
                tag=None,
                commit=commit.sha,
                reason=_reason_for_no_bump(self.strategy.name),
            )

        new_version: typing.Final = _compute_new_version(latest_semver_tag, bump)
        output.progress(f"Creating tag {new_version}...")
        self.provider.create_tag(name=new_version, commit_sha=commit.sha)
        return self._emit(
            output=output,
            bump=bump,
            status="created",
            tag=new_version,
            commit=commit.sha,
            reason=None,
        )

    def _emit(
        self,
        *,
        output: Output,
        bump: Bump,
        status: str,
        tag: str | None,
        commit: str | None,
        reason: str | None,
    ) -> RunResult:
        result: typing.Final = RunResult(
            strategy=self.strategy.name,
            bump=bump.value,
            status=status,
            tag=tag,
            commit=commit,
            reason=reason,
        )
        output.emit(result)
        return result
```

Imports stay (`from semvertag._output import Output` still needed for the parameter annotation). Module-level helpers (`_pick_latest_semver_tag`, `_parse_semver_tags`, `_try_parse_semver`, `_compute_new_version`, `_status_for_no_bump`, `_reason_for_no_bump`) and constants (`_NO_MERGE_REASON`, `_NO_CONFORMING_REASON`, `_NO_TAGS_REASON`, `_ALREADY_TAGGED_REASON`) stay unchanged.

### Step 2: Refactor `semvertag/ioc.py`

Five coordinated edits to `semvertag/ioc.py`:

1. **Drop the 4 output-related imports** from the import at the top:

   ```python
   # Before:
   from semvertag._output import JsonOutput, RichOutput, build_json_output, build_rich_output
   # Delete this line entirely.
   ```

2. **Delete `_build_rich_output` and `_build_json_output` factory functions** (currently lines 21-26):

   ```python
   def _build_rich_output(settings: Settings) -> RichOutput:
       return build_rich_output(quiet=settings.quiet)


   def _build_json_output(settings: Settings) -> JsonOutput:
       return build_json_output(quiet=settings.quiet)
   ```

3. **Delete the entire `OutputsGroup` class** (currently lines 87-101):

   ```python
   class OutputsGroup(modern_di.Group):
       rich_output = providers.Factory(
           scope=Scope.APP,
           creator=_build_rich_output,
           kwargs={"settings": SettingsGroup.settings},
           skip_creator_parsing=True,
           bound_type=None,
       )
       json_output = providers.Factory(
           scope=Scope.APP,
           creator=_build_json_output,
           kwargs={"settings": SettingsGroup.settings},
           skip_creator_parsing=True,
           bound_type=None,
       )
   ```

4. **Drop `"output": OutputsGroup.rich_output` from `UseCasesGroup.semvertag_use_case` kwargs**. The current `kwargs` dict (around lines 143-147):

   ```python
           kwargs={
               "provider": ProvidersGroup.gitlab_provider,
               "strategy": StrategiesGroup.current_strategy,
               "output": OutputsGroup.rich_output,
           },
   ```

   becomes:

   ```python
           kwargs={
               "provider": ProvidersGroup.gitlab_provider,
               "strategy": StrategiesGroup.current_strategy,
           },
   ```

5. **Remove `OutputsGroup` from `ALL_GROUPS`** (currently lines 153-159):

   ```python
   # Before:
   ALL_GROUPS: typing.Final[list[type[modern_di.Group]]] = [
       SettingsGroup,
       OutputsGroup,
       ProvidersGroup,
       StrategiesGroup,
       UseCasesGroup,
   ]
   # After:
   ALL_GROUPS: typing.Final[list[type[modern_di.Group]]] = [
       SettingsGroup,
       ProvidersGroup,
       StrategiesGroup,
       UseCasesGroup,
   ]
   ```

6. **Remove `OutputsGroup` from `__all__`** (currently lines 184-192):

   ```python
   # Before:
   __all__: typing.Final = (
       "ALL_GROUPS",
       "OutputsGroup",
       "ProvidersGroup",
       "SettingsGroup",
       "StrategiesGroup",
       "UseCasesGroup",
       "build_container",
   )
   # After:
   __all__: typing.Final = (
       "ALL_GROUPS",
       "ProvidersGroup",
       "SettingsGroup",
       "StrategiesGroup",
       "UseCasesGroup",
       "build_container",
   )
   ```

7. **Drop the `json` parameter and the override block from `build_container`** (currently lines 162-181). The current function:

   ```python
   def build_container(
       settings: Settings,
       *,
       json: bool = False,
       inner_transport: httpx2.BaseTransport | None = None,
   ) -> modern_di.Container:
       if settings.provider != "gitlab":
           msg = f"Provider {settings.provider!r} not yet supported; v1.0 supports gitlab only."
           raise ConfigError(msg)
       container: typing.Final = modern_di.Container(
           groups=ALL_GROUPS,
           context={Settings: settings},
       )
       if inner_transport is not None:
           provider_instance: typing.Final = _construct_gitlab_provider(settings, inner_transport)
           container.override(ProvidersGroup.gitlab_provider, provider_instance)
       if json:
           json_instance: typing.Final = _build_json_output(settings)
           container.override(OutputsGroup.rich_output, json_instance)
       return container
   ```

   becomes:

   ```python
   def build_container(
       settings: Settings,
       *,
       inner_transport: httpx2.BaseTransport | None = None,
   ) -> modern_di.Container:
       if settings.provider != "gitlab":
           msg = f"Provider {settings.provider!r} not yet supported; v1.0 supports gitlab only."
           raise ConfigError(msg)
       container: typing.Final = modern_di.Container(
           groups=ALL_GROUPS,
           context={Settings: settings},
       )
       if inner_transport is not None:
           provider_instance: typing.Final = _construct_gitlab_provider(settings, inner_transport)
           container.override(ProvidersGroup.gitlab_provider, provider_instance)
       return container
   ```

### Step 3: Refactor `semvertag/__main__.py`

Three coordinated edits:

1. **Delete `_run_with_output_override`** (currently around lines 286-287):

   ```python
   def _run_with_output_override(use_case: SemvertagUseCase, output: Output) -> None:
       dataclasses.replace(use_case, output=output).run()
   ```

   Delete the entire function plus any blank line around it that would otherwise create a double-blank.

2. **Replace the single call site** (currently line 153 in `_main_callback`):

   ```python
   # Before:
               _run_with_output_override(use_case, output)
   # After:
               use_case(output=output)
   ```

3. **Drop `json=json_flag` from the `build_container` call** (currently line 150 in `_main_callback`):

   ```python
   # Before:
           container = ioc.build_container(settings, json=json_flag)
   # After:
           container = ioc.build_container(settings)
   ```

4. **Check for unused imports**. After deleting `_run_with_output_override`, run:

   ```bash
   grep -n "SemvertagUseCase\|^from semvertag._use_case\|^import dataclasses" semvertag/__main__.py
   ```

   - If `SemvertagUseCase` is no longer referenced anywhere in `__main__.py` (it was only used by `_run_with_output_override`'s type hint), drop the `from semvertag._use_case import SemvertagUseCase` line.
   - `dataclasses` was used by `_run_with_output_override` via `dataclasses.replace`. If `dataclasses` is referenced nowhere else in `__main__.py`, drop the `import dataclasses` line. Verify with the grep first.

### Step 4: Refactor `tests/unit/test_use_case.py`

Two edits to the test factory + a sweep of `use_case.run()` call sites:

1. **Update `_make_use_case` factory** (currently lines 81-100). Drop `output` from the `SemvertagUseCase(...)` construction:

   ```python
   # Before:
       use_case: typing.Final = SemvertagUseCase(
           provider=typing.cast("typing.Any", provider),
           strategy=typing.cast("typing.Any", strategy),
           output=typing.cast("Output", output),
       )
       return use_case, provider, output
   # After:
       use_case: typing.Final = SemvertagUseCase(
           provider=typing.cast("typing.Any", provider),
           strategy=typing.cast("typing.Any", strategy),
       )
       return use_case, provider, output
   ```

   (Keep the `output` local variable + the return tuple — tests still use it; it just gets passed at call time now.)

2. **Update all `use_case.run()` call sites** to `use_case(output=output)`. There are multiple — find them with:

   ```bash
   grep -n "use_case\.run()" tests/unit/test_use_case.py
   ```

   For each match, the call pattern is one of:

   ```python
   # Pattern A — output captured from factory:
   use_case, provider, output = _make_use_case(...)
   result: typing.Final = use_case.run()
   # Change to:
   result: typing.Final = use_case(output=output)
   ```

   ```python
   # Pattern B — output discarded from factory (_output):
   use_case, _provider, _output = _make_use_case(...)
   result: typing.Final = use_case.run()
   # Change to (rename _output → output so it can be passed in):
   use_case, _provider, output = _make_use_case(...)
   result: typing.Final = use_case(output=output)
   ```

   Inspect each test to determine which pattern applies. Some tests deliberately discard `output` because they don't assert on it — for those, the `_output` → `output` rename is enough; the assertion sections don't need to change.

### Step 5: Update `tests/integration/conftest.py`

The `install_mock_transport` fixture (lines 55-69) calls `real_build_container(settings, json=json, inner_transport=transport)` and exposes a `json` parameter on its `patched` shim. After dropping `json=` from `build_container`, this fixture must change:

Replace lines 55-69 with:

```python
@pytest.fixture
def install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> collections.abc.Callable[[HandlerCallable], None]:
    real_build_container: typing.Final = ioc.build_container

    def install(handler: HandlerCallable) -> None:
        transport: typing.Final = httpx2.MockTransport(handler)

        def patched(settings: Settings) -> typing.Any:  # noqa: ANN401
            return real_build_container(settings, inner_transport=transport)

        monkeypatch.setattr(ioc, "build_container", patched)

    return install
```

Changes:
- `patched` signature drops the `json: bool = False` parameter
- `real_build_container` call drops `json=json`

### Step 6: Update `tests/integration/test_cli_quiet_json_matrix.py`

The test at line 107-124 monkey-patches `SemvertagUseCase.run` to simulate failure. After renaming `run` → `__call__`, this needs updating.

Find the current code (around lines 115-119):

```python
    def raising_run(self: SemvertagUseCase) -> typing.Any:  # noqa: ANN401, ARG001
        msg = "synthetic generic failure for AC9."
        raise SemvertagError(msg)

    monkeypatch.setattr(SemvertagUseCase, "run", raising_run)
```

Replace with:

```python
    def raising_call(self: SemvertagUseCase, *, output: Output) -> typing.Any:  # noqa: ANN401, ARG001
        msg = "synthetic generic failure for AC9."
        raise SemvertagError(msg)

    monkeypatch.setattr(SemvertagUseCase, "__call__", raising_call)
```

If `Output` is not already imported at the top of the file, add `from semvertag._output import Output` to the imports. Check with:

```bash
grep -n "from semvertag._output\|^import.*Output\|Output," tests/integration/test_cli_quiet_json_matrix.py
```

### Step 7: Run the full test suite

Run: `uv run pytest -q`
Expected: 334 passed, 1 skipped. **No tests added or removed.** If the count changed, something else broke.

If any test fails: READ the failure. Common patterns to expect:
- `TypeError: SemvertagUseCase.__init__() got an unexpected keyword argument 'output'` — missed a `_make_use_case` factory call or an `ioc.py` kwargs entry
- `AttributeError: 'SemvertagUseCase' object has no attribute 'run'` — missed a `use_case.run()` call site
- `TypeError: __call__() missing 1 required keyword-only argument: 'output'` — missed adding `output=output` at a call site

DO NOT silently adjust tests to mask bugs. If a real behavior change snuck in, surface it.

### Step 8: Targeted test verification

Run: `uv run pytest tests/unit/test_use_case.py -v`
Expected: ALL tests PASS (the file with the most-affected surface).

Run: `uv run pytest tests/integration/test_cli_quiet_json_matrix.py -v`
Expected: ALL tests PASS (the monkeypatch target changed).

Run: `uv run pytest tests/integration/test_cli_main_verb.py tests/integration/test_strategy_switching.py -v`
Expected: ALL tests PASS (they go through the full CLI; should be unaffected if the wiring is correct).

### Step 9: Lint check

Run: `just lint-ci`
Expected: PASS (eof-fixer, ruff format check, ruff check, ty check). If ruff flags any unused imports we missed (e.g. `dataclasses` or `SemvertagUseCase` in `__main__.py`), run `just lint` (auto-fix) and re-run `just lint-ci`.

### Step 10: Docs build

Run: `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

### Step 11: Smoke test the CLI surface

Run: `uv run semvertag --help`
Expected: same `--help` output as `main` (the CLI surface didn't change). Spot-check that `--json` and `--quiet` flags are still listed.

### Step 12: Verify cwd before committing

```bash
pwd
git branch --show-current
```

The output MUST show the worktree path and branch `feat/usecase-callable`. If anything is wrong, STOP.

### Step 13: Commit

```bash
git add semvertag/_use_case.py semvertag/ioc.py semvertag/__main__.py tests/unit/test_use_case.py tests/integration/conftest.py tests/integration/test_cli_quiet_json_matrix.py
git commit -m "use_case: separate init from invocation; pass output to __call__

SemvertagUseCase becomes a callable whose dependencies (provider,
strategy) are bound at init and whose per-invocation state (output)
arrives via __call__(*, output: Output). The renamed __call__ replaces
the previous .run() method.

This eliminates _run_with_output_override in __main__.py (the
dataclasses.replace hack that swapped the use case's output post-
construction) and OutputsGroup in ioc.py (output is no longer a DI'd
dependency — it's a per-call helper built by the CLI from --json /
--quiet flags).

Sets up sub-project B (idiomatic modern-di-typer wiring) by removing
the per-invocation override that prevented adopting setup_di / @inject
/ FromDI."
```

---

## Task 3: Pre-merge verification gate

**Files:** none modified.

- [ ] **Step 1: Lint**

Run: `just lint-ci`
Expected: PASS.

- [ ] **Step 2: Full test suite**

Run: `uv run pytest`
Expected: 334 passed, 1 skipped.

- [ ] **Step 3: Branch-coverage gates**

Run: `just test-branch-strategies`
Expected: 100% on `semvertag.strategies.branch_prefix`.

Run: `just test-cc-strategies`
Expected: 100% on `semvertag.strategies.conventional_commits`.

- [ ] **Step 4: Docs build**

Run: `UV_OFFLINE=1 uv run --with-requirements docs/requirements.txt mkdocs build --strict`
Expected: builds clean.

- [ ] **Step 5: LOC + commit sanity check**

Run: `git diff main --stat`
Expected: net negative ~30-40 LOC across the 6 touched files.

Run: `git log --oneline main..HEAD`
Expected: exactly 1 commit (`use_case: separate init from invocation…`).

- [ ] **Step 6: Smoke-test the CLI behavior**

Run: `uv run semvertag --help`
Expected: same `--help` output as main. `--json` and `--quiet` still listed.

Run: `uv run semvertag --version 2>&1 | head -1`
Expected: a version string is printed (regardless of value).

---

## Task 4: Land the worktree

**Files:** none modified by hand.

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Use the skill to merge to `main` (fast-forward expected — main shouldn't have moved during this work) and clean up the worktree.

- [ ] **Step 2: Verify the work is on `main`**

Run (in the main checkout): `git log --oneline -2`
Expected: the `use_case: separate init from invocation…` commit is at HEAD.

Run: `just lint-ci && uv run pytest -q`
Expected: green on `main`.

Run: `grep -n "_run_with_output_override\|OutputsGroup" semvertag/`
Expected: NO matches (modulo `_archive/`).

Run: `grep -n "use_case\.run\b" semvertag/ tests/`
Expected: NO matches (modulo `_archive/`).

---

## Success criteria

When all tasks above are done:

- `SemvertagUseCase` has no `output` field; its only callable is `__call__(*, output: Output) -> RunResult` (no `.run()` method remains).
- `_run_with_output_override` is deleted from `semvertag/__main__.py`.
- `OutputsGroup` is deleted from `semvertag/ioc.py`; `ALL_GROUPS` has 4 groups (Settings, Providers, Strategies, UseCases); `__all__` no longer exports `OutputsGroup`.
- `build_container` no longer accepts a `json=` parameter.
- All 334 tests pass; the smoke test confirms CLI surface is unchanged.
- `_use_case.py`, `__main__.py`, and `ioc.py` are all slightly shorter and cleaner.
- `tests/integration/conftest.py`'s `install_mock_transport` fixture no longer takes or passes a `json` parameter.
- `tests/integration/test_cli_quiet_json_matrix.py` patches `SemvertagUseCase.__call__` (not `.run`) with an output-accepting signature.

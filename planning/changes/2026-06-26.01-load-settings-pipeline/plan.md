# load-settings-pipeline — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the env→CLI→validate→token settings pipeline behind one
public `load_settings` entry point in `semvertag/_settings.py` that raises only
`ConfigError`, shrinking `__main__` to flag-collection + error-to-exit mapping.

**Spec:** [`design.md`](./design.md)

**Branch:** `refactor/load-settings-pipeline`

**Commit strategy:** Per-task commits.

## Global Constraints

- Python imports at module level only — never inside function bodies.
- Annotate every test function argument (including fixtures).
- `just test` runs pytest with `--cov-branch` and `fail_under = 100`: every new
  branch must be covered.
- `just lint-ci` is check-only and runs the planning validator
  (`just check-planning`); `just lint` autofixes.
- Behavior-preserving: no change to `Settings` fields/validators/aliases,
  precedence semantics, the `Provider` protocol, or process exit codes.
- The `ioc._build_current_provider` asserts stay untouched (out of scope).

---

### Task 1: Add `load_settings` (additive) with its unit test surface

**Files:**
- Modify: `semvertag/_settings.py`
- Test: `tests/unit/test_settings.py`

**Interfaces:**
- Consumes: existing `Settings`, `apply_cli_overlay` (still public at this point),
  `pydantic`, and `semvertag._errors.ConfigError`.
- Produces: `load_settings(cli_overrides: dict[str, typing.Any], *, token: str | None = None) -> Settings`
  and module-private `_config_error_from_validation(exc: pydantic.ValidationError) -> ConfigError`.

This task is purely additive — `apply_cli_overlay` stays public and `__main__` is
untouched, so nothing breaks. `load_settings` replicates `__main__`'s current
orchestration so its tests characterize today's behavior.

- [ ] **Step 1: Write the failing tests**

  Add the two imports to the **module-level import block** at the top of
  `tests/unit/test_settings.py` (not inside the appended block — imports stay at
  module level): `from semvertag._errors import ConfigError` and add
  `load_settings` to the existing `from semvertag._settings import ...` line.
  Then append the test functions:

  ```python
  @pytest.mark.usefixtures("clean_settings_env")
  def test_load_settings_cli_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
      monkeypatch.setenv("SEMVERTAG_STRATEGY", "conventional-commits")
      settings = load_settings({"strategy": "branch-prefix", "provider": "gitlab", "project_id": 1})
      assert settings.strategy == "branch-prefix"


  @pytest.mark.usefixtures("clean_settings_env")
  def test_load_settings_uses_defaults_when_unset() -> None:
      settings = load_settings({"provider": "gitlab", "project_id": 1})
      assert settings.request_timeout == _TIMEOUT_DEFAULT_VALUE


  @pytest.mark.usefixtures("clean_settings_env")
  def test_load_settings_routes_token_to_explicit_github() -> None:
      settings = load_settings({"provider": "github", "repo": "o/r"}, token=_PLAINTEXT_SECRET)
      assert settings.github.token.get_secret_value() == _PLAINTEXT_SECRET
      assert settings.gitlab.token.get_secret_value() == ""


  @pytest.mark.usefixtures("clean_settings_env")
  def test_load_settings_routes_token_to_explicit_gitlab() -> None:
      settings = load_settings({"provider": "gitlab", "project_id": 1}, token=_PLAINTEXT_SECRET)
      assert settings.gitlab.token.get_secret_value() == _PLAINTEXT_SECRET


  @pytest.mark.usefixtures("clean_settings_env")
  def test_load_settings_routes_token_to_autodetected_provider(monkeypatch: pytest.MonkeyPatch) -> None:
      monkeypatch.delenv("GITLAB_CI", raising=False)
      monkeypatch.setenv("GITHUB_ACTIONS", "true")
      settings = load_settings({"repo": "o/r"}, token=_PLAINTEXT_SECRET)
      assert settings.provider == "github"
      assert settings.github.token.get_secret_value() == _PLAINTEXT_SECRET


  @pytest.mark.usefixtures("clean_settings_env")
  def test_load_settings_translates_validation_error_to_config_error() -> None:
      with pytest.raises(ConfigError):
          load_settings({"provider": "gitlab"})  # gitlab requires project_id


  @pytest.mark.usefixtures("clean_settings_env")
  def test_load_settings_translates_overlay_value_error_to_config_error() -> None:
      with pytest.raises(ConfigError):
          load_settings({"provider": "gitlab", "project_id": 1, "gitlab.foo.bar": "x"})
  ```

- [ ] **Step 2: Run the tests to verify they fail**

  Run: `just test tests/unit/test_settings.py -q`
  Expected: FAIL — `ImportError: cannot import name 'load_settings'`.

- [ ] **Step 3: Implement `load_settings` and the relocated translator**

  In `semvertag/_settings.py`, add the import near the top
  (`from semvertag._errors import ConfigError` — `_errors` imports nothing from
  `semvertag`, so no cycle) and append:

  ```python
  def _config_error_from_validation(exc: pydantic.ValidationError) -> ConfigError:
      first: typing.Final = exc.errors()[0]
      loc: typing.Final = ".".join(str(part) for part in first.get("loc", ()))
      detail: typing.Final = first.get("msg", "invalid value")
      msg: typing.Final = (
          f"Configuration error at '{loc}': {detail}. Check environment variables and command-line flags."
      )
      return ConfigError(msg)


  def load_settings(cli_overrides: dict[str, typing.Any], *, token: str | None = None) -> Settings:
      """Build a validated Settings from environment + CLI overrides.

      Owns the whole pipeline: split top-level vs dotted once, construct (env +
      top-level), overlay nested, then route --token to the resolved provider.
      Raises only ConfigError on any invalid input.
      """
      top_overrides: typing.Final = {k: v for k, v in cli_overrides.items() if "." not in k}
      nested_overrides: typing.Final = {k: v for k, v in cli_overrides.items() if "." in k}
      try:
          settings = Settings(**top_overrides)
          settings = apply_cli_overlay(settings, nested_overrides)
          if token is not None:
              settings = apply_cli_overlay(settings, {f"{settings.provider}.token": pydantic.SecretStr(token)})
      except pydantic.ValidationError as exc:
          raise _config_error_from_validation(exc) from exc
      except ValueError as exc:  # _apply_cli_overlay depth-2 guard; ValidationError caught above
          raise ConfigError(str(exc)) from exc
      return settings
  ```

  Note: `pydantic.ValidationError` subclasses `ValueError`, so the
  `ValidationError` arm must precede the `ValueError` arm.

- [ ] **Step 4: Run the tests to verify they pass**

  Run: `just test tests/unit/test_settings.py -q`
  Expected: PASS, all new tests green.

- [ ] **Step 5: Commit**

  ```bash
  git add semvertag/_settings.py tests/unit/test_settings.py
  git commit -m "settings: add load_settings pipeline entry point"
  ```

---

### Task 2: Rewire `__main__` to `load_settings`; privatize the overlay

**Files:**
- Modify: `semvertag/__main__.py`
- Modify: `semvertag/_settings.py`
- Modify: `tests/unit/test_settings.py:163-172` (overlay tests)
- Modify: `tests/integration/test_cli_errors.py:95-107`

**Interfaces:**
- Consumes: `load_settings` from Task 1.
- Produces: `_apply_cli_overlay` (renamed from `apply_cli_overlay`, now private);
  `__main__` no longer exports `apply_cli_overlay` or `_config_error_from_validation`.

Swap the CLI orchestration for a single `load_settings` call, then privatize the
overlay now that nothing public calls it. The existing CLI/integration precedence
tests must stay green — that is the behavior-preservation proof.

- [ ] **Step 1: Replace the orchestration block in `_main_callback`**

  In `semvertag/__main__.py`, replace lines 136-155 (the
  `top_overrides`/`Settings(**...)`/`apply_cli_overlay`/token/except block) with:

  ```python
      try:
          settings = load_settings(overrides, token=token)
      except ConfigError as err:
          typer.echo(f"Error: {err}", err=True)
          raise typer.Exit(code=err.exit_code) from err
  ```

  Delete `_config_error_from_validation` (lines 70-75) — it now lives in
  `_settings.py`. Update the import on line 11 to
  `from semvertag._settings import Settings, load_settings`. Remove
  `import pydantic` (line 5) if no other use remains (the `SecretStr` wrap moved
  into `load_settings`; verify with `grep -n pydantic semvertag/__main__.py`).

- [ ] **Step 2: Privatize the overlay**

  In `semvertag/_settings.py`, rename `apply_cli_overlay` → `_apply_cli_overlay`
  and update the two call sites inside `load_settings`.

- [ ] **Step 3: Update the overlay's direct tests**

  In `tests/unit/test_settings.py`: change the import on line 6 to drop
  `apply_cli_overlay`, and in the two tests at lines 163-172 call
  `_apply_cli_overlay` (import it: `from semvertag._settings import _apply_cli_overlay`).
  Rename those two tests' bodies' calls accordingly.

- [ ] **Step 4: Retarget the integration monkeypatch**

  In `tests/integration/test_cli_errors.py:104`, change the patch target to the
  new private name in its home module:

  ```python
      monkeypatch.setattr("semvertag._settings._apply_cli_overlay", raise_value_error)
  ```

- [ ] **Step 5: Run the full suite**

  Run: `just test -q`
  Expected: PASS — all unit, integration, and CLI tests green (behavior
  preserved). If `import pydantic` was left unused, ruff (`just lint-ci`) flags it.

- [ ] **Step 6: Commit**

  ```bash
  git add semvertag/__main__.py semvertag/_settings.py tests/unit/test_settings.py tests/integration/test_cli_errors.py
  git commit -m "settings: route CLI through load_settings; privatize overlay"
  ```

---

### Task 3: Promote architecture, prune redundant coverage, finalize bundle

**Files:**
- Modify: `architecture/cli.md` (the "Settings" section)
- Modify: `tests/integration/` (prune precedence-only assertions now unit-covered)
- Modify: `planning/changes/2026-06-26.01-load-settings-pipeline/design.md` (finalize `summary`)

Promote the living truth and remove integration assertions that only existed to
prove precedence (now owned by the `load_settings` unit tests). Keep one
integration assertion that the CLI wires `load_settings` → DI.

- [ ] **Step 1: Update `architecture/cli.md`**

  In the "Settings" section, replace the description of `apply_cli_overlay` and the
  two-pass token routing with: env + CLI flow funnels through `load_settings`, the
  single entry point that splits top-level vs dotted overrides, constructs +
  overlays + routes `--token` to the resolved provider, and raises only
  `ConfigError`. Note the overlay is now an internal helper (`_apply_cli_overlay`).

- [ ] **Step 2: Prune redundant integration assertions**

  Run: `grep -rn "strategy ==\|request_timeout\|precedence\|overrides env" tests/integration/`
  Remove assertions in the CLI integration tests that only re-prove precedence /
  token routing (now covered by Task 1's unit tests). Keep tests that prove the
  CLI→DI wiring and exit-code mapping. Run `just test -q` after each removal to
  confirm coverage stays at 100% (`fail_under` will fail the run if a removal drops
  a branch — restore it if so).

- [ ] **Step 3: Finalize the bundle summary**

  Edit `design.md` frontmatter `summary:` to state the realized result (what
  shipped and its effect), per the planning convention.

- [ ] **Step 4: Run all gates**

  Run: `just lint-ci && just test && just docs-build`
  Expected: lint clean, tests pass at 100% branch coverage, planning validator
  passes (`just check-planning`), strict mkdocs build succeeds.

- [ ] **Step 5: Commit**

  ```bash
  git add architecture/cli.md tests/integration planning/changes/2026-06-26.01-load-settings-pipeline/design.md
  git commit -m "docs: promote load_settings to architecture; prune redundant tests"
  ```

---

## Self-review notes

- **Spec coverage:** load_settings (Task 1), apply_cli_overlay→private (Task 2),
  `_config_error_from_validation` relocation (Tasks 1+2), `__main__` shrink
  (Task 2), unit test surface (Task 1), architecture promotion + prune (Task 3).
  The `ioc` asserts are a non-goal and correctly have no task.
- **Type consistency:** `load_settings(cli_overrides: dict[str, typing.Any], *,
  token: str | None = None) -> Settings` and `_apply_cli_overlay` are used with
  identical names/signatures across all tasks.
- **Behavior preservation:** Task 2's gate is the unchanged CLI/integration suite
  going green against the rewired callback.

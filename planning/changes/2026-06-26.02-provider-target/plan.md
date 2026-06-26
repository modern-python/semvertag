# provider-target — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the duplicated provider invariant (validator + two `ioc`
asserts) with a discriminated `ProviderTarget` the validator builds and `ioc`
matches exhaustively, removing the asserts and the cross-module coupling.

**Spec:** [`design.md`](./design.md)

**Branch:** `refactor/provider-target`

**Commit strategy:** Per-task commits.

## Global Constraints

- Python imports at MODULE LEVEL only; every test function argument annotated.
- `just test` enforces `fail_under = 100` branch coverage.
- BEHAVIOR-PRESERVING: identical invariant error messages and raise conditions,
  unchanged auto-detection / precedence / env aliases / exit codes; no change to
  the `Provider` protocol, providers, use-case, or output. `Settings.provider`
  (the `Literal` selector) stays.
- Mirror the `_outcome.to_run_result` closed-sum convention for the `ioc` match
  (`case _: typing.assert_never(...)  # pragma: no cover`).

---

### Task 1: Add `ProviderTarget`; build it in the validator

**Files:**
- Modify: `semvertag/_settings.py`
- Test: `tests/unit/test_settings.py`

**Interfaces:**
- Consumes: existing `Settings`, `pydantic`, `typing`.
- Produces: `GitHubTarget(repo: str)`, `GitLabTarget(project_id: int)`,
  `ProviderTarget = GitHubTarget | GitLabTarget`, and
  `Settings.provider_target -> ProviderTarget`.

Additive plus a behavior-preserving validator restructure. `ioc` still uses its
asserts after this task (Task 2 swaps it), so nothing breaks.

- [ ] **Step 1: Write the failing tests**

  Add the two imports to the module-level import block at the top of
  `tests/unit/test_settings.py` — add `GitHubTarget`, `GitLabTarget` to the
  existing `from semvertag._settings import ...` line. Then append:

  ```python
  @pytest.mark.usefixtures("clean_settings_env")
  def test_provider_target_is_github_target_for_github() -> None:
      settings = Settings(provider="github", repo="o/r")
      assert settings.provider_target == GitHubTarget(repo="o/r")


  @pytest.mark.usefixtures("clean_settings_env")
  def test_provider_target_is_gitlab_target_for_gitlab() -> None:
      settings = Settings(provider="gitlab", project_id=_PROJECT_ID_INT_SEMVERTAG)
      assert settings.provider_target == GitLabTarget(project_id=_PROJECT_ID_INT_SEMVERTAG)
  ```

- [ ] **Step 2: Run the tests to verify they fail**

  Run: `just test tests/unit/test_settings.py -q`
  Expected: FAIL — `ImportError: cannot import name 'GitHubTarget'`.

- [ ] **Step 3: Add the target types**

  In `semvertag/_settings.py`, add `import dataclasses` to the module imports,
  and define the targets above the `Settings` class:

  ```python
  @dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
  class GitHubTarget:
      repo: str


  @dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
  class GitLabTarget:
      project_id: int


  ProviderTarget: typing.TypeAlias = GitHubTarget | GitLabTarget
  ```

- [ ] **Step 4: Add the PrivateAttr, property, and build it in the validator**

  Inside `Settings`, add the private attr (with the other field declarations)
  and the property:

  ```python
  _provider_target: ProviderTarget | None = pydantic.PrivateAttr(default=None)

  @property
  def provider_target(self) -> ProviderTarget:
      assert self._provider_target is not None, "provider_target is set by _resolve_provider"  # noqa: S101
      return self._provider_target
  ```

  Replace the existing `_resolve_provider` body's two-`if` invariant block:

  ```python
          if self.provider == "github" and not self.repo:
              msg = "provider=github requires `repo` (set GITHUB_REPOSITORY or pass --repo OWNER/REPO)"
              raise ValueError(msg)
          if self.provider == "gitlab" and self.project_id is None:
              msg = "provider=gitlab requires `project_id` (set CI_PROJECT_ID or pass --project-id N)"
              raise ValueError(msg)
          return self
  ```

  with the build-using-narrowing-locals version (keep the `if self.provider is
  None:` auto-detect line above it unchanged):

  ```python
          if self.provider == "github":
              repo = self.repo
              if not repo:
                  msg = "provider=github requires `repo` (set GITHUB_REPOSITORY or pass --repo OWNER/REPO)"
                  raise ValueError(msg)
              self._provider_target = GitHubTarget(repo=repo)
          else:
              project_id = self.project_id
              if project_id is None:
                  msg = "provider=gitlab requires `project_id` (set CI_PROJECT_ID or pass --project-id N)"
                  raise ValueError(msg)
              self._provider_target = GitLabTarget(project_id=project_id)
          return self
  ```

  The messages and conditions are byte-identical to the originals; the `else`
  branch is gitlab because `provider` is guaranteed `"github"` or `"gitlab"`
  after the auto-detect line. The locals `repo` / `project_id` narrow to
  `str` / `int` across their guards, so the target build needs no `assert`/`cast`.

- [ ] **Step 5: Run the tests to verify they pass**

  Run: `just test tests/unit/test_settings.py -q`
  Expected: PASS, including the two new tests and all existing invariant tests
  (`test_provider_github_requires_repo`, `test_provider_gitlab_requires_project_id`).

- [ ] **Step 6: Full suite + lint gate**

  Run: `just test` then `just lint-ci`
  Expected: full suite green at 100% branch coverage; lint/ty/planning clean.

- [ ] **Step 7: Commit**

  ```bash
  git add semvertag/_settings.py tests/unit/test_settings.py
  git commit -m "settings: build a discriminated ProviderTarget in the validator"
  ```

---

### Task 2: Match the target in `ioc`; remove the asserts

**Files:**
- Modify: `semvertag/ioc.py`

**Interfaces:**
- Consumes: `GitHubTarget`, `GitLabTarget`, `Settings.provider_target` from Task 1.

- [ ] **Step 1: Update the import**

  In `semvertag/ioc.py`, change `from semvertag._settings import Settings` to
  `from semvertag._settings import GitHubTarget, GitLabTarget, Settings`.

- [ ] **Step 2: Replace `_build_current_provider` body**

  Replace the `if settings.provider == "github": assert ... else assert ...`
  block with the exhaustive match, and update the docstring to drop the
  assert/`ty`-narrowing sentences while keeping the eager-resolution note:

  ```python
  def _build_current_provider(
      settings: Settings,
      gitlab_client: httpware.Client,
      github_client: httpware.Client,
  ) -> Provider:
      """Construct the active provider.

      Both clients are eagerly resolved (modern-di Factory eagerly resolves all
      provider_kwargs in resolve()). That's acceptable — httpx2 connection pools
      are lazy, so the unused client doesn't open sockets. The active forge is
      the validated, narrowed Settings.provider_target; the match is exhaustive
      over the closed ProviderTarget sum.
      """
      match settings.provider_target:
          case GitHubTarget(repo=repo):
              return GitHubProvider(
                  config=settings.github, repo=repo, http=github_client, default_branch=settings.default_branch
              )
          case GitLabTarget(project_id=project_id):
              return GitLabProvider(
                  config=settings.gitlab,
                  project_id=project_id,
                  http=gitlab_client,
                  default_branch=settings.default_branch,
              )
          case _:  # pragma: no cover
              typing.assert_never(settings.provider_target)
  ```

- [ ] **Step 3: Full suite + gates**

  Run: `just test` then `just lint-ci`
  Expected: 100% branch coverage (both match arms covered by `test_ioc.py`'s
  github + gitlab container tests; the `case _` is `# pragma: no cover`); ty
  passes (no asserts needed — `repo` / `project_id` come from the narrowed
  target fields); lint/planning clean.

- [ ] **Step 4: Commit**

  ```bash
  git add semvertag/ioc.py
  git commit -m "ioc: match ProviderTarget exhaustively; drop invariant asserts"
  ```

---

### Task 3: Promote architecture; finalize bundle

**Files:**
- Modify: `architecture/cli.md` (the IoC-wiring section)
- Modify: `planning/changes/2026-06-26.02-provider-target/design.md` (finalize `summary`)

- [ ] **Step 1: Update `architecture/cli.md`**

  Find the IoC-wiring section that describes `_build_current_provider` carrying
  `assert` guards on `repo` / `project_id` (the "eager-resolution None-field
  guard" sentence). Rewrite it to describe the new reality: the validator builds
  a discriminated `ProviderTarget` (`GitHubTarget | GitLabTarget`) whose id field
  is non-optional, and `_build_current_provider` matches it exhaustively (closed
  sum, `assert_never` arm) — so the invariant is enforced once, in the validator,
  and `ioc` no longer asserts it. Match the file's prose style; ground every
  sentence against `semvertag/_settings.py` and `semvertag/ioc.py`.

- [ ] **Step 2: Finalize the bundle summary**

  Edit the `summary:` frontmatter in this bundle's `design.md` to the realized
  result (past tense, one line).

- [ ] **Step 3: All gates**

  Run: `just lint-ci && just test && just docs-build`
  Expected: lint/ty/planning clean, 100% branch coverage, strict mkdocs build
  succeeds.

- [ ] **Step 4: Commit**

  ```bash
  git add architecture/cli.md planning/changes/2026-06-26.02-provider-target/design.md
  git commit -m "docs: promote ProviderTarget to architecture"
  ```

---

## Self-review notes

- **Spec coverage:** `ProviderTarget` types + validator build (Task 1),
  `provider_target` property + tests (Task 1), `ioc` exhaustive match + assert
  removal (Task 2), architecture promotion (Task 3).
- **Type consistency:** `GitHubTarget(repo: str)`, `GitLabTarget(project_id:
  int)`, `provider_target -> ProviderTarget` used identically across tasks.
- **Behavior preservation:** identical invariant messages/conditions; the
  existing invariant + `test_ioc` suites are the green-bar proof after each task.

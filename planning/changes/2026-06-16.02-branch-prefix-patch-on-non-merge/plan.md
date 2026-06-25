# branch-prefix-patch-on-non-merge — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `branch-prefix` config flag,
`patch_on_non_merge_commit` (default `False`), that makes a plain (non-merge)
HEAD commit bump patch instead of producing no bump.

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/branch-prefix-patch-on-non-merge`

**Commit strategy:** Per-task commits (two tasks: code, then docs).

**Context for an engineer new to this codebase:**

- The strategy lives in `semvertag/strategies/branch_prefix.py`. `decide(commit)`
  returns a `Bump` enum (`NONE | PATCH | MINOR | MAJOR` from
  `semvertag/_types.py`). The config is a frozen pydantic model
  `BranchPrefixConfig` in the same file.
- `Commit` is a frozen dataclass with `sha` and `message`.
- Tests use `pytest` with `--cov-branch` and `fail_under = 100` (see
  `pyproject.toml [tool.pytest.ini_options]` / `[tool.coverage.report]`). Every
  branch must be covered or the suite fails. The new ternary has a `True` arm
  (new tests) and a `False` arm (existing default-off tests).
- Run tests with `just test`; lint with `just lint-ci`. `just test` uses
  `--no-sync`, so if dependencies changed run `uv sync` first — not needed here.
- The config field needs no IoC/settings wiring: `Settings.branch_prefix`
  (`semvertag/_settings.py:98`) already carries `BranchPrefixConfig` whole, so a
  new field is automatically settable via
  `SEMVERTAG_BRANCH_PREFIX__PATCH_ON_NON_MERGE_COMMIT`.

---

### Task 1: Add `patch_on_non_merge_commit` flag and the non-merge fallback

**Files:**
- Modify: `semvertag/strategies/branch_prefix.py`
- Test: `tests/unit/test_branch_prefix_strategy.py`

Add the config field and the single `decide` ternary, test-first.

- [ ] **Step 1: Write the failing tests**

  Append to `tests/unit/test_branch_prefix_strategy.py` (the helpers
  `_commit`, `_NON_MERGE_CASES`, `_UNRECOGNIZED_MERGE_CASES`, and the imports
  `Bump`, `BranchPrefixConfig`, `BranchPrefixStrategy` already exist at the top
  of the file — reuse them, do not redefine):

  ```python
  _FALLBACK_STRATEGY: typing.Final = BranchPrefixStrategy(
      config=BranchPrefixConfig(patch_on_non_merge_commit=True),
  )


  @pytest.mark.parametrize("message", [message for message, _ in _NON_MERGE_CASES])
  def test_returns_patch_for_non_merge_commit_when_flag_enabled(message: str) -> None:
      assert _FALLBACK_STRATEGY.decide(_commit(message)) is Bump.PATCH


  def test_flag_leaves_recognized_merge_paths_unchanged() -> None:
      assert _FALLBACK_STRATEGY.decide(_commit("Merge branch 'feature/x' into main")) is Bump.MINOR
      assert _FALLBACK_STRATEGY.decide(_commit("Merge branch 'bugfix/y' into main")) is Bump.PATCH


  @pytest.mark.parametrize("message", [message for message, _ in _UNRECOGNIZED_MERGE_CASES])
  def test_flag_leaves_unrecognized_merge_as_none(message: str) -> None:
      assert _FALLBACK_STRATEGY.decide(_commit(message)) is Bump.NONE


  def test_patch_on_non_merge_commit_defaults_to_false() -> None:
      assert BranchPrefixConfig().patch_on_non_merge_commit is False
  ```

- [ ] **Step 2: Run the new tests, verify they fail**

  Run: `just test tests/unit/test_branch_prefix_strategy.py -p no:randomly --override-ini="addopts=" -q`

  Expected: FAIL. `BranchPrefixConfig` uses `ConfigDict(frozen=True)` without
  `extra="forbid"`, so pydantic v2 silently *ignores* the unknown
  `patch_on_non_merge_commit=True` kwarg — construction does not raise. The
  failures are therefore behavioral: `test_returns_patch_for_non_merge_commit_when_flag_enabled`
  fails with `AssertionError` (`decide` still returns `Bump.NONE`), and
  `test_patch_on_non_merge_commit_defaults_to_false` fails with `AttributeError`
  (no such attribute).

- [ ] **Step 3: Add the config field**

  In `semvertag/strategies/branch_prefix.py`, add the field to
  `BranchPrefixConfig` (after `merge_mark_texts`):

  ```python
      merge_mark_texts: tuple[_NonEmptyStr, ...] = pydantic.Field(
          default=("Merge branch", "Merge pull request"),
          min_length=1,
      )
      patch_on_non_merge_commit: bool = False
  ```

- [ ] **Step 4: Add the fallback to `decide`**

  Replace the non-merge exit (currently `return Bump.NONE` under the
  `if not any(mark in subject ...)` guard) with:

  ```python
      def decide(self, commit: Commit) -> Bump:
          subject: typing.Final = subject_line(commit.message)
          if not any(mark in subject for mark in self.config.merge_mark_texts):
              return Bump.PATCH if self.config.patch_on_non_merge_commit else Bump.NONE
          if any(prefix in subject for prefix in self.config.minor):
              return Bump.MINOR
          if any(prefix in subject for prefix in self.config.patch):
              return Bump.PATCH
          return Bump.NONE
  ```

  Leave the trailing `return Bump.NONE` (the unrecognized-merge exit) untouched.

- [ ] **Step 5: Run the strategy tests, verify they pass**

  Run: `just test tests/unit/test_branch_prefix_strategy.py -p no:randomly --override-ini="addopts=" -q`

  Expected: PASS — all existing + 4 new test functions green.

- [ ] **Step 6: Run the full gated suite and lint**

  Run: `just test`
  Expected: PASS — full suite green at 100% branch coverage (the new ternary's
  `True` arm is covered by the new tests, the `False` arm by the existing
  default-off tests).

  Run: `just lint-ci`
  Expected: PASS — eof-fixer, ruff format, ruff check, ty all clean.

- [ ] **Step 7: Commit**

  ```bash
  git add semvertag/strategies/branch_prefix.py tests/unit/test_branch_prefix_strategy.py
  git commit -m "strategies: add opt-in patch bump for non-merge commits

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Document the flag (architecture + user docs)

**Files:**
- Modify: `architecture/strategies.md`
- Modify: `docs/strategies/branch-prefix.md`

Promote the new behavior into the capability doc and the user-facing docs.

- [ ] **Step 1: Update `architecture/strategies.md`**

  In the `## branch-prefix` section, extend step 1 (the `Bump.NONE` rule for a
  subject with no merge mark) to note the opt-in. Add after the existing step-1
  sentence:

  > When `config.patch_on_non_merge_commit` is `True` (default `False`), this
  > non-merge case returns `Bump.PATCH` instead of `Bump.NONE`, so a direct push
  > to the default branch auto-tags a patch release. The flag governs only this
  > exit — a merge commit with an unrecognized prefix (step 4) still returns
  > `Bump.NONE`.

- [ ] **Step 2: Update `docs/strategies/branch-prefix.md` — detection section**

  In `## Merge-commit detection`, change the bullet:

  ```markdown
  - Direct pushes to the default branch → bump = none.
  ```

  to:

  ```markdown
  - Direct pushes to the default branch → bump = none, unless
    `patch_on_non_merge_commit` is enabled (see below), in which case
    bump = patch.
  ```

- [ ] **Step 3: Update `docs/strategies/branch-prefix.md` — config list**

  In `## Customizing the prefixes`, add a fourth bullet after `merge_mark_texts`:

  ```markdown
  - `patch_on_non_merge_commit` — when `true`, a plain (non-merge) commit on
    the default branch bumps patch instead of producing no bump (default
    `false`). Set via `SEMVERTAG_BRANCH_PREFIX__PATCH_ON_NON_MERGE_COMMIT=true`.
    Affects only the non-merge case; a merge commit with an unrecognized prefix
    still produces no bump.
  ```

- [ ] **Step 4: Verify the docs build**

  Run: `mkdocs build --strict`
  Expected: PASS — no broken links or warnings.

- [ ] **Step 5: Commit**

  ```bash
  git add architecture/strategies.md docs/strategies/branch-prefix.md
  git commit -m "docs: document branch-prefix patch_on_non_merge_commit flag

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## Notes for finishing

- This bundle is on lane **full** (`design.md` + `plan.md`). On merge: move the
  bundle to `planning/changes/` with `status: shipped`, `pr:`, and
  `outcome:` filled, and confirm the `architecture/strategies.md` edit from
  Task 2 landed (that hand-edit is what keeps `architecture/` true).
- Release tags are bare semver — not relevant to this change, but the flag, once
  enabled by a consumer, will cause their next direct push to emit a patch tag.

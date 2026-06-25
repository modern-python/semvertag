# default-branch-override — implementation plan

**Goal:** Make `--default-branch` / `SEMVERTAG_DEFAULT_BRANCH` actually override
the resolved default branch, skipping the default-branch API call when set.

**Spec:** [`design.md`](./design.md)

**Branch:** `fix/default-branch-override`

**Commit strategy:** Single commit (small, cohesive bug fix).

TDD throughout: red (failing tests) → green (implement) → refactor.

---

### Task 1: Failing tests (red)

**Files:**
- Modify: `tests/integration/test_github_provider.py`
- Modify: `tests/integration/test_gitlab_provider.py`
- Modify: `tests/unit/test_ioc.py`
- Modify: `tests/unit/test_settings.py`

- [x] Provider tests (both forges): override returns without hitting the
  repo/project endpoint; commit lookup uses the override and skips the
  default-branch GET.
- [x] IoC test: `_build_current_provider` propagates `settings.default_branch`.
- [x] Settings test: blank `default_branch` (empty/whitespace) → `None`; padded name stripped.
- [x] Confirm the new provider tests fail (field/short-circuit absent).

### Task 2: Implement (green)

**Files:**
- Modify: `semvertag/_settings.py` — field validator normalizing blank `default_branch` → `None`
- Modify: `semvertag/providers/github.py` — add field + short-circuit
- Modify: `semvertag/providers/gitlab.py` — add field + short-circuit
- Modify: `semvertag/ioc.py` — wire `default_branch=settings.default_branch`

- [x] Implement; run `just test` to green, `just lint-ci` clean.

### Task 3: Promote + ship

- [x] Update `architecture/providers.md` to document the override seam.
- [x] `just index`; set `status: shipped`, fill `pr`/`outcome` at merge.

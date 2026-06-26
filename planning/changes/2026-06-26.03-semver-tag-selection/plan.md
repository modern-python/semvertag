# semver-tag-selection — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the four-helper semver-tag-selection chain in `_use_case.py` into
one selector that carries the parsed `Version` (no double-parse), and finalize
prerelease baselines via `next_version`.

**Spec:** [`design.md`](./design.md) · **Decision:**
[`../../decisions/2026-06-26-semver-form-tags-only.md`](../../decisions/2026-06-26-semver-form-tags-only.md)

**Branch:** `refactor/semver-tag-selection`

**Commit strategy:** Per-task commits.

## Global Constraints

- Python imports at MODULE LEVEL only; every test function argument annotated.
- `just test` enforces `fail_under = 100` branch coverage.
- BEHAVIOR-PRESERVING **except** the one deliberate change: `next_version` instead
  of `bump_*`, which equals `bump_*` on stable baselines **without build metadata**
  and differs only by finalizing SemVer-form prerelease baselines. The selector
  strips build metadata (`.replace(build=None)`) so the carried `Version` is always
  build-free; a hand-pushed `1.0.0+build` tag therefore bumps correctly to `1.0.1`.
  No change to `Outcome`, providers, strategies, output, or DI.
- Selection stays **SemVer-form only** — no PEP 440 / `v`-prefix recognition (per
  the decision record).
- Tie order: `sorted(...)[-1]` (last-equal-wins) — do NOT use `max()`.

---

### Task 1: Fold the selection chain; bump via `next_version`

**Files:**
- Modify: `semvertag/_use_case.py`
- Test: `tests/unit/test_use_case.py`

**Interfaces:**
- Removed: `_try_parse_semver`, `_parse_semver_tags`, `_pick_latest_semver_tag`,
  `_BUMP_FUNCTIONS`.
- Produced: `_select_latest_semver_tag(tags: list[Tag]) -> tuple[Tag, semver.Version] | None`,
  `_BUMP_PARTS: dict[Bump, str]`, and `_compute_new_version(version: semver.Version, bump: Bump) -> str`.

- [ ] **Step 1: Write the failing direct helper tests**

  In `tests/unit/test_use_case.py`, add `_select_latest_semver_tag` and
  `_compute_new_version` to the existing `from semvertag._use_case import ...`
  line, and add `import semver` to the module imports. Append:

  ```python
  def test_select_latest_returns_none_for_empty() -> None:
      assert _select_latest_semver_tag([]) is None


  def test_select_latest_returns_none_when_all_unparseable() -> None:
      tags = [
          Tag(name="release-2024-Q1", commit_sha="a"),
          Tag(name="latest", commit_sha="b"),
          Tag(name="v0", commit_sha="c"),
      ]
      assert _select_latest_semver_tag(tags) is None


  def test_select_latest_skips_pep440_prerelease() -> None:
      tags = [Tag(name="0.8.1", commit_sha="a"), Tag(name="0.9.0rc1", commit_sha="b")]
      selected = _select_latest_semver_tag(tags)
      assert selected is not None
      tag, version = selected
      assert tag.name == "0.8.1"
      assert version == semver.Version.parse("0.8.1")


  def test_select_latest_includes_semver_form_prerelease_in_ordering() -> None:
      tags = [Tag(name="1.0.0-rc.1", commit_sha="a"), Tag(name="0.9.0", commit_sha="b")]
      selected = _select_latest_semver_tag(tags)
      assert selected is not None
      tag, _version = selected
      assert tag.name == "1.0.0-rc.1"


  def test_select_latest_tie_keeps_last_in_input() -> None:
      tags = [Tag(name="1.0.0+a", commit_sha="x"), Tag(name="1.0.0+b", commit_sha="y")]
      selected = _select_latest_semver_tag(tags)
      assert selected is not None
      tag, _version = selected
      assert tag.commit_sha == "y"


  def test_compute_new_version_finalizes_semver_prerelease() -> None:
      assert _compute_new_version(semver.Version.parse("1.0.0-rc.1"), Bump.PATCH) == "1.0.0"
  ```

- [ ] **Step 2: Run the tests to verify they fail**

  Run: `just test tests/unit/test_use_case.py -q`
  Expected: FAIL — `ImportError: cannot import name '_select_latest_semver_tag'`.

- [ ] **Step 3: Rewrite the helpers in `_use_case.py`**

  Remove `_try_parse_semver`, `_parse_semver_tags`, `_pick_latest_semver_tag`, and
  the `_BUMP_FUNCTIONS` dict. Add:

  ```python
  def _select_latest_semver_tag(tags: list[Tag]) -> tuple[Tag, semver.Version] | None:
      parsed: list[tuple[semver.Version, Tag]] = []
      for tag in tags:
          try:
              version = semver.Version.parse(tag.name)
          except ValueError:
              continue
          parsed.append((version, tag))
      if not parsed:
          return None
      parsed.sort(key=lambda item: item[0])
      version, tag = parsed[-1]
      return tag, version


  _BUMP_PARTS: typing.Final[dict[Bump, str]] = {
      Bump.MAJOR: "major",
      Bump.MINOR: "minor",
      Bump.PATCH: "patch",
  }


  def _compute_new_version(version: semver.Version, bump: Bump) -> str:
      return str(version.next_version(_BUMP_PARTS[bump]))
  ```

- [ ] **Step 4: Rewire `__call__`**

  Replace the selection + already-tagged + compute lines so they consume the
  tuple and pass the carried `Version`:

  ```python
          output.progress("Fetching tag history...")
          tags: typing.Final = self.provider.list_tags()
          selected: typing.Final = _select_latest_semver_tag(tags)

          if selected is None:
              return self._emit(output, NoTags(commit=commit.sha))

          latest_tag, latest_version = selected
          if latest_tag.commit_sha == commit.sha:
              return self._emit(output, AlreadyTagged(tag=latest_tag.name, commit=commit.sha))

          output.progress("Computing bump...")
          bump: typing.Final = self.strategy.decide(commit)
          if bump is Bump.NONE:
              return self._emit(
                  output,
                  NoBump(status=self.strategy.no_bump_status, reason=self.strategy.no_bump_reason, commit=commit.sha),
              )

          new_version: typing.Final = _compute_new_version(latest_version, bump)
  ```

  Leave the `dry_run` / `create_tag` / `Created` lines below unchanged.

- [ ] **Step 5: Run the tests to verify they pass**

  Run: `just test tests/unit/test_use_case.py -q`
  Expected: PASS — new direct tests green, AND every existing use-case test green
  (behavior preserved; `next_version` equals `bump_*` on the `1.4.2`/`2.0.0`
  stable baselines those tests use).

- [ ] **Step 6: Full suite + lint gate**

  Run: `just test` then `just lint-ci`
  Expected: full suite at 100% branch coverage; ruff/ty/planning clean.

- [ ] **Step 7: Commit**

  ```bash
  git add semvertag/_use_case.py tests/unit/test_use_case.py
  git commit -m "use-case: fold semver-tag selection into one selector; bump via next_version"
  ```

---

### Task 2: Promote architecture; finalize bundle

**Files:**
- Modify: `architecture/cli.md` (the "Use-case" section)
- Modify: `planning/changes/2026-06-26.03-semver-tag-selection/design.md` (finalize `summary`)

- [ ] **Step 1: Update `architecture/cli.md`**

  In the "Use-case" section, find step 2 (currently: "list tags and pick the
  highest semver-parseable one (`_pick_latest_semver_tag` sorts by
  `semver.Version`; unparseable names are skipped)") and step 5 (currently:
  "compute the new version (`_compute_new_version` via `semver`'s
  `bump_major/minor/patch`)"). Rewrite them to the new reality, grounding every
  claim against `semvertag/_use_case.py`:
  - Step 2: `_select_latest_semver_tag` parses each tag, skips non-SemVer names
    (PEP 440 prereleases and `v`-prefixed tags included), sorts by `semver.Version`
    precedence, and returns the winning `Tag` **with its parsed `Version`**
    (last-equal-wins on ties).
  - Step 5: the new version is computed by `_compute_new_version` from the carried
    `Version` via `Version.next_version` (which finalizes a SemVer-form prerelease
    baseline), so the winning tag is not parsed twice.
  Match the file's prose style. Add a brief pointer to
  `decisions/2026-06-26-semver-form-tags-only.md` if the section already
  cross-references decisions; otherwise keep it inline.

- [ ] **Step 2: Finalize the bundle summary**

  Edit the `summary:` frontmatter in this bundle's `design.md` to the realized
  result (past tense, one line).

- [ ] **Step 3: All gates**

  Run: `just lint-ci && just test && just docs-build`
  Expected: lint/ty/planning clean, 100% branch coverage, strict mkdocs build
  succeeds.

- [ ] **Step 4: Commit**

  ```bash
  git add architecture/cli.md planning/changes/2026-06-26.03-semver-tag-selection/design.md
  git commit -m "docs: promote semver-tag selection + next_version to architecture"
  ```

---

## Self-review notes

- **Spec coverage:** selector fold + carried `Version` (Task 1), `next_version`
  bump (Task 1), direct edge tests (Task 1), architecture promotion + summary
  (Task 2). The decision record ships with the bundle's planning commit.
- **Type consistency:** `_select_latest_semver_tag(...) -> tuple[Tag,
  semver.Version] | None` and `_compute_new_version(version: semver.Version, bump:
  Bump) -> str` used identically across tasks.
- **Behavior preservation:** existing use-case tests are the green-bar proof;
  `next_version` is the only deliberate behavior change (prerelease finalize).

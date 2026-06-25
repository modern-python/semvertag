# semvertag `--dry-run` Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--dry-run` flag to `semvertag tag` that computes the bump and emits an informative result without calling `provider.create_tag`.

**Architecture:** One CLI flag, one new kwarg on the use case, one new branch in `_use_case.__call__` before `create_tag`, one new branch in `_output._format_result` for the human-readable rendering. New `dry_run` status value joins the existing `RunResult.status` strings. No type widening (status is already plain `str`). Strategy code is untouched; the dry-run skip sits in the use case so both `branch-prefix` and `conventional-commits` benefit.

**Tech Stack:** Python 3.11+, typer, pytest, `--cov=semvertag --cov-branch --fail_under=100` (already configured in `pyproject.toml`).

**Spec:** `planning/specs/2026-06-09-dry-run-flag-design.md`

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `semvertag/_use_case.py` | Modify | Add `dry_run: bool = False` kwarg to `__call__`; skip `create_tag` and emit `status="dry_run"` when true and a bump would have been created |
| `semvertag/__main__.py` | Modify | Add `--dry-run` Typer option to `_tag_command`; pass through to `use_case(...)` |
| `semvertag/_output.py` | Modify | Add `dry_run` branch in `_format_result` for human-readable rendering |
| `tests/unit/test_use_case.py` | Modify | Add unit tests for the dry-run path (status, output, no `create_tag` call) |
| `tests/integration/test_cli_main_verb.py` | Modify | Add integration test exercising `semvertag tag --dry-run --json` against a fake transport; assert no POST to `/repository/tags` |
| `tests/unit/test_output_rich.py` | Modify | Add a test for the new `_format_result` branch |

## Branch

Already on `feat/dry-run-flag` (branched from `origin/main`). Spec commit `9a2d897` is the only commit so far.

---

### Task 1: Use case dry-run kwarg

**Files:**
- Modify: `semvertag/_use_case.py` — `SemvertagUseCase.__call__`
- Test: `tests/unit/test_use_case.py`

- [ ] **Step 1: Write a failing test for the dry-run path**

Append to `tests/unit/test_use_case.py` (after the last existing test):

```python
def test_dry_run_skips_create_tag_and_emits_dry_run_status() -> None:
    use_case, provider, output = _make_use_case()

    result: typing.Final = use_case(output=output, dry_run=True)

    assert result.status == "dry_run"
    assert result.tag == _EXPECTED_NEW_TAG
    assert result.bump == "minor"
    assert result.strategy == _BRANCH_PREFIX_STRATEGY
    assert result.commit == _LATEST_SHA
    assert result.reason is None
    assert provider.create_tag_calls == []
    assert output.emitted_results == [result]


def test_dry_run_does_not_emit_creating_tag_progress() -> None:
    use_case, _provider, output = _make_use_case()

    use_case(output=output, dry_run=True)

    assert not any("Creating tag" in msg for msg in output.progress_messages)


def test_dry_run_does_not_affect_already_tagged_path() -> None:
    use_case, provider, output = _make_use_case(
        tags=[Tag(name=_LATEST_TAG_NAME, commit_sha=_LATEST_SHA)],
    )

    result: typing.Final = use_case(output=output, dry_run=True)

    assert result.status == "already_tagged"
    assert provider.create_tag_calls == []


def test_dry_run_does_not_affect_no_tags_path() -> None:
    use_case, provider, output = _make_use_case(tags=[])

    result: typing.Final = use_case(output=output, dry_run=True)

    assert result.status == "no_tags"
    assert provider.create_tag_calls == []


def test_dry_run_does_not_affect_strategy_no_bump_path() -> None:
    use_case, provider, output = _make_use_case(
        commit_message=_NON_MERGE_MESSAGE,
        bump=Bump.NONE,
    )

    result: typing.Final = use_case(output=output, dry_run=True)

    assert result.status == "no_merge_commit"
    assert provider.create_tag_calls == []


def test_dry_run_false_default_creates_tag() -> None:
    use_case, provider, output = _make_use_case()

    result: typing.Final = use_case(output=output)

    assert result.status == "created"
    assert provider.create_tag_calls == [(_EXPECTED_NEW_TAG, _LATEST_SHA)]
```

The last test (`test_dry_run_false_default_creates_tag`) is intentionally redundant with `test_creates_tag_with_minor_bump_when_feature_merge_against_prior_semver_tag` — keep it anyway. It serves as the regression baseline that the default kwarg value didn't accidentally flip.

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `uv run pytest tests/unit/test_use_case.py -v -k dry_run`

Expected: all 6 new `*_dry_run_*` tests fail with `TypeError: __call__() got an unexpected keyword argument 'dry_run'` (or similar). The default-creates test passes only because `dry_run` defaults aren't yet involved.

Actually — `test_dry_run_false_default_creates_tag` will PASS because it doesn't pass `dry_run`. The others will FAIL. That's fine; this gives us a confirmed-red baseline.

- [ ] **Step 3: Modify `SemvertagUseCase.__call__` to accept and honor `dry_run`**

Open `semvertag/_use_case.py`. Replace the `__call__` method (lines 21-72) with this version:

```python
def __call__(self, *, output: Output, dry_run: bool = False) -> RunResult:
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
            status=self.strategy.no_bump_status,
            tag=None,
            commit=commit.sha,
            reason=self.strategy.no_bump_reason,
        )

    new_version: typing.Final = _compute_new_version(latest_semver_tag, bump)
    if dry_run:
        return self._emit(
            output=output,
            bump=bump,
            status="dry_run",
            tag=new_version,
            commit=commit.sha,
            reason=None,
        )

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
```

The only changes from the existing method:
1. New kwarg `dry_run: bool = False` in the signature.
2. New `if dry_run:` block immediately after `new_version` is computed and before `output.progress("Creating tag ...")` is called.

- [ ] **Step 4: Run the new tests and confirm they pass**

Run: `uv run pytest tests/unit/test_use_case.py -v -k dry_run`

Expected: all 6 tests PASS.

- [ ] **Step 5: Run the full use case test file**

Run: `uv run pytest tests/unit/test_use_case.py -v`

Expected: all tests pass (existing ones unchanged, new ones added).

- [ ] **Step 6: Run the full unit test suite under coverage**

Run: `just test tests/unit/`

Expected: passes; coverage gate intact (`fail_under = 100` is enforced in `pyproject.toml`). The new dry-run branch must be fully covered by the new tests.

If coverage fails on the new `if dry_run:` block, ensure `test_dry_run_skips_create_tag_and_emits_dry_run_status` is the test exercising it.

- [ ] **Step 7: Commit**

```bash
git add semvertag/_use_case.py tests/unit/test_use_case.py
git commit -m "feat(use-case): add dry_run kwarg that skips provider.create_tag"
```

---

### Task 2: CLI `--dry-run` option

**Files:**
- Modify: `semvertag/__main__.py` — `_tag_command`
- Test: `tests/integration/test_cli_main_verb.py`

- [ ] **Step 1: Write a failing integration test**

Append to `tests/integration/test_cli_main_verb.py`:

```python
def test_dry_run_skips_post_to_tags_endpoint_and_emits_dry_run_status(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    recorded: list[httpx2.Request] = []
    install_mock_transport(_make_recording_handler(merge_commit_handler(), recorded))

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag", "--dry-run", "--json"])

    assert result.exit_code == 0, result.output + result.stderr
    lines: typing.Final = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected one JSON line, got: {lines!r}"
    payload: typing.Final = json_module.loads(lines[0])
    assert payload["status"] == "dry_run"
    assert payload["tag"] == _EXPECTED_NEW_TAG
    assert payload["bump"] == "minor"
    posted: typing.Final = [r for r in recorded if r.method == "POST" and r.url.path == _TAGS_POST_PATH]
    assert posted == [], f"dry-run must not POST to tags endpoint; got: {posted}"
```

This reuses the existing `_make_recording_handler` helper and `merge_commit_handler` fixture (both already defined at the top of the file).

- [ ] **Step 2: Run the new test and confirm it fails**

Run: `uv run pytest tests/integration/test_cli_main_verb.py -v -k dry_run`

Expected: FAIL. Likely error is one of:
- Typer error: `No such option: --dry-run` (CLI rejects the flag because it's not defined yet)
- Or status mismatch if Typer silently absorbs unknown options (it shouldn't, but log shape varies).

- [ ] **Step 3: Add the `--dry-run` Typer option**

Open `semvertag/__main__.py`. Find `_tag_command` (around line 168-192). Replace it with:

```python
@MAIN_APP.command("tag")
def _tag_command(
    ctx: typer.Context,
    quiet: typing.Annotated[
        bool,
        typer.Option("--quiet", help="Suppress progress narrative; final result still emits."),
    ] = False,
    json_flag: typing.Annotated[
        bool,
        typer.Option("--json", help="Emit a JSON envelope on stdout instead of human-readable output."),
    ] = False,
    dry_run: typing.Annotated[
        bool,
        typer.Option("--dry-run", help="Compute the bump and print the result, but do not push a tag."),
    ] = False,
) -> None:
    output: Output = build_json_output(quiet=quiet) if json_flag else build_rich_output(quiet=quiet)
    try:
        use_case = _resolve_use_case(ctx=ctx)
        use_case(output=output, dry_run=dry_run)
    except ImportError as exc:
        err = ConfigError(f"Required module unavailable: {exc}.")
        output.error(str(err))
        raise typer.Exit(code=err.exit_code) from exc
    except SemvertagError as err:
        output.error(str(err))
        raise typer.Exit(code=err.exit_code) from err
    except BrokenPipeError as exc:
        raise typer.Exit(code=0) from exc
```

Only two changes:
1. New `dry_run` parameter with the `typer.Option("--dry-run", ...)` annotation.
2. Pass `dry_run=dry_run` to the `use_case(...)` call.

Everything else (`quiet`, `json_flag`, the try/except, all error paths) is unchanged.

- [ ] **Step 4: Run the new integration test and confirm it passes**

Run: `uv run pytest tests/integration/test_cli_main_verb.py -v -k dry_run`

Expected: PASS.

- [ ] **Step 5: Run the full integration suite**

Run: `uv run pytest tests/integration/ -v`

Expected: all integration tests pass (the new one + the existing ones unchanged).

- [ ] **Step 6: Commit**

```bash
git add semvertag/__main__.py tests/integration/test_cli_main_verb.py
git commit -m "feat(cli): add --dry-run flag to tag command"
```

---

### Task 3: Human-readable rendering for `dry_run`

**Files:**
- Modify: `semvertag/_output.py` — `_format_result`
- Test: `tests/unit/test_output_rich.py`

- [ ] **Step 1: Write a failing test**

Append to `tests/unit/test_output_rich.py`:

```python
def test_emit_renders_dry_run_with_would_create_phrasing() -> None:
    output, stdout_buf, _stderr = _make_pair()
    dry_run_result: typing.Final = RunResult(
        strategy="branch-prefix",
        bump="minor",
        status="dry_run",
        tag="1.2.0",
        commit="a2b4d12abc1234567890",
        reason=None,
    )
    output.emit(dry_run_result)
    stdout_text: typing.Final = stdout_buf.getvalue()
    assert "Dry run" in stdout_text
    assert "would create tag 1.2.0" in stdout_text
    assert "a2b4d12" in stdout_text
    assert "branch-prefix" in stdout_text
    assert "minor" in stdout_text
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run: `uv run pytest tests/unit/test_output_rich.py -v -k dry_run`

Expected: FAIL. The current `_format_result` falls through to the catch-all `"No tag created (status: dry_run, ...)"`, so `"Dry run"` and `"would create tag 1.2.0"` won't appear.

- [ ] **Step 3: Add the `dry_run` branch to `_format_result`**

Open `semvertag/_output.py`. Find `_format_result` (lines 56-63). Replace it with:

```python
def _format_result(result: RunResult) -> str:
    short: typing.Final = (result.commit or "")[:_COMMIT_SHORT_LEN]
    if result.status == "created":
        return f"Created tag {result.tag} on commit {short} (strategy: {result.strategy}, bump: {result.bump})"
    if result.status == "dry_run":
        return f"Dry run: would create tag {result.tag} on commit {short} (strategy: {result.strategy}, bump: {result.bump})"
    return (
        f"No tag created (status: {result.status}, strategy: {result.strategy}, "
        f"bump: {result.bump}, reason: {result.reason})"
    )
```

`short` is hoisted above the if-chain so it's declared once with `typing.Final`, no duplicate-Final conflict for `ty`. The no-tag fallback branch doesn't use `short` — the wasted 2-byte slice is fine; clarity beats micro-optimization here.

- [ ] **Step 4: Run the new test and confirm it passes**

Run: `uv run pytest tests/unit/test_output_rich.py -v -k dry_run`

Expected: PASS.

- [ ] **Step 5: Run the full output test suite**

Run: `uv run pytest tests/unit/test_output_rich.py tests/unit/test_output_json.py -v`

Expected: all tests pass. The JSON output test file is unaffected (JSON serialization goes through `dataclasses.asdict`, not `_format_result`).

- [ ] **Step 6: Commit**

```bash
git add semvertag/_output.py tests/unit/test_output_rich.py
git commit -m "feat(output): render dry_run status with 'would create tag' phrasing"
```

---

### Task 4: Final verification, lint, push, open PR

- [ ] **Step 1: Run the full test suite**

Run: `just test`

Expected: all tests pass; 100% branch coverage; no `fail_under` violation.

If coverage fails, find the uncovered branch:
- `--cov-report term-missing` (already configured) prints missing line numbers.
- Most likely culprit: the `dry_run` branch in `_use_case.py` if its dedicated test was skipped, or the `dry_run` branch in `_format_result` if its dedicated test was skipped.

- [ ] **Step 2: Run lint**

Run: `just lint-ci`

Expected: passes (eof-fixer, ruff format, ruff check, ty check).

If `ty` complains about the second `short` declaration in `_format_result` not being `typing.Final` (or being shadowed), drop `typing.Final` from the first declaration too. The intent is just a local variable; the `Final` annotation isn't load-bearing.

If `ty` complains about something else, fix the actual issue. Do NOT add `ty: ignore` comments unless the issue is a known false positive.

- [ ] **Step 3: Skim the full branch diff**

Run: `git log origin/main..HEAD --oneline`

Expected: four commits on `feat/dry-run-flag`, in this order (newest last):

```
<sha> docs: add spec for semvertag --dry-run flag
<sha> feat(use-case): add dry_run kwarg that skips provider.create_tag
<sha> feat(cli): add --dry-run flag to tag command
<sha> feat(output): render dry_run status with 'would create tag' phrasing
```

Run: `git diff origin/main..HEAD --stat`

Expected: 6 files touched (the spec + the 5 production-and-test files from the File Structure table; the spec lives on its own).

- [ ] **Step 4: Push the branch**

```bash
git push -u origin feat/dry-run-flag
```

- [ ] **Step 5: Open the PR**

Run:

```bash
gh pr create --title "feat: add semvertag tag --dry-run flag" --body "$(cat <<'EOF'
## Summary

- Adds \`--dry-run\` to \`semvertag tag\`. When set, the use case computes the bump and emits an informative result (\`status="dry_run"\` with \`bump\` and \`tag\` populated) but never calls \`provider.create_tag\`.
- New status \`dry_run\` joins the existing well-known \`RunResult.status\` values (\`created\`, \`no_tags\`, \`already_tagged\`, strategy-specific \`no_*_commit\`). \`RunResult.status\` is already plain \`str\`; no type widening.
- Human-readable output renders dry-run as: \`Dry run: would create tag {tag} on commit {short} (strategy: {strategy}, bump: {bump})\`.

Spec: \`planning/specs/2026-06-09-dry-run-flag-design.md\`.

## Motivation

PR #14 surfaced a structural issue with \`action-smoke\`: it ran semvertag with \`contents: write\` against the real \`main\`, and when main's HEAD wasn't already tagged, semvertag pushed a real release tag (\`0.4.1\`) from a PR's CI run. \`--dry-run\` is the first half of the fix; the follow-up PR (PR B) will land an \`action.yml\` \`dry-run\` input, update \`action-smoke\` to use it, and bump the version floor.

## Test plan

- [x] Unit tests for the dry-run use-case path (status, output, no \`create_tag\` call)
- [x] Unit tests that dry-run does NOT affect the other early-return paths (\`already_tagged\`, \`no_tags\`, strategy \`no_*_commit\`)
- [x] Integration test for \`semvertag tag --dry-run --json\` against a fake GitLab transport — asserts no POST to \`/repository/tags\`
- [x] Unit test for the new \`_format_result\` \`dry_run\` branch
- [x] 100% branch coverage (\`fail_under = 100\` in \`pyproject.toml\`)
- [x] \`just lint-ci\` passes

## Post-merge follow-ups (NOT in this PR)

1. Cut release \`0.5.0\` (this is a minor — new CLI feature) via the dogfood workflow. \`tag-major.yml\` will float \`v0\`. \`publish.yml\` will push to PyPI on the GitHub release.
2. Open PR B: \`action.yml\` adds a \`dry-run\` input; \`ci.yml\`'s \`action-smoke\` job sets \`with: { dry-run: true }\`, drops \`permissions: contents: write\`, and switches its assertion to "outputs are well-formed AND status != created". Bumps semvertag floor in \`action.yml\` from \`>=0.3.1,<1\` to \`>=0.5.0,<1\`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed. Capture and report it.

If `gh` complains about the heredoc backtick escaping, write the body to a tempfile first:

```bash
cat > /tmp/pr-body.md <<'EOF'
... same body, but without the leading \ on each backtick ...
EOF
gh pr create --title "feat: add semvertag tag --dry-run flag" --body-file /tmp/pr-body.md
```

- [ ] **Step 6: Report the PR URL**

Report the URL verbatim from `gh pr create` output. Do not fabricate it.

---

## Post-merge follow-ups (NOT part of this plan)

Listed here so they're not forgotten:

1. **Release 0.5.0.** After this PR merges, the dogfood workflow (`semvertag.yml`) will auto-tag the merge commit (likely `0.4.x` patch under branch-prefix; since this is a `feat/` merge, it'll be `0.5.0` minor). Manually create a GitHub release pointing at the tag — that fires `publish.yml` (PyPI) and `tag-major.yml` (floats `v0`).
2. **Open PR B.** Once `0.5.0` is on PyPI, open the follow-up PR with:
   - `action.yml`: new `dry-run` input (default `'false'`), pass `--dry-run` to the CLI conditionally, bump version floor from `>=0.3.1,<1` to `>=0.5.0,<1`.
   - `ci.yml`'s `action-smoke` job: drop `permissions: contents: write`, set `with: { dry-run: true }` on `uses: ./`, weaken the assertion to "bump in {none,patch,minor,major} AND status in {created,no-bump} AND status != created".
   - Update the action-smoke comment block in `ci.yml` to reference dry-run as the mechanism (not the "main HEAD is already tagged" assumption).
   - Optionally update `docs/providers/github.md` with a "preview the next bump" usage example.

If `0.5.0` doesn't ship for any reason, PR B can't be tested locally and shouldn't be opened — the floor bump would point at a non-existent version.

---
status: shipped
date: 2026-06-09
slug: dry-run-flag
supersedes: null
superseded_by: null
pr: null
outcome: shipped (#15)
---

# semvertag `--dry-run` flag — design

**Status:** approved
**Date:** 2026-06-09
**Motivating issue:** PR #14's `action-smoke` job failed because semvertag pushed a real release tag (`0.4.1`) from a PR's CI run. The `action-smoke` job is meant to verify the composite action returns well-formed outputs; instead it mutates the real remote whenever main's HEAD isn't already tagged.

## Goal

Add a `--dry-run` flag to the `semvertag tag` CLI that computes the bump but skips the push, so a smoke test (or any other dry-run consumer) can exercise the composite action without side effects.

## Why

- `action-smoke` running with `permissions: contents: write` against the real `main` is structurally unsafe: any PR with a CI run can land a release tag if the current main HEAD is eligible and untagged. This is how PR #14 created `0.4.1`.
- The current "smoke is no-bump" assertion is brittle: it depends on main HEAD being already tagged, an invariant that breaks under tag churn (the dogfood's previous tag attempt failing or being deleted).
- `--dry-run` is a CLI feature with value beyond this test — users running semvertag locally to preview what the next bump would be will use the same flag.

## Scope

This spec covers **PR A only**: the CLI change. PR B (action.yml `dry-run` input, action-smoke update, version-floor bump) is listed under "Follow-ups" and gets its own spec once 0.5.0 is on PyPI.

In scope (PR A):
1. New `--dry-run` boolean option on `semvertag tag` (default: false).
2. `SemvertagUseCase.__call__` gains a `dry_run: bool = False` kwarg.
3. When a bump is computed and `dry_run` is true, the use case emits `status="dry_run"` with the computed `bump` and `tag` populated, and **does not call** `provider.create_tag`.
4. The three other early-return statuses (`no_tags`, `already_tagged`, the strategy's `no_bump_status`) are unaffected — they never reach `create_tag`.
5. Tests covering the dry-run path (unit test on the use case + CLI smoke test).
6. Release `0.5.0` (next minor) once the CLI change lands.

Out of scope (PR A):
- `action.yml` changes — deferred to PR B because the action.yml needs a published semvertag release to consume.
- `ci.yml` action-smoke job changes — deferred to PR B.
- Strategy-level changes — the dry-run skip is strategy-agnostic by construction (it sits in the use case, not in either strategy).
- Documenting `--dry-run` in the GitLab provider docs — only the GitHub Actions doc gets the update in PR B.
- Refactoring `action-smoke` to use a fixture repo — `--dry-run` removes the need.

## Design

### 1. CLI surface

In `semvertag/__main__.py`, the `_tag_command` gains one new option:

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
        ...
```

Naming: `--dry-run` (kebab-case CLI), `dry_run` (snake_case Python kwarg). Typer maps the two automatically.

### 2. Use case short-circuit

In `semvertag/_use_case.py`, `SemvertagUseCase.__call__` gains a kwarg and one new branch:

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
            output=output, bump=Bump.NONE, status="no_tags",
            tag=None, commit=commit.sha, reason=_NO_TAGS_REASON,
        )

    if latest_semver_tag.commit_sha == commit.sha:
        return self._emit(
            output=output, bump=Bump.NONE, status="already_tagged",
            tag=latest_semver_tag.name, commit=commit.sha, reason=_ALREADY_TAGGED_REASON,
        )

    output.progress("Computing bump...")
    bump: typing.Final = self.strategy.decide(commit)
    if bump is Bump.NONE:
        return self._emit(
            output=output, bump=Bump.NONE, status=self.strategy.no_bump_status,
            tag=None, commit=commit.sha, reason=self.strategy.no_bump_reason,
        )

    new_version: typing.Final = _compute_new_version(latest_semver_tag, bump)
    if dry_run:
        return self._emit(
            output=output, bump=bump, status="dry_run",
            tag=new_version, commit=commit.sha, reason=None,
        )

    output.progress(f"Creating tag {new_version}...")
    self.provider.create_tag(name=new_version, commit_sha=commit.sha)
    return self._emit(
        output=output, bump=bump, status="created",
        tag=new_version, commit=commit.sha, reason=None,
    )
```

Key points:

- The dry-run branch sits between bump computation and `create_tag`. Both strategies use the same use case, so both benefit.
- `bump` and `tag` are populated with what WOULD happen — the dry-run output is informative, not just a stub.
- `reason` is `None` (consistent with the `created` branch).
- The three early-return statuses (`no_tags`, `already_tagged`, strategy's `no_bump_status`) don't change under `dry_run`; they don't push anything, so dry-run has no effect on those paths.
- `output.progress("Creating tag...")` is NOT emitted on the dry-run path. The status itself signals the intent; a "Creating" log would be misleading.

The kwarg default (`dry_run: bool = False`) keeps all existing call sites compiling unchanged.

### 3. Status field

`RunResult.status` is a plain `str` (`_types.py:24` — `status: str`). No type widening is required; `dry_run` joins the existing well-known values (`created`, `no_tags`, `already_tagged`, plus per-strategy `no_*_commit` variants).

The CLI's internal statuses are documented in one place outside the source: `action.yml`'s normalization-step comment (currently `no_tags`, `already_tagged`, `no_merge_commit`, `no_conforming_commit`, `...`). PR B updates that comment to include `dry_run`. This PR (PR A) doesn't touch `action.yml`.

### 4. Tests

Two new test cases. Both fixture-driven; no network.

**Unit test for the use case** (`tests/test_use_case.py` or wherever the use case is tested):

- Set up a fake provider that returns: one `latest_semver_tag` at version `0.1.0` on commit `aaa`, and a `latest_commit` at `bbb`.
- Configure a fake strategy that returns `Bump.PATCH` for `bbb`.
- Call `use_case(output=spy_output, dry_run=True)`.
- Assert:
  - `provider.create_tag` is never invoked (use a mock spy, or a FakeProvider that flags the call).
  - The emitted result has `status == "dry_run"`, `bump == "patch"`, `tag == "0.1.1"`, `commit == "bbb"`, `reason is None`.
  - For comparison: same setup with `dry_run=False` emits `status == "created"` and calls `create_tag`.

**Existing tests** for the use case continue to pass without modification (default `dry_run=False`).

**CLI test** (`tests/test_cli.py` or wherever the CLI is exercised):

- Invoke `semvertag tag --dry-run --json` with a fake provider/strategy stack (whatever the existing CLI test harness uses).
- Parse the JSON output; assert `status == "dry_run"` and the provider's `create_tag` was not called.
- Coverage gate: this test should land in whatever module already enforces 100% branch coverage on `_use_case` (per `Justfile`'s `test-branch-strategies`).

### 5. JSON output shape

The JSON envelope already includes `status`, `bump`, `tag`, `commit`, `reason`, `strategy`, `schema_version` (from `_output.py`). The dry-run path uses the existing schema; only the `status` value is new:

```json
{
  "schema_version": "1.0",
  "strategy": "branch-prefix",
  "bump": "patch",
  "status": "dry_run",
  "tag": "0.1.1",
  "commit": "bbb...",
  "reason": null
}
```

No new fields. `schema_version` stays at `1.0` because `status` was already a string with multiple values; consumers that already handle unknown statuses gracefully (e.g. PR #14's action.yml's `case` block) are forward-compatible.

### 6. Human-readable output

`_output.py:_format_result` currently has two branches: `created` (line 57-59, "Created tag X on commit Y...") and the catch-all (line 60-63, "No tag created (status: X, ...)"). Without a dedicated `dry_run` branch, dry-run output would fall through to "No tag created (status: dry_run, ...)" — technically true, but misleading: a dry-run produced an informative result, not a no-op.

Add one branch in `_format_result`, placed before the catch-all. Hoist `short` above the if-chain so `typing.Final` is declared once (avoids a duplicate-Final flag from `ty` and de-duplicates the slice):

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

Mirrors the `created` branch's format, swapping "Created tag" → "Dry run: would create tag". The no-tag fallback doesn't use `short` — the wasted 2-byte slice is fine.

### 7. Release

After the CLI change lands:

1. The dogfood `semvertag.yml` workflow auto-creates the next patch tag on push-to-main (current floor is `0.4.x`).
2. Manually create a GitHub release pointing at the tagged commit, bumping to `0.5.0` (this is a minor — new feature). `tag-major.yml` will float `v0` accordingly.
3. `publish.yml` runs on release-published and pushes `0.5.0` to PyPI.

The semvertag CLI version floor in `action.yml` (currently `>=0.3.1,<1`) is NOT touched in this PR. PR B bumps it.

## Risks

- **Tests must spy on `create_tag` to verify it isn't called.** A test that just asserts the JSON status without verifying the side-effect-not-taken is a weaker test. Make sure the unit test fails if `dry_run=True` accidentally calls `create_tag`.
- **Status enum widening could break downstream callers.** If anyone is `match`-ing on `status` exhaustively (no default branch), a new value crashes them. Mitigation: action.yml's existing `case "$(jq -r '.status' <<<"$result")"` block uses a `*` default that maps unknown → `no-bump`, so the public `action.yml` consumer is forward-compatible. The CLI itself only emits well-known statuses; this is just a new well-known one.
- **`build_rich_output` for `dry_run` may not match what users expect.** A 1-line rendering choice; cheap to change post-merge if feedback comes in.

## Testing

Automated:
- Unit: `_use_case.py` dry-run path returns the right status without calling `create_tag`.
- CLI: `semvertag tag --dry-run --json` returns the right JSON envelope.
- 100% branch coverage on the `semvertag` package (enforced by `pyproject.toml`'s `[tool.coverage.report] fail_under = 100` plus `--cov=semvertag --cov-branch` in pytest's `addopts`).
- All existing tests still pass (default `dry_run=False`).

Manual:
- `uvx --from . semvertag tag --dry-run` against the real repo — verify no tag is pushed and the output is informative.
- `semvertag tag --dry-run --json` — verify JSON shape matches §5.

## Follow-ups (PR B, not in this spec)

- Add `dry-run` input to `action.yml`. When `true`, pass `--dry-run` to the CLI invocation.
- Bump `action.yml`'s semvertag version floor from `>=0.3.1,<1` to `>=0.5.0,<1`.
- Update `ci.yml`'s `action-smoke` job to set `with: { dry-run: true }`, drop `permissions: contents: write`, and switch the assertion from "outputs.status == no-bump" to "outputs are well-formed AND status != created".
- Document `dry-run` in `docs/providers/github.md` (and add a "preview the next bump" usage example).

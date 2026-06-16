---
status: shipped
date: 2026-06-16
slug: branch-prefix-patch-on-non-merge
supersedes: null
superseded_by: null
pr: 24
outcome: Shipped. Opt-in patch_on_non_merge_commit flag (default False) added to
  branch-prefix; a non-merge HEAD commit bumps patch when enabled. Conclusions
  promoted into architecture/strategies.md.
---

# Design: Opt-in patch bump for non-merge commits (branch-prefix)

## Summary

Add an opt-in `branch-prefix` config flag, `patch_on_non_merge_commit` (default
`False`), that makes the strategy return `Bump.PATCH` instead of `Bump.NONE`
when the HEAD commit on the default branch is a plain (non-merge) commit. Teams
that allow direct pushes to the default branch can then auto-tag a patch release
for each such push instead of silently skipping. Default-off preserves today's
behavior byte-for-byte. Scope: the `branch-prefix` strategy only, the
non-merge exit only.

## Motivation

`branch-prefix` exists to bump on merge commits: the merged branch name carries
the level (`feature/` → minor, `bugfix/`/`hotfix/` → patch). A commit pushed
directly to the default branch — not via an MR/PR — carries no merge mark, so
`BranchPrefixStrategy.decide` returns `Bump.NONE` and the run ends with status
`no_merge_commit` (`semvertag/strategies/branch_prefix.py:33-34`,
`semvertag/_use_case.py:52`). For a team that permits direct pushes, that means
real changes land on the default branch with no version movement at all. A
sensible default for "code changed but no merge told me how much" is the
smallest bump: patch. Making it opt-in lets those teams get an automatic patch
release per direct push without affecting anyone relying on merge-only bumping.

## Non-goals

- Not changing the default behavior: the flag defaults to `False`, so existing
  users see no change.
- Not touching the `conventional-commits` strategy; a non-conforming commit
  there still returns `Bump.NONE`. An analogous fallback can be a later change.
- Not changing the merge-with-unrecognized-prefix exit
  (`branch_prefix.py:39`): a commit that *is* a merge but matches neither the
  minor nor patch tables still returns `Bump.NONE`. The flag only governs the
  "not a merge at all" case, matching the request's framing.
- No CLI flag: the existing `branch_prefix` config fields (`minor`, `patch`,
  `merge_mark_texts`) are env/config-only; the new field follows suit.
- No use-case or output-messaging change (see Design §3).

## Design

### 1. Config field

Add one field to `BranchPrefixConfig`
(`semvertag/strategies/branch_prefix.py`):

```python
class BranchPrefixConfig(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    minor: tuple[_NonEmptyStr, ...] = pydantic.Field(default=("feature/",), min_length=1)
    patch: tuple[_NonEmptyStr, ...] = pydantic.Field(default=("bugfix/", "hotfix/"), min_length=1)
    merge_mark_texts: tuple[_NonEmptyStr, ...] = pydantic.Field(
        default=("Merge branch", "Merge pull request"),
        min_length=1,
    )
    patch_on_non_merge_commit: bool = False
```

It rides the existing `Settings.branch_prefix: BranchPrefixConfig` wiring
(`semvertag/_settings.py:98`) and the IoC builder
(`semvertag/ioc.py:68-69`), so it is settable via
`SEMVERTAG_BRANCH_PREFIX__PATCH_ON_NON_MERGE_COMMIT=true` with no new plumbing.
Standard pydantic-settings bool coercion applies (`true`/`1`/`yes` → `True`).

### 2. `decide` change

The non-merge exit gains a single ternary; nothing else in the method moves:

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

### 3. Why no use-case or messaging change

`semvertag/_use_case.py:51-60` turns any non-`NONE` bump into a real tag and
only emits the strategy's `no_bump_status` / `no_bump_reason` on the `NONE`
path. When the flag fires, a non-merge commit yields `Bump.PATCH`, so the run
produces a normal `tagged` (or `dry_run`) result through the existing path. The
`no_merge_commit` status/reason ClassVars are still correct: they are read only
when `decide` returns `NONE`, which still happens for unrecognized merges and
for non-merge commits when the flag is off. No new status string is introduced.

## Testing

Unit tests in `tests/unit/test_branch_prefix_strategy.py`. The global pytest
config runs `--cov-branch` with `fail_under = 100`, so the new ternary's `True`
and `False` arms must both be exercised.

- **Flag on, non-merge → PATCH.** A `BranchPrefixStrategy` built with
  `BranchPrefixConfig(patch_on_non_merge_commit=True)` returns `Bump.PATCH` for
  each existing `_NON_MERGE_CASES` subject (`feat: ...`, `docs: ...`, `""`,
  lowercase `merge branch ...`).
- **Flag on does not disturb the merge paths.** With the flag on, a recognized
  feature merge still returns `MINOR`, a bugfix/hotfix merge still `PATCH`, and
  an unrecognized *merge* (`_UNRECOGNIZED_MERGE_CASES`) still `NONE` — proving
  the flag governs only the non-merge exit, not line 39.
- **Flag off (default) unchanged.** The existing
  `test_returns_none_when_message_is_not_a_merge_commit` already covers the
  `False` arm; it stays green untouched.
- **Default value.** Assert `BranchPrefixConfig().patch_on_non_merge_commit is
  False`.

No config-validation case is needed (a bool cannot be empty). No
integration-level test is required: the `decide → PATCH → tag` wiring is already
covered by existing use-case tests that exercise a non-`NONE` bump.

## Docs

On merge (per the planning convention, the change promotes its conclusions into
the affected capability doc):

- `architecture/strategies.md` — note the opt-in `patch_on_non_merge_commit`
  under the `branch-prefix` section's step 1.
- mkdocs config/reference page for `branch-prefix` — document the new env var
  and its default.

## Risk

Low. The behavior change is gated behind a default-`False` flag, so existing
installs are unaffected. The single new branch is fully covered by the
100%-branch gate. The main user-facing consideration is conceptual, not a code
risk: with the flag on, *any* direct push to the default branch (including a
docs typo fix) triggers a patch tag — which is exactly the intended semantics,
and is documented as such. No rollback concern: flipping the flag back to
`False` restores prior behavior immediately.

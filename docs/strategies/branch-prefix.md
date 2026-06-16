# Branch-prefix strategy

The `branch-prefix` strategy inspects the subject line of each commit
and picks a bump if the subject (a) looks like a merge commit and
(b) contains a configured branch-name prefix. It is the default
strategy because it works out-of-the-box on repos that merge via
short-lived prefixed branches and use the default `git merge`
behavior.

## Default prefix-to-bump table

| Substring in commit subject | Bump |
|---|---|
| `feature/` | minor |
| `bugfix/` or `hotfix/` | patch |
| anything else | none |

A bump of `none` means the commit contributes nothing to the release
decision. Major bumps are not produced by `branch-prefix` — promote
to a new major version manually, or switch to
[Conventional Commits](conventional-commits.md) which recognizes
`feat!` and `BREAKING CHANGE:`.

## Merge-commit detection

The strategy only fires on commits whose subject contains the literal
string `Merge branch` (the default `git merge` subject). Commits
without one of those marks return `none` regardless of prefix. This
means:

- Standard `git merge feature/foo` → subject `Merge branch 'feature/foo' into main` → bump = minor ✓
- GitHub's `Merge pull request #N from user/feature/foo` → bump = minor ✓
- Direct pushes to the default branch → bump = none, unless
  `patch_on_non_merge_commit` is enabled (see below), in which case
  bump = patch.

The `merge_mark_texts` tuple is configurable (defaults to
`("Merge branch", "Merge pull request")`); adapt it for non-default
merge-commit conventions (e.g. squash-merge prefixes).

## Customizing the prefixes

The strategy reads its prefixes from the application's settings layer:

- `minor` — tuple of prefixes that trigger a minor bump (default
  `("feature/",)`).
- `patch` — tuple of prefixes that trigger a patch bump (default
  `("bugfix/", "hotfix/")`).
- `merge_mark_texts` — tuple of substrings that mark a subject as a
  merge commit (default `("Merge branch", "Merge pull request")`).
- `patch_on_non_merge_commit` — when `true`, a plain (non-merge) commit on
  the default branch bumps patch instead of producing no bump (default
  `false`). Set via `SEMVERTAG_BRANCH_PREFIX__PATCH_ON_NON_MERGE_COMMIT=true`.
  Affects only the non-merge case; a merge commit with an unrecognized prefix
  still produces no bump.

These are set via the same pydantic-settings env-var mechanism used
for tokens / endpoints — see the provider docs for the variable
naming convention.

## When to pick a different strategy

If your team commits Conventional Commits messages directly to the
default branch (without merge commits), switch to
[Conventional Commits](conventional-commits.md) — that strategy
scans every commit since the last tag and does not depend on merge
metadata.

## Consumer integration

The strategy is selected per project via the `strategy:` input on the
relevant provider's component / action. See:

- [GitLab CI](../providers/gitlab.md) — set `strategy: branch-prefix`
  on the `include: - component:` block.

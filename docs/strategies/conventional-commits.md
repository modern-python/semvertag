# Conventional Commits strategy

The `conventional-commits` strategy parses the subject line of the
head commit on the default branch against the
[Conventional Commits](https://www.conventionalcommits.org/) grammar
and decides the bump from that one commit. It does not scan the
commits since the latest tag; see [Head commit only](#head-commit-only).

## Default type-to-bump mapping

| Commit marker | Bump |
|---|---|
| `BREAKING CHANGE:` or `BREAKING-CHANGE:` in commit body | major |
| `!` suffix on the type (e.g. `feat!:`, `fix!:`, `refactor!:`) | major |
| `feat:` (or `feat(scope):`) | minor |
| `fix:` (or `fix(scope):`), `perf:` (or `perf(scope):`) | patch |
| Any other type (`chore`, `docs`, `refactor`, `style`, `test`, `build`, `ci`, `revert`, ...) | none |
| Commits whose subject does not match the type-grammar at all | none |

The grammar checked is `^(type)(?:\((scope)\))?(!)?:`. Anything not
matching this pattern returns `none`. The `!` marker takes precedence
over the type — `chore!:` is a major bump even though `chore` is
otherwise unmapped.

## Customizing the type lists

The strategy reads its type lists from the application's settings
layer:

- `minor_types` — tuple of types that trigger a minor bump (default
  `("feat",)`).
- `patch_types` — tuple of types that trigger a patch bump (default
  `("fix", "perf")`).

Both lists are validated against the lowercase-letters-only regex
`^[a-z]+$`. Major bumps come from `BREAKING CHANGE:` / `!` markers
only and are not configurable.

## Head commit only

semvertag runs once per push to the default branch and fetches exactly
one commit, the head. The strategy reads that commit's subject and
body; nothing else on the branch is considered, so a `feat:` two
commits back does not promote a `chore:` head to a minor bump. This
matches a squash-merge workflow, where one push is one commit whose
subject is the pull request title. With a merge-commit workflow the
head is the merge commit, and a default `Merge branch 'foo' into
main` subject does not match the grammar, so the strategy declines
with `no_conforming_commit`; use [Branch prefix](branch-prefix.md)
there, since it reads the merge commit's source branch instead,
keeping in mind that it produces no major bumps.

Because nothing looks back, a run that fails after a bump-worthy push
must be re-run: the next push is judged on its own head, and the
earlier bump is not recovered.

## When to pick a different strategy

If your team merges via short-lived prefixed branches (`feature/...`,
`bugfix/...`) and does not enforce Conventional Commits on each
commit, switch to [Branch prefix](branch-prefix.md) — it reads the
merge commit's source branch rather than the per-commit subject.

## Consumer integration

The strategy is selected per project via the `strategy:` input on the
relevant provider's component / action. See:

- [GitLab CI](../providers/gitlab.md) — set
  `strategy: conventional-commits` on the `include: - component:` block.

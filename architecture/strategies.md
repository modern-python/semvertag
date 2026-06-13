# Strategies

A strategy decides the next semantic-version *bump level* from a single repo
signal: the latest commit on the default branch. It does not pick a tag, read
the tag history, or touch the network — it answers one question, "given this
commit, how much should the version move?", and returns a `Bump`. The use-case
(`semvertag/_use_case.py`) owns everything else: it fetches the commit, picks
the latest semver tag, calls the strategy, and only then applies the bump.

## The contract

`semvertag/strategies/_base.py` defines `BumpStrategy`, a `typing.Protocol`
(structural, not an ABC — strategies are matched by shape, not inheritance).
Every strategy carries three class-level strings and one method:

- `name: str` — the strategy id surfaced in output and matched against
  `--strategy` / `SEMVERTAG_STRATEGY`.
- `no_bump_status: str` / `no_bump_reason: str` — the machine status and the
  human sentence the use-case emits when this strategy declines to bump. Each
  strategy owns its own pair so the "why nothing happened" message is specific
  to the rule that fired.
- `decide(self, commit: Commit) -> Bump` — receives the latest commit
  (`Commit` is a frozen `sha` + `message`, from `semvertag/_types.py`) and
  returns one of `Bump.NONE | PATCH | MINOR | MAJOR` (`semvertag/_types.py`).

The two concrete strategies are frozen, slotted, kw-only dataclasses, each
holding a frozen pydantic config so the prefix/type tables are validated once
at construction and immutable thereafter. They are registered for resolution in `semvertag/ioc.py` inside
`StrategiesGroup`, where `current_strategy` dispatches via
`_build_current_strategy` based on `settings.strategy`. `decide` sees one commit, never a range —
the use-case only fetches the head of the default branch.

## branch-prefix

`semvertag/strategies/branch_prefix.py` infers the bump from the *subject line*
of a merge commit. `BranchPrefixStrategy.decide` takes the first non-blank line
of the message (via `subject_line`, below) and applies, in order:

1. If the subject contains none of `config.merge_mark_texts`, return
   `Bump.NONE`. The default marks are `"Merge branch"` and `"Merge pull
   request"`, so an ordinary GitHub PR merge-commit subject
   (`Merge pull request #N from owner/feature/...`) and a GitLab merge-commit
   subject both qualify under the defaults; a plain non-merge commit does not.
2. If any string in `config.minor` appears in the subject, return `Bump.MINOR`.
   Default: `("feature/",)`.
3. If any string in `config.patch` appears, return `Bump.PATCH`. Default:
   `("bugfix/", "hotfix/")`.
4. Otherwise `Bump.NONE`.

Matching is substring containment, not a prefix anchor — the merged branch name
appears mid-subject in a merge commit, so the prefix is sought anywhere in the
line. The mapping is therefore prefix → level: `feature/` → minor,
`bugfix/`/`hotfix/` → patch. The tables come from `BranchPrefixConfig` (a frozen
pydantic model in the same file), which is populated from settings under
`SEMVERTAG_BRANCH_PREFIX__*` and defaulted via `Settings.branch_prefix`. Each
tuple is `min_length=1`, so a strategy can never be configured with an empty
match set.

## conventional-commits

`semvertag/strategies/conventional_commits.py` derives the bump from a
[Conventional Commits](https://www.conventionalcommits.org/) header on the
commit subject. `ConventionalCommitsStrategy.decide`:

1. Matches the subject against
   `^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!?):` — a lowercase
   type, an optional `(scope)`, an optional `!`, then a colon. No match →
   `Bump.NONE`.
2. Scans the commit *body* (via `body_lines`) for a footer line beginning with
   `BREAKING CHANGE:` or `BREAKING-CHANGE:`. Found → `Bump.MAJOR`.
3. If the header carried `!` (`match["bang"] == "!"`) → `Bump.MAJOR`.
4. If the type is in `config.minor_types` (default `("feat",)`) → `Bump.MINOR`.
5. If the type is in `config.patch_types` (default `("fix", "perf")`) →
   `Bump.PATCH`. Note both `fix` *and* `perf` map to patch by default.
6. Otherwise `Bump.NONE`.

Breaking always wins over the type-table lookup because steps 2–3 return before
step 4. `ConventionalCommitsConfig` (frozen pydantic, same file) validates each
configured type against `^[a-z]+$` at load time, rejecting malformed entries
before any commit is parsed.

## The no-bump path

When a strategy finds nothing to act on it returns `Bump.NONE`. The use-case
detects this with an identity check (`if bump is Bump.NONE:`) and emits a
`RunResult` whose `status`/`reason` are the strategy's own `no_bump_status` /
`no_bump_reason` — `no_merge_commit` for branch-prefix, `no_conforming_commit`
for conventional-commits. `Bump.NONE` is thus the single, explicit "do nothing"
signal; callers never infer a no-op from a missing tag. (The use-case has two
*earlier* no-bump exits of its own — `no_tags` and `already_tagged` — that fire
before the strategy is consulted at all.)

## _commit_parse.py

`semvertag/_commit_parse.py` holds two pure message-slicing helpers shared by
both strategies; it does **not** parse Conventional Commits itself (the type /
scope / breaking-marker regex lives in `conventional_commits.py`):

- `subject_line(message)` — the first non-blank line, right-stripped, or `""`.
- `body_lines(message)` — every line after the subject and its first blank
  separator, right-stripped, blanks within the body preserved as skips. This is
  what lets the conventional-commits strategy find a `BREAKING CHANGE:` footer
  while ignoring the subject and the blank line under it.

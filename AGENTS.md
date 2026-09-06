# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`semvertag` auto-tags a GitLab or GitHub repository with a semantic-version git tag from CI.
[`CONTEXT.md`](CONTEXT.md) opens with what it does and owns the vocabulary — read it before naming a
concept in code, a test name, or an issue title. It ships as a Python CLI plus two thin wrappers over
it: a GitHub Actions composite (`action.yml`) and a GitLab CI Catalog component
(`templates/semvertag.yml`).

## Commands

`just` (task runner) and `uv` (package manager). The [`justfile`](justfile) is the source of truth —
`just --list`, or read it. The one thing it does not say: `just test` passes args through, so
`just test tests/unit/test_branch_prefix_strategy.py -q` works.

## Architecture

A human at a shell, the GitHub Action, and the GitLab CI component all invoke the same
`semvertag tag`, and `semvertag/` is short enough to read. What reading it will not tell you is why
four of its shapes are load-bearing rather than incidental: the two forge adapters are independent
copies sharing only the RFC 8288 pagination loop
([ADR-0001](docs/adr/0001-forge-providers-not-unified.md)) and their status-to-error ladders stay
duplicated for the same reason ([ADR-0003](docs/adr/0003-error-translators-not-tabled.md)); there is
one verb and no `doctor` preflight ([ADR-0006](docs/adr/0006-no-doctor-preflight-command.md)); and
the composite action deliberately does not check the repository out
([ADR-0007](docs/adr/0007-composite-action-does-not-check-out.md)).

## Cutting a release (maintainers)

Push a bare semver tag off green `main` — `git tag 0.9.0 && git push origin 0.9.0`;
[`release.yml`](.github/workflows/release.yml) does the rest and its comments say in what order and
why. Two things that file cannot tell you: the tag is the commitment point, cut by convention only
off a green `main` with no in-workflow CI gate; and if `just publish` succeeds but a later step
fails, do **not** re-push the tag — PyPI rejects re-uploading an existing version, so create the
Release and move `v0` by hand, or cut a new patch tag.

## Workflow

**The spec for a change is its PR body**, not a committed file: why, design, non-goals, verification,
reviewed with the diff. There is no change file and no lane to choose. A trivial PR (typo, dep bump,
formatter, CI tweak) ships a conventional-commit title with no body ceremony.

Two things outlive the PR, and there are exactly two places to put them: an alternative **rejected**
with reasoning becomes an ADR in [`docs/adr/`](docs/adr/) (`NNNN-slug.md`, sequential, with a revisit
trigger), and real work **not scheduled** becomes a GitHub issue. There is no third state, and no
separate truth-home directory — a behaviour change is reviewed with the diff, not promoted to a page.

### Where a fact goes

Four homes, one owner each:

| Home | Holds |
|---|---|
| `semvertag/` | anything readable from the source — the default |
| a named test | an **invariant**: must stay true, and a change could silently break it |
| `docs/adr/` | a rejected alternative, with the reasoning that would otherwise be re-litigated |
| `README.md` and `docs/` | anything a user needs |

Before writing a line anywhere:

> Can an agent get this by reading `semvertag/`? → **don't write it.**
> Would a wrong change here fail a test? → it belongs **in the test**, not in prose.
> Does a user need it? → **`README.md` / `docs/`**.
> Otherwise it does not get written.

**Prose about mechanism has no home. There is no file to add a paragraph to.** This file included:
it is always loaded, so a line that restates a docstring, a justfile comment, or `pyproject.toml`
costs every turn and rots in two places at once. The workflow files here carry dense explanatory
comments; re-telling them in this file is the failure mode to watch for.

An invariant is a test whose name is the claim, with a docstring opening `INVARIANT:` and a second
paragraph naming **what breaks it** — design rationale, not a report of what this one test catches.
Nothing enforces that docstring shape; it is read at review time. A relative link to an ADR *is*
checked — CI runs lychee `--offline` over every `.md` — but a path named in a docstring or a comment
is not. Both ADRs and `INVARIANT:` docstrings ratchet: nothing prunes a record once its call is
settled. Keeping them lean is a standing habit.

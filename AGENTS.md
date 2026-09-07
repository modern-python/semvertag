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
`semvertag tag`, and `semvertag/` is short enough to read.

## Cutting a release (maintainers)

Push a bare semver tag off green `main` — `git tag 0.9.0 && git push origin 0.9.0`;
[`release.yml`](.github/workflows/release.yml) does the rest and its comments say in what order and
why. Two things that file cannot tell you: the tag is the commitment point, cut by convention only
off a green `main` with no in-workflow CI gate; and if `just publish` succeeds but a later step
fails, do **not** re-push the tag — PyPI rejects re-uploading an existing version, so create the
Release and move `v0` by hand, or cut a new patch tag.

## Workflow

Real work **not scheduled** becomes a GitHub issue.

An invariant is a test whose name is the claim, with a docstring opening `INVARIANT:` and a second
paragraph naming **what breaks it** — design rationale, not a report of what this one test catches.
Nothing enforces that docstring shape; it is read at review time.

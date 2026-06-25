# Architecture

The living, code-current truth about *what `semvertag` does now* — one file per
capability, plain prose, dated by git. This is the truth home: the
authoritative account each capability funnels through. `planning/` records *how
it got here*; this directory records *what it is*.

## Capabilities

- **[cli.md](cli.md)** — the `semvertag tag` entry point: flags + environment →
  validated `Settings`, modern-di wiring of provider + strategy, the use-case
  run, and the GitHub Action / GitLab CI component wrappers.
- **[providers.md](providers.md)** — the forge adapters (GitLab, GitHub): the
  forge-neutral contract for reading commits and tags and creating a tag,
  hiding REST-vs-REST differences.
- **[strategies.md](strategies.md)** — bump-level strategies (`branch-prefix`,
  `conventional-commits`): deciding the next semver bump level from a single
  repo signal, no network, no tag history.

## Promotion rule

When a change alters a capability's behavior, hand-edit the matching
`architecture/<capability>.md` in the **same PR** as the code, reviewed in the
same diff — never as a separate post-merge step. That hand-edit is what keeps
this directory true; the change bundle in `planning/changes/` stays as the *why*.

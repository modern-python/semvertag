# GitHub Actions

Use semvertag in GitHub Actions via the published composite action
(`uses: modern-python/semvertag@v0`). The action installs `uv`, runs
`semvertag tag`, and surfaces the result as step outputs. A pure-CLI
fallback for environments that can't consume the action lives at the
bottom of this page.

## Quick Start

The minimum useful workflow: auto-tag on every push to the default
branch.

> **Required setup.** Either rely on the workflow-scoped
> `GITHUB_TOKEN` (which is auto-issued per job) — in which case the
> workflow MUST declare `permissions: contents: write` — OR provide a
> fine-grained PAT with `contents: write` (single repo) or a classic
> PAT with `repo` / `public_repo` scope. Store the PAT as a repo
> secret named `SEMVERTAG_TOKEN`; the alias chain picks it up ahead
> of `GITHUB_TOKEN`.

```yaml
name: semvertag
on:
  push:
    branches: [main]

permissions:
  contents: write

jobs:
  tag:
    runs-on: ubuntu-latest
    steps:
      - uses: modern-python/semvertag@v0
```

The job runs against the latest commit on the default branch and, if
a bump is warranted by the configured strategy, creates a new tag
ref via the GitHub API. If no bump is warranted, the job exits 0
without pushing.

> **Auto-detection.** semvertag detects GitHub Actions from the
> `GITHUB_ACTIONS=true` env var that GHA sets automatically. The
> `--provider` flag is therefore optional inside GHA — explicit
> `--provider github` is only needed when running outside GHA (e.g.
> on a developer laptop targeting a github.com repo).

> **No checkout needed.** semvertag reads the head commit and the tag
> history over the GitHub API and never touches the working tree, so
> the job needs neither an `actions/checkout` step nor a `fetch-depth`
> setting. Add a checkout only if other steps in the same job need the
> repository files.

## Strategy

Pass `--strategy` (or set `SEMVERTAG_STRATEGY`) to one of:

| Value | Description |
|---|---|
| `branch-prefix` (default) | Bump from the source-branch prefix of the latest merge commit. |
| `conventional-commits` | Bump from the head commit's Conventional Commits header. |

```yaml
      - uses: modern-python/semvertag@v0
        with:
          strategy: conventional-commits
```

> **Strategy-specific env vars** (e.g. `SEMVERTAG_BRANCH_PREFIX__MINOR`)
> remain configured on the calling step. The composite action only
> explicitly sets `GITHUB_TOKEN` and `SEMVERTAG_STRATEGY`; every other
> env var on the calling step passes through to the action's run step.
>
> ```yaml
>       - uses: modern-python/semvertag@v0
>         env:
>           SEMVERTAG_BRANCH_PREFIX__MINOR: '["feat/"]'
> ```

## Required permissions

The job creates a tag ref, so the token it uses MUST carry write
access to the repository's contents. semvertag reads the token from
these env vars in order:
`SEMVERTAG_GITHUB__TOKEN`, `SEMVERTAG_TOKEN`, `GITHUB_TOKEN`. The
first set value wins.

## Outputs

When you give the step an `id:`, downstream steps can read three outputs:

| Output | Value |
|---|---|
| `tag` | The created tag (e.g. `v1.2.3`), or empty string when `status` is `no-bump`. |
| `bump` | `none` \| `patch` \| `minor` \| `major`. |
| `status` | `created` (tag pushed) \| `no-bump` (nothing to tag — no prior tag, already tagged, no merge commit, or non-conforming commit). On CLI error the action itself exits non-zero and this output is not written. |

Example: trigger a downstream release-notes job only when a tag was
created.

```yaml
name: semvertag-and-release
on:
  push:
    branches: [main]

jobs:
  tag-and-release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - id: semvertag
        uses: modern-python/semvertag@v0
      - if: steps.semvertag.outputs.status == 'created'
        run: |
          echo "tagged ${{ steps.semvertag.outputs.tag }}"
          echo "bump=${{ steps.semvertag.outputs.bump }}"
```

## Preview the next bump

Pass `dry-run: true` to compute the bump without pushing a tag — useful in
CI smoke tests, in PR previews, or to see what the next release would be:

```yaml
- id: semvertag
  uses: modern-python/semvertag@v0
  with:
    dry-run: true
```

When `dry-run: true`, the action's `status` output is `no-bump` (no real tag
was pushed) and `bump` / `tag` reflect what *would* have happened. The raw
CLI's `status` field is `dry_run`; the action surface normalizes it to
`no-bump` so callers see a stable two-value enum.

You can also run this locally without the action:

```bash
uvx 'semvertag>=0.5.0' tag --dry-run --json
```

Output (example):

```json
{"schema_version":"1.0","strategy":"branch-prefix","bump":"minor","status":"dry_run","tag":"0.6.0","commit":"abc1234..."}
```

## Token scope: `GITHUB_TOKEN` vs Personal Access Tokens

Three cases govern which token the job should use:

- **Workflow-scoped `GITHUB_TOKEN`** (preferred for most projects).
  GitHub Actions issues a fresh token per job; it inherits the
  workflow's `permissions:` block. Add `permissions: contents: write`
  at the workflow level (as in the snippet above). The token is
  auto-exported as `GITHUB_TOKEN` and picked up by the alias chain.
- **Fine-grained PAT scoped to the single repository.** Required
  scope: `Contents: Read and write`. Store as a repo secret named
  `SEMVERTAG_TOKEN`; the alias chain picks it up ahead of
  `GITHUB_TOKEN`. Use this when the workflow runs across
  organizations or needs scopes the workflow token can't grant.
- **Classic PAT.** Required scope: `repo` (private repos) or
  `public_repo` (public repos only). Same storage shape as the
  fine-grained PAT. Less preferred — classic PATs bleed scope
  across all of the user's repos.

> **Masking caveat.** Because the alias chain reads
> `SEMVERTAG_GITHUB__TOKEN` → `SEMVERTAG_TOKEN` → `GITHUB_TOKEN` in
> order and the first set value wins, a stale `SEMVERTAG_TOKEN` left
> over from a prior PAT-based setup will silently override the
> workflow's `GITHUB_TOKEN`. If you migrate from PAT →
> workflow-token, unset `SEMVERTAG_TOKEN` from the repo's secrets.

**GitHub Enterprise**: set `SEMVERTAG_GITHUB__ENDPOINT` (note the
double underscore — pydantic-settings uses `__` as the nested-key
delimiter, so `SEMVERTAG_GITHUB_ENDPOINT` with a single underscore is
silently ignored) as a workflow-level env or a repo secret pointing
to the instance's API root, e.g.
`https://github.example.com/api/v3`. The default is
`https://api.github.com`.

For most consumers on `github.com`-hosted repos with the
workflow-scoped `GITHUB_TOKEN`, the minimal workflow snippet above
is the entire setup.

## Branch-prefix vs conventional-commits

Pick `branch-prefix` if your team merges PRs with branch names that
follow a `fix/...`, `feat/...`, `chore/...` convention. semvertag
reads the most recent merge commit's source-branch prefix and bumps
accordingly — `fix/` bumps patch, `feat/` bumps minor, `chore/`
bumps nothing. This is the default. See
[Branch-prefix strategy](../strategies/branch-prefix.md) for the full
prefix-to-bump table and edge-case behavior.

Pick `conventional-commits` if your team writes
[Conventional Commits](https://www.conventionalcommits.org/) messages
directly on the default branch (e.g. `feat: add X`, `fix: handle Y`,
`feat!: drop Z`), typically with squash merges so that each push is
one commit. semvertag reads the head commit's type prefix (`feat!` or
`BREAKING CHANGE:` → major, `feat:` → minor, `fix:` → patch,
everything else → none); it does not scan the commits since the
latest tag. See
[Conventional Commits strategy](../strategies/conventional-commits.md)
for the full type-to-bump mapping.

## Without the composite action

If your environment can't consume the action — GitHub Enterprise
instances without Marketplace access, security-constrained orgs that
forbid third-party actions, or anyone who wants explicit control over
the uv install step — paste the pure-CLI recipe instead:

```yaml
jobs:
  tag:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install --quiet --no-cache-dir 'uv>=0.4,<1'
      - run: uvx 'semvertag>=0.5.0,<1' tag
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

The behavior matches the composite action exactly; only the install
shape differs. Strategy is set via env (`SEMVERTAG_STRATEGY`) or CLI
flag (`--strategy …`). No outputs are produced in this shape — read
the CLI stdout, or invoke `semvertag tag --json` and parse the
envelope yourself.

## Troubleshooting

- **`Token rejected: 401. Verify SEMVERTAG_TOKEN is valid.`** — the
  token is malformed, expired, or revoked. Verify in GitHub UI
  (Settings → Developer settings → Personal access tokens) or
  rotate the workflow secret. When using the composite action,
  `GITHUB_TOKEN` is set automatically from the `token` input (which
  defaults to `${{ github.token }}`). When using the pure-CLI recipe
  in "Without the composite action", add
  `env: GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}` to the run step.

- **`Token missing scope or insufficient permission: 403`** — the
  token lacks `contents: write` (fine-grained / workflow-scoped) or
  `repo` / `public_repo` (classic). For workflow-scoped tokens,
  add `permissions: contents: write` at the workflow level. For PATs,
  re-issue with the right scope.

- **`GitHub repo not found: repo='...'`** — `GITHUB_REPOSITORY` was
  not exported, or `--repo OWNER/REPO` was not passed. Inside GHA,
  `GITHUB_REPOSITORY` is auto-exported in every job; outside GHA,
  set it explicitly.

- **`Tag already exists: 'v...'`** — a previous run (or a concurrent
  run) already created this tag. semvertag refuses to silently
  succeed on a duplicate. Roll forward by pushing another commit
  that changes the bump, or delete the duplicate tag.

- **GitHub Enterprise, but the job connects to `api.github.com`** —
  the default endpoint is `https://api.github.com`. Set
  `SEMVERTAG_GITHUB__ENDPOINT` (note the double underscore) as a
  workflow-level env pointing to the instance's API root, e.g.
  `https://github.example.com/api/v3`.

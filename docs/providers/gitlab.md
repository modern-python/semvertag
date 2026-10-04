# GitLab CI

Use semvertag in GitLab CI via a small inline job that installs `uv`
and runs `uvx semvertag tag`. Your repo needs no PyPI install and no
pipeline YAML beyond the snippet below.

> A one-line `include: - component: …` via the GitLab CI Catalog is the
> eventual delivery path, and its descriptor lives at
> [`templates/semvertag.yml`](https://github.com/modern-python/semvertag/blob/main/templates/semvertag.yml).
> The component has not yet been published to gitlab.com's Catalog.
> Paste the job below into `.gitlab-ci.yml` until then.

## Quick start

The minimum useful pipeline auto-tags on every push to the default
branch.

> Set `SEMVERTAG_TOKEN` as a project-level masked
> CI/CD variable holding a Project Access Token (or Personal Access
> Token) with `api` + `write_repository` scope. `CI_JOB_TOKEN` works
> on projects where the job-token write scope is opted in
> (see *Token scope* below).

```yaml
stages: [tag]

semvertag:
  stage: tag
  image: python:3.13-slim
  resource_group: semvertag
  variables:
    SEMVERTAG_STRATEGY: branch-prefix
  before_script:
    - pip install --quiet --no-cache-dir 'uv>=0.4,<1'
  script:
    - uvx 'semvertag>=0.1,<1' tag
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

The job runs against the head commit on the default branch and, if a
bump is warranted by the configured strategy, pushes a new tag to the
project's `origin`. If no bump is warranted, the job exits 0 without
pushing.

> semvertag bumps from the highest existing semver tag
> and never creates the first one. It reads plain semver tags such as
> `0.1.0` and `v`-prefixed ones such as `v0.1.0`, and each new tag keeps
> the prefix of the one it bumps from. Other forms (`V0.1.0`,
> `release-0.1.0`) are ignored. Until a readable tag exists, every run
> reports `no_tags` and exits 0. Push one with
> `git tag 0.1.0 && git push origin 0.1.0` (or `v0.1.0` for `v` tags).

> **Upgrading from a release that ignored `v` tags:** if your history is
> `v`-prefixed and you seeded a bare tag such as `0.1.0` to get started,
> semvertag now bumps from whichever tag has the highest version, usually
> your latest `v` tag (after `v1.4.0` comes `v1.5.0`, not `0.2.0`). When
> the same version exists in both forms, the `v` tag wins.

> `resource_group: semvertag` makes GitLab serialize concurrent
> `semvertag` jobs across pipelines on the same project, so
> back-to-back pushes queue instead of racing the `create_tag` API. Drop or rename the group if you intentionally want
> concurrent tag pushes.

## Strategy

Set `SEMVERTAG_STRATEGY` to one of:

| Value | Description |
|---|---|
| `branch-prefix` (default) | Bump from the source-branch prefix of the head commit, which must be a merge commit. |
| `conventional-commits` | Bump from the head commit's Conventional Commits message. |

When the Catalog component lands, this will become a typed `inputs:`
block on the `include:`. The values and default match
[`templates/semvertag.yml`](https://github.com/modern-python/semvertag/blob/main/templates/semvertag.yml)'s
`spec.inputs.strategy` so the migration is a snippet swap.

## Dry run

Pass `--dry-run` to compute the bump and report the planned tag
without pushing it. It needs semvertag 0.5.0 or later, so raise the
floor in the job:

```yaml
semvertag:
  # ...
  script:
    - uvx 'semvertag>=0.5.0,<1' tag --dry-run
```

The Catalog component exposes this as a boolean `dry-run` input,
`false` by default.


## Required permissions

The job pushes a tag, so the token it uses must carry write access to
the repository. semvertag reads the token from these env
vars in order: `SEMVERTAG_GITLAB__TOKEN`, `SEMVERTAG_TOKEN`,
`CI_JOB_TOKEN`, `GITLAB_TOKEN`. The first set value wins.

## Token scope: `CI_JOB_TOKEN` vs Project Access Tokens

Two cases govern which token the job should use:

- On GitLab projects where the maintainer has opted in to job-token
  write scope (Settings → CI/CD → Token Permissions → *Allow access
  from the project's token to write to the repository*), `CI_JOB_TOKEN`
  is auto-exported into every CI job and gets picked up by the alias
  chain with no further configuration.
- On projects that have not opted in, or projects on older GitLab
  versions where `CI_JOB_TOKEN` was scoped read-only by default, the
  consumer creates a Project Access Token (preferred; scoped to the
  one project) or a Personal Access Token (works but bleeds the
  user's scope across all their projects). Token scopes required:
  `api` + `write_repository`. Store the token as a masked CI/CD
  variable named `SEMVERTAG_TOKEN`; the alias chain picks it up
  ahead of `CI_JOB_TOKEN`.

> The alias chain reads `SEMVERTAG_GITLAB__TOKEN` → `SEMVERTAG_TOKEN`
> → `CI_JOB_TOKEN` → `GITLAB_TOKEN` in order and the first set value
> wins, so a stale
> `SEMVERTAG_TOKEN` left over from a prior PAT-based setup will
> silently override a freshly-rotated `CI_JOB_TOKEN`. If you migrate
> from PAT → job-token, unset `SEMVERTAG_TOKEN` (or rotate its value
> to empty) in the project's CI/CD variables.

For self-hosted GitLab, set `SEMVERTAG_GITLAB__ENDPOINT` as a project
CI/CD variable pointing to the instance's API root, e.g.
`https://gitlab.example.com`. The default is `https://gitlab.com` and
is not auto-derived from `CI_SERVER_FQDN`. Note the double underscore:
pydantic-settings uses `__` as the nested-key delimiter, so
`SEMVERTAG_GITLAB_ENDPOINT` with a single underscore is silently
ignored.

> Use scheme + host only for the endpoint. Do not append `/api/v4`
> (the client adds it); a value like `https://gitlab.example.com/api/v4`
> produces `…/api/v4/api/v4/…` URLs and 404s. A missing scheme
> (`gitlab.example.com`) fails at request time with httpx
> `ConnectError`. A trailing slash is tolerated (the client strips it).

For most consumers on `gitlab.com`-hosted projects with job-token
write scope, the minimal job snippet above is the entire setup.

## Branch-prefix vs conventional-commits

Pick `branch-prefix` if your team merges merge requests with branch
names that follow a `feature/...`, `bugfix/...`, `hotfix/...`
convention and lands them as merge commits. semvertag reads the head
commit's source-branch prefix and bumps accordingly: `feature/` bumps
minor, `bugfix/` and `hotfix/` bump patch, and a merge with any other
prefix bumps nothing (`unmapped_branch_prefix`). With squash merges the
head is not a merge commit and the run reports `no_merge_commit`.
This is the default. See
[Branch-prefix strategy](../strategies/branch-prefix.md) for the full
prefix-to-bump table and edge-case behavior.

Pick `conventional-commits` if your team writes
[Conventional Commits](https://www.conventionalcommits.org/) messages
directly on the default branch (e.g. `feat: add X`, `fix: handle Y`,
`feat!: drop Z`), typically with squash merges so that each push is
one commit. semvertag reads the head commit's type prefix and body
(`feat!` or a `BREAKING CHANGE:` footer → major, `feat:` → minor,
`fix:` → patch,
everything else → none); it does not scan the commits since the
latest tag. See
[Conventional Commits strategy](../strategies/conventional-commits.md)
for the full type-to-bump mapping and the head-commit rule.

Set the strategy per project by swapping the `SEMVERTAG_STRATEGY`
value in the job:

```yaml
semvertag:
  # ...
  variables:
    SEMVERTAG_STRATEGY: conventional-commits
```


## Troubleshooting

### `Token missing scope or insufficient permission: 403`

The token does not have `api` + `write_repository` scope, or the
project's protected-tag rules disallow the bot from creating tags.
Verify the `SEMVERTAG_TOKEN` scopes in the GitLab UI (Settings → Access
Tokens).

### `Project id missing. Set CI_PROJECT_ID or pass --project-id.`

The CI runner did not export `CI_PROJECT_ID`. Every standard GitLab CI
job exports the variable, but a custom executor that strips CI
variables would suppress it. Set `SEMVERTAG_PROJECT_ID` as a
project-level CI/CD variable as the override.

### Self-hosted GitLab, but the job connects to `gitlab.com`

The default endpoint is `https://gitlab.com` and is not auto-derived
from `CI_SERVER_FQDN`. Set `SEMVERTAG_GITLAB__ENDPOINT` as a
project-level CI/CD variable pointing to the instance's API root.

### `None of the repo's N tags is SemVer-form (1.2.0 or v1.2.0)`

The repo has tags, but semvertag reads none of them as a bump baseline,
so the run reports `no_tags` and exits 0 without tagging. It reads only
plain SemVer tags (`1.2.0`, `1.0.0-rc.1`) and the same with a lowercase
`v` (`v1.2.0`). It ignores other forms, such as `V1.2.0`,
`release-1.2.0`, PEP 440 prereleases like `0.9.0rc1`, and floating
major tags like `v1`. Push a SemVer tag on a default-branch commit to
start from, e.g. `git tag v0.1.0 && git push origin v0.1.0`.

### A bump-worthy push was never tagged

The run for that push failed or was skipped. Re-run it. Each run judges
only the head commit of its own push and does not look back, so the
next push cannot recover an earlier bump.

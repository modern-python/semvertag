# semvertag

Auto-tag your GitLab repository with semantic version tags from CI —
one tool, two strategies.

semvertag reads the latest commit and tag history from your GitLab
project via the API, decides the appropriate semver bump based on the
strategy you've configured, and creates the new git tag — all from a
single command in your CI pipeline.

## Quick start

In GitLab CI, run semvertag as a job on the default branch (see
[GitLab CI](providers/gitlab.md) for the full snippet):

```yaml
semvertag:
  image: python:3.13-slim
  variables:
    SEMVERTAG_STRATEGY: branch-prefix  # or: conventional-commits
  before_script:
    - pip install --quiet 'uv>=0.4,<1'
  script:
    - uvx 'semvertag>=0.1,<1' tag
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

For local testing or one-off invocations:

```sh
SEMVERTAG_TOKEN=<your-gitlab-token> \
SEMVERTAG_PROJECT_ID=<your-project-id> \
  uvx semvertag tag
```

> A one-line `include: - component: …` via the GitLab CI Catalog will
> replace the CI snippet above once the component is published.

## Strategies

semvertag ships with two bump-decision strategies:

- [**branch-prefix**](strategies/branch-prefix.md) — bump based on the
  source branch of the latest merge commit (`feature/` → minor,
  `bugfix/` / `hotfix/` → patch). The default.
- [**conventional-commits**](strategies/conventional-commits.md) —
  bump based on the latest commit's Conventional Commits header
  (`feat:` → minor, `fix:` / `perf:` → patch, `!` or
  `BREAKING CHANGE:` → major).

Both strategies are configurable via environment variables — see the
strategy pages for the full configuration surface.

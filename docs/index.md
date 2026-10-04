<div class="mp-hero" markdown>

<h1 class="mp-lockup">
<img class="mp-logo mp-logo--light" src="assets/lockup-light.svg" alt="semvertag">
<img class="mp-logo mp-logo--dark" src="assets/lockup-dark.svg" alt="" aria-hidden="true">
</h1>

</div>

Auto-tag your GitHub or GitLab repository with semantic version tags
from CI, using one of two bump strategies.

From a single command in your CI pipeline, semvertag reads the head
commit and tag history through the GitHub or GitLab API, decides the
semver bump with the strategy you've configured, and creates the new
git tag.

## Quick start

semvertag bumps from the highest existing semver tag and never creates
the first one. Before the first run, create a semver tag such as
`0.1.0`, or `v0.1.0` if you want `v`-prefixed tags: each new tag keeps
the prefix of the one it bumps from.

### GitHub Actions

Run the action on pushes to the default branch (see
[GitHub Actions](providers/github.md) for token options and outputs):

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

### GitLab CI

Run semvertag as a job on the default branch (see
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

For local testing or one-off invocations against GitLab:

```sh
SEMVERTAG_TOKEN=<your-gitlab-token> \
SEMVERTAG_PROJECT_ID=<your-project-id> \
  uvx semvertag tag
```

> A one-line `include: - component: …` via the GitLab CI Catalog will
> replace the CI snippet above once the component is published.

## Strategies

semvertag ships with two bump-decision strategies:

- [branch-prefix](strategies/branch-prefix.md), the default, bumps
  based on the source branch named in the head commit, which must be a
  merge commit (`feature/` → minor,
  `bugfix/` / `hotfix/` → patch).
- [conventional-commits](strategies/conventional-commits.md) bumps
  based on the head commit's Conventional Commits message
  (`feat:` → minor, `fix:` / `perf:` → patch, `!` or
  `BREAKING CHANGE:` → major).

Both strategies are configurable through environment variables. The
strategy pages cover the full configuration surface.

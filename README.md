# semvertag

[![PyPI version](https://img.shields.io/pypi/v/semvertag.svg)](https://pypi.org/project/semvertag/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/semvertag.svg)](https://pypi.org/project/semvertag/)
[![Downloads](https://img.shields.io/pypi/dm/semvertag.svg)](https://pypistats.org/packages/semvertag)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/semvertag/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/semvertag/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/semvertag/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/semvertag.svg)](https://github.com/modern-python/semvertag/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/semvertag)](https://github.com/modern-python/semvertag/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/semvertag)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)

Auto-tag your GitLab or GitHub repository with semantic version tags from CI — one tool, two strategies, two providers.

## Install

```sh
uvx semvertag tag
```

## Use it in GitLab CI

Paste this job into your `.gitlab-ci.yml`:

```yaml
stages: [tag]

semvertag:
  stage: tag
  image: python:3.13-slim
  variables:
    SEMVERTAG_STRATEGY: branch-prefix  # or: conventional-commits
  before_script:
    - pip install --quiet 'uv>=0.4,<1'
  script:
    - uvx 'semvertag>=0.5.0,<1' tag
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

It runs `uvx semvertag tag` against your repo on the default branch.
semvertag inspects the latest commit + tag history, decides the
appropriate semver bump, and creates the new tag via the GitLab API.

> A one-line `include: - component: …` via the GitLab CI Catalog will
> replace this snippet once the component is published. For now, paste
> the job inline.

## Use it in GitHub Actions

Paste this workflow into `.github/workflows/semvertag.yml`:

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
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: modern-python/semvertag@v0
```

semvertag auto-detects GitHub Actions, picks the bump from the latest
commit, and creates the tag ref via the GitHub API. `fetch-depth: 0`
matters — the default `1` misses tag-relative history. See
[GitHub Actions docs](docs/providers/github.md) for token scopes,
GitHub Enterprise setup, outputs, and troubleshooting.

## Strategies

- **branch-prefix** (default): the latest commit on the default branch
  must be a merge commit whose source branch starts with `feature/`
  (minor), `bugfix/`, or `hotfix/` (patch).
- **conventional-commits**: parses the latest commit's
  [Conventional Commits](https://www.conventionalcommits.org/)
  header (`feat:` minor, `fix:`/`perf:` patch, `!` or `BREAKING
  CHANGE:` major).

Both are configurable via env vars. See [docs](https://semvertag.modern-python.org)
for the full configuration surface.

## 📚 [Documentation](https://semvertag.modern-python.org)

## 📦 [PyPI](https://pypi.org/project/semvertag)

## 📝 [License](LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in
[`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.

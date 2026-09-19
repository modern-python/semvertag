# The composite action does not check out the repository

`action.yml` sets up `uv` and runs the CLI; it does not run `actions/checkout`, so
`uses: modern-python/semvertag@v0` is not self-contained and the caller owns the checkout step.
Folding one in was rejected because the caller has almost always already checked out, with options
the composite cannot guess: a specific `ref`, a submodule set, LFS objects, a sparse or monorepo
subpath, or a token other than `github.token`. A second checkout would either discard that setup or
fight it, and the failure would be confusing precisely because the step is invisible from the
calling workflow. The established actions in this niche, `mathieudutour/github-tag-action`,
`googleapis/release-please-action` and `cycjimmy/semantic-release-action`, uniformly skip it, so
callers already expect to own it. semvertag reads the head commit and the tag history over the
GitHub API and never touches the working tree, so a folded-in checkout would buy nothing and impose
a `fetch-depth` requirement the tool does not actually have.

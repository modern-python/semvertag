# The composite action does not check out the repository

**Decision:** `action.yml` sets up `uv` and runs the CLI. It does **not** run `actions/checkout`.
The caller checks out, and the caller owns `fetch-depth`.

The tempting alternative is to fold a checkout step in so `uses: modern-python/semvertag@v0` works
on its own. It is rejected because a composite that checks out silently *re-*checks out: the caller
has almost always already done it, with options the composite cannot guess. Real workflows check out
a specific `ref`, a submodule set, LFS objects, a sparse or monorepo subpath, or use a token other
than `github.token`. A second checkout inside the action either discards that setup or fights it,
and the failure is confusing precisely because the step is invisible from the calling workflow.

The established actions in this niche — `mathieudutour/github-tag-action`,
`googleapis/release-please-action`, `cycjimmy/semantic-release-action` — uniformly skip it, so
callers already expect to own the step.

The cost is one documented footgun rather than a hidden one: `actions/checkout` defaults to
`fetch-depth: 1`, which misses the tag-relative history, so the README and
`docs/providers/github.md` both call out `fetch-depth: 0`. That is a line in the caller's workflow
they can see and fix, which is the better trade against a checkout they cannot see at all.

**Revisit trigger:** GitHub gains a way for a composite action to *detect* that the workspace is
already checked out at the ref it needs, so a folded-in checkout could be conditional rather than
unconditional. At that point the convenience is free and the objection disappears.

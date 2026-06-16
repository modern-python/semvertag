# Deferred Work

Items raised in reviews or audits that are real but not actionable now.
Each is parked here with the reason it's deferred and the concrete trigger
that should bring it back. This is the long-tail register — not a backlog
of planned work. When an item is picked up it graduates to a spec/plan
bundle in [`changes/active/`](changes/active/); see [CLAUDE.md](../CLAUDE.md#workflow).

## Open

### conventional-commits non-conforming fallback flag

A `conventional-commits` flag analogous to branch-prefix's
`patch_on_non_merge_commit` (e.g. `patch_on_non_conforming_commit`), so a commit
whose subject is not a Conventional Commits header bumps patch instead of
returning `Bump.NONE`.

- **Deferred because:** the branch-prefix flag shipped alone
  ([branch-prefix-patch-on-non-merge](changes/archive/2026-06-16.02-branch-prefix-patch-on-non-merge/design.md),
  #24) to keep that change focused; the conventional-commits side was an
  explicit non-goal. The two strategies are now asymmetric.
- **Trigger:** a user requests the parallel behavior; or we add any other new
  config knob to `conventional-commits` (fold it in then); or we write a
  strategy-comparison doc where the asymmetry would mislead.

### httpware bounded-error-body adoption

Adopt httpware 0.11.0's opt-in `max_error_body_bytes` cap (raises
`ResponseTooLargeError`) when building the provider clients, to bound the bytes
read from a 4xx/5xx error body.

- **Deferred because:** the 0.12.0 bump
  ([httpware-0.12-get-with-response](changes/archive/2026-06-16.01-httpware-0.12-get-with-response/change.md),
  #24) skipped it — picking a cap value is a real config decision, not a
  mechanical bump, and the default (`None`, unbounded) matches prior behavior.
- **Trigger:** when we next harden provider error handling, or if a forge is
  observed returning large error bodies that bloat logs / memory in practice.

# No `doctor` preflight command

**Decision:** semvertag ships one verb, `tag`. There is no `doctor` subcommand and no preflight
diagnostic mode. Configuration and permission problems surface from the real run, through the domain
error hierarchy and its exit codes.

A `doctor` subsystem shipped and was removed pre-1.0. It ran four checks against the configured
forge — token validity, token scopes, project access, protected-tag permission — and mapped each to
a category exit code. It cost about 400 lines of source plus a comparable weight of tests, and it
picked its exit code by matching *string fragments* out of a check's `cause`, with a comment in the
code instructing the maintainer to keep those fragments in lockstep with the provider's wording.

Three arguments retire it, and they are the reasons not to bring it back.

The diagnostics were redundant. Every failure `doctor` could name — a rejected token, a missing
scope, an unreachable project, a refused tag creation — already surfaces from the real run as a
typed `AuthError` / `ConfigError` / `ProviderAPIError` with the same exit code and a message that
names the fix. The only thing the preflight added was reporting the failure a few seconds earlier,
and reporting it from a second code path that had to be kept in agreement with the first.

It taxed the `Provider` protocol. Four `check_*` operations sat on the forge-neutral contract, so
every forge added — GitHub then, Bitbucket later — owed four implementations that existed purely to
re-ask questions the ordinary operations already answer. A smaller protocol is what made the GitHub
provider cheap.

And the shape is rare for this kind of tool. Focused CLIs — `git`, `kubectl`, `gh`, `aws` — do not
carry one; `doctor` belongs to framework CLIs with many interacting config sources and a large
install surface (Flutter, Homebrew, Hugo). An auto-tagger reading two API endpoints is not that.

**Revisit trigger:** a failure mode appears that the real run genuinely cannot report — one where the
run succeeds or fails misleadingly and only a dedicated check would have caught it — or the
`Provider` protocol grows operations whose only caller would be a preflight. Either would mean the
redundancy argument no longer holds. Wanting a faster failure is not that trigger.

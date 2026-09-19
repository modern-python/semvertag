# No `doctor` preflight command

semvertag ships one verb, `tag`; configuration and permission problems surface from the real run as
a typed `AuthError`, `ConfigError` or `ProviderAPIError` carrying its own exit code. A `doctor`
subsystem shipped and was removed pre-1.0. It checked token validity, token scopes, project access
and protected-tag permission, and chose its exit code by matching string fragments out of a check's
cause, which had to be kept in lockstep with the provider's wording. Every failure it could name
already surfaces from the ordinary run with the same exit code and a message that names the fix, so
the preflight bought only a few seconds of earliness from a second code path. It also taxed the
forge-neutral `Provider` protocol with four `check_*` operations every new forge would owe, and a
small protocol is what made the GitHub provider cheap. Wanting a faster failure is not a reason to
bring it back; a failure the real run genuinely cannot report would be.

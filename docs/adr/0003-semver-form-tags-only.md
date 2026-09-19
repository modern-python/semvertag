# The bump baseline is SemVer-form only, and a prerelease baseline finalizes

`_select_latest_semver_tag` keeps only tags `semver.Version.parse` accepts, strips build metadata,
and takes the maximum by SemVer precedence; `_compute_new_version` then calls `Version.next_version`
rather than `bump_*`, so a prerelease baseline finalizes (`1.0.0-rc.1` plus a patch bump gives
`1.0.0`, not `1.0.1`). That is the correct release-ramp semantics and is identical to `bump_*` on
every stable baseline, so it changed no existing behaviour. PEP 440 prereleases such as `0.9.0rc1`
are deliberately skipped: python-semver cannot parse them, its `coerce` recipe discards the `rc1` and
makes a prerelease masquerade as final, and honest support means running `packaging` alongside
`semver` to consume a form a SemVer tagger should not have to. A leading `v` is skipped too, which is
a deferral rather than a rejection, since it is a one-line strip but would make semvertag consume a
convention it does not emit; the cost until then is that a repo whose history is entirely
`v`-prefixed reports `NoTags` and never bumps.

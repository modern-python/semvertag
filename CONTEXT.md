# semvertag

Auto-tags a GitLab or GitHub repository with a semantic-version git tag from CI:
it reads the head commit of the default branch and the tag history through the
forge's REST API, asks a strategy how far the version should move, and creates
the new tag. Shipped as a Python CLI plus two thin wrappers over it — a GitHub
Actions composite (`action.yml`) and a GitLab CI Catalog component
(`templates/semvertag.yml`).

## Language

A term is listed only when there is a synonym to reject, or a meaning subtle enough that code and
docs must agree on it. General semver and CI vocabulary — tag, version, release, major/minor/patch —
does not belong here, however heavily this project uses it.

**Forge**:
A repository-hosting service semvertag talks to over REST — GitLab or GitHub today.
_Avoid_: host. `host` is already spoken for by the same-origin pagination guard, whose two
user-visible error strings say a `Link` header "points to a different host"; there it means scheme +
netloc, not a forge.

**Provider**:
The adapter for one forge — `GitHubProvider` / `GitLabProvider` under `semvertag/providers/`, matched
structurally against the `Provider` protocol. Also the user-facing selector value
(`SEMVERTAG_PROVIDER=github`). Note the collision: `semvertag/ioc.py` imports `modern_di.providers`
in the same file, where a *provider* is a DI recipe. Say **provider** for the forge adapter and
**modern-di provider** for the other.

**Strategy**:
The rule that turns **one** commit into a `Bump`. It receives the head commit of the default branch
and nothing else — no network, no tag history, no commit range. A strategy never picks a tag or a
version; the use-case does that around it.

**Latest tag**:
The bump baseline: the **highest by SemVer precedence** among the repo's SemVer-parseable tags — not
the most recently created one, and not the tag reachable from HEAD. `_select_latest_semver_tag`
sorts by `semver.Version` and takes the maximum.
_Avoid_: last tag, most recent tag. Both read as "newest by date", which names a different tag the
moment a patch on an older line is pushed after a newer minor.

**Outcome**:
What a run did, as the closed sum `Created | DryRun | NoTags | AlreadyTagged | NoBump` in
`semvertag/_outcome.py`. It is internal and free to grow — the renderers `match` it exhaustively, so
a new variant is a type error until handled. Distinct from **`RunResult`**, the JSON wire DTO it
projects onto, and from **status**, the one string field on that DTO. The wire status tokens are a
frozen public contract (`schema_version` `"1.0"`, parsed by `jq` in `action.yml`); the `Outcome`
variant names are not.

**Prerelease**:
Two incompatible spellings live in this repo and only one is recognized as a bump baseline.
**SemVer-form** (`1.0.0-rc.1`) parses, sorts by SemVer precedence, and finalizes on the next bump.
**PEP 440** (`0.9.0rc1`) does not parse as SemVer and is skipped from selection entirely — yet that
is the form semvertag publishes *itself* under, and what `release.yml` means by "pre-release". Say
which form you mean.

**Release tag** / **floating major tag**:
A release tag is **bare semver, no `v`** (`0.4.0`): what the tool emits, what `just publish` feeds to
`uv version $GITHUB_REF_NAME`, and what `release.yml` triggers on. The floating major tag is
**`v`-prefixed** (`v0`): a single moving ref `release.yml` force-updates so action consumers can pin
`uses: modern-python/semvertag@v0`. Two conventions, one repo; a `v` on a release tag breaks
`just publish`.

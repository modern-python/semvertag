# CLI

The CLI is the one process everything funnels through: a human at a shell, the
GitHub Action, and the GitLab CI component all invoke the same `semvertag tag`
command. It parses flags + environment into validated `Settings`, wires a
provider and a strategy through a modern-di container, and runs the use-case.

## Entry point

`semvertag/__main__.py` builds `MAIN_APP`, a `typer.Typer` app
(`no_args_is_help=True`), with one real command, `tag`, plus a root callback
that gathers global options and an eager `--version`. modern-di is attached via
`modern_di_typer.setup_di(MAIN_APP, ioc.container)`, and `main()` enters the
container as a context manager before running the app.

`tag` (`_tag_command`) takes `--quiet`, `--json`, and `--dry-run`. It builds the
output (`build_json_output` or `build_rich_output`), resolves the use-case from
DI, and calls it. `--dry-run` is threaded straight into the use-case
(`use_case(output=output, dry_run=dry_run)`): the use-case still fetches the
commit, reads the tag history, and computes the new version, but when
`dry_run` is true it short-circuits *before* `provider.create_tag` — emitting a
`dry_run` status with the planned tag instead of pushing it. Errors are caught
at this boundary: any `SemvertagError` (or `ImportError`) is printed via the
output and re-raised as `typer.Exit(code=err.exit_code)`, mapping the domain
error hierarchy to process exit codes; `BrokenPipeError` exits 0.

## IoC wiring

`semvertag/ioc.py` defines a modern-di `Container` over four `Group`s:

- `SettingsGroup` — a `ContextProvider` for `Settings`; the callback sets the
  validated instance into the container context (`set_context(Settings,
  settings)`) so everything downstream resolves from one settings object.
- `ProvidersGroup` — `gitlab_client` / `github_client` factories (with
  `_close_client` finalizers) and `current_provider`, which dispatches on
  `settings.provider`.
- `StrategiesGroup` — the two strategy factories plus `current_strategy`,
  dispatching on `settings.strategy`.
- `UseCasesGroup` — `semvertag_use_case`, built from `current_provider` +
  `current_strategy`.

The CLI resolves the use-case through `_resolve_use_case`, a
`@modern_di_typer.inject`'d function with a `FromDI(SemvertagUseCase)` parameter.
Because modern-di's `Factory` eagerly resolves all kwargs, both HTTP clients are
constructed even though only one provider runs; this is safe (lazy httpx2 pools).
`Settings._resolve_provider` builds a discriminated `provider_target` — either
`GitHubTarget(repo=…)` or `GitLabTarget(project_id=…)` — with a non-optional id
field, so the invariant is enforced once, in the validator. `_build_current_provider`
matches `settings.provider_target` exhaustively (closed sum; `case _:
typing.assert_never(…)`) and carries no `assert` guards on `repo` /
`project_id`; `ty` is satisfied by the match binding.

## Settings

`semvertag/_settings.py` defines `Settings` (and nested `GitLabConfig` /
`GitHubConfig`) as `pydantic-settings` models. Sources are the environment
(prefix `SEMVERTAG_`, nested delimiter `__`) and CLI overrides; `AliasChoices`
lets one field accept several env names — e.g. the GitLab token reads
`SEMVERTAG_GITLAB__TOKEN`, `SEMVERTAG_TOKEN`, `CI_JOB_TOKEN`, or `GITLAB_TOKEN`;
`provider` accepts `SEMVERTAG_PROVIDER` or `PROVIDER`; `project_id` accepts
`CI_PROJECT_ID`; `repo` accepts `GITHUB_REPOSITORY`. A `model_validator`
auto-detects the provider from CI env (`GITHUB_ACTIONS` / `GITLAB_CI`) when
unset and enforces that github needs `repo` and gitlab needs `project_id`. A
field validator clamps `request_timeout` to a 10-second ceiling.

The entire env + CLI pipeline is owned by the public function
`load_settings(cli_overrides, *, token=None) -> Settings`. It is the single
entry point that `_main_callback` calls after collecting flags via
`_collect_overrides`. Internally it splits `cli_overrides` once into top-level
(no `.`) and nested (dotted) maps, constructs `Settings(**top_level)` so
pydantic reads the environment and top-level overrides together, then applies
the nested map through the internal helper `_apply_cli_overlay`. The helper is
built on `model_copy(update=...)`: it copies nested sub-model objects for dotted
keys (`gitlab.endpoint`) and the top-level fields, then re-validates the whole
model so field and model validators fire again on the merged result. If `--token`
is supplied, a final overlay routes it to `{settings.provider}.token` — applied
after the provider is resolved, so it lands on whichever forge is active
regardless of whether the provider was explicit or auto-detected. Precedence is
therefore **CLI over env over default** — env (and defaults) build the base
instance, then non-`None` CLI overrides overwrite it. All failure modes
(`pydantic.ValidationError` from construction or the overlay's re-validate, and
`ValueError` from the nesting-depth-2 guard) are translated inside
`load_settings` and raised only as `ConfigError`; pydantic is an
implementation detail invisible above the `_settings.py` module boundary.

## Use-case

`semvertag/_use_case.py` defines `SemvertagUseCase`, a frozen dataclass holding
a `provider` and a `strategy`; calling it (`__call__(*, output, dry_run=False)
-> Outcome`) is the whole orchestration:

1. fetch the latest commit on the default branch;
2. list tags and pick the highest semver-parseable one (`_pick_latest_semver_tag`
   sorts by `semver.Version`; unparseable names are skipped);
3. early no-bump exits — `NoTags` when there is no prior semver tag (it does
   **not** seed an initial tag in v1.0), `AlreadyTagged` when the head commit
   already carries the latest tag;
4. ask the strategy for a `Bump`; `Bump.NONE` exits with `NoBump`, carrying the
   strategy's own status/reason;
5. compute the new version (`_compute_new_version` via `semver`'s
   `bump_major/minor/patch`);
6. if `dry_run`, return `DryRun`; else `provider.create_tag` and return
   `Created`.

Every exit returns one of the closed `Outcome` variants and funnels through
`_emit`, which hands it to `output.emit(outcome, strategy=self.strategy.name)`
and returns it.

## Outcome

`semvertag/_outcome.py` defines the closed sum `Outcome = Created | DryRun |
NoTags | AlreadyTagged | NoBump` — five frozen/slotted/kw-only variants, each
carrying only its meaningful fields. `NoBump` holds the strategy-supplied
`status` + `reason` as data, so the sum stays closed and decoupled from the open
set of strategies. The free function `to_run_result(outcome, *, strategy) ->
RunResult` projects a variant onto the JSON wire DTO via one exhaustive `match`
(final `case _: assert_never`) — the single place the four fixed wire status
tokens and reasons live. The dependency points one way: `_outcome → _types`.
Renderers `match` over `Outcome`, not over a status string; adding a sixth
variant is a `ty` error in every match until handled.

## Output

`semvertag/_output.py` defines an `Output` protocol (`progress` /
`emit(outcome, *, strategy)` / `error`) with two implementations. `RichOutput`
is the human path: progress lines and a one-sentence result to stdout via
`rich` (a `match` over `Outcome` — the no-bump cases read as a reason sentence,
not a raw status token), errors to stderr. `JsonOutput` is the machine path:
`progress` is a no-op and `emit` runs `to_run_result` then writes a single
compact JSON envelope (`dataclasses.asdict(result)`, `schema_version` `"1.0"`)
to stdout. `--quiet` suppresses progress narrative on both while still emitting
the final result. `RichOutput` redacts all output paths; `JsonOutput` redacts
only its `error` path — `emit` writes the result envelope as unredacted JSON
(see providers.md).

## Distribution wrappers

Two thin wrappers shell out to the same published CLI:

- `action.yml` — a composite GitHub Action. It sets up `uv`, exports
  `GITHUB_TOKEN` and `SEMVERTAG_STRATEGY` from inputs, and runs
  `uvx 'semvertag>=0.5.0,<1' tag --json $dry_run_flag`, where `$dry_run_flag`
  expands to `--dry-run` when the `dry-run` input is `"true"`. It parses the
  JSON envelope with `jq` and normalizes the CLI's internal status to a stable
  `created | no-bump` enum for `tag` / `bump` / `status` outputs.
- `templates/semvertag.yml` — a GitLab CI Catalog component. It pip-installs
  `uv`, maps the `strategy` input to `SEMVERTAG_STRATEGY`, and runs
  `uvx 'semvertag>=0.1,<1' tag`.

Both shell out to the same CLI, but they are **not** symmetric on dry-run:
`action.yml` passes `--dry-run` through (gated on the `dry-run` input), whereas
`templates/semvertag.yml` exposes only a `strategy` input and runs `tag` with no
`--dry-run` flag — the GitLab component has no dry-run path today.

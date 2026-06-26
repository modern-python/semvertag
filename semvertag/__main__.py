import importlib.metadata
import typing

import modern_di_typer
import typer

from semvertag import ioc
from semvertag._errors import ConfigError, SemvertagError
from semvertag._output import Output, build_json_output, build_rich_output
from semvertag._settings import Settings, load_settings
from semvertag._use_case import SemvertagUseCase


_PACKAGE_NAME: typing.Final = "semvertag"


MAIN_APP: typing.Final = typer.Typer(
    name="semvertag",
    help=("Auto-tag GitLab and GitHub repos with semantic version tags — one tool, two strategies, two providers."),
    no_args_is_help=True,
    add_completion=True,
)

modern_di_typer.setup_di(MAIN_APP, ioc.container)


def _version_callback(value: bool) -> None:
    if not value:
        return
    try:
        version = importlib.metadata.version(_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        version = "0"
    typer.echo(version)
    raise typer.Exit


def _collect_overrides(  # noqa: PLR0913
    *,
    project_id: int | None,
    strategy: str | None,
    default_branch: str | None,
    gitlab_endpoint: str | None,
    github_endpoint: str | None,
    provider: str | None,
    repo: str | None,
    request_timeout: float | None,
) -> dict[str, typing.Any]:
    overrides: dict[str, typing.Any] = {}
    if provider is not None:
        overrides["provider"] = provider
    if project_id is not None:
        overrides["project_id"] = project_id
    if repo is not None:
        overrides["repo"] = repo
    if strategy is not None:
        overrides["strategy"] = strategy
    if default_branch is not None:
        overrides["default_branch"] = default_branch
    if gitlab_endpoint is not None:
        overrides["gitlab.endpoint"] = gitlab_endpoint
    if github_endpoint is not None:
        overrides["github.endpoint"] = github_endpoint
    if request_timeout is not None:
        overrides["request_timeout"] = request_timeout
    return overrides


@MAIN_APP.callback()
def _main_callback(  # noqa: PLR0913
    ctx: typer.Context,
    project_id: typing.Annotated[
        int | None,
        typer.Option("--project-id", help="GitLab project id (or set CI_PROJECT_ID)."),
    ] = None,
    repo: typing.Annotated[
        str | None,
        typer.Option("--repo", help="GitHub repo as OWNER/REPO (or set GITHUB_REPOSITORY)."),
    ] = None,
    provider: typing.Annotated[
        str | None,
        typer.Option("--provider", help="Provider: 'github' or 'gitlab' (default: auto-detect from CI env)."),
    ] = None,
    strategy: typing.Annotated[
        str | None,
        typer.Option("--strategy", help="Bump strategy: branch-prefix | conventional-commits."),
    ] = None,
    token: typing.Annotated[
        str | None,
        typer.Option("--token", help="API token (overrides SEMVERTAG_TOKEN); routed to the active provider."),
    ] = None,
    default_branch: typing.Annotated[
        str | None,
        typer.Option("--default-branch", help="Default branch name override."),
    ] = None,
    gitlab_endpoint: typing.Annotated[
        str | None,
        typer.Option("--gitlab-endpoint", help="GitLab API endpoint URL."),
    ] = None,
    github_endpoint: typing.Annotated[
        str | None,
        typer.Option("--github-endpoint", help="GitHub API endpoint URL (for GitHub Enterprise)."),
    ] = None,
    request_timeout: typing.Annotated[
        float | None,
        typer.Option("--request-timeout", help="Per-request timeout in seconds (clamped to 10)."),
    ] = None,
    _version: typing.Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = None,
) -> None:
    if ctx.resilient_parsing:
        return

    overrides = _collect_overrides(
        project_id=project_id,
        strategy=strategy,
        default_branch=default_branch,
        gitlab_endpoint=gitlab_endpoint,
        github_endpoint=github_endpoint,
        provider=provider,
        repo=repo,
        request_timeout=request_timeout,
    )
    try:
        settings = load_settings(overrides, token=token)
    except ConfigError as err:
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=err.exit_code) from err

    app_container = modern_di_typer.fetch_di_container(ctx)
    app_container.set_context(Settings, settings)


@modern_di_typer.inject
def _resolve_use_case(
    use_case: typing.Annotated[SemvertagUseCase, modern_di_typer.FromDI(SemvertagUseCase)],
) -> SemvertagUseCase:
    return use_case


@MAIN_APP.command("tag")
def _tag_command(
    ctx: typer.Context,
    quiet: typing.Annotated[
        bool,
        typer.Option("--quiet", help="Suppress progress narrative; final result still emits."),
    ] = False,
    json_flag: typing.Annotated[
        bool,
        typer.Option("--json", help="Emit a JSON envelope on stdout instead of human-readable output."),
    ] = False,
    dry_run: typing.Annotated[
        bool,
        typer.Option("--dry-run", help="Compute the bump and print the result, but do not push a tag."),
    ] = False,
) -> None:
    output: Output = build_json_output(quiet=quiet) if json_flag else build_rich_output(quiet=quiet)
    try:
        use_case = _resolve_use_case(ctx=ctx)
        use_case(output=output, dry_run=dry_run)
    except ImportError as exc:
        err = ConfigError(f"Required module unavailable: {exc}.")
        output.error(str(err))
        raise typer.Exit(code=err.exit_code) from exc
    except SemvertagError as err:
        output.error(str(err))
        raise typer.Exit(code=err.exit_code) from err
    except BrokenPipeError as exc:
        raise typer.Exit(code=0) from exc


def main() -> None:
    with ioc.container:
        MAIN_APP()


if __name__ == "__main__":  # pragma: no cover
    main()

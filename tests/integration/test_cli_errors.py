import collections.abc
import importlib.metadata
import sys
import typing
import unittest.mock

import pytest
from typer.testing import CliRunner

from semvertag import __main__ as cli_main
from semvertag import ioc
from semvertag.__main__ import MAIN_APP, _main_callback
from semvertag._errors import ProviderAPIError
from semvertag._output import Output
from tests.conftest import HandlerCallable
from tests.integration.conftest import merge_commit_handler


_EXIT_CONFIG_ERROR: typing.Final = 2
_EXIT_PROVIDER_API_ERROR: typing.Final = 4


class _RaisingUseCase:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def __call__(self, *, output: Output, dry_run: bool = False) -> typing.NoReturn:  # noqa: ARG002
        raise self._exc


@pytest.fixture
def install_raising_use_case() -> typing.Iterator[collections.abc.Callable[[BaseException], None]]:
    def install(exc: BaseException) -> None:
        ioc.container.override(ioc.UseCasesGroup.semvertag_use_case, _RaisingUseCase(exc))

    with ioc.container:
        yield install
        ioc.container.reset_override(ioc.UseCasesGroup.semvertag_use_case)


def test_version_flag_prints_installed_package_version(cli_runner: CliRunner) -> None:
    result: typing.Final = cli_runner.invoke(MAIN_APP, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip()


def test_version_flag_falls_back_to_zero_when_package_metadata_missing(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_not_found(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr("semvertag.__main__.importlib.metadata.version", raise_not_found)
    result: typing.Final = cli_runner.invoke(MAIN_APP, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "0"


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--project-id", "999"),
        ("--strategy", "branch-prefix"),
        ("--token", "glpat-override"),
        ("--default-branch", "main"),
        ("--gitlab-endpoint", "https://gitlab.example.test"),
        ("--github-endpoint", "https://api.github.example.test"),
        ("--request-timeout", "5.0"),
    ],
)
def test_each_cli_override_flag_drives_tag_command_to_success(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
    flag: str,
    value: str,
) -> None:
    install_mock_transport(merge_commit_handler())
    result: typing.Final = cli_runner.invoke(MAIN_APP, [flag, value, "tag"])
    assert result.exit_code == 0, result.output + (result.stderr or "")


def test_invalid_env_var_triggers_pydantic_validation_error_path(
    cli_env: None,  # noqa: ARG001
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMVERTAG_REQUEST_TIMEOUT", "-1")
    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])
    assert result.exit_code == _EXIT_CONFIG_ERROR, result.output
    assert "Configuration error at 'request_timeout'" in result.stderr


def test_overlay_value_error_is_rewrapped_as_config_error(
    cli_env: None,  # noqa: ARG001
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_value_error(*_args: object, **_kwargs: object) -> typing.NoReturn:
        msg = "forced overlay failure"
        raise ValueError(msg)

    monkeypatch.setattr("semvertag._settings._apply_cli_overlay", raise_value_error)
    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])
    assert result.exit_code == _EXIT_CONFIG_ERROR, result.output
    assert "forced overlay failure" in result.stderr


def test_import_error_from_use_case_exits_with_config_error_code(
    cli_env: None,  # noqa: ARG001
    install_raising_use_case: collections.abc.Callable[[BaseException], None],
    cli_runner: CliRunner,
) -> None:
    install_raising_use_case(ImportError("optional dep missing"))
    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])
    assert result.exit_code == _EXIT_CONFIG_ERROR, result.output
    assert "Required module unavailable" in result.stderr


def test_broken_pipe_error_from_use_case_exits_clean(
    cli_env: None,  # noqa: ARG001
    install_raising_use_case: collections.abc.Callable[[BaseException], None],
    cli_runner: CliRunner,
) -> None:
    install_raising_use_case(BrokenPipeError("broken"))
    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])
    assert result.exit_code == 0, result.output


def test_semvertag_error_from_use_case_exits_with_its_exit_code(
    cli_env: None,  # noqa: ARG001
    install_raising_use_case: collections.abc.Callable[[BaseException], None],
    cli_runner: CliRunner,
) -> None:
    install_raising_use_case(ProviderAPIError("upstream blew up"))
    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])
    assert result.exit_code == _EXIT_PROVIDER_API_ERROR, result.output
    assert "upstream blew up" in (result.stderr or "") + result.output


def test_main_callback_returns_early_when_resilient_parsing_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_constructed() -> typing.NoReturn:
        pytest.fail("Settings must not be constructed during resilient_parsing")

    monkeypatch.setattr("semvertag.__main__.Settings", fail_if_constructed)
    ctx = unittest.mock.MagicMock()
    ctx.resilient_parsing = True
    _main_callback(
        ctx,
        project_id=None,
        strategy=None,
        token=None,
        default_branch=None,
        gitlab_endpoint=None,
        request_timeout=None,
        _version=None,
    )


def test_main_entry_point_runs_typer_app_inside_ioc_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["semvertag", "--version"])
    with pytest.raises(SystemExit) as exc_info:
        cli_main.main()
    assert exc_info.value.code == 0

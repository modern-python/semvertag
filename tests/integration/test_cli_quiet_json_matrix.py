import collections.abc
import json as json_module
import time
import typing

import httpx2
import pytest
from typer.testing import CliRunner

from semvertag.__main__ import MAIN_APP
from semvertag._errors import SemvertagError
from semvertag._output import Output
from semvertag._use_case import SemvertagUseCase
from tests.conftest import HandlerCallable
from tests.integration.conftest import (
    GITLAB_PROJECT_ID,
    merge_commit_handler,
)


_EXPECTED_NEW_TAG: typing.Final = "1.5.0"
_PROGRESS_MARKERS: typing.Final[tuple[str, ...]] = (
    "Detected strategy",
    "Fetching",
    "Computing bump",
    "Creating tag",
)
_PROJECT_PATH: typing.Final = f"/api/v4/projects/{GITLAB_PROJECT_ID}"
_NOT_FOUND_STATUS: typing.Final = 404
_UNAUTHORIZED_STATUS: typing.Final = 401
_SERVICE_UNAVAILABLE_STATUS: typing.Final = 503

_EXIT_GENERIC_FAILURE: typing.Final = 1
_EXIT_CONFIG_ERROR: typing.Final = 2
_EXIT_AUTH_ERROR: typing.Final = 3
_EXIT_PROVIDER_API_ERROR: typing.Final = 4


def test_emits_progress_and_human_result_when_no_flags(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    install_mock_transport(merge_commit_handler())

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == 0
    for marker in _PROGRESS_MARKERS:
        assert marker in result.stdout, f"missing progress marker {marker!r}"
    assert f"Created tag {_EXPECTED_NEW_TAG}" in result.stdout
    assert result.stderr == ""


def test_emits_only_human_result_when_quiet(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    install_mock_transport(merge_commit_handler())

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag", "--quiet"])

    assert result.exit_code == 0
    for marker in _PROGRESS_MARKERS[:-1]:
        assert marker not in result.stdout, f"unexpected progress marker {marker!r} under --quiet"
    assert f"Created tag {_EXPECTED_NEW_TAG}" in result.stdout
    assert result.stderr == ""


def test_emits_only_json_envelope_when_json_only(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    install_mock_transport(merge_commit_handler())

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag", "--json"])

    assert result.exit_code == 0
    lines: typing.Final = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    payload: typing.Final = json_module.loads(lines[0])
    assert payload["status"] == "created"
    for marker in _PROGRESS_MARKERS:
        assert marker not in result.stdout, f"unexpected progress marker {marker!r} under --json"
    assert result.stderr == ""


def test_emits_only_json_envelope_when_quiet_and_json(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    install_mock_transport(merge_commit_handler())

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag", "--quiet", "--json"])

    assert result.exit_code == 0
    lines: typing.Final = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    payload: typing.Final = json_module.loads(lines[0])
    assert next(iter(payload.keys())) == "schema_version"
    assert payload["status"] == "created"
    assert result.stderr == ""


def test_exits_with_one_on_generic_semvertag_error(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_mock_transport(merge_commit_handler())

    def raising_call(self: SemvertagUseCase, *, output: Output, dry_run: bool = False) -> typing.Any:  # noqa: ANN401, ARG001
        msg = "synthetic generic failure for AC9."
        raise SemvertagError(msg)

    monkeypatch.setattr(SemvertagUseCase, "__call__", raising_call)

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == _EXIT_GENERIC_FAILURE
    assert "synthetic generic failure" in result.stderr


def test_exits_with_two_on_config_error_via_404(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET" and request.url.path == _PROJECT_PATH:
            return httpx2.Response(_NOT_FOUND_STATUS, json={"message": "404 Not Found"})
        return httpx2.Response(404, json={"message": "404 Not Found"})

    install_mock_transport(handler)

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == _EXIT_CONFIG_ERROR
    assert "GitLab project not found" in result.stderr
    assert "Verify CI_PROJECT_ID or --project-id" in result.stderr


def test_exits_with_three_on_auth_error_via_401(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET" and request.url.path == _PROJECT_PATH:
            return httpx2.Response(_UNAUTHORIZED_STATUS, json={"message": "401 Unauthorized"})
        return httpx2.Response(404, json={"message": "404 Not Found"})

    install_mock_transport(handler)

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == _EXIT_AUTH_ERROR
    assert "Token rejected: 401" in result.stderr


def test_exits_with_four_on_provider_api_error_via_503_after_retry_exhaustion(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(_SERVICE_UNAVAILABLE_STATUS, json={"message": "service down"})

    install_mock_transport(handler)

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == _EXIT_PROVIDER_API_ERROR
    assert "GitLab API failure: 503" in result.stderr


def test_exits_with_two_when_project_id_missing(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],  # noqa: ARG001
) -> None:
    monkeypatch.setenv("SEMVERTAG_TOKEN", "glpat-XXXXXXXXXXXXXXXXXXXX")

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == _EXIT_CONFIG_ERROR
    assert "project_id" in result.stderr

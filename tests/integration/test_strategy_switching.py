import collections.abc
import json as json_module
import typing

import pytest
from typer.testing import CliRunner

from semvertag.__main__ import MAIN_APP
from tests.conftest import HandlerCallable
from tests.integration.conftest import merge_commit_handler


def test_creates_minor_tag_when_strategy_is_conventional_commits_and_latest_commit_is_feat(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMVERTAG_STRATEGY", "conventional-commits")
    install_mock_transport(merge_commit_handler(commit_message="feat: add foo"))

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == 0
    assert "Created tag 1.5.0" in result.stdout


def test_creates_major_tag_when_strategy_is_conventional_commits_and_latest_commit_is_breaking(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMVERTAG_STRATEGY", "conventional-commits")
    install_mock_transport(merge_commit_handler(commit_message="feat!: drop python 3.9"))

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == 0
    assert "Created tag 2.0.0" in result.stdout


def test_creates_patch_tag_when_strategy_is_conventional_commits_and_latest_commit_is_fix(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMVERTAG_STRATEGY", "conventional-commits")
    install_mock_transport(merge_commit_handler(commit_message="fix: correct off-by-one"))

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == 0
    assert "Created tag 1.4.3" in result.stdout


def test_skips_with_no_conforming_commit_when_strategy_is_cc_and_message_has_no_type(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMVERTAG_STRATEGY", "conventional-commits")
    install_mock_transport(merge_commit_handler(commit_message="Fixed thing"))

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == 0
    assert "No tag created" in result.stdout
    assert "No conforming Conventional Commits type" in result.stdout


def test_marina_journey_same_fixture_different_strategies_produces_different_bumps(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_mock_transport(merge_commit_handler(commit_message="feat!: drop python 3.9"))

    monkeypatch.setenv("SEMVERTAG_STRATEGY", "branch-prefix")
    bp_result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])
    assert bp_result.exit_code == 0
    assert "not a merge commit" in bp_result.stdout

    monkeypatch.setenv("SEMVERTAG_STRATEGY", "conventional-commits")
    cc_result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])
    assert cc_result.exit_code == 0
    assert "Created tag 2.0.0" in cc_result.stdout


def test_json_envelope_carries_strategy_field_set_to_conventional_commits(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMVERTAG_STRATEGY", "conventional-commits")
    install_mock_transport(merge_commit_handler(commit_message="feat: add foo"))

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag", "--json"])

    assert result.exit_code == 0
    lines: typing.Final = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    payload: typing.Final = json_module.loads(lines[0])
    assert payload["strategy"] == "conventional-commits"
    assert payload["bump"] == "minor"
    assert payload["status"] == "created"
    assert payload["tag"] == "1.5.0"

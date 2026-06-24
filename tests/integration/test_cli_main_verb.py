import collections.abc
import json as json_module
import typing

import httpx2
import pytest
from typer.testing import CliRunner

from semvertag import ioc
from semvertag.__main__ import MAIN_APP
from tests.conftest import HandlerCallable
from tests.integration.conftest import (
    DEFAULT_COMMIT_SHA,
    DEFAULT_TAG_NAME,
    GITLAB_PROJECT_ID,
    merge_commit_handler,
)


_EXPECTED_NEW_TAG: typing.Final = "1.5.0"
_PROJECT_PATH: typing.Final = f"/api/v4/projects/{GITLAB_PROJECT_ID}"
_TAGS_POST_PATH: typing.Final = f"{_PROJECT_PATH}/repository/tags"


def _make_recording_handler(
    base: HandlerCallable,
    recorded: list[httpx2.Request],
) -> HandlerCallable:
    def wrapper(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        return base(request)

    return wrapper


def test_creates_tag_when_latest_commit_is_feature_merge_and_prior_tag_exists(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    recorded: list[httpx2.Request] = []
    install_mock_transport(_make_recording_handler(merge_commit_handler(), recorded))

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == 0, result.output + result.stderr
    assert f"Created tag {_EXPECTED_NEW_TAG}" in result.stdout
    posted: typing.Final = [r for r in recorded if r.method == "POST" and r.url.path == _TAGS_POST_PATH]
    assert len(posted) == 1
    body: typing.Final = json_module.loads(posted[0].content.decode())
    assert body == {"tag_name": _EXPECTED_NEW_TAG, "ref": DEFAULT_COMMIT_SHA}


def test_skips_with_already_tagged_when_latest_commit_sha_matches_latest_tag(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    install_mock_transport(
        merge_commit_handler(
            tags=[{"name": DEFAULT_TAG_NAME, "commit": {"id": DEFAULT_COMMIT_SHA}}],
        ),
    )

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == 0, result.output + result.stderr
    assert "already tagged" in result.stdout


def test_skips_with_no_merge_commit_when_latest_commit_is_not_a_merge(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    install_mock_transport(merge_commit_handler(commit_message="Fix typo in README"))

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == 0, result.output + result.stderr
    assert "not a merge commit" in result.stdout


def test_skips_with_no_tags_when_repo_has_zero_semver_conforming_tags(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    install_mock_transport(merge_commit_handler(tags=[]))

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag"])

    assert result.exit_code == 0, result.output + result.stderr
    assert "no prior semver-conforming tag" in result.stdout


def test_emits_json_envelope_with_schema_version_first_when_json_flag_set(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    install_mock_transport(merge_commit_handler())

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag", "--json"])

    assert result.exit_code == 0, result.output + result.stderr
    lines: typing.Final = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly one JSON line, got: {lines!r}"
    payload: typing.Final = json_module.loads(lines[0])
    assert next(iter(payload.keys())) == "schema_version"
    assert payload["schema_version"] == "1.0"
    for key in ("strategy", "bump", "status", "tag", "commit", "reason"):
        assert key in payload
    assert payload["tag"] == _EXPECTED_NEW_TAG
    assert payload["status"] == "created"


def test_main_callback_accepts_github_provider_with_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    monkeypatch.setenv("SEMVERTAG_GITHUB__TOKEN", "ghp_xxx")
    runner = CliRunner()
    with ioc.container:
        result = runner.invoke(
            MAIN_APP,
            ["--provider", "github", "--repo", "owner/repo", "tag", "--quiet"],
        )
    # The callback should succeed (settings.provider resolves to "github" without error).
    # `tag` will fail because no real network; check exit code is NOT ConfigError (2).
    # AuthError (3) or ProviderAPIError (4) both prove the provider was reached.
    assert result.exit_code in (0, 3, 4)


def test_main_callback_auto_detects_github_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITLAB_CI", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_xxx")
    runner = CliRunner()
    with ioc.container:
        result = runner.invoke(MAIN_APP, ["tag", "--quiet"])
    assert result.exit_code in (0, 3, 4)


def test_dry_run_skips_post_to_tags_endpoint_and_emits_dry_run_status(
    cli_env: None,  # noqa: ARG001
    install_mock_transport: collections.abc.Callable[[HandlerCallable], None],
    cli_runner: CliRunner,
) -> None:
    recorded: list[httpx2.Request] = []
    install_mock_transport(_make_recording_handler(merge_commit_handler(), recorded))

    result: typing.Final = cli_runner.invoke(MAIN_APP, ["tag", "--dry-run", "--json"])

    assert result.exit_code == 0, result.output + result.stderr
    lines: typing.Final = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected one JSON line, got: {lines!r}"
    payload: typing.Final = json_module.loads(lines[0])
    assert payload["status"] == "dry_run"
    assert payload["tag"] == _EXPECTED_NEW_TAG
    assert payload["bump"] == "minor"
    posted: typing.Final = [r for r in recorded if r.method == "POST" and r.url.path == _TAGS_POST_PATH]
    assert posted == [], f"dry-run must not POST to tags endpoint; got: {posted}"

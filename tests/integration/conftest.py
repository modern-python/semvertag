import collections.abc
import typing

import httpware
import httpx2
import pytest
from typer.testing import CliRunner

from semvertag import ioc
from tests.conftest import HandlerCallable


GITLAB_PROJECT_ID: typing.Final = 999
GITLAB_ENDPOINT: typing.Final = "https://gitlab.example.test"
GITLAB_TOKEN: typing.Final = "glpat-XXXXXXXXXXXXXXXXXXXX"
DEFAULT_COMMIT_SHA: typing.Final = "a2b4d12"
DEFAULT_TAG_NAME: typing.Final = "1.4.2"


_RUNNER: typing.Final = CliRunner()


@pytest.fixture
def cli_runner() -> CliRunner:
    return _RUNNER


_CLEAN_ENV_KEYS: typing.Final = (
    "SEMVERTAG_TOKEN",
    "SEMVERTAG_PROJECT_ID",
    "SEMVERTAG_GITLAB__ENDPOINT",
    "SEMVERTAG_GITLAB__TOKEN",
    "SEMVERTAG_STRATEGY",
    "SEMVERTAG_QUIET",
    "CI_JOB_TOKEN",
    "CI_PROJECT_ID",
    "GITLAB_TOKEN",
)


@pytest.fixture(autouse=True)
def _clean_env_before_each(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _CLEAN_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMVERTAG_TOKEN", GITLAB_TOKEN)
    monkeypatch.setenv("SEMVERTAG_PROJECT_ID", str(GITLAB_PROJECT_ID))
    monkeypatch.setenv("SEMVERTAG_GITLAB__ENDPOINT", GITLAB_ENDPOINT)


@pytest.fixture
def install_mock_transport() -> typing.Iterator[collections.abc.Callable[[HandlerCallable], None]]:
    def install(handler: HandlerCallable) -> None:
        mock_transport: typing.Final = httpx2.MockTransport(handler)
        mock_client: typing.Final = httpware.Client(transport=mock_transport, base_url=GITLAB_ENDPOINT)
        ioc.container.override(ioc.ProvidersGroup.gitlab_client, mock_client)

    with ioc.container:
        yield install
        ioc.container.reset_override(ioc.ProvidersGroup.gitlab_client)


_PROJECT_PATH: typing.Final = f"/api/v4/projects/{GITLAB_PROJECT_ID}"


def merge_commit_handler(
    *,
    commit_sha: str = DEFAULT_COMMIT_SHA,
    commit_message: str = "Merge branch 'feature/foo' into main",
    tags: list[dict[str, typing.Any]] | None = None,
) -> HandlerCallable:
    resolved_tags: typing.Final = (
        tags if tags is not None else [{"name": DEFAULT_TAG_NAME, "commit": {"id": "00000000"}}]
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        method: typing.Final = request.method
        path: typing.Final = request.url.path
        if method == "GET" and path == _PROJECT_PATH:
            return httpx2.Response(200, json={"default_branch": "main"})
        if method == "GET" and path == f"{_PROJECT_PATH}/repository/commits":
            return httpx2.Response(200, json=[{"id": commit_sha, "message": commit_message}])
        if method == "GET" and path == f"{_PROJECT_PATH}/repository/tags":
            return httpx2.Response(200, json=resolved_tags)
        if method == "POST" and path == f"{_PROJECT_PATH}/repository/tags":
            return httpx2.Response(201, json={"name": "created"})
        return httpx2.Response(404, json={"message": "404 Not Found"})

    return handler

import collections.abc
import typing

import httpware
import httpx2
import pydantic
import pytest

from semvertag._settings import GitLabConfig
from semvertag.providers.gitlab import GitLabProvider


GITLAB_PROJECT_ID: typing.Final = 999
GITLAB_ENDPOINT: typing.Final = "https://gitlab.example.test"
GITLAB_TOKEN: typing.Final = "glpat-XXXXXXXXXXXXXXXXXXXX"

GITHUB_ENDPOINT: typing.Final = "https://api.github.test"
GITHUB_TOKEN: typing.Final = "ghp_XXXXXXXXXXXXXXXXXXXX"
GITHUB_REPO: typing.Final = "owner/repo"
_REQUEST_TIMEOUT: typing.Final = 8.0
_TOKEN_HEADER: typing.Final = "PRIVATE-TOKEN"


HandlerCallable: typing.TypeAlias = collections.abc.Callable[[httpx2.Request], httpx2.Response]


_HOST_CI_ENV_VARS: typing.Final = (
    # Provider auto-detection markers
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "SEMVERTAG_PROVIDER",
    "PROVIDER",
    # Repo / project identifiers (aliased into Settings.repo / Settings.project_id)
    "GITHUB_REPOSITORY",
    "SEMVERTAG_REPO",
    "CI_PROJECT_ID",
    "SEMVERTAG_PROJECT_ID",
    # Token aliases (aliased into Settings.github.token / Settings.gitlab.token)
    "GITHUB_TOKEN",
    "GITLAB_TOKEN",
    "CI_JOB_TOKEN",
    "SEMVERTAG_TOKEN",
    "SEMVERTAG_GITHUB__TOKEN",
    "SEMVERTAG_GITLAB__TOKEN",
    # Endpoint overrides
    "SEMVERTAG_GITHUB__ENDPOINT",
    "SEMVERTAG_GITLAB__ENDPOINT",
)


@pytest.fixture(autouse=True)
def _isolate_ci_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every env var that Settings reads, so tests aren't accidentally driven by the host runner.

    Without this, GitHub Actions runners (which auto-export GITHUB_ACTIONS=true,
    GITHUB_REPOSITORY, GITHUB_TOKEN) and GitLab CI runners (GITLAB_CI=true,
    CI_PROJECT_ID, CI_JOB_TOKEN) make Settings pick fields the test never asked for —
    causing assertions like "Settings(provider='github') should raise because repo is missing"
    to silently fail because GITHUB_REPOSITORY was set by the runner.

    Tests that exercise env-driven behavior set the specific vars they need via their own
    monkeypatch.setenv calls. This fixture only clears the default state.
    """
    for var in _HOST_CI_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def default_handler(request: httpx2.Request) -> httpx2.Response:
    method: typing.Final = request.method
    path: typing.Final = request.url.path
    project_path: typing.Final = f"/api/v4/projects/{GITLAB_PROJECT_ID}"

    if method == "GET" and path == project_path:
        return httpx2.Response(200, json={"default_branch": "main"})
    if method == "GET" and path == f"{project_path}/repository/commits":
        return httpx2.Response(
            200,
            json=[{"id": "a2b4d12", "message": "default test commit"}],
        )
    if method == "GET" and path == f"{project_path}/repository/tags":
        return httpx2.Response(200, json=[])
    if method == "POST" and path == f"{project_path}/repository/tags":
        return httpx2.Response(201, json={"name": "default-tag"})
    return httpx2.Response(404, json={"message": "404 Not Found"})


def compose_handler(
    base: HandlerCallable,
    overrides: dict[tuple[str, str], httpx2.Response],
) -> HandlerCallable:
    def composed(request: httpx2.Request) -> httpx2.Response:
        request_method: typing.Final = request.method.upper()
        request_path: typing.Final = request.url.path
        for (method, path_prefix), response in overrides.items():
            if request_method == method.upper() and request_path.startswith(path_prefix):
                return response
        return base(request)

    return composed


@pytest.fixture
def gitlab_transport() -> httpx2.MockTransport:
    return httpx2.MockTransport(default_handler)


@pytest.fixture
def gitlab_client(gitlab_transport: httpx2.MockTransport) -> collections.abc.Iterator[httpx2.Client]:
    config: typing.Final = GitLabConfig(endpoint=GITLAB_ENDPOINT, token=pydantic.SecretStr(GITLAB_TOKEN))
    with httpx2.Client(
        transport=gitlab_transport,
        base_url=GITLAB_ENDPOINT,
        timeout=_REQUEST_TIMEOUT,
        headers={_TOKEN_HEADER: config.token.get_secret_value()},
    ) as client:
        yield client


@pytest.fixture
def gitlab_http(gitlab_client: httpx2.Client) -> httpware.Client:
    return httpware.Client(httpx2_client=gitlab_client)


@pytest.fixture
def gitlab_provider(gitlab_http: httpware.Client) -> GitLabProvider:
    config: typing.Final = GitLabConfig(endpoint=GITLAB_ENDPOINT, token=pydantic.SecretStr(GITLAB_TOKEN))
    return GitLabProvider(config=config, project_id=GITLAB_PROJECT_ID, http=gitlab_http)

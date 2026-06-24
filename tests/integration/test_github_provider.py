import typing

import httpware
import httpx2
import pydantic
import pytest

from semvertag._errors import AuthError, ConfigError, ProviderAPIError
from semvertag._settings import GitHubConfig
from semvertag._types import Commit, Tag
from semvertag.providers._base import Provider
from semvertag.providers.github import GitHubProvider
from tests.conftest import (
    GITHUB_ENDPOINT,
    GITHUB_REPO,
    GITHUB_TOKEN,
    HandlerCallable,
    compose_handler,
)


_REPO_PATH: typing.Final = f"/repos/{GITHUB_REPO}"
_COMMITS_PATH: typing.Final = f"{_REPO_PATH}/commits"
_TAGS_PATH: typing.Final = f"{_REPO_PATH}/tags"
_REFS_PATH: typing.Final = f"{_REPO_PATH}/git/refs"
_DEFAULT_BRANCH: typing.Final = "main"
_DEFAULT_COMMIT_SHA: typing.Final = "abc1234"
_DEFAULT_COMMIT_MESSAGE: typing.Final = "default test commit"
_UNAUTHORIZED_STATUS: typing.Final = 401
_FORBIDDEN_STATUS: typing.Final = 403
_NOT_FOUND_STATUS: typing.Final = 404
_UNPROCESSABLE_STATUS: typing.Final = 422
_TOO_MANY_REQUESTS_STATUS: typing.Final = 429
_SERVICE_UNAVAILABLE_STATUS: typing.Final = 503
_EXPECTED_PAGE_CALLS: typing.Final = 2
_PAGINATION_CAP: typing.Final = 100


def _github_default_handler(request: httpx2.Request) -> httpx2.Response:
    method = request.method
    path = request.url.path
    if method == "GET" and path == _REPO_PATH:
        return httpx2.Response(200, json={"default_branch": _DEFAULT_BRANCH})
    if method == "GET" and path == _COMMITS_PATH:
        return httpx2.Response(200, json=[{"sha": _DEFAULT_COMMIT_SHA, "commit": {"message": _DEFAULT_COMMIT_MESSAGE}}])
    if method == "GET" and path == _TAGS_PATH:
        return httpx2.Response(
            200,
            json=[
                {"name": "v0.1.0", "commit": {"sha": "old1234"}},
                {"name": "v0.2.0", "commit": {"sha": "new1234"}},
            ],
        )
    if method == "POST" and path == _REFS_PATH:
        return httpx2.Response(201, json={"ref": "refs/tags/v1.0.0", "object": {"sha": _DEFAULT_COMMIT_SHA}})
    return httpx2.Response(404, json={"message": "Not Found"})


def _make_provider(
    handler: HandlerCallable,
    *,
    default_branch: str | None = None,
) -> tuple[GitHubProvider, httpx2.Client]:
    transport = httpx2.MockTransport(handler)
    config = GitHubConfig(endpoint=GITHUB_ENDPOINT, token=pydantic.SecretStr(GITHUB_TOKEN))
    inner = httpx2.Client(
        transport=transport,
        base_url=GITHUB_ENDPOINT,
        headers={
            "Authorization": f"Bearer {config.token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    client = httpware.Client(httpx2_client=inner)
    provider = GitHubProvider(config=config, repo=GITHUB_REPO, http=client, default_branch=default_branch)
    # Return the inner httpx2.Client so tests can use it as a context manager
    # for teardown; httpware.Client doesn't own its lifecycle when constructed via httpx2_client=.
    return provider, inner


# Protocol conformance


def test_github_provider_exposes_every_member_required_by_protocol() -> None:
    expected_members: typing.Final = (
        "name",
        "get_default_branch",
        "get_latest_commit_on_default_branch",
        "list_tags",
        "create_tag",
    )
    for member in expected_members:
        assert hasattr(GitHubProvider, member), f"GitHubProvider is missing Provider member: {member!r}"
    assert Provider.__name__ == "Provider"


# get_default_branch


def test_get_default_branch_returns_value() -> None:
    provider, client = _make_provider(_github_default_handler)
    with client:
        assert provider.get_default_branch() == _DEFAULT_BRANCH


def test_get_default_branch_returns_override_without_calling_api() -> None:
    repo_called = {"v": False}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _REPO_PATH:
            repo_called["v"] = True
        return _github_default_handler(request)

    provider, client = _make_provider(handler, default_branch="develop")
    with client:
        assert provider.get_default_branch() == "develop"
    assert repo_called["v"] is False


def test_get_latest_commit_uses_override_branch_and_skips_default_branch_call() -> None:
    repo_called = {"v": False}
    captured_params: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _REPO_PATH:
            repo_called["v"] = True
            return httpx2.Response(200, json={"default_branch": "main"})
        if request.url.path == _COMMITS_PATH:
            captured_params.update(dict(request.url.params))
            return httpx2.Response(200, json=[{"sha": "deadbeef", "commit": {"message": "msg"}}])
        return httpx2.Response(404)

    provider, client = _make_provider(handler, default_branch="develop")
    with client:
        commit = provider.get_latest_commit_on_default_branch()
    assert repo_called["v"] is False
    assert captured_params["sha"] == "develop"
    assert commit == Commit(sha="deadbeef", message="msg")


def test_get_default_branch_raises_config_error_on_404() -> None:
    overrides = {("GET", _REPO_PATH): httpx2.Response(404, json={"message": "Not Found"})}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ConfigError, match=f"repo='{GITHUB_REPO}'"):
        provider.get_default_branch()


def test_get_default_branch_raises_config_error_when_default_branch_none() -> None:
    overrides = {("GET", _REPO_PATH): httpx2.Response(200, json={"default_branch": None})}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ConfigError, match="Default branch missing"):
        provider.get_default_branch()


def test_get_default_branch_raises_config_error_when_default_branch_empty_string() -> None:
    overrides = {("GET", _REPO_PATH): httpx2.Response(200, json={"default_branch": ""})}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ConfigError, match="Default branch missing"):
        provider.get_default_branch()


def test_get_default_branch_raises_provider_api_error_on_malformed_body() -> None:
    overrides = {("GET", _REPO_PATH): httpx2.Response(200, text="not json at all")}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_RepoResponse response could not be decoded"):
        provider.get_default_branch()


def test_get_default_branch_raises_provider_api_error_on_malformed_json() -> None:
    overrides = {("GET", _REPO_PATH): httpx2.Response(200, json=[])}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_RepoResponse response could not be decoded"):
        provider.get_default_branch()


def test_get_default_branch_sends_bearer_token_header() -> None:
    captured_headers: dict[str, str] = {}
    captured_url_path: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured_headers.update(request.headers)
        captured_url_path["path"] = request.url.path
        return httpx2.Response(200, json={"default_branch": "main"})

    provider, client = _make_provider(handler)
    with client:
        provider.get_default_branch()
    assert captured_headers.get("authorization") == f"Bearer {GITHUB_TOKEN}"
    assert captured_url_path["path"] == _REPO_PATH


# get_latest_commit_on_default_branch


def test_get_latest_commit_returns_head() -> None:
    provider, client = _make_provider(_github_default_handler)
    with client:
        commit = provider.get_latest_commit_on_default_branch()
    assert commit == Commit(sha=_DEFAULT_COMMIT_SHA, message=_DEFAULT_COMMIT_MESSAGE)


def test_get_latest_commit_raises_provider_api_error_when_empty() -> None:
    overrides = {("GET", _COMMITS_PATH): httpx2.Response(200, json=[])}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="No commits on default branch"):
        provider.get_latest_commit_on_default_branch()


def test_get_latest_commit_raises_provider_api_error_when_body_not_json() -> None:
    overrides = {("GET", _COMMITS_PATH): httpx2.Response(200, text="not json")}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_CommitList response could not be decoded"):
        provider.get_latest_commit_on_default_branch()


def test_get_latest_commit_raises_provider_api_error_when_body_not_list() -> None:
    overrides = {("GET", _COMMITS_PATH): httpx2.Response(200, json={"sha": "x", "commit": {"message": "y"}})}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_CommitList response could not be decoded"):
        provider.get_latest_commit_on_default_branch()


def test_get_latest_commit_raises_provider_api_error_when_commit_object_missing_keys() -> None:
    overrides = {("GET", _COMMITS_PATH): httpx2.Response(200, json=[{"sha": "x"}])}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_CommitList response could not be decoded"):
        provider.get_latest_commit_on_default_branch()


def test_get_latest_commit_passes_sha_and_per_page_one_query() -> None:
    captured_params: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _REPO_PATH:
            return httpx2.Response(200, json={"default_branch": "main"})
        if request.url.path == _COMMITS_PATH:
            captured_params.update(dict(request.url.params))
            return httpx2.Response(200, json=[{"sha": "deadbeef", "commit": {"message": "msg"}}])
        return httpx2.Response(404)

    provider, client = _make_provider(handler)
    with client:
        provider.get_latest_commit_on_default_branch()
    assert captured_params == {"sha": "main", "per_page": "1"}


# list_tags


def test_list_tags_returns_tags() -> None:
    provider, client = _make_provider(_github_default_handler)
    with client:
        tags = provider.list_tags()
    assert tags == [
        Tag(name="v0.1.0", commit_sha="old1234"),
        Tag(name="v0.2.0", commit_sha="new1234"),
    ]


def test_list_tags_returns_empty_list_when_no_tags() -> None:
    overrides = {("GET", _TAGS_PATH): httpx2.Response(200, json=[])}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client:
        assert provider.list_tags() == []


def test_list_tags_raises_provider_api_error_when_body_not_json() -> None:
    overrides = {("GET", _TAGS_PATH): httpx2.Response(200, text="not json")}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_TagList response could not be decoded"):
        provider.list_tags()


def test_list_tags_raises_provider_api_error_when_body_not_list() -> None:
    overrides = {("GET", _TAGS_PATH): httpx2.Response(200, json={"unexpected": "shape"})}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_TagList response could not be decoded"):
        provider.list_tags()


def test_list_tags_raises_provider_api_error_when_tag_object_missing_keys() -> None:
    overrides = {("GET", _TAGS_PATH): httpx2.Response(200, json=[{"name": "v1"}])}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_TagList response could not be decoded"):
        provider.list_tags()


def test_list_tags_follows_link_header_next() -> None:
    page1_url = f"{GITHUB_ENDPOINT}{_TAGS_PATH}?per_page=100&page=2"

    def handler(request: httpx2.Request) -> httpx2.Response:
        page = request.url.params.get("page", "1")
        if request.method == "GET" and request.url.path == _TAGS_PATH and page == "1":
            return httpx2.Response(
                200,
                json=[{"name": "v0.1.0", "commit": {"sha": "old1234"}}],
                headers={"link": f'<{page1_url}>; rel="next"'},
            )
        if request.method == "GET" and request.url.path == _TAGS_PATH and page == "2":
            return httpx2.Response(200, json=[{"name": "v0.2.0", "commit": {"sha": "new1234"}}])
        return httpx2.Response(404)

    provider, client = _make_provider(handler)
    with client:
        tags = provider.list_tags()
    assert tags == [
        Tag(name="v0.1.0", commit_sha="old1234"),
        Tag(name="v0.2.0", commit_sha="new1234"),
    ]


def test_list_tags_stops_when_link_header_has_no_next_rel() -> None:
    overrides = {
        ("GET", _TAGS_PATH): httpx2.Response(
            200,
            json=[{"name": "v0.1.0", "commit": {"sha": "old1234"}}],
            headers={"Link": '<https://api.github.test/prev>; rel="prev"'},
        ),
    }
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client:
        tags = provider.list_tags()
    assert tags == [Tag(name="v0.1.0", commit_sha="old1234")]


def test_list_tags_refuses_cross_origin_next_link() -> None:
    evil_url = "https://evil.test/repos/owner/repo/tags?page=2"

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(
            200,
            json=[{"name": "v0.1.0", "commit": {"sha": "old1234"}}],
            headers={"link": f'<{evil_url}>; rel="next"'},
        )

    provider, client = _make_provider(handler)
    with client, pytest.raises(ProviderAPIError, match="different host"):
        provider.list_tags()


def test_list_tags_raises_provider_api_error_when_pagination_exceeds_cap() -> None:
    call_counter: dict[str, int] = {"count": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path != _TAGS_PATH:
            return _github_default_handler(request)
        call_counter["count"] += 1
        next_url = f"{GITHUB_ENDPOINT}{_TAGS_PATH}?page={call_counter['count'] + 1}&per_page=100"
        return httpx2.Response(
            200,
            json=[{"name": f"tag-{call_counter['count']}", "commit": {"sha": "sha"}}],
            headers={"Link": f'<{next_url}>; rel="next"'},
        )

    provider, client = _make_provider(handler)
    with client, pytest.raises(ProviderAPIError, match="Tag pagination exceeded"):
        provider.list_tags()
    assert call_counter["count"] == _PAGINATION_CAP


# create_tag


def test_create_tag_succeeds_on_201() -> None:
    provider, client = _make_provider(_github_default_handler)
    with client:
        provider.create_tag("v1.0.0", _DEFAULT_COMMIT_SHA)  # raises on failure


def test_create_tag_already_exists_structured_becomes_config_error() -> None:
    overrides = {
        ("POST", _REFS_PATH): httpx2.Response(
            422,
            json={
                "message": "Reference already exists",
                "errors": [{"resource": "Reference", "code": "already_exists"}],
            },
        )
    }
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ConfigError, match=r"Tag already exists.*v1\.0\.0"):
        provider.create_tag("v1.0.0", _DEFAULT_COMMIT_SHA)


def test_create_tag_other_422_becomes_generic_config_error() -> None:
    overrides = {("POST", _REFS_PATH): httpx2.Response(422, json={"message": "Invalid ref format"})}
    provider, client = _make_provider(compose_handler(_github_default_handler, overrides))
    with client, pytest.raises(ConfigError, match="422"):
        provider.create_tag("invalid name", _DEFAULT_COMMIT_SHA)


def test_create_tag_sends_correct_json_body() -> None:
    captured_payloads: list[bytes] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST" and request.url.path == _REFS_PATH:
            captured_payloads.append(request.content)
            return httpx2.Response(201, json={"ref": "refs/tags/v1.0.0"})
        return _github_default_handler(request)

    provider, client = _make_provider(handler)
    with client:
        provider.create_tag("v1.0.0", _DEFAULT_COMMIT_SHA)
    assert len(captured_payloads) == 1
    body = captured_payloads[0].replace(b" ", b"")
    assert b'"ref":"refs/tags/v1.0.0"' in body
    assert b'"sha":"abc1234"' in body


# Error translation matrix — parametrized across all four verbs


def _call_get_default_branch(provider: GitHubProvider) -> None:
    provider.get_default_branch()


def _call_get_latest_commit(provider: GitHubProvider) -> None:
    provider.get_latest_commit_on_default_branch()


def _call_list_tags(provider: GitHubProvider) -> None:
    provider.list_tags()


def _call_create_tag(provider: GitHubProvider) -> None:
    provider.create_tag(name="v1.0.0", commit_sha=_DEFAULT_COMMIT_SHA)


_MAIN_VERB_CALLS: typing.Final = (
    ("get_default_branch", _call_get_default_branch, ("GET", _REPO_PATH)),
    ("get_latest_commit", _call_get_latest_commit, ("GET", _COMMITS_PATH)),
    ("list_tags", _call_list_tags, ("GET", _TAGS_PATH)),
    ("create_tag", _call_create_tag, ("POST", _REFS_PATH)),
)


def _handler_that_returns_for(
    endpoint_key: tuple[str, str],
    response: httpx2.Response,
) -> HandlerCallable:
    target_method, target_path = endpoint_key

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == target_method and request.url.path.startswith(target_path):
            return response
        return _github_default_handler(request)

    return handler


def _handler_that_raises_for(
    endpoint_key: tuple[str, str],
    exc_factory: typing.Callable[[], BaseException],
) -> HandlerCallable:
    target_method, target_path = endpoint_key

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == target_method and request.url.path.startswith(target_path):
            raise exc_factory()
        return _github_default_handler(request)

    return handler


@pytest.mark.parametrize(
    ("verb_callable", "endpoint_key"),
    [(call, key) for _name, call, key in _MAIN_VERB_CALLS],
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_auth_error_on_401(
    verb_callable: typing.Callable[[GitHubProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    handler: typing.Final = _handler_that_returns_for(endpoint_key, httpx2.Response(_UNAUTHORIZED_STATUS, json={}))
    provider, client = _make_provider(handler)
    with client, pytest.raises(AuthError, match="Token rejected: 401"):
        verb_callable(provider)


@pytest.mark.parametrize(
    ("verb_callable", "endpoint_key"),
    [(call, key) for _name, call, key in _MAIN_VERB_CALLS],
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_auth_error_on_403(
    verb_callable: typing.Callable[[GitHubProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    handler: typing.Final = _handler_that_returns_for(endpoint_key, httpx2.Response(_FORBIDDEN_STATUS, json={}))
    provider, client = _make_provider(handler)
    with client, pytest.raises(AuthError, match="Token missing scope"):
        verb_callable(provider)


@pytest.mark.parametrize(
    ("verb_callable", "endpoint_key"),
    [(call, key) for _name, call, key in _MAIN_VERB_CALLS],
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_config_error_on_404(
    verb_callable: typing.Callable[[GitHubProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    handler: typing.Final = _handler_that_returns_for(endpoint_key, httpx2.Response(_NOT_FOUND_STATUS, json={}))
    provider, client = _make_provider(handler)
    with client, pytest.raises(ConfigError, match=f"repo='{GITHUB_REPO}'"):
        verb_callable(provider)


@pytest.mark.parametrize(
    ("verb_callable", "endpoint_key"),
    [(call, key) for _name, call, key in _MAIN_VERB_CALLS],
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_provider_api_error_on_429(
    verb_callable: typing.Callable[[GitHubProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    handler: typing.Final = _handler_that_returns_for(endpoint_key, httpx2.Response(_TOO_MANY_REQUESTS_STATUS, json={}))
    provider, client = _make_provider(handler)
    with client, pytest.raises(ProviderAPIError, match="GitHub rate limit: 429"):
        verb_callable(provider)


@pytest.mark.parametrize(
    ("verb_callable", "endpoint_key"),
    [(call, key) for _name, call, key in _MAIN_VERB_CALLS],
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_provider_api_error_on_5xx(
    verb_callable: typing.Callable[[GitHubProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    handler: typing.Final = _handler_that_returns_for(
        endpoint_key, httpx2.Response(_SERVICE_UNAVAILABLE_STATUS, json={})
    )
    provider, client = _make_provider(handler)
    with client, pytest.raises(ProviderAPIError, match=f"GitHub API failure: {_SERVICE_UNAVAILABLE_STATUS}"):
        verb_callable(provider)


@pytest.mark.parametrize(
    ("verb_callable", "endpoint_key"),
    [(call, key) for _name, call, key in _MAIN_VERB_CALLS],
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_provider_api_error_when_network_error(
    verb_callable: typing.Callable[[GitHubProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    handler: typing.Final = _handler_that_raises_for(
        endpoint_key,
        lambda: httpx2.ConnectError("simulated network failure"),
    )
    provider, client = _make_provider(handler)
    with client, pytest.raises(ProviderAPIError, match="GitHub unreachable") as exc_info:
        verb_callable(provider)
    assert isinstance(exc_info.value.__cause__, httpware.NetworkError)

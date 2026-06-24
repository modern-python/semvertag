import typing

import httpware
import httpx2
import pydantic
import pytest

from semvertag._errors import AuthError, ConfigError, ProviderAPIError
from semvertag._settings import GitLabConfig
from semvertag._types import Commit, Tag
from semvertag.providers._base import Provider
from semvertag.providers.gitlab import (
    GitLabProvider,
)
from tests.conftest import (
    GITLAB_ENDPOINT,
    GITLAB_PROJECT_ID,
    GITLAB_TOKEN,
    HandlerCallable,
    compose_handler,
    default_handler,
)


_PROJECT_PATH: typing.Final = f"/api/v4/projects/{GITLAB_PROJECT_ID}"
_COMMITS_PATH: typing.Final = f"{_PROJECT_PATH}/repository/commits"
_TAGS_PATH: typing.Final = f"{_PROJECT_PATH}/repository/tags"
_DEFAULT_COMMIT_SHA: typing.Final = "a2b4d12"
_DEFAULT_COMMIT_MESSAGE: typing.Final = "default test commit"
_UNAUTHORIZED_STATUS: typing.Final = 401
_FORBIDDEN_STATUS: typing.Final = 403
_NOT_FOUND_STATUS: typing.Final = 404
_UNPROCESSABLE_STATUS: typing.Final = 422
_TOO_MANY_REQUESTS_STATUS: typing.Final = 429
_SERVICE_UNAVAILABLE_STATUS: typing.Final = 503
_EXPECTED_PAGE_CALLS: typing.Final = 2
_PAGINATION_CAP: typing.Final = 100


_TOKEN_HEADER: typing.Final = "PRIVATE-TOKEN"


def _make_provider(
    handler: HandlerCallable,
    *,
    default_branch: str | None = None,
) -> tuple[GitLabProvider, httpx2.Client]:
    transport: typing.Final = httpx2.MockTransport(handler)
    config: typing.Final = GitLabConfig(endpoint=GITLAB_ENDPOINT, token=pydantic.SecretStr(GITLAB_TOKEN))
    inner_client: typing.Final = httpx2.Client(
        transport=transport,
        base_url=GITLAB_ENDPOINT,
        headers={_TOKEN_HEADER: config.token.get_secret_value()},
    )
    http: typing.Final = httpware.Client(httpx2_client=inner_client)
    provider: typing.Final = GitLabProvider(
        config=config, project_id=GITLAB_PROJECT_ID, http=http, default_branch=default_branch
    )
    # Return the inner httpx2.Client so tests can use it as a context manager
    # for teardown; httpware.Client doesn't own its lifecycle when constructed via httpx2_client=.
    return provider, inner_client


# Protocol conformance


def test_gitlab_provider_exposes_every_member_required_by_protocol() -> None:
    expected_members: typing.Final = (
        "name",
        "get_default_branch",
        "get_latest_commit_on_default_branch",
        "list_tags",
        "create_tag",
    )
    for member in expected_members:
        assert hasattr(GitLabProvider, member), f"GitLabProvider is missing Provider member: {member!r}"
    assert Provider.__name__ == "Provider"


# AC3 -- get_default_branch


def test_returns_main_when_default_branch_endpoint_responds_200(
    gitlab_provider: GitLabProvider,
) -> None:
    assert gitlab_provider.get_default_branch() == "main"


def test_get_default_branch_returns_override_without_calling_api() -> None:
    project_called: typing.Final = {"v": False}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _PROJECT_PATH:
            project_called["v"] = True
        return default_handler(request)

    provider, client = _make_provider(handler, default_branch="develop")
    with client:
        assert provider.get_default_branch() == "develop"
    assert project_called["v"] is False


def test_get_latest_commit_uses_override_branch_and_skips_default_branch_call() -> None:
    project_called: typing.Final = {"v": False}
    captured_params: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _PROJECT_PATH:
            project_called["v"] = True
            return httpx2.Response(200, json={"default_branch": "main"})
        if request.url.path == _COMMITS_PATH:
            captured_params.update(dict(request.url.params))
            return httpx2.Response(200, json=[{"id": "deadbeef", "message": "msg"}])
        return httpx2.Response(404)

    provider, client = _make_provider(handler, default_branch="develop")
    with client:
        commit = provider.get_latest_commit_on_default_branch()
    assert project_called["v"] is False
    assert captured_params["ref_name"] == "develop"
    assert commit == Commit(sha="deadbeef", message="msg")


def test_raises_config_error_when_default_branch_is_null() -> None:
    overrides: typing.Final = {
        ("GET", _PROJECT_PATH): httpx2.Response(200, json={"default_branch": None}),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ConfigError, match="Default branch missing"):
        provider.get_default_branch()


def test_raises_provider_api_error_when_default_branch_response_malformed() -> None:
    overrides: typing.Final = {
        ("GET", _PROJECT_PATH): httpx2.Response(200, json={"unexpected": "shape"}),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_ProjectResponse response could not be decoded"):
        provider.get_default_branch()


def test_raises_provider_api_error_when_default_branch_body_is_not_json() -> None:
    overrides: typing.Final = {
        ("GET", _PROJECT_PATH): httpx2.Response(200, text="not json at all"),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_ProjectResponse response could not be decoded"):
        provider.get_default_branch()


def test_raises_provider_api_error_when_default_branch_body_is_not_object() -> None:
    overrides: typing.Final = {
        ("GET", _PROJECT_PATH): httpx2.Response(200, json=[]),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_ProjectResponse response could not be decoded"):
        provider.get_default_branch()


def test_get_default_branch_sends_private_token_header() -> None:
    captured_headers: dict[str, str] = {}
    captured_url_path: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured_headers.update(request.headers)
        captured_url_path["path"] = request.url.path
        return httpx2.Response(200, json={"default_branch": "main"})

    provider, client = _make_provider(handler)
    with client:
        provider.get_default_branch()
    assert captured_headers.get("private-token") == GITLAB_TOKEN
    assert captured_url_path["path"] == _PROJECT_PATH


# AC4 -- get_latest_commit_on_default_branch


def test_returns_commit_when_get_latest_commit_happy_path(
    gitlab_provider: GitLabProvider,
) -> None:
    commit: typing.Final = gitlab_provider.get_latest_commit_on_default_branch()
    assert commit == Commit(sha=_DEFAULT_COMMIT_SHA, message=_DEFAULT_COMMIT_MESSAGE)


def test_raises_provider_api_error_when_no_commits_on_default_branch() -> None:
    overrides: typing.Final = {
        ("GET", _COMMITS_PATH): httpx2.Response(200, json=[]),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="No commits on default branch"):
        provider.get_latest_commit_on_default_branch()


def test_get_latest_commit_raises_provider_api_error_when_body_not_json() -> None:
    overrides: typing.Final = {
        ("GET", _COMMITS_PATH): httpx2.Response(200, text="not json"),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_CommitList response could not be decoded"):
        provider.get_latest_commit_on_default_branch()


def test_get_latest_commit_raises_provider_api_error_when_body_not_list() -> None:
    overrides: typing.Final = {
        ("GET", _COMMITS_PATH): httpx2.Response(200, json={"id": "x", "message": "y"}),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_CommitList response could not be decoded"):
        provider.get_latest_commit_on_default_branch()


def test_get_latest_commit_raises_provider_api_error_when_commit_object_missing_keys() -> None:
    overrides: typing.Final = {
        ("GET", _COMMITS_PATH): httpx2.Response(200, json=[{"short_id": "x"}]),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_CommitList response could not be decoded"):
        provider.get_latest_commit_on_default_branch()


def test_get_default_branch_raises_config_error_when_default_branch_empty_string() -> None:
    overrides: typing.Final = {
        ("GET", _PROJECT_PATH): httpx2.Response(200, json={"default_branch": ""}),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ConfigError, match="Default branch missing"):
        provider.get_default_branch()


def test_get_latest_commit_passes_ref_name_and_per_page_one_query() -> None:
    captured_params: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _PROJECT_PATH:
            return httpx2.Response(200, json={"default_branch": "main"})
        if request.url.path == _COMMITS_PATH:
            captured_params.update(dict(request.url.params))
            return httpx2.Response(200, json=[{"id": "deadbeef", "message": "msg"}])
        return httpx2.Response(404)

    provider, client = _make_provider(handler)
    with client:
        provider.get_latest_commit_on_default_branch()
    assert captured_params == {"ref_name": "main", "per_page": "1"}


# AC5 -- list_tags


def test_returns_all_tags_including_non_semver_names() -> None:
    overrides: typing.Final = {
        ("GET", _TAGS_PATH): httpx2.Response(
            200,
            json=[
                {"name": "1.4.2", "commit": {"id": "sha-a"}},
                {"name": "release-2024-Q1", "commit": {"id": "sha-b"}},
                {"name": "v1.4.1", "commit": {"id": "sha-c"}},
            ],
        ),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client:
        tags = provider.list_tags()
    assert tags == [
        Tag(name="1.4.2", commit_sha="sha-a"),
        Tag(name="release-2024-Q1", commit_sha="sha-b"),
        Tag(name="v1.4.1", commit_sha="sha-c"),
    ]


def test_paginates_tags_when_link_header_advertises_next() -> None:
    page_two_url: typing.Final = f"{GITLAB_ENDPOINT}{_TAGS_PATH}?page=2&per_page=100"
    page_state: dict[str, int] = {"calls": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path != _TAGS_PATH:
            return default_handler(request)
        page_state["calls"] += 1
        if page_state["calls"] == 1:
            return httpx2.Response(
                200,
                json=[{"name": "1.0.0", "commit": {"id": "sha-1"}}],
                headers={"Link": f'<{page_two_url}>; rel="next"'},
            )
        return httpx2.Response(
            200,
            json=[{"name": "1.0.1", "commit": {"id": "sha-2"}}],
        )

    provider, client = _make_provider(handler)
    with client:
        tags = provider.list_tags()
    assert tags == [
        Tag(name="1.0.0", commit_sha="sha-1"),
        Tag(name="1.0.1", commit_sha="sha-2"),
    ]
    assert page_state["calls"] == _EXPECTED_PAGE_CALLS


def test_returns_empty_list_when_no_tags(gitlab_provider: GitLabProvider) -> None:
    assert gitlab_provider.list_tags() == []


def test_list_tags_raises_provider_api_error_when_body_not_json() -> None:
    overrides: typing.Final = {
        ("GET", _TAGS_PATH): httpx2.Response(200, text="not json"),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_TagList response could not be decoded"):
        provider.list_tags()


def test_list_tags_raises_provider_api_error_when_body_not_list() -> None:
    overrides: typing.Final = {
        ("GET", _TAGS_PATH): httpx2.Response(200, json={"unexpected": "shape"}),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_TagList response could not be decoded"):
        provider.list_tags()


def test_list_tags_raises_provider_api_error_when_tag_object_missing_keys() -> None:
    overrides: typing.Final = {
        ("GET", _TAGS_PATH): httpx2.Response(200, json=[{"name": "v1"}]),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ProviderAPIError, match="_TagList response could not be decoded"):
        provider.list_tags()


def test_list_tags_refuses_to_follow_off_host_next_link() -> None:
    off_host_url: typing.Final = "https://attacker.example.test/api/v4/projects/999/repository/tags?page=2"

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path != _TAGS_PATH:
            return default_handler(request)
        return httpx2.Response(
            200,
            json=[{"name": "1.0.0", "commit": {"id": "sha-1"}}],
            headers={"Link": f'<{off_host_url}>; rel="next"'},
        )

    provider, client = _make_provider(handler)
    with client, pytest.raises(ProviderAPIError, match="different host"):
        provider.list_tags()


def test_stops_pagination_when_link_header_has_no_next_rel() -> None:
    overrides: typing.Final = {
        ("GET", _TAGS_PATH): httpx2.Response(
            200,
            json=[{"name": "1.0.0", "commit": {"id": "sha-1"}}],
            headers={"Link": '<https://example.test/prev>; rel="prev"'},
        ),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client:
        tags = provider.list_tags()
    assert tags == [Tag(name="1.0.0", commit_sha="sha-1")]


def test_raises_provider_api_error_when_pagination_exceeds_cap() -> None:
    call_counter: dict[str, int] = {"count": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path != _TAGS_PATH:
            return default_handler(request)
        call_counter["count"] += 1
        next_url = f"{GITLAB_ENDPOINT}{_TAGS_PATH}?page={call_counter['count'] + 1}&per_page=100"
        return httpx2.Response(
            200,
            json=[{"name": f"tag-{call_counter['count']}", "commit": {"id": "sha"}}],
            headers={"Link": f'<{next_url}>; rel="next"'},
        )

    provider, client = _make_provider(handler)
    with client, pytest.raises(ProviderAPIError, match="Tag pagination exceeded"):
        provider.list_tags()
    assert call_counter["count"] == _PAGINATION_CAP


# AC6 -- create_tag


def test_create_tag_succeeds_on_201(gitlab_provider: GitLabProvider) -> None:
    assert gitlab_provider.create_tag(name="1.4.3", commit_sha=_DEFAULT_COMMIT_SHA) is None


def test_create_tag_raises_config_error_on_400_already_exists() -> None:
    overrides: typing.Final = {
        ("POST", _TAGS_PATH): httpx2.Response(400, json={"message": "Tag 1.4.3 already exists"}),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ConfigError, match=r"Tag already exists: '1\.4\.3'"):
        provider.create_tag(name="1.4.3", commit_sha=_DEFAULT_COMMIT_SHA)


def test_create_tag_raises_config_error_on_generic_400() -> None:
    overrides: typing.Final = {
        ("POST", _TAGS_PATH): httpx2.Response(400, json={"message": "ref is invalid"}),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ConfigError, match="Request rejected by GitLab: 400"):
        provider.create_tag(name="badref", commit_sha="zzz")


def test_create_tag_raises_config_error_on_400_with_non_json_body() -> None:
    overrides: typing.Final = {
        ("POST", _TAGS_PATH): httpx2.Response(400, text="not json"),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ConfigError, match="Request rejected by GitLab: 400"):
        provider.create_tag(name="x", commit_sha="y")


def test_create_tag_sends_json_body() -> None:
    captured_payloads: list[bytes] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST" and request.url.path == _TAGS_PATH:
            captured_payloads.append(request.content)
            return httpx2.Response(201, json={"name": "1.4.3"})
        return default_handler(request)

    provider, client = _make_provider(handler)
    with client:
        provider.create_tag(name="1.4.3", commit_sha=_DEFAULT_COMMIT_SHA)
    assert len(captured_payloads) == 1
    assert b'"tag_name":"1.4.3"' in captured_payloads[0].replace(b" ", b"")
    assert b'"ref":"a2b4d12"' in captured_payloads[0].replace(b" ", b"")


# AC7 -- Error translation matrix


def _call_get_default_branch(provider: GitLabProvider) -> None:
    provider.get_default_branch()


def _call_get_latest_commit(provider: GitLabProvider) -> None:
    provider.get_latest_commit_on_default_branch()


def _call_list_tags(provider: GitLabProvider) -> None:
    provider.list_tags()


def _call_create_tag(provider: GitLabProvider) -> None:
    provider.create_tag(name="1.4.3", commit_sha=_DEFAULT_COMMIT_SHA)


_MAIN_VERB_CALLS: typing.Final = (
    ("get_default_branch", _call_get_default_branch, ("GET", _PROJECT_PATH)),
    ("get_latest_commit", _call_get_latest_commit, ("GET", _COMMITS_PATH)),
    ("list_tags", _call_list_tags, ("GET", _TAGS_PATH)),
    ("create_tag", _call_create_tag, ("POST", _TAGS_PATH)),
)


@pytest.mark.parametrize(
    ("verb_name", "verb_callable", "endpoint_key"),
    _MAIN_VERB_CALLS,
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_auth_error_on_401(
    verb_name: str,  # noqa: ARG001
    verb_callable: typing.Callable[[GitLabProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    overrides: typing.Final = {endpoint_key: httpx2.Response(_UNAUTHORIZED_STATUS, json={})}
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(AuthError, match="Token rejected: 401"):
        verb_callable(provider)


@pytest.mark.parametrize(
    ("verb_name", "verb_callable", "endpoint_key"),
    _MAIN_VERB_CALLS,
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_auth_error_on_403(
    verb_name: str,  # noqa: ARG001
    verb_callable: typing.Callable[[GitLabProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    overrides: typing.Final = {endpoint_key: httpx2.Response(_FORBIDDEN_STATUS, json={})}
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(AuthError, match="Token missing scope"):
        verb_callable(provider)


@pytest.mark.parametrize(
    ("verb_name", "verb_callable", "endpoint_key"),
    _MAIN_VERB_CALLS,
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_config_error_on_404(
    verb_name: str,  # noqa: ARG001
    verb_callable: typing.Callable[[GitLabProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    overrides: typing.Final = {endpoint_key: httpx2.Response(_NOT_FOUND_STATUS, json={})}
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ConfigError, match=f"project_id={GITLAB_PROJECT_ID}"):
        verb_callable(provider)


def test_create_tag_raises_config_error_on_422() -> None:
    overrides: typing.Final = {
        ("POST", _TAGS_PATH): httpx2.Response(_UNPROCESSABLE_STATUS, json={}),
    }
    provider, client = _make_provider(compose_handler(default_handler, overrides))
    with client, pytest.raises(ConfigError, match="Request rejected by GitLab: 422"):
        provider.create_tag(name="1.4.3", commit_sha=_DEFAULT_COMMIT_SHA)


def _handler_that_returns_for(
    endpoint_key: tuple[str, str],
    response: httpx2.Response,
) -> HandlerCallable:
    target_method, target_path = endpoint_key

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == target_method and request.url.path.startswith(target_path):
            return response
        return default_handler(request)

    return handler


def _handler_that_raises_for(
    endpoint_key: tuple[str, str],
    exc_factory: typing.Callable[[], BaseException],
) -> HandlerCallable:
    target_method, target_path = endpoint_key

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == target_method and request.url.path.startswith(target_path):
            raise exc_factory()
        return default_handler(request)

    return handler


@pytest.mark.parametrize(
    ("verb_name", "verb_callable", "endpoint_key"),
    _MAIN_VERB_CALLS,
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_provider_api_error_on_5xx(
    verb_name: str,  # noqa: ARG001
    verb_callable: typing.Callable[[GitLabProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    handler: typing.Final = _handler_that_returns_for(
        endpoint_key,
        httpx2.Response(_SERVICE_UNAVAILABLE_STATUS, json={}),
    )
    provider, client = _make_provider(handler)
    with client, pytest.raises(ProviderAPIError, match=f"GitLab API failure: {_SERVICE_UNAVAILABLE_STATUS}"):
        verb_callable(provider)


@pytest.mark.parametrize(
    ("verb_name", "verb_callable", "endpoint_key"),
    _MAIN_VERB_CALLS,
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_provider_api_error_on_429(
    verb_name: str,  # noqa: ARG001
    verb_callable: typing.Callable[[GitLabProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    handler: typing.Final = _handler_that_returns_for(
        endpoint_key,
        httpx2.Response(_TOO_MANY_REQUESTS_STATUS, json={}),
    )
    provider, client = _make_provider(handler)
    with client, pytest.raises(ProviderAPIError, match="GitLab rate limit: 429"):
        verb_callable(provider)


@pytest.mark.parametrize(
    ("verb_name", "verb_callable", "endpoint_key"),
    _MAIN_VERB_CALLS,
    ids=[name for name, _call, _key in _MAIN_VERB_CALLS],
)
def test_raises_provider_api_error_when_network_error(
    verb_name: str,  # noqa: ARG001
    verb_callable: typing.Callable[[GitLabProvider], None],
    endpoint_key: tuple[str, str],
) -> None:
    handler: typing.Final = _handler_that_raises_for(
        endpoint_key,
        lambda: httpx2.ConnectError("simulated network failure"),
    )
    provider, client = _make_provider(handler)
    with client, pytest.raises(ProviderAPIError, match="GitLab unreachable") as exc_info:
        verb_callable(provider)
    assert isinstance(exc_info.value.__cause__, httpware.NetworkError)

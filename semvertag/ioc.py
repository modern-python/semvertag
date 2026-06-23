import typing

import httpware
import modern_di
from modern_di import Scope, providers

from semvertag._settings import Settings
from semvertag._use_case import SemvertagUseCase
from semvertag.providers._base import Provider
from semvertag.providers.github import GitHubProvider
from semvertag.providers.gitlab import GitLabProvider
from semvertag.strategies._base import BumpStrategy
from semvertag.strategies.branch_prefix import BranchPrefixStrategy
from semvertag.strategies.conventional_commits import ConventionalCommitsStrategy


_GITLAB_TOKEN_HEADER: typing.Final = "PRIVATE-TOKEN"
_GITHUB_ACCEPT: typing.Final = "application/vnd.github+json"
_GITHUB_API_VERSION: typing.Final = "2022-11-28"
_RETRY_STATUS_CODES: typing.Final = frozenset({408, 429, 500, 502, 503, 504})
_MAX_RESPONSE_BODY_BYTES: typing.Final = 1024 * 1024  # 1 MiB — defensive cap on response bodies


def _build_gitlab_client(settings: Settings) -> httpware.Client:
    return httpware.Client(
        base_url=settings.gitlab.endpoint,
        timeout=settings.request_timeout,
        headers={_GITLAB_TOKEN_HEADER: settings.gitlab.token.get_secret_value()},
        middleware=[httpware.Retry(retry_status_codes=_RETRY_STATUS_CODES)],
        max_response_body_bytes=_MAX_RESPONSE_BODY_BYTES,
    )


def _build_github_client(settings: Settings) -> httpware.Client:
    return httpware.Client(
        base_url=settings.github.endpoint,
        timeout=settings.request_timeout,
        headers={
            "Authorization": f"Bearer {settings.github.token.get_secret_value()}",
            "Accept": _GITHUB_ACCEPT,
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        },
        middleware=[httpware.Retry(retry_status_codes=_RETRY_STATUS_CODES)],
        max_response_body_bytes=_MAX_RESPONSE_BODY_BYTES,
    )


def _build_current_provider(
    settings: Settings,
    gitlab_client: httpware.Client,
    github_client: httpware.Client,
) -> Provider:
    """
    Construct the active provider.

    Both clients are eagerly resolved (modern-di Factory eagerly resolves all
    provider_kwargs in resolve()). That's acceptable — httpx2 connection pools
    are lazy, so the unused client doesn't open sockets.

    Only the active branch constructs a Provider instance; the assert serves
    both as type-narrowing for `ty` and as a clear failure mode if the
    Settings._resolve_provider validator's invariant ever breaks.
    """
    if settings.provider == "github":
        assert settings.repo is not None, "provider=github invariant: validator guarantees repo is set"  # noqa: S101
        return GitHubProvider(config=settings.github, repo=settings.repo, http=github_client)
    assert settings.project_id is not None, "provider=gitlab invariant: validator guarantees project_id is set"  # noqa: S101
    return GitLabProvider(config=settings.gitlab, project_id=settings.project_id, http=gitlab_client)


def _build_branch_prefix_strategy(settings: Settings) -> BranchPrefixStrategy:
    return BranchPrefixStrategy(config=settings.branch_prefix)


def _build_conventional_commits_strategy(settings: Settings) -> ConventionalCommitsStrategy:
    return ConventionalCommitsStrategy(config=settings.conventional_commits)


def _build_current_strategy(settings: Settings) -> BumpStrategy:
    if settings.strategy == "conventional-commits":
        return _build_conventional_commits_strategy(settings)
    return _build_branch_prefix_strategy(settings)


def _close_client(client: httpware.Client) -> None:
    client.close()


class SettingsGroup(modern_di.Group):
    settings = providers.ContextProvider(scope=Scope.APP, context_type=Settings)


class ProvidersGroup(modern_di.Group):
    gitlab_client = providers.Factory(
        scope=Scope.APP,
        creator=_build_gitlab_client,
        bound_type=None,
        cache_settings=providers.CacheSettings(finalizer=_close_client),
    )
    github_client = providers.Factory(
        scope=Scope.APP,
        creator=_build_github_client,
        bound_type=None,
        cache_settings=providers.CacheSettings(finalizer=_close_client),
    )
    current_provider = providers.Factory(
        scope=Scope.APP,
        creator=_build_current_provider,
        kwargs={"gitlab_client": gitlab_client, "github_client": github_client},
    )


class StrategiesGroup(modern_di.Group):
    branch_prefix_strategy = providers.Factory(scope=Scope.APP, creator=_build_branch_prefix_strategy)
    conventional_commits_strategy = providers.Factory(scope=Scope.APP, creator=_build_conventional_commits_strategy)
    current_strategy = providers.Factory(scope=Scope.APP, creator=_build_current_strategy)


class UseCasesGroup(modern_di.Group):
    semvertag_use_case = providers.Factory(
        scope=Scope.APP,
        creator=SemvertagUseCase,
        kwargs={
            "provider": ProvidersGroup.current_provider,
            "strategy": StrategiesGroup.current_strategy,
        },
    )


ALL_GROUPS: typing.Final[list[type[modern_di.Group]]] = [
    SettingsGroup,
    ProvidersGroup,
    StrategiesGroup,
    UseCasesGroup,
]


container: typing.Final = modern_di.Container(groups=ALL_GROUPS)

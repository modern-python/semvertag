import typing

import httpware

from semvertag import ioc
from semvertag._settings import Settings
from semvertag.providers.github import GitHubProvider
from semvertag.providers.gitlab import GitLabProvider
from semvertag.strategies.branch_prefix import BranchPrefixStrategy
from semvertag.strategies.conventional_commits import ConventionalCommitsStrategy


_StrategyName = typing.Literal["branch-prefix", "conventional-commits"]


def _settings(
    *,
    strategy: _StrategyName = "branch-prefix",
) -> Settings:
    return Settings(project_id=999, strategy=strategy)


def test_container_resolves_branch_prefix_strategy_by_default() -> None:
    settings: typing.Final = _settings(strategy="branch-prefix")
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        strategy = ioc.container.resolve_provider(ioc.StrategiesGroup.current_strategy)
        assert isinstance(strategy, BranchPrefixStrategy)
        assert strategy.name == "branch-prefix"


def test_container_resolves_conventional_commits_strategy_when_settings_strategy_is_cc() -> None:
    settings: typing.Final = _settings(strategy="conventional-commits")
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        strategy = ioc.container.resolve_provider(ioc.StrategiesGroup.current_strategy)
        assert isinstance(strategy, ConventionalCommitsStrategy)
        assert strategy.name == "conventional-commits"


def test_named_strategy_factories_resolve_to_their_concrete_types_regardless_of_settings() -> None:
    settings: typing.Final = _settings(strategy="conventional-commits")
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        bp = ioc.container.resolve_provider(ioc.StrategiesGroup.branch_prefix_strategy)
        cc = ioc.container.resolve_provider(ioc.StrategiesGroup.conventional_commits_strategy)
        assert isinstance(bp, BranchPrefixStrategy)
        assert isinstance(cc, ConventionalCommitsStrategy)


def test_container_builds_gitlab_client_with_settings_values() -> None:
    settings: typing.Final = _settings()
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        client = ioc.container.resolve_provider(ioc.ProvidersGroup.gitlab_client)
        assert isinstance(client, httpware.Client)


def test_container_resolves_github_provider_when_settings_provider_is_github() -> None:
    settings = Settings(provider="github", repo="owner/repo")
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        provider = ioc.container.resolve_provider(ioc.ProvidersGroup.current_provider)
        assert isinstance(provider, GitHubProvider)
        assert provider.name == "github"


def test_container_resolves_gitlab_provider_when_settings_provider_is_gitlab() -> None:
    settings = Settings(provider="gitlab", project_id=999)
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        provider = ioc.container.resolve_provider(ioc.ProvidersGroup.current_provider)
        assert isinstance(provider, GitLabProvider)
        assert provider.name == "gitlab"


def test_github_provider_receives_default_branch_override() -> None:
    settings = Settings(provider="github", repo="owner/repo", default_branch="develop")
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        provider = ioc.container.resolve_provider(ioc.ProvidersGroup.current_provider)
        assert isinstance(provider, GitHubProvider)
        assert provider.default_branch == "develop"


def test_gitlab_provider_receives_default_branch_override() -> None:
    settings = Settings(provider="gitlab", project_id=999, default_branch="develop")
    with ioc.container:
        ioc.container.set_context(Settings, settings)
        provider = ioc.container.resolve_provider(ioc.ProvidersGroup.current_provider)
        assert isinstance(provider, GitLabProvider)
        assert provider.default_branch == "develop"


def test_gitlab_client_is_built_with_response_body_cap() -> None:
    client: typing.Final = ioc._build_gitlab_client(_settings())
    assert client._max_response_body_bytes == ioc._MAX_RESPONSE_BODY_BYTES


def test_github_client_is_built_with_response_body_cap() -> None:
    client: typing.Final = ioc._build_github_client(_settings())
    assert client._max_response_body_bytes == ioc._MAX_RESPONSE_BODY_BYTES

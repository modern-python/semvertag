import typing

import pydantic
import pytest

from semvertag._settings import GitLabConfig, Settings, apply_cli_overlay


_NESTED_TOKEN: typing.Final = "tok-nested"
_FLAT_SEMVERTAG_TOKEN: typing.Final = "tok-flat"
_CI_JOB_TOKEN_VALUE: typing.Final = "tok-ci"
_GITLAB_TOKEN_VALUE: typing.Final = "tok-gitlab-native"
_CUSTOM_ENDPOINT: typing.Final = "https://gitlab.example.com"
_TIMEOUT_OVER_CEILING: typing.Final = "99"
_TIMEOUT_UNDER_CEILING: typing.Final = "5.5"
_TIMEOUT_CEILING_VALUE: typing.Final = 10.0
_TIMEOUT_UNDER_VALUE: typing.Final = 5.5
_TIMEOUT_DEFAULT_VALUE: typing.Final = 8.0
_PLAINTEXT_SECRET: typing.Final = "plaintext-secret-marker"
_PROJECT_ID_SEMVERTAG: typing.Final = "999"
_PROJECT_ID_CI: typing.Final = "777"
_PROJECT_ID_INT_SEMVERTAG: typing.Final = 999
_PROJECT_ID_INT_CI: typing.Final = 777


@pytest.mark.usefixtures("clean_settings_env")
def test_uses_defaults_when_no_env_set() -> None:
    settings: typing.Final = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG)
    assert settings.strategy == "branch-prefix"
    assert settings.default_branch is None
    assert settings.request_timeout == _TIMEOUT_DEFAULT_VALUE
    assert settings.project_id == _PROJECT_ID_INT_SEMVERTAG
    assert settings.gitlab.endpoint == "https://gitlab.com"
    assert settings.gitlab.token.get_secret_value() == ""
    assert settings.github.token.get_secret_value() == ""


@pytest.mark.usefixtures("clean_settings_env")
@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_default_branch_is_treated_as_unset(blank: str) -> None:
    settings: typing.Final = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG, default_branch=blank)
    assert settings.default_branch is None


@pytest.mark.usefixtures("clean_settings_env")
def test_default_branch_is_stripped() -> None:
    settings: typing.Final = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG, default_branch="  develop  ")
    assert settings.default_branch == "develop"


@pytest.mark.usefixtures("clean_settings_env")
def test_resolves_token_from_ci_job_token_when_only_native_var_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI_JOB_TOKEN", _CI_JOB_TOKEN_VALUE)
    settings: typing.Final = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG)
    assert settings.gitlab.token.get_secret_value() == _CI_JOB_TOKEN_VALUE


@pytest.mark.usefixtures("clean_settings_env")
def test_prefers_semvertag_token_over_provider_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMVERTAG_TOKEN", _FLAT_SEMVERTAG_TOKEN)
    monkeypatch.setenv("GITLAB_TOKEN", _GITLAB_TOKEN_VALUE)
    monkeypatch.setenv("CI_JOB_TOKEN", _CI_JOB_TOKEN_VALUE)
    settings: typing.Final = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG)
    assert settings.gitlab.token.get_secret_value() == _FLAT_SEMVERTAG_TOKEN


@pytest.mark.usefixtures("clean_settings_env")
def test_prefers_nested_prefix_over_flat_semvertag_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMVERTAG_GITLAB__TOKEN", _NESTED_TOKEN)
    monkeypatch.setenv("SEMVERTAG_TOKEN", _FLAT_SEMVERTAG_TOKEN)
    monkeypatch.setenv("CI_JOB_TOKEN", _CI_JOB_TOKEN_VALUE)
    settings: typing.Final = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG)
    assert settings.gitlab.token.get_secret_value() == _NESTED_TOKEN


@pytest.mark.usefixtures("clean_settings_env")
def test_reads_nested_env_var_for_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMVERTAG_GITLAB__ENDPOINT", _CUSTOM_ENDPOINT)
    settings: typing.Final = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG)
    assert settings.gitlab.endpoint == _CUSTOM_ENDPOINT


@pytest.mark.usefixtures("clean_settings_env")
def test_secret_str_is_redacted_in_repr() -> None:
    gitlab: typing.Final = GitLabConfig(token=pydantic.SecretStr(_PLAINTEXT_SECRET))
    settings: typing.Final = Settings(gitlab=gitlab, project_id=_PROJECT_ID_INT_SEMVERTAG)
    assert _PLAINTEXT_SECRET not in repr(settings)
    assert _PLAINTEXT_SECRET not in repr(settings.gitlab)
    assert _PLAINTEXT_SECRET not in repr(settings.gitlab.token)
    assert _PLAINTEXT_SECRET not in str(settings.gitlab.token)
    assert "**********" in repr(settings.gitlab.token)


@pytest.mark.usefixtures("clean_settings_env")
def test_request_timeout_clamps_to_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMVERTAG_REQUEST_TIMEOUT", _TIMEOUT_OVER_CEILING)
    settings: typing.Final = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG)
    assert settings.request_timeout == _TIMEOUT_CEILING_VALUE


@pytest.mark.usefixtures("clean_settings_env")
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (_TIMEOUT_UNDER_CEILING, _TIMEOUT_UNDER_VALUE),
        ("10.0", _TIMEOUT_CEILING_VALUE),
    ],
)
def test_request_timeout_passes_through_when_below_ten(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: float,
) -> None:
    monkeypatch.setenv("SEMVERTAG_REQUEST_TIMEOUT", raw)
    settings: typing.Final = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG)
    assert settings.request_timeout == expected


@pytest.mark.usefixtures("clean_settings_env")
def test_request_timeout_rejects_non_positive_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMVERTAG_REQUEST_TIMEOUT", "0")
    with pytest.raises(pydantic.ValidationError):
        Settings()


@pytest.mark.usefixtures("clean_settings_env")
def test_resolves_project_id_from_semvertag_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMVERTAG_PROJECT_ID", _PROJECT_ID_SEMVERTAG)
    settings: typing.Final = Settings()
    assert settings.project_id == _PROJECT_ID_INT_SEMVERTAG


@pytest.mark.usefixtures("clean_settings_env")
def test_resolves_project_id_from_ci_project_id_when_only_native_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI_PROJECT_ID", _PROJECT_ID_CI)
    settings: typing.Final = Settings()
    assert settings.project_id == _PROJECT_ID_INT_CI


@pytest.mark.usefixtures("clean_settings_env")
def test_prefers_semvertag_project_id_over_ci_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMVERTAG_PROJECT_ID", _PROJECT_ID_SEMVERTAG)
    monkeypatch.setenv("CI_PROJECT_ID", _PROJECT_ID_CI)
    settings: typing.Final = Settings()
    assert settings.project_id == _PROJECT_ID_INT_SEMVERTAG


@pytest.mark.usefixtures("clean_settings_env")
def test_apply_cli_overlay_rejects_keys_deeper_than_two_levels() -> None:
    base: typing.Final = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG)
    with pytest.raises(ValueError, match="exceeds nesting depth 2"):
        apply_cli_overlay(base, {"gitlab.foo.bar": "x"})


@pytest.mark.usefixtures("clean_settings_env")
def test_apply_cli_overlay_updates_top_level_key() -> None:
    base: typing.Final = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG)
    result = apply_cli_overlay(base, {"default_branch": "develop"})
    assert result.default_branch == "develop"


def test_provider_defaults_to_gitlab_when_no_ci_env_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    monkeypatch.delenv("SEMVERTAG_PROVIDER", raising=False)
    monkeypatch.delenv("PROVIDER", raising=False)
    settings = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG)
    assert settings.provider == "gitlab"


def test_provider_detects_github_from_github_actions_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITLAB_CI", raising=False)
    monkeypatch.delenv("SEMVERTAG_PROVIDER", raising=False)
    settings = Settings(repo="owner/repo")
    assert settings.provider == "github"


def test_provider_detects_gitlab_from_gitlab_ci_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.delenv("SEMVERTAG_PROVIDER", raising=False)
    settings = Settings(project_id=_PROJECT_ID_INT_SEMVERTAG)
    assert settings.provider == "gitlab"


def test_provider_raises_when_both_ci_envs_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.delenv("SEMVERTAG_PROVIDER", raising=False)
    with pytest.raises(Exception, match="ambiguous"):
        Settings(project_id=_PROJECT_ID_INT_SEMVERTAG, repo="owner/repo")


def test_explicit_provider_overrides_auto_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITLAB_CI", "true")
    settings = Settings(provider="gitlab", project_id=_PROJECT_ID_INT_SEMVERTAG)
    assert settings.provider == "gitlab"


def test_provider_github_requires_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    with pytest.raises(Exception, match=r"provider=github requires .*repo"):
        Settings(provider="github")


def test_provider_gitlab_requires_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)
    with pytest.raises(Exception, match=r"provider=gitlab requires .*project_id"):
        Settings(provider="gitlab")


def test_github_config_endpoint_defaults_to_api_github_com() -> None:
    settings = Settings(provider="github", repo="owner/repo")
    assert settings.github.endpoint == "https://api.github.com"


def test_github_config_endpoint_overridable_for_enterprise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMVERTAG_GITHUB__ENDPOINT", "https://github.acme.com/api/v3")
    settings = Settings(provider="github", repo="owner/repo")
    assert settings.github.endpoint == "https://github.acme.com/api/v3"


def test_repo_alias_picks_up_github_repository_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "octocat/Hello-World")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    settings = Settings()
    assert settings.repo == "octocat/Hello-World"
    assert settings.provider == "github"

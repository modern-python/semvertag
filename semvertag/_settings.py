import dataclasses
import logging
import os
import typing

import pydantic
import pydantic_settings

from semvertag._errors import ConfigError
from semvertag.strategies.branch_prefix import BranchPrefixConfig
from semvertag.strategies.conventional_commits import ConventionalCommitsConfig


_logger: typing.Final = logging.getLogger(__name__)

_REQUEST_TIMEOUT_CEILING: typing.Final = 10.0
_ENV_PREFIX: typing.Final = "SEMVERTAG_"
_ENV_NESTED_DELIMITER: typing.Final = "__"


class GitLabConfig(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="SEMVERTAG_GITLAB__",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    endpoint: str = "https://gitlab.com"
    token: pydantic.SecretStr = pydantic.Field(
        default=pydantic.SecretStr(""),
        validation_alias=pydantic.AliasChoices(
            "SEMVERTAG_GITLAB__TOKEN",
            "SEMVERTAG_TOKEN",
            "CI_JOB_TOKEN",
            "GITLAB_TOKEN",
        ),
    )


class GitHubConfig(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="SEMVERTAG_GITHUB__",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    endpoint: str = "https://api.github.com"
    token: pydantic.SecretStr = pydantic.Field(
        default=pydantic.SecretStr(""),
        validation_alias=pydantic.AliasChoices(
            "SEMVERTAG_GITHUB__TOKEN",
            "SEMVERTAG_TOKEN",
            "GITHUB_TOKEN",
        ),
    )


def _detect_provider_from_env() -> typing.Literal["gitlab", "github"]:
    github_ci = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    gitlab_ci = os.environ.get("GITLAB_CI", "").lower() == "true"
    if github_ci and gitlab_ci:
        msg = (
            "ambiguous CI context: both GITHUB_ACTIONS and GITLAB_CI are set. "
            "Pass --provider github|gitlab or set SEMVERTAG_PROVIDER to disambiguate."
        )
        raise ValueError(msg)
    if github_ci:
        return "github"
    return "gitlab"


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class GitHubTarget:
    repo: str


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class GitLabTarget:
    project_id: int


ProviderTarget: typing.TypeAlias = GitHubTarget | GitLabTarget


class Settings(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix=_ENV_PREFIX,
        env_nested_delimiter=_ENV_NESTED_DELIMITER,
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    strategy: typing.Literal["branch-prefix", "conventional-commits"] = "branch-prefix"
    provider: typing.Literal["gitlab", "github"] | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("SEMVERTAG_PROVIDER", "PROVIDER"),
    )
    default_branch: str | None = None
    request_timeout: float = pydantic.Field(default=8.0, gt=0)
    project_id: int | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("SEMVERTAG_PROJECT_ID", "CI_PROJECT_ID"),
    )
    repo: str | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("SEMVERTAG_REPO", "GITHUB_REPOSITORY"),
    )
    gitlab: GitLabConfig = pydantic.Field(default_factory=GitLabConfig)
    github: GitHubConfig = pydantic.Field(default_factory=GitHubConfig)
    branch_prefix: BranchPrefixConfig = pydantic.Field(default_factory=BranchPrefixConfig)
    conventional_commits: ConventionalCommitsConfig = pydantic.Field(default_factory=ConventionalCommitsConfig)

    _provider_target: ProviderTarget | None = pydantic.PrivateAttr(default=None)

    @property
    def provider_target(self) -> ProviderTarget:
        assert self._provider_target is not None, "provider_target is set by _resolve_provider"  # noqa: S101
        return self._provider_target

    @pydantic.field_validator("default_branch")
    @classmethod
    def _blank_default_branch_is_unset(cls, value: str | None) -> str | None:
        # An empty or whitespace-only override (e.g. a declared-but-empty
        # SEMVERTAG_DEFAULT_BRANCH in CI) means "no override" — fall back to the
        # forge API, never abort. Strip so a stray-padded name still resolves.
        stripped: typing.Final = (value or "").strip()
        return stripped or None

    @pydantic.field_validator("request_timeout")
    @classmethod
    def _clamp_request_timeout(cls, value: float) -> float:
        if value > _REQUEST_TIMEOUT_CEILING:
            _logger.warning(
                "request_timeout=%.3f exceeds ceiling %.1f; clamping to %.1f",
                value,
                _REQUEST_TIMEOUT_CEILING,
                _REQUEST_TIMEOUT_CEILING,
            )
            return _REQUEST_TIMEOUT_CEILING
        return value

    @pydantic.model_validator(mode="after")
    def _resolve_provider(self) -> "Settings":
        if self.provider is None:
            self.provider = _detect_provider_from_env()
        if self.provider == "github":
            repo = self.repo
            if not repo:
                msg = "provider=github requires `repo` (set GITHUB_REPOSITORY or pass --repo OWNER/REPO)"
                raise ValueError(msg)
            self._provider_target = GitHubTarget(repo=repo)
        else:  # gitlab — revisit this branch when adding a third provider to the Literal
            project_id = self.project_id
            if project_id is None:
                msg = "provider=gitlab requires `project_id` (set CI_PROJECT_ID or pass --project-id N)"
                raise ValueError(msg)
            self._provider_target = GitLabTarget(project_id=project_id)
        return self


def _apply_cli_overlay(settings: Settings, overrides: dict[str, typing.Any]) -> Settings:
    top_updates: dict[str, typing.Any] = {}
    nested_updates: dict[str, dict[str, typing.Any]] = {}
    for dotted_key, value in overrides.items():
        head, _, leaf = dotted_key.partition(".")
        if "." in leaf:
            msg = f"CLI overlay key '{dotted_key}' exceeds nesting depth 2."
            raise ValueError(msg)
        if leaf:
            nested_updates.setdefault(head, {})[leaf] = value
        else:
            top_updates[head] = value
    for head, leaves in nested_updates.items():
        top_updates[head] = getattr(settings, head).model_copy(update=leaves)
    copied = settings.model_copy(update=top_updates)
    # Re-validate to trigger field validators (e.g. _clamp_request_timeout).
    # getattr (not model_dump) preserves live SecretStr values.
    return type(settings).model_validate({name: getattr(copied, name) for name in type(copied).model_fields})


def _config_error_from_validation(exc: pydantic.ValidationError) -> ConfigError:
    first: typing.Final = exc.errors()[0]
    loc: typing.Final = ".".join(str(part) for part in first.get("loc", ()))
    detail: typing.Final = first.get("msg", "invalid value")
    msg: typing.Final = f"Configuration error at '{loc}': {detail}. Check environment variables and command-line flags."
    return ConfigError(msg)


def load_settings(cli_overrides: dict[str, typing.Any], *, token: str | None = None) -> Settings:
    """Build a validated Settings from environment + CLI overrides.

    Owns the whole pipeline: split top-level vs dotted once, construct (env +
    top-level), overlay nested, then route --token to the resolved provider.
    Raises only ConfigError on any invalid input.
    """
    top_overrides: typing.Final = {k: v for k, v in cli_overrides.items() if "." not in k}
    nested_overrides: typing.Final = {k: v for k, v in cli_overrides.items() if "." in k}
    try:
        settings = Settings(**top_overrides)
        settings = _apply_cli_overlay(settings, nested_overrides)
        if token is not None:
            settings = _apply_cli_overlay(settings, {f"{settings.provider}.token": pydantic.SecretStr(token)})
    except pydantic.ValidationError as exc:
        raise _config_error_from_validation(exc) from exc
    except ValueError as exc:  # _apply_cli_overlay depth-2 guard; ValidationError caught above
        raise ConfigError(str(exc)) from exc
    return settings

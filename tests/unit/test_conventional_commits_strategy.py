import typing

import pydantic
import pytest

from semvertag._types import Bump, Commit
from semvertag.strategies._base import Decline
from semvertag.strategies.conventional_commits import (
    ConventionalCommitsConfig,
    ConventionalCommitsStrategy,
)


_SHA: typing.Final = "abc1234"
_NOT_CONFORMING: typing.Final = Decline(
    status="no_conforming_commit", reason="Commit subject is not a Conventional Commit."
)
_NO_BUMPING_TYPE: typing.Final = Decline(status="no_bumping_type", reason="Commit type is not configured to bump.")


@pytest.fixture
def default_strategy() -> ConventionalCommitsStrategy:
    return ConventionalCommitsStrategy(config=ConventionalCommitsConfig())


def _commit(message: str) -> Commit:
    return Commit(sha=_SHA, message=message)


def test_returns_minor_when_subject_is_feat(default_strategy: ConventionalCommitsStrategy) -> None:
    assert default_strategy.decide(_commit("feat: add new thing")) is Bump.MINOR


@pytest.mark.parametrize("message", ["fix: correct typo", "perf: faster path"])
def test_returns_patch_when_subject_is_fix_or_perf(
    default_strategy: ConventionalCommitsStrategy,
    message: str,
) -> None:
    assert default_strategy.decide(_commit(message)) is Bump.PATCH


def test_returns_major_when_subject_has_bang_suffix(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    assert default_strategy.decide(_commit("feat!: drop python 3.9")) is Bump.MAJOR


@pytest.mark.parametrize("message", ["fix!: incompatible response", "perf!: rework", "chore!: bump"])
def test_returns_major_when_any_type_has_bang_suffix(
    default_strategy: ConventionalCommitsStrategy,
    message: str,
) -> None:
    assert default_strategy.decide(_commit(message)) is Bump.MAJOR


def test_returns_minor_when_subject_has_scope(default_strategy: ConventionalCommitsStrategy) -> None:
    assert default_strategy.decide(_commit("feat(api): scoped")) is Bump.MINOR


def test_returns_major_when_scoped_and_bang(default_strategy: ConventionalCommitsStrategy) -> None:
    assert default_strategy.decide(_commit("feat(api/v2)!: scoped breaking")) is Bump.MAJOR


def test_returns_major_when_breaking_change_footer_with_space(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    msg: typing.Final = "feat: new thing\n\nBREAKING CHANGE: old thing removed"
    assert default_strategy.decide(_commit(msg)) is Bump.MAJOR


def test_returns_major_when_breaking_change_footer_with_hyphen(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    msg: typing.Final = "feat: new thing\n\nBREAKING-CHANGE: hyphen variant"
    assert default_strategy.decide(_commit(msg)) is Bump.MAJOR


def test_returns_major_when_bang_and_footer_both_set(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    msg: typing.Final = "feat!: breaking subject\n\nBREAKING CHANGE: also footer"
    assert default_strategy.decide(_commit(msg)) is Bump.MAJOR


def test_returns_major_when_footer_present_on_unrecognized_type(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    msg: typing.Final = "chore: bump deps\n\nBREAKING CHANGE: api surface changed"
    assert default_strategy.decide(_commit(msg)) is Bump.MAJOR


def test_declines_when_type_is_unrecognized_and_no_breaking_signal(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    assert default_strategy.decide(_commit("chore: bump deps")) == _NO_BUMPING_TYPE


@pytest.mark.parametrize(
    "message",
    [
        "docs: clarify",
        "refactor: rename",
        "test: add cases",
        "build: bump",
        "ci: tweak",
        "style: format",
        "revert: previous change",
    ],
)
def test_declines_for_unrecognized_types(
    default_strategy: ConventionalCommitsStrategy,
    message: str,
) -> None:
    assert default_strategy.decide(_commit(message)) == _NO_BUMPING_TYPE


def test_declines_when_subject_has_no_cc_header(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    assert default_strategy.decide(_commit("Fixed thing")) == _NOT_CONFORMING


def test_returns_minor_when_bang_appears_in_description_not_before_colon(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    assert default_strategy.decide(_commit("feat: emphasis!")) is Bump.MINOR


def test_returns_minor_when_breaking_change_phrase_is_mid_body_not_a_footer(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    msg: typing.Final = "feat: new thing\n\nNote: this is a BREAKING CHANGE: warning in prose"
    assert default_strategy.decide(_commit(msg)) is Bump.MINOR


def test_declines_when_type_is_uppercase(default_strategy: ConventionalCommitsStrategy) -> None:
    assert default_strategy.decide(_commit("FEAT: shouting")) == _NOT_CONFORMING


def test_returns_minor_when_breaking_change_footer_is_lowercase(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    msg: typing.Final = "feat: thing\n\nbreaking change: lowercase footer is not recognized"
    assert default_strategy.decide(_commit(msg)) is Bump.MINOR


def test_declines_when_message_is_empty(default_strategy: ConventionalCommitsStrategy) -> None:
    assert default_strategy.decide(_commit("")) == _NOT_CONFORMING


def test_declines_when_message_is_whitespace_only(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    assert default_strategy.decide(_commit("   \n\n   \n")) == _NOT_CONFORMING


def test_returns_major_when_crlf_line_endings_used(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    msg: typing.Final = "feat: x\r\n\r\nBREAKING CHANGE: y\r\n"
    assert default_strategy.decide(_commit(msg)) is Bump.MAJOR


def test_returns_minor_or_patch_when_custom_config_extends_type_lists() -> None:
    config: typing.Final = ConventionalCommitsConfig(
        minor_types=("feat", "feature"),
        patch_types=("fix", "patch"),
    )
    strategy: typing.Final = ConventionalCommitsStrategy(config=config)
    assert strategy.decide(_commit("feature: alt minor alias")) is Bump.MINOR
    assert strategy.decide(_commit("patch: alt patch alias")) is Bump.PATCH


def test_has_expected_class_var_name_and_satisfies_protocol_shape(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    assert ConventionalCommitsStrategy.name == "conventional-commits"
    assert default_strategy.name == "conventional-commits"
    assert callable(default_strategy.decide)


def test_declines_when_subject_has_leading_whitespace(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    assert default_strategy.decide(_commit("  feat: foo")) == _NOT_CONFORMING


def test_declines_when_space_appears_before_colon(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    assert default_strategy.decide(_commit("feat : foo")) == _NOT_CONFORMING


@pytest.mark.parametrize(
    "message",
    [
        "feat: x\n\n\tBREAKING CHANGE: tab-indented footer",
        "feat: x\n\n    BREAKING CHANGE: space-indented footer",
        "feat: x\n\n  BREAKING-CHANGE: hyphen variant indented",
    ],
)
def test_returns_major_when_breaking_change_footer_is_indented(
    default_strategy: ConventionalCommitsStrategy,
    message: str,
) -> None:
    assert default_strategy.decide(_commit(message)) is Bump.MAJOR


def test_returns_major_when_breaking_change_footer_follows_subject_without_blank_line(
    default_strategy: ConventionalCommitsStrategy,
) -> None:
    msg: typing.Final = "feat: x\nBREAKING CHANGE: no separator"
    assert default_strategy.decide(_commit(msg)) is Bump.MAJOR


@pytest.mark.parametrize("bad_type", ["Feat", "feat-x", "feat2", "", "feat ", " feat"])
def test_config_rejects_type_spellings_not_matching_regex(bad_type: str) -> None:
    with pytest.raises(pydantic.ValidationError, match="must match"):
        ConventionalCommitsConfig(minor_types=(bad_type,))


def test_config_accepts_only_lowercase_letter_types() -> None:
    config: typing.Final = ConventionalCommitsConfig(
        minor_types=("feat", "feature", "doc"),
        patch_types=("fix", "perf", "hotfix"),
    )
    assert "feature" in config.minor_types
    assert "hotfix" in config.patch_types


def test_declines_merge_commit_subject_as_not_conforming(default_strategy: ConventionalCommitsStrategy) -> None:
    assert default_strategy.decide(_commit("Merge branch 'feature/x' into main")) == _NOT_CONFORMING


def test_declines_scoped_non_bumping_type_as_no_bumping_type(default_strategy: ConventionalCommitsStrategy) -> None:
    assert default_strategy.decide(_commit("chore(deps): bump uv")) == _NO_BUMPING_TYPE

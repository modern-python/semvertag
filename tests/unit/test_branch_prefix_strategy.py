import typing

import pydantic
import pytest

from semvertag._types import Bump, Commit
from semvertag.strategies._base import BumpStrategy
from semvertag.strategies.branch_prefix import BranchPrefixConfig, BranchPrefixStrategy


DEFAULT_STRATEGY: typing.Final = BranchPrefixStrategy(config=BranchPrefixConfig())
COMMIT_SHA: typing.Final = "0" * 40


def _commit(message: str) -> Commit:
    return Commit(sha=COMMIT_SHA, message=message)


_NON_MERGE_CASES: typing.Final = [
    ("feat: ship the new login", Bump.NONE),
    ("docs: update README", Bump.NONE),
    ("", Bump.NONE),
    ("merge branch 'feature/x' into main", Bump.NONE),
]


@pytest.mark.parametrize(("message", "expected"), _NON_MERGE_CASES)
def test_returns_none_when_message_is_not_a_merge_commit(message: str, expected: Bump) -> None:
    assert DEFAULT_STRATEGY.decide(_commit(message)) is expected


_MINOR_CASES: typing.Final = [
    ("Merge branch 'feature/new-thing' into main", Bump.MINOR),
    ("Merge branch 'feature/' into main", Bump.MINOR),
    ("Merge branch 'feature/x-123' into develop", Bump.MINOR),
]


@pytest.mark.parametrize(("message", "expected"), _MINOR_CASES)
def test_returns_minor_when_message_contains_feature_prefix(message: str, expected: Bump) -> None:
    assert DEFAULT_STRATEGY.decide(_commit(message)) is expected


_PATCH_CASES: typing.Final = [
    ("Merge branch 'bugfix/x' into main", Bump.PATCH),
    ("Merge branch 'hotfix/cve-2025' into main", Bump.PATCH),
    ("Merge branch 'bugfix/x' and 'hotfix/y' into main", Bump.PATCH),
]


@pytest.mark.parametrize(("message", "expected"), _PATCH_CASES)
def test_returns_patch_when_message_contains_bugfix_or_hotfix_prefix(message: str, expected: Bump) -> None:
    assert DEFAULT_STRATEGY.decide(_commit(message)) is expected


def test_returns_minor_when_message_contains_both_feature_and_bugfix_prefixes() -> None:
    message: typing.Final = "Merge branch 'feature/x' into release; cherry-picked from bugfix/y"
    assert DEFAULT_STRATEGY.decide(_commit(message)) is Bump.MINOR


_UNRECOGNIZED_MERGE_CASES: typing.Final = [
    ("Merge branch 'release/2.0' into main", Bump.NONE),
    ("Merge branch 'chore/cleanup' into main", Bump.NONE),
    ("Merge branch 'develop' into main", Bump.NONE),
]


@pytest.mark.parametrize(("message", "expected"), _UNRECOGNIZED_MERGE_CASES)
def test_returns_none_when_merge_message_has_no_recognized_prefix(message: str, expected: Bump) -> None:
    assert DEFAULT_STRATEGY.decide(_commit(message)) is expected


_ALL_CASES: typing.Final = _NON_MERGE_CASES + _MINOR_CASES + _PATCH_CASES + _UNRECOGNIZED_MERGE_CASES


def test_never_returns_major_across_all_default_inputs() -> None:
    observed: typing.Final = {DEFAULT_STRATEGY.decide(_commit(message)) for message, _ in _ALL_CASES}
    assert Bump.MAJOR not in observed


def test_branch_prefix_strategy_exposes_every_member_required_by_bump_strategy_protocol() -> None:
    required: typing.Final = ("name", "decide")
    for member in required:
        assert hasattr(BranchPrefixStrategy, member), f"missing protocol member: {member}"
    assert BumpStrategy.__name__ == "BumpStrategy"


def test_honors_custom_minor_prefix_when_config_overrides_default() -> None:
    custom: typing.Final = BranchPrefixStrategy(
        config=BranchPrefixConfig(
            minor=("feat/",),
            patch=("fix/",),
            merge_mark_texts=("Auto-merge:",),
        ),
    )
    assert custom.decide(_commit("Auto-merge: feat/new-thing")) is Bump.MINOR
    assert custom.decide(_commit("Auto-merge: fix/bug-123")) is Bump.PATCH
    assert custom.decide(_commit("Auto-merge: feature/x")) is Bump.NONE
    assert custom.decide(_commit("Merge branch 'feat/x' into main")) is Bump.NONE


def test_recognizes_github_pr_merge_subject_under_defaults() -> None:
    default: typing.Final = BranchPrefixStrategy(config=BranchPrefixConfig())
    assert default.decide(_commit("Merge pull request #42 from org/feature/new-thing")) is Bump.MINOR
    assert default.decide(_commit("Merge pull request #43 from org/bugfix/bug-123")) is Bump.PATCH
    assert default.decide(_commit("Merge pull request #44 from org/hotfix/urgent")) is Bump.PATCH
    assert default.decide(_commit("Merge pull request #45 from org/chore/cleanup")) is Bump.NONE


def test_recognizes_gitlab_merge_branch_subject_under_defaults() -> None:
    default: typing.Final = BranchPrefixStrategy(config=BranchPrefixConfig())
    assert default.decide(_commit("Merge branch 'feature/new-thing' into main")) is Bump.MINOR
    assert default.decide(_commit("Merge branch 'bugfix/bug-123' into main")) is Bump.PATCH


_INVALID_CONFIG_CASES: typing.Final = [
    {"minor": ()},
    {"patch": ()},
    {"merge_mark_texts": ()},
    {"merge_mark_texts": ("",)},
    {"minor": ("",)},
    {"patch": ("",)},
    {"minor": ("feature/", "")},
]


@pytest.mark.parametrize("invalid_kwargs", _INVALID_CONFIG_CASES)
def test_raises_validation_error_when_config_field_is_empty(invalid_kwargs: dict[str, typing.Any]) -> None:
    with pytest.raises(pydantic.ValidationError):
        BranchPrefixConfig(**invalid_kwargs)


def test_ignores_body_lines_when_subject_is_not_a_merge() -> None:
    message: typing.Final = "feat: build pipeline\n\nReviewed-by: alice\nfeature/x mentioned in body"
    assert DEFAULT_STRATEGY.decide(_commit(message)) is Bump.NONE


def test_ignores_body_prefixes_when_subject_is_an_unrecognized_merge() -> None:
    message: typing.Final = "Merge branch 'release/2.0' into main\nfeature/foo touched in body\nbugfix/y also mentioned"
    assert DEFAULT_STRATEGY.decide(_commit(message)) is Bump.NONE


def test_returns_minor_when_subject_is_a_feature_merge_with_trailing_body() -> None:
    message: typing.Final = "Merge branch 'feature/new-thing' into main\n\nReviewed-by: bob"
    assert DEFAULT_STRATEGY.decide(_commit(message)) is Bump.MINOR


_FALLBACK_STRATEGY: typing.Final = BranchPrefixStrategy(
    config=BranchPrefixConfig(patch_on_non_merge_commit=True),
)


@pytest.mark.parametrize("message", [message for message, _ in _NON_MERGE_CASES])
def test_returns_patch_for_non_merge_commit_when_flag_enabled(message: str) -> None:
    assert _FALLBACK_STRATEGY.decide(_commit(message)) is Bump.PATCH


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Merge branch 'feature/x' into main", Bump.MINOR),
        ("Merge branch 'bugfix/y' into main", Bump.PATCH),
    ],
)
def test_flag_leaves_recognized_merge_paths_unchanged(message: str, expected: Bump) -> None:
    assert _FALLBACK_STRATEGY.decide(_commit(message)) is expected


@pytest.mark.parametrize("message", [message for message, _ in _UNRECOGNIZED_MERGE_CASES])
def test_flag_leaves_unrecognized_merge_as_none(message: str) -> None:
    assert _FALLBACK_STRATEGY.decide(_commit(message)) is Bump.NONE


def test_patch_on_non_merge_commit_defaults_to_false() -> None:
    assert BranchPrefixConfig().patch_on_non_merge_commit is False

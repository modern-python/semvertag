import typing

from semvertag._outcome import (
    _ALREADY_TAGGED_REASON,
    _NO_TAGS_REASON,
    AlreadyTagged,
    Created,
    DryRun,
    NoBump,
    NoTags,
    to_run_result,
)
from semvertag._types import Bump, RunResult


_STRATEGY: typing.Final = "branch-prefix"
_COMMIT: typing.Final = "abc1234def"


def test_created_maps_to_created_wire_result() -> None:
    result: typing.Final = to_run_result(Created(tag="0.4.0", bump=Bump.MINOR, commit=_COMMIT), strategy=_STRATEGY)
    assert result == RunResult(
        strategy=_STRATEGY, bump="minor", status="created", tag="0.4.0", commit=_COMMIT, reason=None
    )


def test_dry_run_maps_to_dry_run_wire_result() -> None:
    result: typing.Final = to_run_result(DryRun(tag="1.0.0", bump=Bump.MAJOR, commit=_COMMIT), strategy=_STRATEGY)
    assert result == RunResult(
        strategy=_STRATEGY, bump="major", status="dry_run", tag="1.0.0", commit=_COMMIT, reason=None
    )


def test_no_tags_maps_with_none_bump_and_fixed_reason() -> None:
    result: typing.Final = to_run_result(NoTags(commit=_COMMIT), strategy=_STRATEGY)
    assert result == RunResult(
        strategy=_STRATEGY, bump="none", status="no_tags", tag=None, commit=_COMMIT, reason=_NO_TAGS_REASON
    )


def test_already_tagged_maps_with_tag_and_fixed_reason() -> None:
    result: typing.Final = to_run_result(AlreadyTagged(tag="0.3.1", commit=_COMMIT), strategy=_STRATEGY)
    assert result == RunResult(
        strategy=_STRATEGY,
        bump="none",
        status="already_tagged",
        tag="0.3.1",
        commit=_COMMIT,
        reason=_ALREADY_TAGGED_REASON,
    )


def test_no_bump_passes_strategy_status_and_reason_through() -> None:
    outcome: typing.Final = NoBump(
        status="no_merge_commit", reason="Latest commit is not a merge commit.", commit=_COMMIT
    )
    result: typing.Final = to_run_result(outcome, strategy="conventional-commits")
    assert result == RunResult(
        strategy="conventional-commits",
        bump="none",
        status="no_merge_commit",
        tag=None,
        commit=_COMMIT,
        reason="Latest commit is not a merge commit.",
    )


def test_schema_version_is_preserved_on_the_wire() -> None:
    result: typing.Final = to_run_result(NoTags(commit=_COMMIT), strategy=_STRATEGY)
    assert result.schema_version == "1.0"

import dataclasses
import typing

import pytest

from semvertag._outcome import AlreadyTagged, Created, DryRun, NoBump, NoTags, Outcome
from semvertag._types import Bump, CheckResult, Commit, Tag
from semvertag._use_case import SemvertagUseCase


_MERGE_MESSAGE: typing.Final = "Merge branch 'feature/foo' into main"
_NON_MERGE_MESSAGE: typing.Final = "Fix typo in README"
_LATEST_SHA: typing.Final = "abc1234"
_PRIOR_SHA: typing.Final = "0000000"
_LATEST_TAG_NAME: typing.Final = "1.4.2"
_EXPECTED_NEW_TAG: typing.Final = "1.5.0"
_BRANCH_PREFIX_STRATEGY: typing.Final = "branch-prefix"
_CONVENTIONAL_STRATEGY: typing.Final = "conventional-commits"
_NO_BUMP_STATUS_BY_STRATEGY: typing.Final = {
    _BRANCH_PREFIX_STRATEGY: "no_merge_commit",
    _CONVENTIONAL_STRATEGY: "no_conforming_commit",
}
_NO_BUMP_REASON_BY_STRATEGY: typing.Final = {
    _BRANCH_PREFIX_STRATEGY: "Latest commit on default branch is not a merge commit.",
    _CONVENTIONAL_STRATEGY: "No conforming Conventional Commits type found in commit message.",
}


@dataclasses.dataclass(slots=True, kw_only=True)
class _RecordingOutput:
    progress_messages: list[str] = dataclasses.field(default_factory=list)
    emitted: list[tuple[Outcome, str]] = dataclasses.field(default_factory=list)
    error_messages: list[str] = dataclasses.field(default_factory=list)

    def progress(self, message: str) -> None:
        self.progress_messages.append(message)

    def emit(self, outcome: Outcome, *, strategy: str) -> None:
        self.emitted.append((outcome, strategy))

    def error(self, message: str) -> None:
        self.error_messages.append(message)


@dataclasses.dataclass(slots=True, kw_only=True)
class _StubProvider:
    name: str = "stub"
    commit: Commit
    tags: list[Tag]
    create_tag_calls: list[tuple[str, str]] = dataclasses.field(default_factory=list)

    def get_default_branch(self) -> str:
        return "main"

    def get_latest_commit_on_default_branch(self) -> Commit:
        return self.commit

    def list_tags(self) -> list[Tag]:
        return self.tags

    def create_tag(self, name: str, commit_sha: str) -> None:
        self.create_tag_calls.append((name, commit_sha))

    def check_token(self) -> CheckResult:  # pragma: no cover
        return CheckResult(name="token", status="passed", cause="stub")

    def check_scopes(self) -> CheckResult:  # pragma: no cover
        return CheckResult(name="scopes", status="passed", cause="stub")

    def check_project_access(self) -> CheckResult:  # pragma: no cover
        return CheckResult(name="project_access", status="passed", cause="stub")

    def check_protected_tags(self) -> CheckResult:  # pragma: no cover
        return CheckResult(name="protected_tags", status="passed", cause="stub")


@dataclasses.dataclass(slots=True, kw_only=True)
class _StubStrategy:
    name: str
    no_bump_status: str = "no_merge_commit"
    no_bump_reason: str = "Latest commit on default branch is not a merge commit."
    bump_to_return: Bump

    def decide(self, commit: Commit) -> Bump:  # noqa: ARG002
        return self.bump_to_return


def _make_use_case(
    *,
    commit_message: str = _MERGE_MESSAGE,
    commit_sha: str = _LATEST_SHA,
    tags: list[Tag] | None = None,
    bump: Bump = Bump.MINOR,
    strategy_name: str = _BRANCH_PREFIX_STRATEGY,
) -> tuple[SemvertagUseCase, _StubProvider, _RecordingOutput]:
    provider: typing.Final = _StubProvider(
        commit=Commit(sha=commit_sha, message=commit_message),
        tags=tags if tags is not None else [Tag(name=_LATEST_TAG_NAME, commit_sha=_PRIOR_SHA)],
    )
    strategy: typing.Final = _StubStrategy(
        name=strategy_name,
        no_bump_status=_NO_BUMP_STATUS_BY_STRATEGY[strategy_name],
        no_bump_reason=_NO_BUMP_REASON_BY_STRATEGY[strategy_name],
        bump_to_return=bump,
    )
    output: typing.Final = _RecordingOutput()
    use_case: typing.Final = SemvertagUseCase(
        provider=typing.cast("typing.Any", provider),
        strategy=typing.cast("typing.Any", strategy),
    )
    return use_case, provider, output


def test_creates_tag_with_minor_bump_when_feature_merge_against_prior_semver_tag() -> None:
    use_case, provider, output = _make_use_case()

    result: typing.Final = use_case(output=output)

    assert isinstance(result, Created)
    assert result.tag == _EXPECTED_NEW_TAG
    assert result.bump is Bump.MINOR
    assert result.commit == _LATEST_SHA
    assert provider.create_tag_calls == [(_EXPECTED_NEW_TAG, _LATEST_SHA)]
    assert output.emitted == [(result, _BRANCH_PREFIX_STRATEGY)]


def test_skips_with_already_tagged_when_latest_commit_sha_matches_a_tag() -> None:
    use_case, provider, output = _make_use_case(
        tags=[Tag(name=_LATEST_TAG_NAME, commit_sha=_LATEST_SHA)],
    )

    result: typing.Final = use_case(output=output)

    assert isinstance(result, AlreadyTagged)
    assert result.tag == _LATEST_TAG_NAME
    assert result.commit == _LATEST_SHA
    assert provider.create_tag_calls == []


def test_skips_with_no_merge_commit_under_branch_prefix_when_bump_is_none() -> None:
    use_case, provider, output = _make_use_case(
        commit_message=_NON_MERGE_MESSAGE,
        bump=Bump.NONE,
    )

    result: typing.Final = use_case(output=output)

    assert isinstance(result, NoBump)
    assert result.status == "no_merge_commit"
    assert result.reason
    assert provider.create_tag_calls == []


def test_skips_with_no_conforming_commit_under_conventional_commits_when_bump_is_none() -> None:
    use_case, _provider, output = _make_use_case(
        commit_message="random text",
        bump=Bump.NONE,
        strategy_name=_CONVENTIONAL_STRATEGY,
    )

    result: typing.Final = use_case(output=output)

    assert isinstance(result, NoBump)
    assert result.status == "no_conforming_commit"
    assert output.emitted == [(result, _CONVENTIONAL_STRATEGY)]


def test_skips_with_no_tags_when_no_semver_conforming_tags_exist() -> None:
    use_case, provider, output = _make_use_case(tags=[])

    result: typing.Final = use_case(output=output)

    assert isinstance(result, NoTags)
    assert result.commit == _LATEST_SHA
    assert provider.create_tag_calls == []


def test_skips_with_no_tags_when_only_non_semver_tags_exist() -> None:
    use_case, _provider, output = _make_use_case(
        tags=[
            Tag(name="release-2024-Q1", commit_sha="aaa"),
            Tag(name="latest", commit_sha="bbb"),
        ],
    )

    result: typing.Final = use_case(output=output)

    assert isinstance(result, NoTags)


def test_picks_highest_semver_tag_not_first_in_list_when_computing_bump() -> None:
    use_case, provider, output = _make_use_case(
        tags=[
            Tag(name="0.5.0", commit_sha="x"),
            Tag(name="2.0.0", commit_sha=_PRIOR_SHA),
            Tag(name="1.9.0", commit_sha="y"),
        ],
        bump=Bump.PATCH,
    )

    result: typing.Final = use_case(output=output)

    assert isinstance(result, Created)
    assert result.tag == "2.0.1"
    assert provider.create_tag_calls == [("2.0.1", _LATEST_SHA)]


@pytest.mark.parametrize(
    ("bump", "expected_tag"),
    [
        (Bump.MAJOR, "2.0.0"),
        (Bump.MINOR, "1.5.0"),
        (Bump.PATCH, "1.4.3"),
    ],
)
def test_bump_arithmetic_dispatches_to_semver_bump_kind(bump: Bump, expected_tag: str) -> None:
    use_case, _provider, output = _make_use_case(bump=bump)
    result: typing.Final = use_case(output=output)
    assert isinstance(result, Created)
    assert result.tag == expected_tag
    assert result.bump is bump


def test_progress_messages_fire_before_each_phase() -> None:
    _use_case, _provider, output = _make_use_case()
    _use_case(output=output)
    assert any("Detected strategy" in msg for msg in output.progress_messages)
    assert any("Fetching" in msg for msg in output.progress_messages)
    assert any("Computing bump" in msg for msg in output.progress_messages)
    assert any("Creating tag" in msg for msg in output.progress_messages)


def test_dry_run_skips_create_tag_and_emits_dry_run_status() -> None:
    use_case, provider, output = _make_use_case()

    result: typing.Final = use_case(output=output, dry_run=True)

    assert isinstance(result, DryRun)
    assert result.tag == _EXPECTED_NEW_TAG
    assert result.bump is Bump.MINOR
    assert result.commit == _LATEST_SHA
    assert provider.create_tag_calls == []
    assert output.emitted == [(result, _BRANCH_PREFIX_STRATEGY)]


def test_dry_run_does_not_emit_creating_tag_progress() -> None:
    use_case, _provider, output = _make_use_case()

    use_case(output=output, dry_run=True)

    assert not any("Creating tag" in msg for msg in output.progress_messages)


def test_dry_run_does_not_affect_already_tagged_path() -> None:
    use_case, provider, output = _make_use_case(
        tags=[Tag(name=_LATEST_TAG_NAME, commit_sha=_LATEST_SHA)],
    )

    result: typing.Final = use_case(output=output, dry_run=True)

    assert isinstance(result, AlreadyTagged)
    assert provider.create_tag_calls == []


def test_dry_run_does_not_affect_no_tags_path() -> None:
    use_case, provider, output = _make_use_case(tags=[])

    result: typing.Final = use_case(output=output, dry_run=True)

    assert isinstance(result, NoTags)
    assert provider.create_tag_calls == []


def test_dry_run_does_not_affect_strategy_no_bump_path() -> None:
    use_case, provider, output = _make_use_case(
        commit_message=_NON_MERGE_MESSAGE,
        bump=Bump.NONE,
    )

    result: typing.Final = use_case(output=output, dry_run=True)

    assert isinstance(result, NoBump)
    assert result.status == "no_merge_commit"
    assert provider.create_tag_calls == []


def test_dry_run_false_default_creates_tag() -> None:
    use_case, provider, output = _make_use_case()

    result: typing.Final = use_case(output=output)

    assert isinstance(result, Created)
    assert provider.create_tag_calls == [(_EXPECTED_NEW_TAG, _LATEST_SHA)]

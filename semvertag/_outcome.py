import dataclasses
import typing

from semvertag._types import Bump, RunResult


# These are the JSON wire reasons. The human terminal path (_output._format_outcome)
# words NoTags/AlreadyTagged differently on purpose — edit both if you change the
# message for one audience.
_NO_TAGS_REASON: typing.Final = "No prior semver-conforming tags found; not seeding an initial tag in v1.0."
_ALREADY_TAGGED_REASON: typing.Final = "Latest commit already tagged."


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Created:
    """A new tag was pushed."""

    tag: str
    bump: Bump
    commit: str


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class DryRun:
    """A tag would have been pushed; --dry-run short-circuited the create."""

    tag: str
    bump: Bump
    commit: str


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class NoTags:
    """No prior semver tag to bump from; v1.0 does not seed one."""

    commit: str


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class AlreadyTagged:
    """The head commit already carries the latest tag."""

    tag: str
    commit: str


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class NoBump:
    """The strategy declined to bump; status/reason are the strategy's own."""

    status: str
    reason: str
    commit: str


Outcome: typing.TypeAlias = Created | DryRun | NoTags | AlreadyTagged | NoBump


def to_run_result(outcome: Outcome, *, strategy: str) -> RunResult:
    """Project a closed Outcome onto the JSON wire DTO.

    The single place the four fixed wire status tokens and the fixed reasons
    live; NoBump passes the strategy's own status/reason through. The
    no-bump-ish variants map to ``bump="none"``. The final ``assert_never`` arm
    makes a newly-added variant a ty error here until it is handled.
    """
    match outcome:
        case Created(tag=tag, bump=bump, commit=commit):
            return RunResult(strategy=strategy, bump=bump.value, status="created", tag=tag, commit=commit, reason=None)
        case DryRun(tag=tag, bump=bump, commit=commit):
            return RunResult(strategy=strategy, bump=bump.value, status="dry_run", tag=tag, commit=commit, reason=None)
        case NoTags(commit=commit):
            return RunResult(
                strategy=strategy,
                bump=Bump.NONE.value,
                status="no_tags",
                tag=None,
                commit=commit,
                reason=_NO_TAGS_REASON,
            )
        case AlreadyTagged(tag=tag, commit=commit):
            return RunResult(
                strategy=strategy,
                bump=Bump.NONE.value,
                status="already_tagged",
                tag=tag,
                commit=commit,
                reason=_ALREADY_TAGGED_REASON,
            )
        case NoBump(status=status, reason=reason, commit=commit):
            return RunResult(
                strategy=strategy, bump=Bump.NONE.value, status=status, tag=None, commit=commit, reason=reason
            )
        case _:  # pragma: no cover
            typing.assert_never(outcome)

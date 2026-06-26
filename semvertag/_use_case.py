import dataclasses
import typing

import semver

from semvertag._outcome import AlreadyTagged, Created, DryRun, NoBump, NoTags, Outcome
from semvertag._output import Output
from semvertag._types import Bump, Tag
from semvertag.providers._base import Provider
from semvertag.strategies._base import BumpStrategy


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class SemvertagUseCase:
    provider: Provider
    strategy: BumpStrategy

    def __call__(self, *, output: Output, dry_run: bool = False) -> Outcome:
        output.progress(f"Detected strategy: {self.strategy.name}")
        output.progress("Fetching latest commit on default branch...")
        commit: typing.Final = self.provider.get_latest_commit_on_default_branch()

        output.progress("Fetching tag history...")
        tags: typing.Final = self.provider.list_tags()
        selected: typing.Final = _select_latest_semver_tag(tags)

        if selected is None:
            return self._emit(output, NoTags(commit=commit.sha))

        latest_tag, latest_version = selected
        if latest_tag.commit_sha == commit.sha:
            return self._emit(output, AlreadyTagged(tag=latest_tag.name, commit=commit.sha))

        output.progress("Computing bump...")
        bump: typing.Final = self.strategy.decide(commit)
        if bump is Bump.NONE:
            return self._emit(
                output,
                NoBump(status=self.strategy.no_bump_status, reason=self.strategy.no_bump_reason, commit=commit.sha),
            )

        new_version: typing.Final = _compute_new_version(latest_version, bump)
        if dry_run:
            return self._emit(output, DryRun(tag=new_version, bump=bump, commit=commit.sha))

        output.progress(f"Creating tag {new_version}...")
        self.provider.create_tag(name=new_version, commit_sha=commit.sha)
        return self._emit(output, Created(tag=new_version, bump=bump, commit=commit.sha))

    def _emit(self, output: Output, outcome: Outcome) -> Outcome:
        output.emit(outcome, strategy=self.strategy.name)
        return outcome


def _select_latest_semver_tag(tags: list[Tag]) -> tuple[Tag, semver.Version] | None:
    parsed: list[tuple[semver.Version, Tag]] = []
    for tag in tags:
        try:
            version = semver.Version.parse(tag.name).replace(build=None)
        except ValueError:
            continue
        parsed.append((version, tag))
    if not parsed:
        return None
    parsed.sort(key=lambda item: item[0])
    version, tag = parsed[-1]
    return tag, version


_BUMP_PARTS: typing.Final[dict[Bump, str]] = {
    Bump.MAJOR: "major",
    Bump.MINOR: "minor",
    Bump.PATCH: "patch",
}


def _compute_new_version(version: semver.Version, bump: Bump) -> str:
    return str(version.next_version(_BUMP_PARTS[bump]))

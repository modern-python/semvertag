import dataclasses
import re
import typing

import pydantic

from semvertag._commit_parse import body_lines, subject_line
from semvertag._types import Bump, Commit
from semvertag.strategies._base import Decline


_TYPE_PATTERN: typing.Final = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!?):")
_VALID_TYPE_RE: typing.Final = re.compile(r"^[a-z]+$")
_BREAKING_TOKENS: typing.Final = ("BREAKING CHANGE:", "BREAKING-CHANGE:")
_NOT_CONFORMING: typing.Final = Decline(
    status="no_conforming_commit", reason="Commit subject is not a Conventional Commit."
)
_NO_BUMPING_TYPE: typing.Final = Decline(status="no_bumping_type", reason="Commit type is not configured to bump.")


class ConventionalCommitsConfig(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    minor_types: tuple[str, ...] = ("feat",)
    patch_types: tuple[str, ...] = ("fix", "perf")

    @pydantic.field_validator("minor_types", "patch_types")
    @classmethod
    def _validate_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not _VALID_TYPE_RE.match(item):
                msg = f"Conventional Commits type {item!r} must match {_VALID_TYPE_RE.pattern}."
                raise ValueError(msg)
        return value


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class ConventionalCommitsStrategy:
    name: typing.ClassVar[str] = "conventional-commits"
    config: ConventionalCommitsConfig

    def decide(self, commit: Commit) -> Bump | Decline:
        subject: typing.Final = subject_line(commit.message)
        match: typing.Final = _TYPE_PATTERN.match(subject)
        if match is None:
            return _NOT_CONFORMING
        for line in body_lines(commit.message):
            stripped = line.lstrip()
            if any(stripped.startswith(token) for token in _BREAKING_TOKENS):
                return Bump.MAJOR
        if match["bang"] == "!":
            return Bump.MAJOR
        commit_type: typing.Final = match["type"]
        if commit_type in self.config.minor_types:
            return Bump.MINOR
        if commit_type in self.config.patch_types:
            return Bump.PATCH
        return _NO_BUMPING_TYPE

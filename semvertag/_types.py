import dataclasses
import enum


class Bump(enum.Enum):
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class RunResult:
    schema_version: str = "1.0"
    strategy: str
    bump: str
    status: str
    tag: str | None
    commit: str | None
    reason: str | None


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Commit:
    sha: str
    message: str


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Tag:
    name: str
    commit_sha: str

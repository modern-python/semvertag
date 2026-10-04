import dataclasses
import typing

from semvertag._types import Bump, Commit


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Decline:
    status: str
    reason: str


class BumpStrategy(typing.Protocol):
    @property
    def name(self) -> str: ...

    def decide(self, commit: Commit) -> Bump | Decline: ...

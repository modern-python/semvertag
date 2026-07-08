import typing

from semvertag._types import Bump, Commit


class BumpStrategy(typing.Protocol):
    @property
    def name(self) -> str: ...
    @property
    def no_bump_status(self) -> str: ...
    @property
    def no_bump_reason(self) -> str: ...

    def decide(self, commit: Commit) -> Bump: ...

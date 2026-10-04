import dataclasses
import typing

import pydantic

from semvertag._commit_parse import subject_line
from semvertag._types import Bump, Commit
from semvertag.strategies._base import Decline


_NOT_A_MERGE_COMMIT: typing.Final = Decline(
    status="no_merge_commit", reason="Latest commit on default branch is not a merge commit."
)
_UNMAPPED_BRANCH_PREFIX: typing.Final = Decline(
    status="unmapped_branch_prefix", reason="Merge commit's source branch has no configured prefix."
)
_NonEmptyStr: typing.TypeAlias = typing.Annotated[str, pydantic.Field(min_length=1)]


class BranchPrefixConfig(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    minor: tuple[_NonEmptyStr, ...] = pydantic.Field(default=("feature/",), min_length=1)
    patch: tuple[_NonEmptyStr, ...] = pydantic.Field(default=("bugfix/", "hotfix/"), min_length=1)
    merge_mark_texts: tuple[_NonEmptyStr, ...] = pydantic.Field(
        default=("Merge branch", "Merge pull request"),
        min_length=1,
    )
    patch_on_non_merge_commit: bool = False


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class BranchPrefixStrategy:
    name: typing.ClassVar[str] = "branch-prefix"
    config: BranchPrefixConfig

    def decide(self, commit: Commit) -> Bump | Decline:
        subject: typing.Final = subject_line(commit.message)
        if not any(mark in subject for mark in self.config.merge_mark_texts):
            return Bump.PATCH if self.config.patch_on_non_merge_commit else _NOT_A_MERGE_COMMIT
        if any(prefix in subject for prefix in self.config.minor):
            return Bump.MINOR
        if any(prefix in subject for prefix in self.config.patch):
            return Bump.PATCH
        return _UNMAPPED_BRANCH_PREFIX

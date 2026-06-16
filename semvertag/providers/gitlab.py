import dataclasses
import typing

import httpware
import pydantic

from semvertag import _link_pagination
from semvertag._errors import ConfigError, ProviderAPIError
from semvertag._settings import GitLabConfig
from semvertag._types import Commit, Tag
from semvertag.providers import _errors


_API_PREFIX: typing.Final = "/api/v4/projects"
_TAGS_PER_PAGE: typing.Final = 100
_MAX_TAG_PAGES: typing.Final = 100


class _ProjectResponse(pydantic.BaseModel):
    default_branch: str | None


class _CommitItem(pydantic.BaseModel):
    id: str
    message: str


class _TagCommit(pydantic.BaseModel):
    id: str


class _TagItem(pydantic.BaseModel):
    name: str
    commit: _TagCommit


class _CommitList(pydantic.RootModel[list[_CommitItem]]):
    pass


class _TagList(pydantic.RootModel[list[_TagItem]]):
    pass


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class GitLabProvider:
    name: typing.ClassVar[str] = "gitlab"
    config: GitLabConfig
    project_id: int
    http: httpware.Client

    def get_default_branch(self) -> str:
        try:
            project = self.http.get(
                f"{_API_PREFIX}/{self.project_id}",
                response_model=_ProjectResponse,
            )
        except httpware.ClientError as exc:
            raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc
        if not project.default_branch:
            msg = "Default branch missing from GitLab response. Verify the project has a default branch configured."
            raise ConfigError(msg)
        return project.default_branch

    def get_latest_commit_on_default_branch(self) -> Commit:
        default_branch: typing.Final = self.get_default_branch()
        try:
            commits = self.http.get(
                f"{_API_PREFIX}/{self.project_id}/repository/commits",
                params={"ref_name": default_branch, "per_page": 1},
                response_model=_CommitList,
            )
        except httpware.ClientError as exc:
            raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc
        if not commits.root:
            msg = f"No commits on default branch '{default_branch}'. The branch appears empty."
            raise ProviderAPIError(msg)
        head = commits.root[0]
        return Commit(sha=head.id, message=head.message)

    def list_tags(self) -> list[Tag]:
        tags: list[Tag] = []
        url: str = f"{_API_PREFIX}/{self.project_id}/repository/tags"
        params: dict[str, typing.Any] | None = {"per_page": _TAGS_PER_PAGE, "page": 1}
        for _ in range(_MAX_TAG_PAGES):
            try:
                response, page = self.http.get_with_response(url, params=params, response_model=_TagList)
            except httpware.ClientError as exc:
                raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc
            tags.extend(Tag(name=item.name, commit_sha=item.commit.id) for item in page.root)
            next_url = _link_pagination.next_page_url(response, current_url=str(response.request.url))
            if next_url is None:
                return tags
            if not _link_pagination.same_origin(next_url, self.config.endpoint):
                msg = (
                    "GitLab pagination Link header points to a different host than SEMVERTAG_GITLAB__ENDPOINT. "
                    "Refusing to follow to protect credentials."
                )
                raise ProviderAPIError(msg)
            url, params = next_url, None
        msg = (
            f"Tag pagination exceeded {_MAX_TAG_PAGES} pages. "
            "The project has an unexpected number of tags; please file an issue."
        )
        raise ProviderAPIError(msg)

    def create_tag(self, name: str, commit_sha: str) -> None:
        try:
            self.http.send(
                self.http.build_request(
                    "POST",
                    f"{_API_PREFIX}/{self.project_id}/repository/tags",
                    json={"tag_name": name, "ref": commit_sha},
                )
            )
        except httpware.BadRequestError as exc:
            raise _errors.translate_create_tag_bad_request(exc, tag_name=name) from exc
        except httpware.ClientError as exc:
            raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc

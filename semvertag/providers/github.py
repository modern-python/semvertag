import dataclasses
import typing

import httpware
import pydantic

from semvertag import _link_pagination
from semvertag._errors import ConfigError, ProviderAPIError
from semvertag._settings import GitHubConfig
from semvertag._types import Commit, Tag
from semvertag.providers import _errors


_API_PREFIX: typing.Final = "/repos"
_TAGS_PER_PAGE: typing.Final = 100
_MAX_TAG_PAGES: typing.Final = 100


class _RepoResponse(pydantic.BaseModel):
    default_branch: str | None


class _CommitMeta(pydantic.BaseModel):
    message: str


class _CommitItem(pydantic.BaseModel):
    sha: str
    commit: _CommitMeta


class _TagCommit(pydantic.BaseModel):
    sha: str


class _TagItem(pydantic.BaseModel):
    name: str
    commit: _TagCommit


class _CommitList(pydantic.RootModel[list[_CommitItem]]):
    pass


class _TagList(pydantic.RootModel[list[_TagItem]]):
    pass


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class GitHubProvider:
    name: typing.ClassVar[str] = "github"
    config: GitHubConfig
    repo: str
    http: httpware.Client

    def get_default_branch(self) -> str:
        try:
            repo_info = self.http.get(
                f"{_API_PREFIX}/{self.repo}",
                response_model=_RepoResponse,
            )
        except httpware.ClientError as exc:
            raise _errors.translate_github(exc, repo=self.repo) from exc
        if not repo_info.default_branch:
            msg = "Default branch missing from GitHub response. Verify the repo has a default branch."
            raise ConfigError(msg)
        return repo_info.default_branch

    def get_latest_commit_on_default_branch(self) -> Commit:
        default_branch: typing.Final = self.get_default_branch()
        try:
            commits = self.http.get(
                f"{_API_PREFIX}/{self.repo}/commits",
                params={"sha": default_branch, "per_page": 1},
                response_model=_CommitList,
            )
        except httpware.ClientError as exc:
            raise _errors.translate_github(exc, repo=self.repo) from exc
        if not commits.root:
            msg = f"No commits on default branch '{default_branch}'. The branch appears empty."
            raise ProviderAPIError(msg)
        head = commits.root[0]
        return Commit(sha=head.sha, message=head.commit.message)

    def list_tags(self) -> list[Tag]:
        tags: list[Tag] = []
        url: str = f"{_API_PREFIX}/{self.repo}/tags"
        params: dict[str, typing.Any] | None = {"per_page": _TAGS_PER_PAGE, "page": 1}
        for _ in range(_MAX_TAG_PAGES):
            try:
                response, page = self.http.get_with_response(url, params=params, response_model=_TagList)
            except httpware.ClientError as exc:
                raise _errors.translate_github(exc, repo=self.repo) from exc
            tags.extend(Tag(name=item.name, commit_sha=item.commit.sha) for item in page.root)
            next_url = _link_pagination.next_page_url(response, current_url=str(response.request.url))
            if next_url is None:
                return tags
            if not _link_pagination.same_origin(next_url, self.config.endpoint):
                msg = (
                    "GitHub pagination Link header points to a different host than SEMVERTAG_GITHUB__ENDPOINT. "
                    "Refusing to follow to protect credentials."
                )
                raise ProviderAPIError(msg)
            url, params = next_url, None
        msg = (
            f"Tag pagination exceeded {_MAX_TAG_PAGES} pages. "
            "The repo has an unexpected number of tags; please file an issue."
        )
        raise ProviderAPIError(msg)

    def create_tag(self, name: str, commit_sha: str) -> None:
        try:
            self.http.send(
                self.http.build_request(
                    "POST",
                    f"{_API_PREFIX}/{self.repo}/git/refs",
                    json={"ref": f"refs/tags/{name}", "sha": commit_sha},
                )
            )
        except httpware.UnprocessableEntityError as exc:
            raise _errors.translate_create_tag_github_unprocessable(exc, tag_name=name) from exc
        except httpware.ClientError as exc:
            raise _errors.translate_github(exc, repo=self.repo) from exc

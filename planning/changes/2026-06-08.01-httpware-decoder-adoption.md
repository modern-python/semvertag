---
summary: "Adopt the httpware response decoder in the providers."
---

# httpware decoder adoption — design spec

**Date:** 2026-06-08
**Status:** Approved, ready for implementation planning
**Topic slug:** `httpware-decoder-adoption`
**Predecessor:** `2026-06-07-httpware-migration-design.md` (the initial port that left this gap)

## Goal

Close the loop on the httpware migration: switch `GitLabProvider`'s three GET methods to use httpware's `response_model=` / `send_with_response` decoder paths, delete the in-tree validator helpers that exist only because the prior migration bypassed the decoder, and add the missing `DecodeError → ProviderAPIError` branch to the error translator. After this lands, semvertag uses every httpware feature it depends on (`PydanticDecoder`) instead of pulling it in but routing around it.

## Background

The httpware migration (`2026-06-07-httpware-migration-design.md`, merged in `cdff5b9`) ported `GitLabProvider` from a hand-rolled `RetryingTransport` + `HttpClient` stack onto `httpware.Client` + `httpware.Retry`. During Task 3 of that work, the implementer noticed that httpware's decoder path leaked the underlying library's exception (`pydantic.ValidationError`) past the documented `except httpware.ClientError` contract, and chose to bypass the decoder entirely — all three GET methods landed on raw `client.send()` + module-local `_validate_*` helpers.

That bypass was a correct local call but a structural smell: semvertag installs `httpware[pydantic]` and never uses `PydanticDecoder`. Two upstream fixes shipped to make adoption possible:

- **httpware 0.8.1** added `httpware.DecodeError(ClientError)` and wrapped the decoder call in `Client.send` / `AsyncClient.send` with a `try / except Exception → raise DecodeError(...) from exc`. The seam's exception contract is now uniform — `except httpware.ClientError` catches decoder failures alongside transport and status failures.
- **httpware 0.8.2** added `client.send_with_response(request, *, response_model)` returning `tuple[httpx2.Response, T]`. This is what `list_tags` needs: it must read the `Link` header for pagination AND get the decoded body, which `send(..., response_model=T)` can't deliver (the typed path returns only `T`, not the response).

Both upstream pieces are in place. This spec covers the semvertag-side adoption.

## Non-goals

- No changes to httpware. That work shipped in 0.8.1 + 0.8.2.
- No changes to `ioc.py`, transport configuration, retry policy, or any production code outside `gitlab.py`, `_errors.py`, and the dependency declaration.
- No restructuring of the error tree, the `translate_gitlab` shape, or `create_tag`'s 400-body inspection.

## Target shape

```
semvertag/providers/
├── gitlab.py        ← 3 GETs adopt response_model= / send_with_response;
│                      6 validator helpers + 1 TypeVar deleted; 2 RootModel wrappers added
└── _errors.py       ← translate_gitlab gains a DecodeError → ProviderAPIError branch
pyproject.toml       ← httpware[pydantic] floored at >=0.8.2
```

## Constraint analysis: why partial-vs-full adoption is not a choice

The three GETs have different decoder fits:

| Method | Body shape | Needs response headers? | Decoder fit |
|---|---|---|---|
| `get_default_branch` | single object | no | `client.get(url, response_model=_ProjectResponse)` |
| `get_latest_commit_on_default_branch` | `list[_CommitItem]` | no | `client.get(url, response_model=_CommitList)` where `_CommitList = RootModel[list[_CommitItem]]` |
| `list_tags` | `list[_TagItem]` | **yes** (`Link` header for pagination) | `client.send_with_response(req, response_model=_TagList)` where `_TagList = RootModel[list[_TagItem]]` |

`RootModel[list[X]]` is necessary because `response_model: type[T]` expects an actual class — generic aliases like `list[_CommitItem]` are runtime-OK via `TypeAdapter` but trip `ty` static analysis. `RootModel` wraps the list in a real `BaseModel` subclass that satisfies `type[T]`, with the list reachable via `.root`.

`send_with_response` covers the pagination case without forcing every caller of `client.get` to unwrap a `DecodedResponse[T]` (a breaking change considered upstream and rejected as bad ROI for one consumer).

## Provider call-site shapes

```python
import httpware
import pydantic

from semvertag.providers import _errors


class _ProjectResponse(pydantic.BaseModel):
    default_branch: str | None


class _CommitItem(pydantic.BaseModel):
    id: str
    message: str


class _CommitList(pydantic.RootModel[list[_CommitItem]]):
    pass


class _TagCommit(pydantic.BaseModel):
    id: str


class _TagItem(pydantic.BaseModel):
    name: str
    commit: _TagCommit


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
            page = self.http.get(
                f"{_API_PREFIX}/{self.project_id}/repository/commits",
                params={"ref_name": default_branch, "per_page": 1},
                response_model=_CommitList,
            )
        except httpware.ClientError as exc:
            raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc
        if not page.root:
            msg = f"No commits on default branch '{default_branch}'. The branch appears empty."
            raise ProviderAPIError(msg)
        head = page.root[0]
        return Commit(sha=head.id, message=head.message)

    def list_tags(self) -> list[Tag]:
        tags: list[Tag] = []
        url: str = f"{_API_PREFIX}/{self.project_id}/repository/tags"
        params: dict[str, typing.Any] | None = {"per_page": _TAGS_PER_PAGE, "page": 1}
        for _ in range(_MAX_TAG_PAGES):
            try:
                response, page = self.http.send_with_response(
                    self.http.build_request("GET", url, params=params),
                    response_model=_TagList,
                )
            except httpware.ClientError as exc:
                raise _errors.translate_gitlab(exc, project_id=self.project_id) from exc
            tags.extend(Tag(name=item.name, commit_sha=item.commit.id) for item in page.root)
            next_url = _next_page_url(response, current_url=str(response.request.url))
            if next_url is None:
                return tags
            if not _same_origin(next_url, self.config.endpoint):
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
        # Unchanged from the prior migration. POST has no response body to decode;
        # the existing BadRequestError + ClientError catches still cover everything.
        ...
```

The pagination helpers (`_next_page_url`, `_parse_rel_values`, `_same_origin`, `_LINK_ENTRY_RE`) remain untouched.

## Translation module extension

`semvertag/providers/_errors.py` gains one isinstance branch in `_translate_gitlab_transport` (placed there because `DecodeError` is a non-`StatusError` `ClientError`, same as `TimeoutError`, `NetworkError`, `RetryBudgetExhaustedError`):

```python
if isinstance(exc, httpware.DecodeError):
    return ProviderAPIError(
        f"GitLab {exc.model.__name__} response could not be decoded: {exc.original}"
    )
```

Branch ordering: `DecodeError` should be checked **before** the generic `ClientError` fallback at the end of `_translate_gitlab_transport`, since `DecodeError` is a `ClientError` subclass and the fallback would otherwise swallow it with the less informative `f"GitLab request failed: {type(exc).__name__}"` message.

The message uses `exc.model.__name__` (e.g. `_ProjectResponse`, `_CommitList`, `_TagList`) and `exc.original` (the underlying `pydantic.ValidationError` or `pydantic`-level `JSONDecodeError`). Operators get "what we tried to decode" + "why it failed" without semvertag having to import pydantic to format the message.

## Helpers to delete

After the call-site swap, none of these are reachable from production code:

| Helper | Now reachable via |
|---|---|
| `_validate_obj(response, model, *, label)` | `PydanticDecoder.decode` (inside httpware) |
| `_validate_project_response(response)` | `response_model=_ProjectResponse` |
| `_validate_commit_list(response)` | `response_model=_CommitList` |
| `_validate_tag_list(response)` | `response_model=_TagList` (via `send_with_response`) |
| `_validate_list(response, model, *, label)` | `PydanticDecoder.decode` |
| `_TModel: typing.TypeVar(...)` | no remaining caller |

Net: ~31 lines deleted from `gitlab.py`, ~10 lines added (two `RootModel` wrappers + `.root` accesses). The `import pydantic` line stays (used for `BaseModel` and `RootModel`); `pydantic.ValidationError` and `httpx2.DecodingError` imports become unused and should drop too.

## Dependency floor

`pyproject.toml` — the dependency line moves from unpinned to a 0.8.2 floor:

```toml
dependencies = [
    ...
    "httpware[pydantic]>=0.8.2",
]
```

0.8.2 is required because:

- `httpware.DecodeError` lands in 0.8.1 (without it, the `except httpware.ClientError` in the new call sites would let `pydantic.ValidationError` escape, defeating the whole adoption)
- `client.send_with_response` lands in 0.8.2 (without it, `list_tags` can't get both the decoded list and the response headers from a single call)

Both are required for the design above; 0.8.2 covers both.

## Test impact

| Test file | Action |
|---|---|
| `tests/unit/test_providers_errors.py` | Add one test for the new `DecodeError → ProviderAPIError` branch (mirrors the existing `TimeoutError`/`NetworkError` tests; uses a synthetic `type(...)` for the model so the test file stays decoupled from `gitlab.py`'s internal models) |
| `tests/integration/test_gitlab_provider.py` | Update 2-4 assertions whose error messages shift from `"shape invalid: ..."` / `"malformed JSON"` (old `_validate_*` wording) to `"could not be decoded: ..."` (new `translate_gitlab` wording). Tests that pin exception **type** + status semantics need no change. |
| `tests/conftest.py`, `tests/integration/conftest.py` | No expected changes — fixtures already use `httpware.Client` and `httpx2.MockTransport`, both of which keep their current shape. |

Coverage stays at 100%. The deleted `_validate_*` branches don't need coverage anymore; the new call sites are covered by the existing integration tests (mock transport returns a payload → typed decode → assertion on `_ProjectResponse.default_branch` etc.).

## Test for the `DecodeError` translator branch

```python
def test_translate_gitlab_decode_error_becomes_provider_api_error() -> None:
    underlying = ValueError("input should be a valid dictionary")
    exc = httpware.DecodeError(
        response=_response(200, body=b"null"),
        model=type("FakeModel", (), {}),
        original=underlying,
    )
    result = translate_gitlab(exc, project_id=_PROJECT_ID)
    assert isinstance(result, ProviderAPIError)
    assert "FakeModel" in str(result)
    assert "valid dictionary" in str(result).lower()
```

The synthetic `type("FakeModel", (), {})` avoids importing `gitlab.py`'s internal models into the test file. The test file already has a `_response(...)` helper from the prior migration spec; it's reused here.

## Out of scope

- **GitHub / Bitbucket provider scaffolding.** The pattern this spec sets up (RootModel for list endpoints, `send_with_response` for pagination) is the right shape for future providers, but adding them is its own work item.
- **Streaming responses.** httpware's `client.stream(...)` exists and bypasses the middleware chain; not relevant to any current `GitLabProvider` method.
- **`create_tag` POST changes.** Stays raw `send()` because the body is `{"tag_name": ..., "ref": ...}` (request body) and the response body — when not a 400 with "already exists" — is a `Tag` object semvertag currently doesn't read. No reason to swap to `response_model=`.
- **Removing `httpx2` as a direct dep.** Tests still need `httpx2.MockTransport` and `httpx2.Request`; the dep stays.

## Open items for the implementation plan

These are plan-time decisions, not design-time:

1. **Exact pydantic `RootModel` import surface.** `pydantic.RootModel` has been stable since pydantic v2.0; the project's pydantic floor is already 2.x (transitive via `pydantic-settings`). Confirm by checking the lockfile during plan execution, but no surprises expected.
2. **Test assertion wording shifts.** Plan should grep `tests/integration/test_gitlab_provider.py` for the strings `"shape invalid"` and `"malformed JSON"` and list the exact test names that need their assertions updated. Currently estimated at 2-4 tests; the grep will give the exact count.
3. **Unused-import cleanup.** Once `_validate_*` helpers delete, `pydantic.ValidationError` and `httpx2.DecodingError` become unused. Ruff's `F401` will surface them; the plan should explicitly list them in the import-removal step so the implementer doesn't miss them.

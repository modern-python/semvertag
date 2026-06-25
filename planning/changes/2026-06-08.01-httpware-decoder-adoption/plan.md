# httpware decoder adoption — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch `GitLabProvider`'s three GET methods to use `httpware`'s `response_model=` / `send_with_response` decoder paths, extend `translate_gitlab` with a `DecodeError` branch, delete the six in-tree `_validate_*` helpers. After this lands, semvertag actually uses `PydanticDecoder` instead of installing it and routing around it.

**Architecture:** Two single-object GETs adopt `client.get(..., response_model=BaseModel)` directly. The list endpoints use `pydantic.RootModel[list[X]]` wrappers (because generic aliases trip `ty`); `get_latest_commit_on_default_branch` calls `client.get(..., response_model=_CommitList)` then reads `.root`, and `list_tags` calls `client.send_with_response(req, response_model=_TagList)` (needs the response back too for the `Link` header). `create_tag` is unchanged. `_errors.translate_gitlab` gains one `isinstance(exc, httpware.DecodeError)` branch.

**Tech Stack:** Python 3.11+, `httpware[pydantic]>=0.8.2`, `pydantic 2.13+` (RootModel), `httpx2`, `pytest`. Tests use `httpx2.MockTransport` injected via `httpware.Client(httpx2_client=...)`.

**Reference spec:** `planning/specs/2026-06-08-httpware-decoder-adoption-design.md`

---

## File structure

**Modify:**
- `pyproject.toml` — floor `httpware[pydantic]` at `>=0.8.2`.
- `semvertag/providers/_errors.py` — add `DecodeError` branch at the top of `_translate_gitlab_transport`.
- `semvertag/providers/gitlab.py` — add `_CommitList`, `_TagList` RootModel wrappers; rewrite the three GET methods to use decoder paths; delete `_validate_obj`, `_validate_project_response`, `_validate_commit_list`, `_validate_tag_list`, `_validate_list`, `_TModel`; drop unused `pydantic.ValidationError` + `httpx2.DecodingError` references.
- `tests/unit/test_providers_errors.py` — add one test for the new `DecodeError → ProviderAPIError` branch.
- `tests/integration/test_gitlab_provider.py` — update 9 `pytest.raises(..., match=...)` strings to match the new translated DecodeError wording.

**No new files. No deletions of whole files.**

After this lands, `gitlab.py` contains only domain types + RootModel wrappers + the four public provider methods + the pagination utilities (`_LINK_ENTRY_RE`, `_next_page_url`, `_parse_rel_values`, `_same_origin`). All generic JSON-validation plumbing is gone.

---

## Task 1: Bump httpware dependency to 0.8.2

**Files:**
- Modify: `pyproject.toml` (`dependencies` array, the `"httpware[pydantic]"` line)

- [ ] **Step 1: Edit `pyproject.toml`**

Find the dependencies block and change:

```toml
    "httpware[pydantic]",
```

to:

```toml
    "httpware[pydantic]>=0.8.2",
```

Leave the other entries (`typer`, `rich`, `semver`, `pydantic-settings`, `modern-di-typer`, `httpx2`) alone.

- [ ] **Step 2: Resolve the lockfile**

Run: `uv lock --upgrade-package httpware`
Expected: `Added httpware v0.8.2` (replacing the prior pin). No errors.

- [ ] **Step 3: Install**

Run: `just install`
Expected: completes without errors.

- [ ] **Step 4: Smoke-test the new symbols**

Run: `uv run python -c "import httpware; print(httpware.DecodeError, httpware.Client.send_with_response)"`
Expected: prints `<class 'httpware.errors.DecodeError'> <function Client.send_with_response at 0x...>`. No `AttributeError`.

- [ ] **Step 5: Full suite (baseline check)**

Run: `just test`
Expected: 332 tests pass, 100% coverage. The dep bump alone should not change behavior.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml
git commit -m "chore: floor httpware[pydantic] at >=0.8.2 (DecodeError, send_with_response)"
```

`uv.lock` is gitignored in this project; do not add it.

---

## Task 2: Extend `translate_gitlab` with `DecodeError` branch (TDD)

**Files:**
- Modify: `semvertag/providers/_errors.py`
- Modify: `tests/unit/test_providers_errors.py`

The translation extension is small (one new isinstance branch) but it gates the decoder adoption in Task 3 — without it, `httpware.DecodeError` would fall through to the generic `f"GitLab request failed: {type(exc).__name__}"` fallback with the less informative wording. We TDD it now so Task 3 can rely on it.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_providers_errors.py` (after the existing `test_translate_gitlab_network_error_becomes_provider_api_error` and friends):

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

The synthetic `type("FakeModel", (), {})` keeps the test decoupled from `gitlab.py`'s internal models. The `_response` helper already exists in this file from the prior migration.

- [ ] **Step 2: Run the test to verify it fails (no DecodeError branch yet)**

Run: `uv run pytest tests/unit/test_providers_errors.py::test_translate_gitlab_decode_error_becomes_provider_api_error -v`
Expected: FAIL. The assertion `"FakeModel" in str(result)` fails because the current code falls through to `f"GitLab request failed: {type(exc).__name__}"`, which produces `"GitLab request failed: DecodeError"` — no `FakeModel` substring.

- [ ] **Step 3: Add the `DecodeError` branch to `_translate_gitlab_transport`**

Edit `semvertag/providers/_errors.py`. Find `_translate_gitlab_transport`:

```python
def _translate_gitlab_transport(exc: httpware.ClientError) -> Exception:
    if isinstance(exc, httpware.TimeoutError):
        return ProviderAPIError("GitLab request timed out. Try again or increase SEMVERTAG_REQUEST_TIMEOUT.")
    if isinstance(exc, httpware.RetryBudgetExhaustedError):
        return ProviderAPIError(f"GitLab retries exhausted after {exc.attempts} attempts. Try again later.")
    if isinstance(exc, httpware.NetworkError):
        return ProviderAPIError("GitLab unreachable. Check network connectivity.")
    return ProviderAPIError(f"GitLab request failed: {type(exc).__name__}")
```

Replace with:

```python
def _translate_gitlab_transport(exc: httpware.ClientError) -> Exception:
    if isinstance(exc, httpware.DecodeError):
        return ProviderAPIError(
            f"GitLab {exc.model.__name__} response could not be decoded: {exc.original}"
        )
    if isinstance(exc, httpware.TimeoutError):
        return ProviderAPIError("GitLab request timed out. Try again or increase SEMVERTAG_REQUEST_TIMEOUT.")
    if isinstance(exc, httpware.RetryBudgetExhaustedError):
        return ProviderAPIError(f"GitLab retries exhausted after {exc.attempts} attempts. Try again later.")
    if isinstance(exc, httpware.NetworkError):
        return ProviderAPIError("GitLab unreachable. Check network connectivity.")
    return ProviderAPIError(f"GitLab request failed: {type(exc).__name__}")
```

(Only the first `if` block is added; everything else is unchanged.)

- [ ] **Step 4: Run the new test to verify it passes**

Run: `uv run pytest tests/unit/test_providers_errors.py::test_translate_gitlab_decode_error_becomes_provider_api_error -v`
Expected: PASS.

- [ ] **Step 5: Run the full `_errors` test file to make sure nothing regressed**

Run: `uv run pytest tests/unit/test_providers_errors.py -v`
Expected: 16 tests pass (was 15; we added one).

- [ ] **Step 6: Full suite + coverage**

Run: `just test`
Expected: 333 tests pass (was 332; the new test adds one), 100% coverage.

- [ ] **Step 7: Lint**

Run: `just lint-ci`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add semvertag/providers/_errors.py tests/unit/test_providers_errors.py
git commit -m "providers/_errors: translate httpware.DecodeError to ProviderAPIError"
```

---

## Task 3: Port the three GET methods to decoder paths

**Files:**
- Modify: `semvertag/providers/gitlab.py` (rewrite the three GET methods + class-level model definitions; delete validator helpers)
- Modify: `tests/integration/test_gitlab_provider.py` (update 9 `match=` strings)

This is the largest task. The translator branch from Task 2 is in place, so `httpware.DecodeError` raised during the new decoder calls flows uniformly through `except httpware.ClientError` → `_errors.translate_gitlab` → `ProviderAPIError` with the new wording.

- [ ] **Step 1: Read the current state end-to-end (no edits)**

Read:
- `semvertag/providers/gitlab.py` (220-ish lines). Note the existing models (`_ProjectResponse`, `_CommitItem`, `_TagCommit`, `_TagItem`), the three GET methods you're rewriting, and the validator helpers (`_validate_obj`, `_validate_project_response`, `_validate_commit_list`, `_validate_tag_list`, `_validate_list`, `_TModel`) that will be deleted.
- `tests/integration/test_gitlab_provider.py` lines 95-300 — these contain the 9 `pytest.raises(..., match=...)` assertions you'll need to update.

- [ ] **Step 2: Add the two RootModel wrappers in `gitlab.py`**

After the existing `_TagItem` class (around line 36), insert:

```python
class _CommitList(pydantic.RootModel[list[_CommitItem]]):
    pass


class _TagList(pydantic.RootModel[list[_TagItem]]):
    pass
```

These will be referenced as `response_model=_CommitList` / `response_model=_TagList`. They wrap the list under `.root`.

- [ ] **Step 3: Rewrite `get_default_branch`**

Find the current method body and replace with:

```python
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
```

The diff: `self.http.send(self.http.build_request(...))` + `_validate_project_response(response)` collapses to `self.http.get(..., response_model=_ProjectResponse)`. Error handling shape unchanged.

- [ ] **Step 4: Rewrite `get_latest_commit_on_default_branch`**

Find the current method and replace with:

```python
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
```

Two changes from current: (1) `self.http.send(self.http.build_request("GET", url, params=...))` + `_validate_commit_list(response)` collapses to `self.http.get(url, params=..., response_model=_CommitList)`; (2) `items[0]` becomes `page.root[0]` because the RootModel wraps the list.

- [ ] **Step 5: Rewrite `list_tags`**

Find the current method and replace with:

```python
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
```

Two changes: (1) `self.http.send(self.http.build_request(...))` + `_validate_tag_list(response)` becomes `self.http.send_with_response(..., response_model=_TagList)` which returns `(response, page)`; (2) `for item in items` becomes `for item in page.root`. Everything else (pagination loop, Link-header walk, same-origin check, page-cap) is unchanged.

- [ ] **Step 6: Delete the validator helpers**

In `gitlab.py`, delete these definitions and any blank lines between them:
- `def _validate_project_response(response: httpx2.Response) -> _ProjectResponse:` and its body
- `def _validate_tag_list(response: httpx2.Response) -> list[_TagItem]:` and its body
- `def _validate_commit_list(response: httpx2.Response) -> list[_CommitItem]:` and its body
- `_TModel = typing.TypeVar("_TModel", bound=pydantic.BaseModel)` line
- `def _validate_obj(response: httpx2.Response, model: type[_TModel], *, label: str) -> _TModel:` and its body
- `def _validate_list(response: httpx2.Response, model: type[_TModel], *, label: str) -> list[_TModel]:` and its body

After this step `gitlab.py` should contain: imports → domain constants → BaseModel classes → RootModel wrappers → `_LINK_ENTRY_RE` → `GitLabProvider` class → `_next_page_url` → `_parse_rel_values` → `_same_origin`. No `_validate_*`, no `_TModel`.

- [ ] **Step 7: Verify unused imports**

The validator helpers were the only consumers of `pydantic.ValidationError` and `httpx2.DecodingError`. Ruff's `F401` will flag them after Step 6.

Run: `uv run ruff check semvertag/providers/gitlab.py`
Expected: ruff reports unused `pydantic.ValidationError` and/or `httpx2.DecodingError` references. (Note: only the *names* might be flagged depending on whether `import pydantic` / `import httpx2` are also unused — likely they're still used for `pydantic.BaseModel`/`pydantic.RootModel` and `httpx2.Response` typing, so the module imports stay.)

If ruff flags any imports, remove them. With `fix = true` in `[tool.ruff]`, running `uv run ruff check . --fix` will auto-remove unused names.

- [ ] **Step 8: Update integration tests — substring match strings**

In `tests/integration/test_gitlab_provider.py`, replace 9 `match=` strings. The new translated message shape is `f"GitLab {exc.model.__name__} response could not be decoded: {exc.original}"` where `{exc.model.__name__}` is `_ProjectResponse`, `_CommitList`, or `_TagList`.

Use these exact replacements:

| Line | Old `match=` | New `match=` |
|---|---|---|
| 99 | `"response shape"` | `"_ProjectResponse response could not be decoded"` |
| 108 | `"malformed JSON"` | `"_ProjectResponse response could not be decoded"` |
| 117 | `"expected object"` | `"_ProjectResponse response could not be decoded"` |
| 161 | `"malformed JSON"` | `"_CommitList response could not be decoded"` |
| 170 | `"expected list"` | `"_CommitList response could not be decoded"` |
| 179 | `"response shape"` | `"_CommitList response could not be decoded"` |
| 271 | `"malformed JSON"` | `"_TagList response could not be decoded"` |
| 280 | `"expected list"` | `"_TagList response could not be decoded"` |
| 289 | `"shape invalid"` | `"_TagList response could not be decoded"` |

(Line numbers are pre-edit references; if line numbers shift during your editing, identify each occurrence by the old match string.)

The test names themselves (`test_raises_provider_api_error_when_default_branch_body_is_not_json`, etc.) stay — the test still verifies that a malformed JSON response produces a `ProviderAPIError` via the new decode path.

- [ ] **Step 9: Run integration tests to confirm the new wording matches**

Run: `uv run pytest tests/integration/test_gitlab_provider.py -v 2>&1 | tail -30`
Expected: all tests pass. If any of the 9 updated tests still fail with `regex did not match: actual exception text was '...'`, the actual text is in the failure message — adjust the `match=` regex accordingly (most likely the pydantic-specific underlying error wording differs from what you expected; in that case keep the model-name prefix and drop the literal `"could not be decoded"` to make the regex more permissive).

- [ ] **Step 10: Full suite with branch coverage**

Run: `just test`
Expected: all tests pass; coverage stays at 100%. The deleted validator branches no longer need coverage; the new call sites are covered by the same integration tests that previously exercised the validator code paths.

If coverage dropped on `semvertag/providers/gitlab.py`, identify which lines are uncovered. The most likely culprit is a RootModel-related code path; add a targeted integration test or use `# pragma: no cover` with a one-line justification.

- [ ] **Step 11: Lint**

Run: `just lint-ci`
Expected: clean.

- [ ] **Step 12: Commit**

```bash
git add semvertag/providers/gitlab.py tests/integration/test_gitlab_provider.py
git commit -m "providers/gitlab: adopt response_model=/send_with_response; delete in-tree validators"
```

---

## Task 4: Final validation

**Files:** none modified — this is the verification gate.

- [ ] **Step 1: Full lint sweep**

Run: `just lint-ci`
Expected: clean.

- [ ] **Step 2: Full test sweep with branch coverage**

Run: `just test-branch`
Expected: all tests pass; 100% statement + branch coverage.

- [ ] **Step 3: Docs build**

Run: `uv run --with mkdocs --with mkdocs-material mkdocs build --strict`
Expected: clean. If a doc page references the deleted `_validate_*` helpers or the old "shape invalid" / "malformed JSON" wording, update the prose. (Unlikely — the prior migration's final review confirmed `docs/` has no references to internal validator helpers.)

- [ ] **Step 4: Verify the symbols we now depend on are present in the resolved version**

Run:
```bash
uv run python -c "
import httpware
assert hasattr(httpware, 'DecodeError'), 'httpware.DecodeError missing'
assert hasattr(httpware.Client, 'send_with_response'), 'Client.send_with_response missing'
print('httpware seam OK')
"
```
Expected: prints `httpware seam OK`. If it fails, the lockfile didn't pick up 0.8.2 — re-run `uv lock --upgrade-package httpware && just install`.

- [ ] **Step 5: Skim `git log --oneline main..HEAD` to confirm the commit history reads cleanly**

Expected sequence (or similar):
```
<sha> providers/gitlab: adopt response_model=/send_with_response; delete in-tree validators
<sha> providers/_errors: translate httpware.DecodeError to ProviderAPIError
<sha> chore: floor httpware[pydantic] at >=0.8.2 (DecodeError, send_with_response)
```

If you committed any small lint / coverage follow-ups, those are fine too.

- [ ] **Step 6 — Optional**: Invoke `superpowers:requesting-code-review` for a final cross-cutting review of the branch.

---

## Self-review notes

- **Spec coverage:** Every section of `planning/specs/2026-06-08-httpware-decoder-adoption-design.md` maps to a task: dep floor → Task 1; `_errors.py` extension → Task 2; call-site shapes + helper deletion → Task 3; verification gate → Task 4. The three "Open items for the implementation plan" are all resolved at plan-time: (1) RootModel availability verified (pydantic 2.13.4 installed); (2) exact count of assertion updates is 9 with explicit line numbers and replacement strings in Task 3 Step 8; (3) unused-import cleanup is Task 3 Step 7.
- **Placeholder scan:** No `TBD`, `TODO`, "appropriate error handling", or "similar to Task N" patterns. Step 7 of Task 3 includes a contingency (auto-fix or manual remove) but each branch is concrete.
- **Type consistency:** `_CommitList = RootModel[list[_CommitItem]]` and `_TagList = RootModel[list[_TagItem]]` are defined in Task 3 Step 2 and consumed in Steps 4 and 5 with `page.root` access — consistent. `httpware.DecodeError` has attributes `model` (type) and `original` (Exception) per spec §3 and per the production translator branch in Task 2 Step 3 — consistent with the test fixture in Task 2 Step 1 (`type("FakeModel", (), {})` + `ValueError("input should be...")`).

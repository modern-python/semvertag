# BMad → Superpowers Migration + httpx2 Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut over from BMad to Superpowers workflow, then prove the new workflow by refactoring `semvertag/providers/gitlab.py` to use a schema-based `HttpClient` wrapper that erases its 6-step defensive dance per method.

**Architecture:** Two phases. **Phase 1** is mechanical workspace housekeeping on `main`: `git mv _bmad _archive/bmad`, update tool excludes, add a project `CLAUDE.md`. **Phase 2** is the wrapper pilot in a worktree under full TDD: build a generic `HttpClient` (taking a Pydantic schema per call, returning typed instances), then rewrite every method in `gitlab.py` to use it, then rewire DI. Existing integration tests are the parity guarantee — they pass before and after, with only error-message match patterns updated where Pydantic produces richer messages.

**Tech Stack:** Python 3.10+, `httpx2`, `pydantic` (already transitive via `pydantic-settings`), `pytest`, `modern-di`, `ty` (type checker), `ruff`, `uv`.

**Spec:** `planning/specs/2026-05-31-bmad-to-superpowers-migration-and-httpx2-wrapper-design.md`

---

## Phase 1 — Migration scaffolding (direct-to-`main`, no worktree)

### Task 1: Archive `_bmad/` and update tool excludes

**Files:**
- Move: `_bmad/` → `_archive/bmad/` (via `git mv`)
- Modify: `pyproject.toml:61` (`tool.ruff.extend-exclude`)
- Modify: `pyproject.toml:90` (`tool.coverage.run.omit`)
- Modify: `pyproject.toml:93` (`tool.ty.src.exclude`)

- [ ] **Step 1: Verify pre-move state**

Run: `git status` — must be clean. Run: `ls _bmad/ | head -5` — must show BMad story files. Run: `ls _archive/ 2>/dev/null || echo "missing"` — `_archive/` may or may not exist.

- [ ] **Step 2: Create `_archive/` parent if missing and move**

```bash
mkdir -p _archive
git mv _bmad _archive/bmad
```

Run: `ls _archive/bmad/ | head -5` — must show the moved BMad files. Run: `ls _bmad 2>/dev/null && echo "STILL EXISTS"` — must print nothing (no `STILL EXISTS`).

- [ ] **Step 3: Update `pyproject.toml` excludes**

Three string replacements, all `_bmad` → `_archive/bmad`:

```toml
# Line ~61
extend-exclude = ["docs", "_autosemver_reference", "_archive/bmad"]

# Line ~90
omit = ["_autosemver_reference/*", "_archive/bmad/*", "tests/*"]

# Line ~93
exclude = ["_autosemver_reference", "_archive/bmad", "docs"]
```

- [ ] **Step 4: Verify tools accept the new excludes**

Run: `just lint-ci`
Expected: passes (linters honor the new exclude paths, no errors from inside `_archive/bmad/`).

Run: `uv run pytest -x -q`
Expected: 425+ tests pass (no coverage failures from `_archive/bmad/`).

- [ ] **Step 5: Commit**

```bash
git add _archive/bmad _bmad pyproject.toml
git commit -m "chore: archive _bmad/ as read-only reference

Move _bmad/ to _archive/bmad/ to retire the BMad workflow.
Update ruff, coverage, and ty excludes accordingly.
Nothing is deleted; the archive stays on disk for historical reference."
```

Run: `git log --oneline -1`
Expected: shows the new commit; `_bmad/` no longer appears in `git ls-files`.

---

### Task 2: Add project `CLAUDE.md`

**Files:**
- Create: `CLAUDE.md` (repo root)

`planning/plans/.gitkeep` already exists (committed during the brainstorm in `37aeb6b`); no work needed there.

- [ ] **Step 1: Write `CLAUDE.md`**

Create `/Users/kevinsmith/src/pypi/autosemver/CLAUDE.md` with this exact content:

```markdown
# semvertag — Claude project guide

## Workflow

This project uses **Superpowers** (brainstorm → plan → TDD → review).

- Brainstorm specs live in `planning/specs/YYYY-MM-DD-<topic>-design.md`.
- Implementation plans live in `planning/plans/YYYY-MM-DD-<topic>.md`.
- Use TDD by default: red, green, refactor. Tests before implementation.
- Use git worktrees for feature isolation (`superpowers:using-git-worktrees`).
- Use the verification gate before claiming work complete
  (`superpowers:verification-before-completion`).
- Request code review via a subagent before landing
  (`superpowers:requesting-code-review`).

## Commit messages

Imperative present-tense, scoped where helpful:

- `providers: add HttpClient wrapper`
- `docs: update README hero section`
- `fix: handle empty default branch in GitLab provider`

No story-numbered prefixes (`land story X.Y`, `contextualise story X.Y`). Those
belong to the retired BMad workflow.

## Reference directories (do not edit)

- `_archive/bmad/` — retired BMad workspace. Historical specs, PRD,
  architecture, retrospectives, and 14 dense story files. Read for context;
  do not extend, do not delete.
- `_autosemver_reference/` — the original Raiffeisen-internal `autosemver`
  package. Behavioral reference only — port logic and test shapes from it
  but never `git mv` files in or take it as a starter.

## Test stack and lint

See `Justfile` for the canonical commands. Quick reference:

- `just lint-ci` — eof-fixer, ruff format check, ruff check, ty check
- `just test` — pytest with coverage
- `just test-branch` — pytest with branch coverage
- `just test-branch-strategies` / `just test-cc-strategies` / `just test-doctor`
  — 100% branch coverage gates on specific modules
- `mkdocs build --strict` — docs build gate

## What the codebase ships

`semvertag` is a public-OSS auto-tagger for GitLab/GitHub/Bitbucket
repositories. Two strategies (`branch-prefix`, `conventional-commits`), one
provider implemented today (GitLab), distributed as a Python CLI plus a
GitHub Actions wrapper (`action.yml`) and a GitLab CI Catalog component
(`templates/semvertag.yml`).
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add project CLAUDE.md for Superpowers workflow

Point at spec/plan locations, commit-message convention, reference
directories (_archive/bmad/, _autosemver_reference/), and the canonical
lint/test commands."
```

Run: `git log --oneline -1`
Expected: shows the new commit.

---

### Phase 1 Gate

- [ ] **Step 1: Run full verification**

Run: `just lint-ci`
Expected: PASS.

Run: `uv run pytest`
Expected: 425+ tests PASS.

Run: `uv run mkdocs build --strict`
Expected: builds successfully in ~1s.

If any of these fail, do **not** proceed to Phase 2 — fix the regression first.

---

## Phase 2 — Wrapper pilot (worktree, TDD)

### Task 3: Spawn a worktree for the wrapper work

**Files:** none modified in the main checkout yet.

- [ ] **Step 1: Invoke the worktree skill**

Use the `superpowers:using-git-worktrees` skill to create an isolated worktree off `main`. Suggested branch name: `feat/http-client-wrapper`. Suggested worktree path: per the skill's default (typically `../<repo>-<branch>` or a configured location).

- [ ] **Step 2: Verify worktree state**

Run (inside the new worktree): `git status` — must be clean, on the new branch. Run: `git log --oneline -1` — must match the latest commit on `main` from Phase 1.

All subsequent Phase 2 work happens inside this worktree.

---

### Task 4: Stub `HttpClient` and write the happy-path `request` test

**Files:**
- Create: `semvertag/providers/_http.py`
- Create: `tests/unit/test_http_client.py`

- [ ] **Step 1: Write the failing happy-path test**

Create `tests/unit/test_http_client.py`:

```python
import typing

import httpx2
import pydantic
import pytest

from semvertag.providers._http import HttpClient


_BASE_URL: typing.Final = "https://example.test"


class _SampleResponse(pydantic.BaseModel):
    name: str
    count: int


def _build_client(handler: typing.Callable[[httpx2.Request], httpx2.Response]) -> HttpClient:
    transport: typing.Final = httpx2.MockTransport(handler)
    inner: typing.Final = httpx2.Client(transport=transport, base_url=_BASE_URL)
    return HttpClient(
        client=inner,
        auth_headers=lambda: {"X-Test-Auth": "token-xyz"},
        status_translator=lambda _status: None,
    )


def test_request_returns_validated_schema_instance_on_happy_path() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"name": "alice", "count": 7})

    http: typing.Final = _build_client(handler)
    result: typing.Final = http.request("GET", "/things/1", schema=_SampleResponse)
    assert isinstance(result, _SampleResponse)
    assert result.name == "alice"
    assert result.count == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_http_client.py::test_request_returns_validated_schema_instance_on_happy_path -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'semvertag.providers._http'`.

- [ ] **Step 3: Write minimal `HttpClient` to make the test pass**

Create `semvertag/providers/_http.py`:

```python
import collections.abc
import dataclasses
import typing

import httpx2
import pydantic


T = typing.TypeVar("T", bound=pydantic.BaseModel)

AuthHeaders: typing.TypeAlias = collections.abc.Callable[[], dict[str, str]]
StatusTranslator: typing.TypeAlias = collections.abc.Callable[[int], None]


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class HttpClient:
    client: httpx2.Client
    auth_headers: AuthHeaders
    status_translator: StatusTranslator

    def request(self, method: str, url: str, *, schema: type[T], **kwargs: typing.Any) -> T:
        response = self.client.request(method, url, headers=self.auth_headers(), **kwargs)
        payload = response.json()
        return schema.model_validate(payload)


__all__: typing.Final = ("AuthHeaders", "HttpClient", "StatusTranslator")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_http_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add semvertag/providers/_http.py tests/unit/test_http_client.py
git commit -m "providers: add HttpClient stub with happy-path request

Schema-based wrapper around httpx2.Client. First test only covers the
happy path; error paths follow in subsequent commits."
```

---

### Task 5: Add `RequestError` and malformed-JSON failure tests

**Files:**
- Modify: `tests/unit/test_http_client.py`
- Modify: `semvertag/providers/_http.py`

- [ ] **Step 1: Add two failing tests**

Append to `tests/unit/test_http_client.py`:

```python
from semvertag._errors import ProviderAPIError


def test_request_translates_request_error_to_provider_api_error() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    http: typing.Final = _build_client(handler)
    with pytest.raises(ProviderAPIError, match="request failed"):
        http.request("GET", "/things/1", schema=_SampleResponse)


def test_request_translates_malformed_json_to_provider_api_error() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="this is not json")

    http: typing.Final = _build_client(handler)
    with pytest.raises(ProviderAPIError, match="malformed JSON"):
        http.request("GET", "/things/1", schema=_SampleResponse)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_http_client.py -v`
Expected: 2 FAILs (no exception translation yet — the `httpx2.ConnectError` leaks out, and `response.json()` raises `ValueError`/`DecodingError`).

- [ ] **Step 3: Implement error translation**

Replace the `request` method body in `semvertag/providers/_http.py`:

```python
    def request(self, method: str, url: str, *, schema: type[T], **kwargs: typing.Any) -> T:
        try:
            response = self.client.request(method, url, headers=self.auth_headers(), **kwargs)
        except httpx2.RequestError as exc:
            msg = f"request failed: {type(exc).__name__}"
            raise ProviderAPIError(msg) from exc
        try:
            payload = response.json()
        except (ValueError, httpx2.DecodingError) as exc:
            msg = "malformed JSON in response body"
            raise ProviderAPIError(msg) from exc
        return schema.model_validate(payload)
```

Add the import at the top of `_http.py`:

```python
from semvertag._errors import ProviderAPIError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_http_client.py -v`
Expected: 3 PASS (original happy-path + the two new error cases).

- [ ] **Step 5: Commit**

```bash
git add semvertag/providers/_http.py tests/unit/test_http_client.py
git commit -m "providers: translate RequestError and JSON decode errors

HttpClient.request now wraps httpx2.RequestError -> ProviderAPIError and
catches non-JSON response bodies."
```

---

### Task 6: Add schema-validation failure tests (missing field, wrong type)

**Files:**
- Modify: `tests/unit/test_http_client.py`
- Modify: `semvertag/providers/_http.py`

- [ ] **Step 1: Add two failing tests**

Append to `tests/unit/test_http_client.py`:

```python
def test_request_translates_missing_field_to_provider_api_error() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"name": "alice"})  # missing 'count'

    http: typing.Final = _build_client(handler)
    with pytest.raises(ProviderAPIError, match="response shape"):
        http.request("GET", "/things/1", schema=_SampleResponse)


def test_request_translates_wrong_field_type_to_provider_api_error() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"name": "alice", "count": "seven"})

    http: typing.Final = _build_client(handler)
    with pytest.raises(ProviderAPIError, match="response shape"):
        http.request("GET", "/things/1", schema=_SampleResponse)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_http_client.py -v`
Expected: 2 FAILs (the pydantic `ValidationError` leaks out instead of becoming `ProviderAPIError`).

- [ ] **Step 3: Wrap pydantic validation**

Update the `request` method's final line in `semvertag/providers/_http.py`:

```python
        try:
            return schema.model_validate(payload)
        except pydantic.ValidationError as exc:
            msg = f"response shape invalid: {exc}"
            raise ProviderAPIError(msg) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_http_client.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add semvertag/providers/_http.py tests/unit/test_http_client.py
git commit -m "providers: translate pydantic ValidationError -> ProviderAPIError

The full pydantic error (with field path and type) is preserved in the
message so failures stay diagnosable."
```

---

### Task 7: Add `status_translator` hook test (runs before validation)

**Files:**
- Modify: `tests/unit/test_http_client.py`
- Modify: `semvertag/providers/_http.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/unit/test_http_client.py`:

```python
from semvertag._errors import AuthError


def test_status_translator_runs_before_json_decode_and_validation() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        # Body is HTML, not JSON — would fail both decode and schema validation.
        return httpx2.Response(401, text="<html>Unauthorized</html>")

    def translator(status: int) -> None:
        if status == 401:
            msg = "token rejected"
            raise AuthError(msg)

    http: typing.Final = HttpClient(
        client=httpx2.Client(transport=httpx2.MockTransport(handler), base_url=_BASE_URL),
        auth_headers=lambda: {},
        status_translator=translator,
    )

    with pytest.raises(AuthError, match="token rejected"):
        http.request("GET", "/things/1", schema=_SampleResponse)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_http_client.py::test_status_translator_runs_before_json_decode_and_validation -v`
Expected: FAIL — the translator is not invoked; instead `ProviderAPIError` raises from `response.json()`.

- [ ] **Step 3: Invoke the translator after the request**

Update the `request` method in `_http.py` to call `status_translator(response.status_code)` between the request and the JSON decode:

```python
    def request(self, method: str, url: str, *, schema: type[T], **kwargs: typing.Any) -> T:
        try:
            response = self.client.request(method, url, headers=self.auth_headers(), **kwargs)
        except httpx2.RequestError as exc:
            msg = f"request failed: {type(exc).__name__}"
            raise ProviderAPIError(msg) from exc
        self.status_translator(response.status_code)
        try:
            payload = response.json()
        except (ValueError, httpx2.DecodingError) as exc:
            msg = "malformed JSON in response body"
            raise ProviderAPIError(msg) from exc
        try:
            return schema.model_validate(payload)
        except pydantic.ValidationError as exc:
            msg = f"response shape invalid: {exc}"
            raise ProviderAPIError(msg) from exc
```

- [ ] **Step 4: Run all tests to verify**

Run: `uv run pytest tests/unit/test_http_client.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add semvertag/providers/_http.py tests/unit/test_http_client.py
git commit -m "providers: invoke status_translator before JSON decode

This ensures a 401 raises AuthError rather than trying (and failing) to
validate the error-body shape against the success schema."
```

---

### Task 8: Add `request_many` (list response)

**Files:**
- Modify: `tests/unit/test_http_client.py`
- Modify: `semvertag/providers/_http.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_http_client.py`:

```python
def test_request_many_returns_list_of_validated_instances() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[{"name": "a", "count": 1}, {"name": "b", "count": 2}])

    http: typing.Final = _build_client(handler)
    result: typing.Final = http.request_many("GET", "/things", schema=_SampleResponse)
    assert len(result) == 2
    assert all(isinstance(item, _SampleResponse) for item in result)
    assert result[0].name == "a"
    assert result[1].count == 2


def test_request_many_translates_dict_payload_to_provider_api_error() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"not": "a list"})

    http: typing.Final = _build_client(handler)
    with pytest.raises(ProviderAPIError, match="expected list"):
        http.request_many("GET", "/things", schema=_SampleResponse)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_http_client.py -v -k request_many`
Expected: 2 FAILs (`request_many` doesn't exist).

- [ ] **Step 3: Implement `request_many`**

Add to `_http.py` (inside the `HttpClient` class, after `request`):

```python
    def request_many(self, method: str, url: str, *, schema: type[T], **kwargs: typing.Any) -> list[T]:
        try:
            response = self.client.request(method, url, headers=self.auth_headers(), **kwargs)
        except httpx2.RequestError as exc:
            msg = f"request failed: {type(exc).__name__}"
            raise ProviderAPIError(msg) from exc
        self.status_translator(response.status_code)
        try:
            payload = response.json()
        except (ValueError, httpx2.DecodingError) as exc:
            msg = "malformed JSON in response body"
            raise ProviderAPIError(msg) from exc
        if not isinstance(payload, list):
            msg = f"response shape invalid: expected list, got {type(payload).__name__}"
            raise ProviderAPIError(msg)
        try:
            return [schema.model_validate(item) for item in payload]
        except pydantic.ValidationError as exc:
            msg = f"response shape invalid: {exc}"
            raise ProviderAPIError(msg) from exc
```

(Yes, there's duplication with `request`. We'll refactor in Task 10 once the API is settled — premature DRY now would couple us to one implementation shape.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_http_client.py -v`
Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add semvertag/providers/_http.py tests/unit/test_http_client.py
git commit -m "providers: add HttpClient.request_many for list responses

Returns list[T] from a JSON-array body. Dict payloads raise
ProviderAPIError with an explicit 'expected list' message."
```

---

### Task 9: Add `request_raw` (escape hatch for create_tag and pagination)

**Files:**
- Modify: `tests/unit/test_http_client.py`
- Modify: `semvertag/providers/_http.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_http_client.py`:

```python
def test_request_raw_returns_response_with_auth_headers_applied() -> None:
    captured_headers: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured_headers.update(request.headers)
        return httpx2.Response(418, text="teapot")

    http: typing.Final = _build_client(handler)
    response: typing.Final = http.request_raw("GET", "/teapot")
    assert response.status_code == 418
    assert response.text == "teapot"
    assert captured_headers.get("x-test-auth") == "token-xyz"


def test_request_raw_does_not_call_status_translator() -> None:
    call_count = {"n": 0}

    def translator(_status: int) -> None:
        call_count["n"] += 1

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, text="server error")

    http: typing.Final = HttpClient(
        client=httpx2.Client(transport=httpx2.MockTransport(handler), base_url=_BASE_URL),
        auth_headers=lambda: {},
        status_translator=translator,
    )
    response: typing.Final = http.request_raw("GET", "/whatever")
    assert response.status_code == 500
    assert call_count["n"] == 0


def test_request_raw_translates_request_error_to_provider_api_error() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out")

    http: typing.Final = _build_client(handler)
    with pytest.raises(ProviderAPIError, match="request failed"):
        http.request_raw("GET", "/whatever")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_http_client.py -v -k request_raw`
Expected: 3 FAILs (`request_raw` doesn't exist).

- [ ] **Step 3: Implement `request_raw`**

Add to `_http.py`:

```python
    def request_raw(self, method: str, url: str, **kwargs: typing.Any) -> httpx2.Response:
        try:
            return self.client.request(method, url, headers=self.auth_headers(), **kwargs)
        except httpx2.RequestError as exc:
            msg = f"request failed: {type(exc).__name__}"
            raise ProviderAPIError(msg) from exc
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_http_client.py -v`
Expected: 11 PASS.

- [ ] **Step 5: Commit**

```bash
git add semvertag/providers/_http.py tests/unit/test_http_client.py
git commit -m "providers: add HttpClient.request_raw escape hatch

Applies auth headers and translates RequestError but does NOT call
status_translator or decode the body. For callers (create_tag, pagination)
that need to inspect status + body together."
```

---

### Task 10: Extract shared request prelude in `HttpClient`

**Files:**
- Modify: `semvertag/providers/_http.py`

Now that the three methods exist and their tests pin behavior, collapse the duplicated "request + RequestError translation + status_translator" prelude into one private helper.

- [ ] **Step 1: Refactor without changing tests**

Replace the `HttpClient` class body in `_http.py` with:

```python
@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class HttpClient:
    client: httpx2.Client
    auth_headers: AuthHeaders
    status_translator: StatusTranslator

    def request(self, method: str, url: str, *, schema: type[T], **kwargs: typing.Any) -> T:
        response = self._request_translated(method, url, **kwargs)
        payload = self._decode_json(response)
        try:
            return schema.model_validate(payload)
        except pydantic.ValidationError as exc:
            msg = f"response shape invalid: {exc}"
            raise ProviderAPIError(msg) from exc

    def request_many(self, method: str, url: str, *, schema: type[T], **kwargs: typing.Any) -> list[T]:
        response = self._request_translated(method, url, **kwargs)
        payload = self._decode_json(response)
        if not isinstance(payload, list):
            msg = f"response shape invalid: expected list, got {type(payload).__name__}"
            raise ProviderAPIError(msg)
        try:
            return [schema.model_validate(item) for item in payload]
        except pydantic.ValidationError as exc:
            msg = f"response shape invalid: {exc}"
            raise ProviderAPIError(msg) from exc

    def request_raw(self, method: str, url: str, **kwargs: typing.Any) -> httpx2.Response:
        return self._request_raw(method, url, **kwargs)

    def _request_translated(self, method: str, url: str, **kwargs: typing.Any) -> httpx2.Response:
        response = self._request_raw(method, url, **kwargs)
        self.status_translator(response.status_code)
        return response

    def _request_raw(self, method: str, url: str, **kwargs: typing.Any) -> httpx2.Response:
        try:
            return self.client.request(method, url, headers=self.auth_headers(), **kwargs)
        except httpx2.RequestError as exc:
            msg = f"request failed: {type(exc).__name__}"
            raise ProviderAPIError(msg) from exc

    @staticmethod
    def _decode_json(response: httpx2.Response) -> typing.Any:
        try:
            return response.json()
        except (ValueError, httpx2.DecodingError) as exc:
            msg = "malformed JSON in response body"
            raise ProviderAPIError(msg) from exc
```

- [ ] **Step 2: Run all `HttpClient` tests**

Run: `uv run pytest tests/unit/test_http_client.py -v`
Expected: 11 PASS — no behavior changes.

- [ ] **Step 3: Lint**

Run: `just lint-ci`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add semvertag/providers/_http.py
git commit -m "providers: refactor HttpClient internals to share request prelude

Extract _request_raw / _request_translated / _decode_json helpers. No
behavior change; existing tests still pass."
```

---

### Task 11: Refactor `get_default_branch` to use `HttpClient`

**Files:**
- Modify: `semvertag/providers/gitlab.py`
- Modify: `tests/conftest.py` (update `gitlab_provider` fixture signature)
- Modify: `tests/integration/test_gitlab_provider.py` (update `_make_provider` helper + adjust 3-5 error-message match patterns)

> **Note on the migration shape:** this is the **first** method refactor and it pulls in three structural changes that the next refactor tasks will not need to repeat:
> 1. Adding the `http: HttpClient` field to `GitLabProvider` (replacing `client: httpx2.Client`).
> 2. Updating the fixture in `tests/conftest.py` to construct an `HttpClient`.
> 3. Updating the `_make_provider` helper in `tests/integration/test_gitlab_provider.py`.
>
> After this task, subsequent method refactors are pure provider-body rewrites.

- [ ] **Step 1: Add the first schema and refactor `get_default_branch`**

In `semvertag/providers/gitlab.py`:

1. Add `import pydantic` to the import block.
2. Add `from semvertag.providers._http import HttpClient` to the imports.
3. Inside the file, define the first schema near the top (after the constants):

```python
class _ProjectResponse(pydantic.BaseModel):
    default_branch: str | None = None
```

4. Change the `GitLabProvider` dataclass field from `client: httpx2.Client` to `http: HttpClient`.
5. Replace `get_default_branch` body with:

```python
    def get_default_branch(self) -> str:
        project = self.http.request(
            "GET",
            self._url(f"{_API_PREFIX}/{self.project_id}"),
            schema=_ProjectResponse,
        )
        if not project.default_branch:
            msg = "Default branch missing from GitLab response. Verify the project has a default branch configured."
            raise ConfigError(msg)
        return project.default_branch
```

Leave the other provider methods unchanged for now — they'll still reference `self.client`, which no longer exists. The tests for those methods will fail until refactored. That's OK; we'll run only the `get_default_branch` tests this task.

- [ ] **Step 2: Update `tests/conftest.py` fixture**

Replace the `gitlab_provider` fixture with:

```python
@pytest.fixture
def gitlab_http(gitlab_client: httpx2.Client) -> "HttpClient":
    from semvertag.providers._http import HttpClient

    config: typing.Final = GitLabConfig(endpoint=GITLAB_ENDPOINT, token=pydantic.SecretStr(GITLAB_TOKEN))
    return HttpClient(
        client=gitlab_client,
        auth_headers=lambda: {"PRIVATE-TOKEN": config.token.get_secret_value()},
        status_translator=_make_status_translator(GITLAB_PROJECT_ID),
    )


@pytest.fixture
def gitlab_provider(gitlab_http: "HttpClient") -> GitLabProvider:
    config: typing.Final = GitLabConfig(endpoint=GITLAB_ENDPOINT, token=pydantic.SecretStr(GITLAB_TOKEN))
    return GitLabProvider(config=config, project_id=GITLAB_PROJECT_ID, http=gitlab_http)
```

Add this helper at module level in `conftest.py` (above the fixtures):

```python
def _make_status_translator(project_id: int) -> typing.Callable[[int], None]:
    from semvertag.providers.gitlab import _translate_status

    def translator(status: int) -> None:
        _translate_status(status, project_id)

    return translator
```

Add the `from semvertag.providers._http import HttpClient` import at the top (or use the inline imports as shown — either works; pick whichever the linter prefers).

- [ ] **Step 3: Update `tests/integration/test_gitlab_provider.py` `_make_provider` helper**

Replace `_make_provider` (around line 42):

```python
def _make_provider(handler: HandlerCallable) -> tuple[GitLabProvider, httpx2.Client]:
    from semvertag.providers._http import HttpClient
    from semvertag.providers.gitlab import _translate_status

    transport: typing.Final = httpx2.MockTransport(handler)
    client: typing.Final = httpx2.Client(transport=transport, base_url=GITLAB_ENDPOINT)
    config: typing.Final = GitLabConfig(endpoint=GITLAB_ENDPOINT, token=pydantic.SecretStr(GITLAB_TOKEN))
    http: typing.Final = HttpClient(
        client=client,
        auth_headers=lambda: {"PRIVATE-TOKEN": config.token.get_secret_value()},
        status_translator=lambda status: _translate_status(status, GITLAB_PROJECT_ID),
    )
    provider: typing.Final = GitLabProvider(config=config, project_id=GITLAB_PROJECT_ID, http=http)
    return provider, client
```

Do the same for `_make_provider_with_retrying_transport`.

- [ ] **Step 4: Update `get_default_branch` integration-test message patterns**

In `tests/integration/test_gitlab_provider.py`, find the three tests for `get_default_branch` error paths (around lines 99-114) and update the match patterns:

```python
# test_raises_provider_api_error_when_default_branch_response_malformed
with client, pytest.raises(ProviderAPIError, match="response shape"):
    provider.get_default_branch()

# test_raises_provider_api_error_when_default_branch_body_is_not_json
with client, pytest.raises(ProviderAPIError, match="malformed JSON"):
    provider.get_default_branch()
```

(The Pydantic-based wrapper produces different message text than the old hand-coded checks. The new messages are more informative — they include the field path.)

- [ ] **Step 5: Run the `get_default_branch` tests**

Run: `uv run pytest tests/integration/test_gitlab_provider.py -v -k "default_branch or protocol"`
Expected: PASS. Other tests may fail — that's expected; we haven't refactored them yet.

- [ ] **Step 6: Commit**

```bash
git add semvertag/providers/gitlab.py semvertag/providers/_http.py tests/conftest.py tests/integration/test_gitlab_provider.py
git commit -m "providers: refactor get_default_branch via HttpClient

GitLabProvider now takes http: HttpClient instead of client: httpx2.Client.
Other provider methods are temporarily broken (will be refactored in
subsequent commits)."
```

---

### Task 12: Refactor `get_latest_commit_on_default_branch`

**Files:**
- Modify: `semvertag/providers/gitlab.py`
- Modify: `tests/integration/test_gitlab_provider.py` (3 error-message match updates)

- [ ] **Step 1: Add schema and refactor method**

In `gitlab.py`, near the other schemas:

```python
class _CommitItem(pydantic.BaseModel):
    id: str
    message: str
```

Replace `get_latest_commit_on_default_branch` body:

```python
    def get_latest_commit_on_default_branch(self) -> Commit:
        default_branch: typing.Final = self.get_default_branch()
        items = self.http.request_many(
            "GET",
            self._url(f"{_API_PREFIX}/{self.project_id}/repository/commits"),
            schema=_CommitItem,
            params={"ref_name": default_branch, "per_page": 1},
        )
        if not items:
            msg = f"No commits on default branch '{default_branch}'. The branch appears empty."
            raise ProviderAPIError(msg)
        head = items[0]
        return Commit(sha=head.id, message=head.message)
```

- [ ] **Step 2: Update integration-test match patterns**

In `tests/integration/test_gitlab_provider.py`, update the `get_latest_commit` error tests:

```python
# test_get_latest_commit_raises_provider_api_error_when_body_not_json
match="malformed JSON"

# test_get_latest_commit_raises_provider_api_error_when_body_not_list
match="expected list"

# test_get_latest_commit_raises_provider_api_error_when_commit_object_missing_keys
match="response shape"
```

- [ ] **Step 3: Run the relevant tests**

Run: `uv run pytest tests/integration/test_gitlab_provider.py -v -k "latest_commit or default_branch or protocol"`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add semvertag/providers/gitlab.py tests/integration/test_gitlab_provider.py
git commit -m "providers: refactor get_latest_commit_on_default_branch via HttpClient"
```

---

### Task 13: Refactor `list_tags` (request_raw + module-level validation helper)

**Files:**
- Modify: `semvertag/providers/gitlab.py`
- Modify: `tests/integration/test_gitlab_provider.py` (match-pattern updates)

`list_tags` is the trickiest method because it paginates via the GitLab `Link` header. Pagination needs simultaneous access to body + headers, which `request_many` doesn't expose. So all pages go through `request_raw` with explicit schema validation via a module-level helper.

- [ ] **Step 1: Add schemas**

In `gitlab.py`, near the other schemas:

```python
class _TagCommit(pydantic.BaseModel):
    id: str


class _TagItem(pydantic.BaseModel):
    name: str
    commit: _TagCommit
```

- [ ] **Step 2: Use `request_raw` uniformly across pages**

Pagination needs simultaneous access to the body AND the `Link` header. `request_many` doesn't expose headers, so all pages go through `request_raw` with explicit schema validation via a module-level helper. This keeps the pagination loop uniform.

Replace `list_tags` body:

```python
    def list_tags(self) -> list[Tag]:
        tags: list[Tag] = []
        base_url: typing.Final = self._url(f"{_API_PREFIX}/{self.project_id}/repository/tags")
        url: str = base_url
        params: dict[str, typing.Any] | None = {"per_page": _TAGS_PER_PAGE, "page": 1}
        for _ in range(_MAX_TAG_PAGES):
            response = self.http.request_raw("GET", url, params=params)
            _translate_status(response.status_code, self.project_id)
            items = _validate_tag_list(response)
            tags.extend(Tag(name=item.name, commit_sha=item.commit.id) for item in items)
            next_url = _next_page_url(response, current_url=url)
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

Add the module-level helper near the other `_*` helpers in `gitlab.py`:

```python
def _validate_tag_list(response: httpx2.Response) -> list[_TagItem]:
    try:
        payload = response.json()
    except (ValueError, httpx2.DecodingError) as exc:
        msg = "GitLab tags response malformed JSON."
        raise ProviderAPIError(msg) from exc
    if not isinstance(payload, list):
        msg = "GitLab tags response shape invalid: expected list."
        raise ProviderAPIError(msg)
    try:
        return [_TagItem.model_validate(item) for item in payload]
    except pydantic.ValidationError as exc:
        msg = f"GitLab tags response shape invalid: {exc}"
        raise ProviderAPIError(msg) from exc
```

> This explicit pagination loop is messier than the other methods because it
> needs simultaneous access to body + Link header. That's by design — the
> spec called out pagination as a case where `request_raw` is the right tool
> and per-call validation lives in the provider. If this pattern recurs in
> GitHub later, we'll add a `request_paginated` helper to HttpClient then.

- [ ] **Step 3: Update integration-test match patterns for list_tags**

Run `grep -n "list_tags\|tags response" tests/integration/test_gitlab_provider.py` to find the affected tests. Update each `match=` pattern that asserts on tag-list error messages to one of the new wordings: `"malformed JSON"`, `"shape invalid"`, or `"expected list"` — whichever fits the failure mode being tested. The pagination Link-header tests (`"different host"`, `"exceeded ... pages"`) should NOT need changes — those messages are unchanged.

If a test you can't immediately match comes up, run it first (`uv run pytest tests/integration/test_gitlab_provider.py::<test_name> -v`) — the pytest output shows the actual exception message, which tells you which new fragment to assert on.

- [ ] **Step 4: Run list_tags tests**

Run: `uv run pytest tests/integration/test_gitlab_provider.py -v -k "list_tags or tags"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add semvertag/providers/gitlab.py tests/integration/test_gitlab_provider.py
git commit -m "providers: refactor list_tags via HttpClient with explicit pagination

Pagination requires raw response access (Link header), so list_tags uses
request_raw uniformly across pages with a module-level _validate_tag_list
helper for body validation."
```

---

### Task 14: Refactor `create_tag`

**Files:**
- Modify: `semvertag/providers/gitlab.py`
- Modify: `tests/integration/test_gitlab_provider.py` (likely no match-pattern changes — `create_tag`'s error messages are mostly provider-built, not wrapper-built)

- [ ] **Step 1: Refactor `create_tag` body**

Replace:

```python
    def create_tag(self, name: str, commit_sha: str) -> None:
        response = self.http.request_raw(
            "POST",
            self._url(f"{_API_PREFIX}/{self.project_id}/repository/tags"),
            json={"tag_name": name, "ref": commit_sha},
        )
        if response.status_code == _HTTP_CREATED:
            return
        if response.status_code == _HTTP_BAD_REQUEST:
            body_message = ""
            try:
                payload = response.json()
                body_message = str(payload.get("message", "")) if isinstance(payload, dict) else ""
            except (ValueError, httpx2.DecodingError):
                pass
            if _TAG_EXISTS_FRAGMENT in body_message.lower():
                msg = f"Tag already exists: '{name}'. The tag was created by a concurrent run or previous invocation."
                raise ConfigError(msg)
            msg = "Request rejected by GitLab: 400. Check tag name format and that the referenced commit exists."
            raise ConfigError(msg)
        _translate_status(response.status_code, self.project_id)
```

- [ ] **Step 2: Run create_tag tests**

Run: `uv run pytest tests/integration/test_gitlab_provider.py -v -k create_tag`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add semvertag/providers/gitlab.py
git commit -m "providers: refactor create_tag via HttpClient.request_raw

create_tag still needs raw response access for the 'tag already exists'
400 branch. The wrapper kills the RequestError handling boilerplate."
```

---

### Task 15: Refactor `check_token`, `check_scopes`, `check_project_access`, `check_protected_tags`

**Files:**
- Modify: `semvertag/providers/gitlab.py`

The `check_*` methods don't raise — they return `CheckResult` with `status="failed"` and a human-readable cause. They need `request_raw` so they can convert `ProviderAPIError` (from `RequestError`) into a `CheckResult` rather than propagating.

- [ ] **Step 1: Refactor `_safe_get` to use `HttpClient.request_raw`**

Replace `_safe_get` in `gitlab.py`:

```python
    def _safe_get(self, url: str) -> tuple[httpx2.Response | None, str | None]:
        try:
            return self.http.request_raw("GET", url), None
        except ProviderAPIError as exc:
            cause = exc.__cause__
            error_kind = type(cause).__name__ if isinstance(cause, httpx2.RequestError) else "RequestError"
            return None, error_kind
```

The `check_*` method bodies stay structurally the same — they already use `_safe_get`. The only change is that `_safe_get` now goes through `HttpClient`, which applies auth headers and translates `RequestError` to `ProviderAPIError`. We recover the original exception class name via `exc.__cause__` (which `raise ... from exc` populates), preserving the `error_type` strings the existing tests expect (e.g. `"ReadTimeout"`, `"ConnectError"`).

- [ ] **Step 2: Run all check_* tests**

Run: `uv run pytest tests/integration/test_gitlab_provider.py -v -k "check_"`
Expected: PASS. If any fail because of message-text expectations, adjust the test or restore the original `ProviderAPIError` message format in `_http.py` to include the exception class name verbatim.

- [ ] **Step 3: Commit**

```bash
git add semvertag/providers/gitlab.py tests/integration/test_gitlab_provider.py
git commit -m "providers: route check_* methods through HttpClient.request_raw

_safe_get now wraps HttpClient.request_raw and converts ProviderAPIError
back into the (response | None, error_kind | None) shape that the check_*
methods consume. The check_* method bodies are otherwise unchanged."
```

---

### Task 16: Update DI wiring in `ioc.py`

**Files:**
- Modify: `semvertag/ioc.py`
- Modify: `tests/unit/test_ioc.py` if it asserts on the provider's `client` field

- [ ] **Step 1: Update `_construct_gitlab_provider`**

Replace it in `semvertag/ioc.py`:

```python
def _construct_gitlab_provider(
    settings: Settings,
    transport: httpx2.BaseTransport,
) -> "GitLabProvider":
    from semvertag.providers._http import HttpClient  # noqa: PLC0415
    from semvertag.providers.gitlab import GitLabProvider, _translate_status  # noqa: PLC0415

    if settings.project_id is None:
        msg = "Project id missing. Set CI_PROJECT_ID or pass --project-id."
        raise ConfigError(msg)
    client: typing.Final = httpx2.Client(
        transport=transport,
        base_url=settings.gitlab.endpoint,
        timeout=settings.request_timeout,
    )
    project_id: typing.Final = settings.project_id
    http: typing.Final = HttpClient(
        client=client,
        auth_headers=lambda: {"PRIVATE-TOKEN": settings.gitlab.token.get_secret_value()},
        status_translator=lambda status: _translate_status(status, project_id),
    )
    return GitLabProvider(
        config=settings.gitlab,
        project_id=project_id,
        http=http,
    )
```

- [ ] **Step 2: Update `_close_provider_client` finalizer**

The finalizer needs to close the underlying httpx2 client, which now lives at `provider.http.client`:

```python
def _close_provider_client(provider: "GitLabProvider") -> None:
    provider.http.client.close()
```

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest -x -q`
Expected: 425+ PASS. Any failures here mean something missed in the refactor.

- [ ] **Step 4: Commit**

```bash
git add semvertag/ioc.py tests/unit/test_ioc.py
git commit -m "ioc: wire HttpClient into GitLabProvider construction

_construct_gitlab_provider now builds the HttpClient with the per-provider
auth-header and status-translator callables. The finalizer closes
provider.http.client (the underlying httpx2 client)."
```

---

### Task 17: Cleanup dead code in `gitlab.py`

**Files:**
- Modify: `semvertag/providers/gitlab.py`

- [ ] **Step 1: Scan for dead imports and helpers**

Run: `uv run ruff check semvertag/providers/gitlab.py`
Expected: warnings for any now-unused imports (e.g. possibly `httpx2` if no method references it directly any more) and unused helpers.

- [ ] **Step 2: Delete what's unused**

Delete any import or helper flagged by `ruff` as unused. Likely candidates after the refactor:
- `_safe_get` if no longer referenced (it might still be — the refactor kept it as a one-liner).
- `_request_failed_message` (subsumed by `HttpClient`).
- Possibly direct `httpx2` imports if no symbol from it is still referenced.

Do NOT delete:
- `_translate_status` — still called by `list_tags`, `create_tag`, and the wrapper-injected translator.
- Pagination helpers (`_next_page_url`, `_same_origin`, `_LINK_ENTRY_RE`, `_parse_rel_values`).
- HTTP status constants — still used by `create_tag` and `_translate_status`.

- [ ] **Step 3: Verify**

Run: `uv run ruff check semvertag/providers/gitlab.py`
Expected: no warnings.

Run: `uv run pytest -x -q`
Expected: 425+ PASS.

- [ ] **Step 4: Commit**

```bash
git add semvertag/providers/gitlab.py
git commit -m "providers: drop dead helpers superseded by HttpClient"
```

---

### Task 18: Pre-review verification gate

**Files:** none modified.

This is the `superpowers:verification-before-completion` gate. Run each command and capture its full output before claiming work complete.

- [ ] **Step 1: Lint**

Run: `just lint-ci`
Expected: all four checks (`eof-fixer`, `ruff format --check`, `ruff check --no-fix`, `ty check`) PASS.

- [ ] **Step 2: Full test suite**

Run: `uv run pytest`
Expected: 425+ tests PASS, no failures, no errors.

- [ ] **Step 3: Branch-coverage gates**

Run: `just test-branch-strategies`
Expected: 100% branch coverage on `semvertag.strategies.branch_prefix`.

Run: `just test-cc-strategies`
Expected: 100% branch coverage on `semvertag.strategies.conventional_commits`.

Run: `just test-doctor`
Expected: 100% branch coverage on `semvertag.doctor`.

- [ ] **Step 4: Provider branch coverage check (informal)**

Run: `uv run pytest -o "addopts=" --cov=semvertag.providers --cov-branch --cov-report=term-missing tests/`
Expected: 100% branch coverage on `semvertag.providers` (no Missing lines reported). If anything is missing, add a unit or integration test before proceeding.

- [ ] **Step 5: Docs build**

Run: `uv run mkdocs build --strict`
Expected: builds clean (~1s).

- [ ] **Step 6: LOC delta sanity check**

Run: `git diff main --stat -- semvertag/providers/gitlab.py`
Expected: net negative LOC of roughly ~150-200 lines on `gitlab.py`. If it's positive or near-zero, the wrapper isn't pulling weight — pause and review before requesting code review.

---

### Task 19: Code review via subagent

**Files:** none modified.

- [ ] **Step 1: Invoke `superpowers:requesting-code-review`**

Use the skill to dispatch a code-review subagent against the worktree branch. The subagent reviews the diff between `main` and `HEAD` of the worktree.

- [ ] **Step 2: Receive review via `superpowers:receiving-code-review`**

Use the receiving-code-review skill to process findings. Verify each finding rather than blindly accepting; address legitimate issues by adding new commits in the worktree.

- [ ] **Step 3: Re-run the verification gate (Task 18) if any code changed**

If the review prompted any code changes, re-run all of Task 18 before proceeding to land.

---

### Task 20: Land the worktree

**Files:** none modified by hand; merge/rebase + cleanup.

- [ ] **Step 1: Invoke `superpowers:finishing-a-development-branch`**

Use the skill to pick the right landing path (PR or fast-forward merge) and clean up the worktree afterward.

- [ ] **Step 2: Verify the wrapper work is on `main`**

Run (in the main checkout): `git log --oneline main..HEAD || git log --oneline -10`
Expected: the wrapper commits from the worktree are now in `main`'s history.

Run: `just lint-ci && uv run pytest`
Expected: all green on `main`.

---

## Success criteria (recap from spec)

When all tasks above are done:

- `_bmad/` is gone from the working tree (lives at `_archive/bmad/`).
- `planning/specs/` contains the migration spec.
- `planning/plans/` contains this plan (and `.gitkeep`).
- Repo-root `CLAUDE.md` exists and points at the Superpowers flow.
- `semvertag/providers/_http.py` contains `HttpClient`, used by every method in `gitlab.py` directly or via `_safe_get`.
- All existing tests pass; no behavior changes to the GitLab provider's external contract.
- `semvertag/providers/gitlab.py` is meaningfully shorter (target ~40–50% LOC reduction).
- Branch coverage on `semvertag.providers` remains at 100%.

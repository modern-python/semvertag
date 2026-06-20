---
status: shipped
date: 2026-06-16
slug: httpware-max-error-body-bytes
spec: httpware-max-error-body-bytes
pr: 26
---

# httpware-max-error-body-bytes — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build both provider HTTP clients with a 1 MiB `max_error_body_bytes`
cap and translate the resulting `ResponseTooLargeError` into a clear
`ProviderAPIError`.

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/httpware-max-error-body-bytes`

**Commit strategy:** Per-task commits (wiring, translation, docs).

**Context for an engineer new to this codebase:**

- Provider HTTP clients are built in `semvertag/ioc.py` by `_build_gitlab_client`
  and `_build_github_client`, each returning an `httpware.Client`. httpware
  0.12.0 is already a dependency.
- `httpware.Client(..., max_error_body_bytes=N)` makes the client raise
  `httpware.ResponseTooLargeError` on a 4xx/5xx whose declared `Content-Length`
  exceeds `N`, before reading the body. The cap is stored on the private
  attribute `client._max_error_body_bytes` (httpware exposes no public getter).
- `ResponseTooLargeError` is an `httpware.ClientError` subclass (NOT a
  `StatusError`). Its constructor is keyword-only:
  `httpware.ResponseTooLargeError(*, status_code: int, limit: int,
  content_length: int | None)`.
- Provider errors are translated to the semvertag domain hierarchy in
  `semvertag/providers/_errors.py`. `translate_gitlab` / `translate_github`
  route any non-`StatusError` `ClientError` to the shared `_translate_transport`,
  which currently ends in a generic fallback.
- Tests: `just test` runs the full suite with `--cov-branch` and
  `fail_under = 100` — every branch must be covered. The per-file fast loop is
  `just test <path> -p no:randomly --override-ini="addopts=" -q` (disables
  coverage + random ordering). `ruff` runs with `select = ["ALL"]` but
  `tests/**/*.py` already ignores `SLF001`, so reading private members
  (`ioc._build_*`, `client._max_error_body_bytes`) in tests needs no suppression.
- `just lint-ci` must pass (eof-fixer, ruff format, ruff check, ty).

---

### Task 1: Cap constant and client wiring

**Files:**
- Modify: `semvertag/ioc.py`
- Test: `tests/unit/test_ioc.py`

Add the cap constant and pass it to both client builders, test-first.

- [ ] **Step 1: Write the failing tests**

  Append to `tests/unit/test_ioc.py` (the imports `typing`, `httpware`, `ioc`,
  and the `_settings` helper already exist at the top of the file — reuse them):

  ```python
  def test_gitlab_client_is_built_with_error_body_cap() -> None:
      client: typing.Final = ioc._build_gitlab_client(_settings())
      assert client._max_error_body_bytes == ioc._MAX_ERROR_BODY_BYTES


  def test_github_client_is_built_with_error_body_cap() -> None:
      client: typing.Final = ioc._build_github_client(_settings())
      assert client._max_error_body_bytes == ioc._MAX_ERROR_BODY_BYTES


  def test_error_body_cap_is_one_mebibyte() -> None:
      assert ioc._MAX_ERROR_BODY_BYTES == 1024 * 1024
  ```

- [ ] **Step 2: Run the new tests, verify they fail**

  Run: `just test tests/unit/test_ioc.py -p no:randomly --override-ini="addopts=" -q`

  Expected: FAIL with `AttributeError: module 'semvertag.ioc' has no attribute
  '_MAX_ERROR_BODY_BYTES'` (the constant does not exist yet).

- [ ] **Step 3: Add the constant**

  In `semvertag/ioc.py`, add alongside the other module constants (after
  `_RETRY_STATUS_CODES`):

  ```python
  _MAX_ERROR_BODY_BYTES: typing.Final = 1024 * 1024  # 1 MiB — defensive cap on 4xx/5xx error bodies
  ```

- [ ] **Step 4: Pass the cap to both builders**

  In `_build_gitlab_client`, add the argument to the `httpware.Client(...)` call:

  ```python
  def _build_gitlab_client(settings: Settings) -> httpware.Client:
      return httpware.Client(
          base_url=settings.gitlab.endpoint,
          timeout=settings.request_timeout,
          headers={_GITLAB_TOKEN_HEADER: settings.gitlab.token.get_secret_value()},
          middleware=[httpware.Retry(retry_status_codes=_RETRY_STATUS_CODES)],
          max_error_body_bytes=_MAX_ERROR_BODY_BYTES,
      )
  ```

  In `_build_github_client`, add the same argument:

  ```python
  def _build_github_client(settings: Settings) -> httpware.Client:
      return httpware.Client(
          base_url=settings.github.endpoint,
          timeout=settings.request_timeout,
          headers={
              "Authorization": f"Bearer {settings.github.token.get_secret_value()}",
              "Accept": _GITHUB_ACCEPT,
              "X-GitHub-Api-Version": _GITHUB_API_VERSION,
          },
          middleware=[httpware.Retry(retry_status_codes=_RETRY_STATUS_CODES)],
          max_error_body_bytes=_MAX_ERROR_BODY_BYTES,
      )
  ```

- [ ] **Step 5: Run the ioc tests, verify they pass**

  Run: `just test tests/unit/test_ioc.py -p no:randomly --override-ini="addopts=" -q`
  Expected: PASS — the three new tests plus the existing ones green.

- [ ] **Step 6: Commit**

  ```bash
  git add semvertag/ioc.py tests/unit/test_ioc.py
  git commit -m "providers: cap provider error-body reads at 1 MiB

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Translate ResponseTooLargeError

**Files:**
- Modify: `semvertag/providers/_errors.py`
- Test: `tests/unit/test_providers_errors.py`

Map `ResponseTooLargeError` to an actionable `ProviderAPIError`, test-first.

- [ ] **Step 1: Write the failing tests**

  Append to `tests/unit/test_providers_errors.py` (the imports `httpware`,
  `ProviderAPIError`, `translate_gitlab`, `translate_github`, and the constant
  `_PROJECT_ID` already exist at the top of the file — reuse them):

  ```python
  def test_translate_gitlab_response_too_large_becomes_provider_api_error() -> None:
      exc = httpware.ResponseTooLargeError(status_code=413, limit=1_048_576, content_length=5_000_000)
      result = translate_gitlab(exc, project_id=_PROJECT_ID)
      assert isinstance(result, ProviderAPIError)
      assert "GitLab" in str(result)
      assert "5000000" in str(result)
      assert "1048576" in str(result)


  def test_translate_github_response_too_large_becomes_provider_api_error() -> None:
      exc = httpware.ResponseTooLargeError(status_code=413, limit=1_048_576, content_length=5_000_000)
      result = translate_github(exc, repo="owner/repo")
      assert isinstance(result, ProviderAPIError)
      assert "GitHub" in str(result)
      assert "5000000" in str(result)
  ```

- [ ] **Step 2: Run the new tests, verify they fail**

  Run: `just test tests/unit/test_providers_errors.py -p no:randomly --override-ini="addopts=" -q`

  Expected: FAIL with `AssertionError`. `ResponseTooLargeError` is a
  `ClientError`, so it currently falls through `_translate_transport` to the
  generic fallback `"GitLab request failed: ResponseTooLargeError"`, which
  contains neither `"5000000"` nor `"1048576"`.

- [ ] **Step 3: Add the translation branch**

  In `semvertag/providers/_errors.py`, inside `_translate_transport`, add a
  branch before the final `return` fallback (placement among the other
  `isinstance` branches is fine — the types are disjoint):

  ```python
      if isinstance(exc, httpware.ResponseTooLargeError):
          return ProviderAPIError(
              f"{provider_label} returned an error response body of {exc.content_length} bytes, "
              f"exceeding the {exc.limit}-byte cap (HTTP {exc.status_code}); refusing to read it."
          )
  ```

  For reference, the function becomes:

  ```python
  def _translate_transport(exc: httpware.ClientError, *, provider_label: str) -> Exception:
      if isinstance(exc, httpware.DecodeError):
          return ProviderAPIError(f"{provider_label} {exc.model.__name__} response could not be decoded: {exc.original}")
      if isinstance(exc, httpware.TimeoutError):
          return ProviderAPIError(f"{provider_label} request timed out. Try again or increase SEMVERTAG_REQUEST_TIMEOUT.")
      if isinstance(exc, httpware.RetryBudgetExhaustedError):
          return ProviderAPIError(f"{provider_label} retries exhausted after {exc.attempts} attempts. Try again later.")
      if isinstance(exc, httpware.NetworkError):
          return ProviderAPIError(f"{provider_label} unreachable. Check network connectivity.")
      if isinstance(exc, httpware.ResponseTooLargeError):
          return ProviderAPIError(
              f"{provider_label} returned an error response body of {exc.content_length} bytes, "
              f"exceeding the {exc.limit}-byte cap (HTTP {exc.status_code}); refusing to read it."
          )
      return ProviderAPIError(f"{provider_label} request failed: {type(exc).__name__}")
  ```

- [ ] **Step 4: Run the error tests, verify they pass**

  Run: `just test tests/unit/test_providers_errors.py -p no:randomly --override-ini="addopts=" -q`
  Expected: PASS — both new tests plus the existing ones green.

- [ ] **Step 5: Run the full gated suite and lint**

  Run: `just test`
  Expected: PASS — full suite green at 100% branch coverage (the new branch's
  taken path is covered by both new translation tests).

  Run: `just lint-ci`
  Expected: PASS — eof-fixer, ruff format, ruff check, ty all clean.

- [ ] **Step 6: Commit**

  ```bash
  git add semvertag/providers/_errors.py tests/unit/test_providers_errors.py
  git commit -m "providers: translate ResponseTooLargeError to ProviderAPIError

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Document the cap

**Files:**
- Modify: `architecture/providers.md`

Promote the hardening into the capability doc.

- [ ] **Step 1: Update `architecture/providers.md`**

  In the HTTP-client section (the `## HTTP client` heading near the end of the
  file), add a sentence noting the cap. Match the surrounding prose style:

  > Both clients are built with a 1 MiB `max_error_body_bytes` cap
  > (`semvertag/ioc.py`): httpware raises `ResponseTooLargeError` on a 4xx/5xx
  > whose declared `Content-Length` exceeds the cap, before reading the body, as
  > a defensive bound against a hostile or malfunctioning endpoint. The error is
  > an `httpware.ClientError` (not a `StatusError`), so `_translate_transport`
  > maps it to `ProviderAPIError`. Real GitLab/GitHub error bodies are tiny JSON
  > and never approach the cap.

- [ ] **Step 2: Verify the docs build**

  Run: `just docs-build`
  Expected: PASS — strict mkdocs build with no warnings. (`architecture/` is
  outside the mkdocs site, so this mainly confirms nothing else broke; run it
  anyway as the docs gate.)

- [ ] **Step 3: Commit**

  ```bash
  git add architecture/providers.md
  git commit -m "docs: note the 1 MiB provider error-body cap

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

## Notes for finishing

- Lane **full** (`design.md` + `plan.md`). On merge: move the bundle to
  `planning/changes/` with `status: shipped`, `pr:`, `outcome:` filled;
  confirm the `architecture/providers.md` edit landed; and remove the
  "httpware bounded-error-body adoption" item from `planning/deferred.md` (this
  change resolves it).

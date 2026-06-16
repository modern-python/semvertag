---
status: shipped
date: 2026-06-16
slug: httpware-max-error-body-bytes
supersedes: null
superseded_by: null
pr: 26
outcome: Shipped. Both provider clients built with a 1 MiB max_error_body_bytes
  cap; ResponseTooLargeError translates to ProviderAPIError (None-length
  guarded). Conclusions promoted into architecture/providers.md.
---

# Design: Bound provider error-body reads (httpware max_error_body_bytes)

## Summary

Adopt httpware 0.11.0's opt-in `max_error_body_bytes` cap when constructing the
GitLab and GitHub clients, set to a hardcoded **1 MiB**. With the cap set,
httpware raises `ResponseTooLargeError` on a 4xx/5xx whose declared
`Content-Length` exceeds the limit, *before* reading the body — a defensive
bound against a misbehaving or hostile endpoint returning an oversized error
body. A new branch in `_translate_transport` maps that error to a clear
`ProviderAPIError`. No new configuration surface; behavior for real
GitLab/GitHub responses (tiny JSON) is unchanged.

## Motivation

The 0.12.0 bump
([httpware-0.12-get-with-response](../../archive/2026-06-16.01-httpware-0.12-get-with-response/change.md),
#24) consciously deferred this: picking a cap value is a judgment call, not a
mechanical bump. Both providers read a 4xx/5xx error body to surface a message
(and to distinguish "already exists" on tag creation). Today that read is
unbounded — a compromised or malfunctioning endpoint (or a misconfigured
`SEMVERTAG_*__ENDPOINT` pointed at a hostile host) could return a multi-megabyte
or unbounded error body that bloats memory and logs. httpware 0.11.0 added an
opt-in guard for exactly this; semvertag should use it.

## Non-goals

- No new setting or CLI flag. The cap is a defensive constant, not an operator
  tuning knob — real GitLab/GitHub error bodies are orders of magnitude smaller
  than any sane cap, so there is nothing to tune.
- Not bounding *success* response bodies (tag lists, commits). Those are
  paginated and already bounded by `per_page` + the `_MAX_TAG_PAGES` cap; this
  change is strictly about error bodies.
- Not closing the chunked-body gap. httpware's cap keys on a declared
  `Content-Length`; a chunked error body with no declared length is still read.
  That deeper bound is httpware's concern, tracked upstream.

## Design

### 1. Cap constant and client wiring

Add a module constant to `semvertag/ioc.py` and pass it to both client builders:

```python
_MAX_ERROR_BODY_BYTES: typing.Final = 1024 * 1024  # 1 MiB — defensive cap on 4xx/5xx error bodies
```

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

`_build_github_client` gets the same `max_error_body_bytes=_MAX_ERROR_BODY_BYTES`
argument. **1 MiB** is ~200× the largest plausible GitLab/GitHub JSON error body,
so it never trips in normal operation while still bounding a pathological
multi-MB/GB body; the memory cost is irrelevant for a one-shot CLI.

### 2. Error translation

`ResponseTooLargeError` is an `httpware.ClientError` subclass (not a
`StatusError`), so it already routes through `_translate_transport` in
`semvertag/providers/_errors.py`. Add an explicit branch *before* the generic
fallback so the message is actionable rather than `"<provider> request failed:
ResponseTooLargeError"`:

```python
def _translate_transport(exc: httpware.ClientError, *, provider_label: str) -> Exception:
    if isinstance(exc, httpware.DecodeError):
        ...
    if isinstance(exc, httpware.ResponseTooLargeError):
        return ProviderAPIError(
            f"{provider_label} returned an error response body of {exc.content_length} bytes, "
            f"exceeding the {exc.limit}-byte cap (HTTP {exc.status_code}); refusing to read it."
        )
    ...
    return ProviderAPIError(f"{provider_label} request failed: {type(exc).__name__}")
```

`ResponseTooLargeError(*, status_code, limit, content_length)` carries the three
values the message uses. Placement among the other transport branches does not
matter for correctness (the types are disjoint); putting it alongside the others
keeps the function's shape consistent.

### 3. Behavioral trade-off

When the cap trips, httpware raises `ResponseTooLargeError` *instead of* the
normal `StatusError`, so that one pathological response loses its specific
mapping (e.g. 401 → `AuthError`, a 400 "already exists" → `ConfigError`) and
surfaces as a generic `ProviderAPIError`. This is acceptable: a real
GitLab/GitHub error body never approaches 1 MiB, so the only responses that hit
this path are pathological, and "the server returned an absurdly large error
body" is the right thing to report about them.

## Testing

Global pytest config runs `--cov-branch` with `fail_under = 100`, so the new
`_translate_transport` branch must be covered.

- **Translation** (`tests/unit/test_providers_errors.py`): construct
  `httpware.ResponseTooLargeError(status_code=413, limit=1_048_576,
  content_length=5_000_000)`, pass it through `translate_gitlab(exc,
  project_id=...)` and `translate_github(exc, repo=...)`, and assert each returns
  a `ProviderAPIError` whose message contains the byte counts and the provider
  label. Covers the new branch for both providers.
- **Wiring** (`tests/unit/test_ioc.py`): assert
  `_build_gitlab_client(settings)._max_error_body_bytes == _MAX_ERROR_BODY_BYTES`
  and the same for `_build_github_client`. httpware exposes the cap only as the
  private `_max_error_body_bytes`; reading it in a test is fine —
  `tests/**/*.py` already ignores `SLF001` in the ruff config.
- **No behavioral cap test.** Faking a large declared `Content-Length` through
  `httpx2.MockTransport` does not work — httpx2 normalizes the header to the
  actual body size, so the cap never sees an oversized length and the mocked
  4xx/5xx surfaces as an ordinary `StatusError`. The cap mechanism itself is
  httpware's tested concern; semvertag tests cover the wiring and the
  translation only.

## Docs

- `architecture/providers.md` — in the HTTP-client section, note that both
  clients are built with a 1 MiB `max_error_body_bytes` cap and that
  `ResponseTooLargeError` translates to `ProviderAPIError` via
  `_translate_transport`.
- No user-facing docs change: the cap is internal and not configurable.

## Risk

Low. The cap is far above any real error body, so normal operation is
byte-for-byte unchanged; the only observable difference is on pathological
oversized error responses, which previously read unbounded and now fail fast
with a clear message. The single new branch is covered by the 100%-branch gate.
No rollback concern — removing the `max_error_body_bytes` argument restores the
prior unbounded read.

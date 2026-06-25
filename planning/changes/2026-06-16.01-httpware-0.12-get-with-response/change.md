---
summary: "Bump httpware to 0.12.0; adopt `get_with_response` at the pagination call sites."
---

# Change: Bump httpware to 0.12.0 and adopt get_with_response in pagination

**Lane:** lightweight — net change is a dependency-floor bump plus a two-line
mechanical refactor at the two pagination call sites. Four files touched, but
`pyproject.toml` + `uv.lock` are dependency config and the code delta is a
straight 1:1 method swap with no behavior change. No public-API change.

## Goal

We pin `httpware[pydantic]>=0.8.2` (lock 0.8.2) while latest is 0.12.0 — every
intervening release is additive/no-break. Raise the floor to `>=0.12.0` and
adopt 0.12.0's `get_with_response`, which collapses the
`send_with_response(build_request("GET", ...))` pair used for Link-header
pagination into a single call. Picks up 0.11.0's security/correctness hardening
(URL secret redaction, RetryBudget fix) for free via the version move.

## Approach

`get_with_response(url, *, params=..., response_model=...) -> tuple[Response, T]`
is the ergonomic shortcut for "raw response + typed body in one call" — exactly
the pagination shape in both providers. Swap the two call sites; behavior is
identical (same request, same returned `(response, page)` tuple), so existing
pagination tests stay green. No `architecture/` contract moves — the providers'
external behavior is unchanged; the HTTP-client prose in `providers.md` does not
name `send_with_response`/`build_request`, so no doc edit is required.

Deferred (not in this bundle): adopting `max_error_body_bytes` /
`ResponseTooLargeError` from 0.11.0 — that's a real behavior/config decision.

## Files

- `pyproject.toml` — `httpware[pydantic]>=0.8.2` → `>=0.12.0`
- `uv.lock` — relock via `uv lock`
- `semvertag/providers/gitlab.py` — `list_tags` call site → `get_with_response`
- `semvertag/providers/github.py` — `list_tags` call site → `get_with_response`

## Verification

- [x] `uv lock` resolves httpware to 0.12.0.
- [x] Refactor both call sites to `get_with_response`.
- [x] `just test` — 428 passed (existing pagination tests cover behavior).
- [x] `just lint-ci` — clean (ruff format, ruff check, ty all pass).

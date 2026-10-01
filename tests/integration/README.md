# Integration test notes

## Mocking the HTTP transport

Integration tests inject `httpx2.MockTransport` into the production `httpware.Client` so the GitLab provider can be exercised end-to-end without a real GitLab.

Two seams exist, depending on the test entry point:

- **CLI-level tests** (`test_cli_*.py`) drive `semvertag.__main__` through Typer's `CliRunner` and let the DI container build the production stack. They override `ioc.ProvidersGroup.gitlab_client` with a mock-backed `httpware.Client` via the `install_mock_transport` fixture in `conftest.py`.
- **Provider-level tests** (`test_gitlab_provider.py`) bypass the container and call the `_make_provider(handler)` helper, which constructs an `httpware.Client(transport=httpx2.MockTransport(handler), base_url=...)` directly.

## Disabling retry sleeps

Retry-exhaustion paths (`test_raises_provider_api_error_on_5xx`, `..._on_429`, the exit-4 cases in `test_cli_quiet_json_matrix.py`) would otherwise wait on `httpware.Retry`'s full-jitter backoff. The standard fix is to monkeypatch the stdlib sleep used by `httpware.middleware.resilience.retry`:

```python
monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)
```

Patching the global `time.sleep` is equivalent to patching `httpware.middleware.resilience.retry.time.sleep` because that module imports `time` and references `time.sleep` via the module attribute. If a future `httpware` refactor changes the binding shape (e.g. `from time import sleep`), this monkeypatch will silently break — tests will pass but take seconds longer.

If `httpware.Retry` ever grows an injectable `_sleep` parameter, prefer that over the monkeypatch — it closes the coupling.

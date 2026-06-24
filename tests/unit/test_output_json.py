import dataclasses
import io
import json
import re
import sys
import typing

import pytest
import rich.console

from semvertag._outcome import Created, NoBump
from semvertag._output import JsonOutput
from semvertag._types import Bump, RunResult


_GITLAB_TOKEN: typing.Final = "glpat-AbCdEf1234567890ABCD"
_REDACTED: typing.Final = "***"
_ERROR_MESSAGE: typing.Final = "ConfigError: bad config"
_SNAKE_CASE_RE: typing.Final = re.compile(r"^[a-z][a-z0-9_]*$")
_EXPECTED_KEY_ORDER: typing.Final = (
    "schema_version",
    "strategy",
    "bump",
    "status",
    "tag",
    "commit",
    "reason",
)
# RunResult kept for the DTO-shape tests (positional/frozen); the wire envelope
# is now produced from Outcome variants via JsonOutput.emit.
_CREATED_RESULT: typing.Final = RunResult(
    strategy="branch-prefix",
    bump="minor",
    status="created",
    tag="1.2.0",
    commit="a2b4d12abc1234567890",
    reason=None,
)
_STRATEGY: typing.Final = "branch-prefix"
_CREATED_OUTCOME: typing.Final = Created(tag="1.2.0", bump=Bump.MINOR, commit="a2b4d12abc1234567890")
_NO_BUMP_OUTCOME: typing.Final = NoBump(
    status="no_merge_commit", reason="no_merge_commit", commit="a2b4d12abc1234567890"
)


def _make_json_output(*, quiet: bool = False) -> tuple[JsonOutput, io.StringIO]:
    stderr_buf: typing.Final = io.StringIO()
    error_console: typing.Final = rich.console.Console(
        file=stderr_buf,
        force_terminal=False,
        color_system=None,
    )
    return JsonOutput(error_console=error_console, quiet=quiet), stderr_buf


@pytest.mark.parametrize("quiet", [False, True])
def test_progress_is_no_op_regardless_of_quiet(
    monkeypatch: pytest.MonkeyPatch,
    quiet: bool,
) -> None:
    output, _stderr = _make_json_output(quiet=quiet)
    stdout_buf: typing.Final = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    output.progress("anything")
    assert stdout_buf.getvalue() == ""


def test_emit_writes_exactly_one_json_line(monkeypatch: pytest.MonkeyPatch) -> None:
    output, _stderr = _make_json_output()
    stdout_buf: typing.Final = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    output.emit(_CREATED_OUTCOME, strategy=_STRATEGY)
    raw: typing.Final = stdout_buf.getvalue()
    assert raw.endswith("\n")
    lines: typing.Final = [line for line in raw.split("\n") if line]
    assert len(lines) == 1
    parsed: typing.Final = json.loads(lines[0])
    assert parsed["tag"] == "1.2.0"


def test_emit_envelope_has_schema_version_first(monkeypatch: pytest.MonkeyPatch) -> None:
    output, _stderr = _make_json_output()
    stdout_buf: typing.Final = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    output.emit(_CREATED_OUTCOME, strategy=_STRATEGY)
    parsed: typing.Final = json.loads(stdout_buf.getvalue())
    keys: typing.Final = list(parsed.keys())
    assert keys[0] == "schema_version"
    assert parsed["schema_version"] == "1.0"


def test_emit_envelope_keys_are_snake_case(monkeypatch: pytest.MonkeyPatch) -> None:
    output, _stderr = _make_json_output()
    stdout_buf: typing.Final = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    output.emit(_CREATED_OUTCOME, strategy=_STRATEGY)
    parsed: typing.Final = json.loads(stdout_buf.getvalue())
    for key in parsed:
        assert _SNAKE_CASE_RE.match(key), f"key not snake_case: {key!r}"


def test_emit_envelope_renders_null_for_unset_optional_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, _stderr = _make_json_output()
    stdout_buf: typing.Final = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    output.emit(_NO_BUMP_OUTCOME, strategy=_STRATEGY)
    raw: typing.Final = stdout_buf.getvalue()
    assert '"tag":null' in raw
    parsed: typing.Final = json.loads(raw)
    assert parsed["tag"] is None
    assert parsed["commit"] == "a2b4d12abc1234567890"


def test_emit_envelope_order_matches_dataclass_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, _stderr = _make_json_output()
    stdout_buf: typing.Final = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    output.emit(_CREATED_OUTCOME, strategy=_STRATEGY)
    parsed: typing.Final = json.loads(stdout_buf.getvalue())
    assert tuple(parsed.keys()) == _EXPECTED_KEY_ORDER


def test_error_writes_to_stderr_as_plain_text_not_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, stderr_buf = _make_json_output()
    stdout_buf: typing.Final = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    output.error(_ERROR_MESSAGE)
    assert _ERROR_MESSAGE in stderr_buf.getvalue()
    assert stdout_buf.getvalue() == ""
    with pytest.raises(json.JSONDecodeError):
        json.loads(stderr_buf.getvalue())


@pytest.mark.parametrize("quiet", [False, True])
def test_json_matrix_keeps_stdout_pure_json(
    monkeypatch: pytest.MonkeyPatch,
    quiet: bool,
) -> None:
    output, stderr_buf = _make_json_output(quiet=quiet)
    stdout_buf: typing.Final = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    output.progress("p")
    output.emit(_CREATED_OUTCOME, strategy=_STRATEGY)
    output.error(_ERROR_MESSAGE)
    stdout_text: typing.Final = stdout_buf.getvalue()
    lines: typing.Final = [line for line in stdout_text.split("\n") if line]
    assert len(lines) == 1
    json.loads(lines[0])
    assert _ERROR_MESSAGE in stderr_buf.getvalue()


def test_redacts_tokens_in_error_message() -> None:
    output, stderr_buf = _make_json_output()
    output.error(f"failure with {_GITLAB_TOKEN}")
    stderr_text: typing.Final = stderr_buf.getvalue()
    assert _GITLAB_TOKEN not in stderr_text
    assert _REDACTED in stderr_text


def test_run_result_rejects_positional_construction() -> None:
    with pytest.raises(TypeError):
        RunResult("conv", "minor", "created", "1.0.0", "abc", None)  # ty: ignore[too-many-positional-arguments, missing-argument]


def test_run_result_rejects_field_mutation() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _CREATED_RESULT.tag = "2.0.0"  # ty: ignore[invalid-assignment]

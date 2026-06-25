"""Structural validator for templates/semvertag.yml.

Shared between the `.github/workflows/ci.yml` lint step and the
regression test fixtures in test_ci_descriptor_gate.py so the gate
and its tests cannot drift.
"""

import pathlib
import sys
import typing

import yaml


_DIGEST_MARKER: typing.Final = "@sha256:"
_VERSION_MARKER: typing.Final = "@v"
_SUBSTITUTION_LITERAL: typing.Final = "$[[ inputs.strategy ]]"
_EXPECTED_OPTIONS: typing.Final = {"branch-prefix", "conventional-commits"}
_EXPECTED_DOC_COUNT: typing.Final = 2
_EXPECTED_ARGV_LEN: typing.Final = 2


class DescriptorGateError(SystemExit):
    """Raised when the descriptor's shape is wrong; subclasses SystemExit so the gate exits non-zero."""

    def __init__(self, message: str) -> None:
        super().__init__(f"templates/semvertag.yml gate FAILED: {message}")


def _require(condition: object, message: str) -> None:
    if not condition:
        raise DescriptorGateError(message)


def validate(path: str) -> None:
    """Raise DescriptorGateError on any structural violation; return None on success."""
    with pathlib.Path(path).open(encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))

    _require(
        len(docs) == _EXPECTED_DOC_COUNT,
        f"expected {_EXPECTED_DOC_COUNT} YAML docs (spec + body), got {len(docs)}",
    )
    spec, body = docs

    _require(isinstance(spec, dict), f"first doc must be a mapping, got {type(spec).__name__}")
    _require("spec" in spec, "first doc missing top-level 'spec' key")
    _require(isinstance(spec.get("spec"), dict), "'spec' must be a mapping")
    _require("inputs" in spec["spec"], "spec.inputs missing")

    inputs = spec["spec"]["inputs"]
    _require(isinstance(inputs, dict), f"spec.inputs must be a mapping, got {type(inputs).__name__}")
    _require(set(inputs) == {"strategy"}, f"expected inputs={{strategy}}, got {sorted(inputs)}")

    s = inputs["strategy"]
    _require(isinstance(s, dict), "spec.inputs.strategy must be a mapping")
    _require(s.get("type") == "string", f"spec.inputs.strategy.type must be 'string', got {s.get('type')!r}")
    _require(
        s.get("default") == "branch-prefix",
        f"spec.inputs.strategy.default must be 'branch-prefix', got {s.get('default')!r}",
    )
    _require(
        set(s.get("options", [])) == _EXPECTED_OPTIONS,
        f"spec.inputs.strategy.options must equal {sorted(_EXPECTED_OPTIONS)}, got {sorted(s.get('options', []))}",
    )

    _require(isinstance(body, dict), f"second doc must be a mapping, got {type(body).__name__}")
    _require("semvertag" in body, "job 'semvertag' missing from body")

    job = body["semvertag"]
    _require(isinstance(job, dict), "body.semvertag must be a mapping")
    for key in ("image", "resource_group", "variables", "before_script", "script"):
        _require(key in job, f"job.{key} missing")

    image = job["image"]
    _require(
        isinstance(image, str) and _DIGEST_MARKER in image,
        f"job.image must be digest-pinned (contain '{_DIGEST_MARKER}'), got {image!r}",
    )

    _require(
        job.get("resource_group") == "semvertag",
        f"job.resource_group must be 'semvertag', got {job.get('resource_group')!r}",
    )

    strategy_var = job["variables"].get("SEMVERTAG_STRATEGY")
    _require(
        strategy_var == _SUBSTITUTION_LITERAL,
        f"job.variables.SEMVERTAG_STRATEGY must be exactly {_SUBSTITUTION_LITERAL!r}, got {strategy_var!r}",
    )

    before_script = job["before_script"]
    _require(
        isinstance(before_script, list) and before_script,
        f"job.before_script must be a non-empty list, got {before_script!r}",
    )
    _require(
        ">=" in before_script[0] or "==" in before_script[0],
        f"job.before_script[0] must pin the uv version (contain '>=' or '=='), got {before_script[0]!r}",
    )

    script = job["script"]
    _require(isinstance(script, list) and script, f"job.script must be a non-empty list, got {script!r}")
    first = script[0]
    _require(
        ">=" in first or "==" in first or _VERSION_MARKER in first,
        f"job.script[0] must pin the semvertag version (contain '>=', '==', or '{_VERSION_MARKER}'), got {first!r}",
    )


def main(argv: list[str]) -> None:
    if len(argv) != _EXPECTED_ARGV_LEN:
        raise DescriptorGateError(f"usage: python -m tests._descriptor_gate <path>; got {argv!r}")
    validate(argv[1])
    sys.stdout.write(f"{argv[1]} shape OK\n")


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv)

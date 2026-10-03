"""Structural validator for templates/semvertag.yml, run by test_ci_descriptor_gate.py."""

import pathlib
import re
import typing

import yaml


_DIGEST_MARKER: typing.Final = "@sha256:"
_VERSION_MARKER: typing.Final = "@v"
_SUBSTITUTION_LITERAL: typing.Final = "$[[ inputs.strategy ]]"
_DRY_RUN_LITERAL: typing.Final = "$[[ inputs.dry-run ]]"
_DRY_RUN_FLAG: typing.Final = "--dry-run"
_SEMVERTAG_FLOOR_PATTERN: typing.Final = re.compile(r"semvertag(?:>=|==|@v)(\d+(?:\.\d+)*)")
_MIN_SEMVERTAG: typing.Final = (0, 5, 0)
_EXPECTED_OPTIONS: typing.Final = {"branch-prefix", "conventional-commits"}
_EXPECTED_DOC_COUNT: typing.Final = 2


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
    _require(
        set(inputs) == {"strategy", "dry-run"},
        f"expected inputs={{dry-run, strategy}}, got {sorted(inputs)}",
    )

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

    d = inputs["dry-run"]
    _require(isinstance(d, dict), "spec.inputs.dry-run must be a mapping")
    _require(d.get("type") == "boolean", f"spec.inputs.dry-run.type must be 'boolean', got {d.get('type')!r}")
    _require(d.get("default") is False, f"spec.inputs.dry-run.default must be False, got {d.get('default')!r}")

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
    _require(
        _DRY_RUN_LITERAL in first and _DRY_RUN_FLAG in first,
        f"job.script[0] must map inputs.dry-run onto {_DRY_RUN_FLAG} (contain {_DRY_RUN_LITERAL!r}), got {first!r}",
    )
    floor = _SEMVERTAG_FLOOR_PATTERN.search(first)
    parts = tuple(int(n) for n in floor.group(1).split(".")) if floor else ()
    _require(
        parts + (0,) * (len(_MIN_SEMVERTAG) - len(parts)) >= _MIN_SEMVERTAG,
        f"job.script[0] semvertag floor must be >= {'.'.join(map(str, _MIN_SEMVERTAG))} "
        f"(first release with {_DRY_RUN_FLAG}), got {first!r}",
    )

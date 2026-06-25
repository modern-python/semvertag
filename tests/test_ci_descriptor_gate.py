"""Regression tests for the shared descriptor-shape gate in tests/_descriptor_gate.py.

Authored as part of Story 4.3b code review (Constraint 7 exception
granted at code-review time on 2026-05-30) so the CI gate gains a
committed negative-test fixture instead of relying on the dev's
informal manual mutation check.
"""

import pathlib
import typing

import pytest
import yaml

from tests._descriptor_gate import DescriptorGateError, main, validate


_REPO_ROOT: typing.Final = pathlib.Path(__file__).parent.parent
_DESCRIPTOR_PATH: typing.Final = _REPO_ROOT / "templates" / "semvertag.yml"


@pytest.fixture
def shipped_descriptor_docs() -> list[typing.Any]:
    with _DESCRIPTOR_PATH.open(encoding="utf-8") as f:
        return list(yaml.safe_load_all(f))


def _write_descriptor(tmp_path: pathlib.Path, docs: list[typing.Any]) -> pathlib.Path:
    target = tmp_path / "semvertag.yml"
    with target.open("w", encoding="utf-8") as f:
        yaml.safe_dump_all(docs, f, sort_keys=False)
    return target


def test_shipped_descriptor_passes() -> None:
    """Positive case: the descriptor we actually ship must pass the gate."""
    validate(str(_DESCRIPTOR_PATH))


def test_missing_options_key_fails(tmp_path: pathlib.Path, shipped_descriptor_docs: list[typing.Any]) -> None:
    """Negative: drop spec.inputs.strategy.options → gate raises with a useful message."""
    spec, body = shipped_descriptor_docs
    del spec["spec"]["inputs"]["strategy"]["options"]
    bad = _write_descriptor(tmp_path, [spec, body])
    with pytest.raises(DescriptorGateError, match="options must equal"):
        validate(str(bad))


def test_missing_default_key_fails(tmp_path: pathlib.Path, shipped_descriptor_docs: list[typing.Any]) -> None:
    """Negative: drop spec.inputs.strategy.default → gate raises with a useful message."""
    spec, body = shipped_descriptor_docs
    del spec["spec"]["inputs"]["strategy"]["default"]
    bad = _write_descriptor(tmp_path, [spec, body])
    with pytest.raises(DescriptorGateError, match="default must be 'branch-prefix'"):
        validate(str(bad))


def test_single_document_layout_fails(tmp_path: pathlib.Path) -> None:
    """Negative: collapse to a single YAML document (no `---` separator) → gate detects mis-shape."""
    bad = tmp_path / "semvertag.yml"
    bad.write_text(
        "spec:\n"
        "  inputs:\n"
        "    strategy:\n"
        "      type: string\n"
        "      default: branch-prefix\n"
        "      options: [branch-prefix, conventional-commits]\n"
        "semvertag:\n"
        "  image: python:3.13-slim@sha256:abc\n"
        "  resource_group: semvertag\n"
        "  variables:\n"
        "    SEMVERTAG_STRATEGY: '$[[ inputs.strategy ]]'\n"
        "  before_script: [\"pip install 'uv>=0.4,<1'\"]\n"
        "  script: [\"uvx 'semvertag>=1,<2'\"]\n",
        encoding="utf-8",
    )
    with pytest.raises(DescriptorGateError, match="expected 2 YAML docs"):
        validate(str(bad))


def test_wrong_substitution_syntax_fails(tmp_path: pathlib.Path, shipped_descriptor_docs: list[typing.Any]) -> None:
    """Negative: GitHub-style ${{ }} substitution instead of GitLab $[[ ]] → gate catches AP1 footgun."""
    spec, body = shipped_descriptor_docs
    body["semvertag"]["variables"]["SEMVERTAG_STRATEGY"] = "${{ inputs.strategy }}"
    bad = _write_descriptor(tmp_path, [spec, body])
    with pytest.raises(DescriptorGateError, match="SEMVERTAG_STRATEGY must be exactly"):
        validate(str(bad))


def test_missing_resource_group_fails(tmp_path: pathlib.Path, shipped_descriptor_docs: list[typing.Any]) -> None:
    """Negative: drop resource_group → gate raises (D2 concurrency protection regression-proof)."""
    spec, body = shipped_descriptor_docs
    del body["semvertag"]["resource_group"]
    bad = _write_descriptor(tmp_path, [spec, body])
    with pytest.raises(DescriptorGateError, match=r"job.resource_group missing"):
        validate(str(bad))


def test_unpinned_image_fails(tmp_path: pathlib.Path, shipped_descriptor_docs: list[typing.Any]) -> None:
    """Negative: drop the @sha256 digest → gate raises (D1 pinning regression-proof)."""
    spec, body = shipped_descriptor_docs
    body["semvertag"]["image"] = "python:3.13-slim"
    bad = _write_descriptor(tmp_path, [spec, body])
    with pytest.raises(DescriptorGateError, match="digest-pinned"):
        validate(str(bad))


def test_unpinned_uv_fails(tmp_path: pathlib.Path, shipped_descriptor_docs: list[typing.Any]) -> None:
    """Negative: drop the uv version specifier → gate raises (D1 pinning regression-proof)."""
    spec, body = shipped_descriptor_docs
    body["semvertag"]["before_script"] = ["pip install --quiet --no-cache-dir uv"]
    bad = _write_descriptor(tmp_path, [spec, body])
    with pytest.raises(DescriptorGateError, match=r"before_script.* must pin the uv version"):
        validate(str(bad))


def test_unpinned_semvertag_fails(tmp_path: pathlib.Path, shipped_descriptor_docs: list[typing.Any]) -> None:
    """Negative: drop the semvertag version specifier → gate raises (D1 pinning regression-proof)."""
    spec, body = shipped_descriptor_docs
    body["semvertag"]["script"] = ["uvx semvertag"]
    bad = _write_descriptor(tmp_path, [spec, body])
    with pytest.raises(DescriptorGateError, match=r"script.* must pin the semvertag version"):
        validate(str(bad))


def test_main_prints_shape_ok_for_valid_descriptor(capsys: pytest.CaptureFixture[str]) -> None:
    main(["_descriptor_gate", str(_DESCRIPTOR_PATH)])
    captured: typing.Final = capsys.readouterr()
    assert captured.out == f"{_DESCRIPTOR_PATH} shape OK\n"


def test_main_raises_when_argv_length_wrong() -> None:
    with pytest.raises(DescriptorGateError, match=r"usage: python -m tests\._descriptor_gate"):
        main(["_descriptor_gate"])

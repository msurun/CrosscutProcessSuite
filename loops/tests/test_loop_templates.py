"""Guard declarative loop templates, their schema contract and the PRODUCT 4.1 table.

The literal snapshot preserves the loop-type knowledge the product document describes:
process kind, tuning rule and default test step for every shipped type.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_loops.loop_templates import (
    LoopTemplateError,
    load_loop_templates,
    validate_loop_template,
)
from jsonschema import Draft202012Validator

PRODUCT_TABLE = {
    "flow": ("self_regulating", "simc", 5.0),
    "pressure": ("self_regulating", "simc", 5.0),
    "level_tight": ("integrating", "simc", 3.0),
    "level_averaging": ("integrating", "simc", 2.0),
    "temperature": ("self_regulating", "simc", 5.0),
    "density": ("self_regulating", "simc", 5.0),
    "composition": ("self_regulating", "simc", 3.0),
    "speed": ("self_regulating", "simc", 5.0),
    "cascade": ("self_regulating", "simc", 3.0),
    "ratio": ("self_regulating", "simc", 5.0),
    "feedforward": ("self_regulating", "simc", 3.0),
}


def test_declarative_templates_match_the_product_table() -> None:
    """Every PRODUCT 4.1 loop type exists with its process kind, rule and default step."""
    loaded = load_loop_templates()
    assert set(loaded) == set(PRODUCT_TABLE)
    for key, (process_kind, rule, step) in PRODUCT_TABLE.items():
        assert loaded[key]["process_kind"] == process_kind
        assert loaded[key]["tuning"]["rule"] == rule
        assert loaded[key]["tests"]["default_step_pct"] == step


def test_loader_reads_packaged_templates() -> None:
    """Load every shipped template through the resource API used by installed wheels."""
    assert len(load_loop_templates()) == len(PRODUCT_TABLE)


def test_every_template_matches_the_canonical_schema() -> None:
    """The repository schema validates every shipped template."""
    canonical = _canonical_schema()
    validator = Draft202012Validator(canonical)
    for key, record in load_loop_templates().items():
        assert list(validator.iter_errors(record)) == [], key


def test_packaged_schema_matches_the_canonical_schema() -> None:
    """Prevent wheel validation from drifting from the repository contract."""
    packaged = Path(__file__).resolve().parents[1] / (
        "src/crosscut_loops/loop_templates/loop_template.schema.json"
    )
    schema = _canonical_schema()
    Draft202012Validator.check_schema(schema)
    assert schema == json.loads(packaged.read_text(encoding="utf-8"))


def _canonical_schema() -> dict[str, Any]:
    """The schema that lives in the repository's top-level schemas folder."""
    path = Path(__file__).resolve().parents[2] / "schemas/loop_template.schema.json"
    schema: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return schema


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("process_kind", "unknown"),
        ("diagnosis_rules", []),
        ("diagnosis_rules", ["guess"]),
        ("tuning", {"rule": "ziegler"}),
        ("tests", {"allowed": [], "default_step_pct": 5.0}),
        ("key", "Invalid key"),
        ("label", ""),
        ("extra", True),
    ],
)
def test_loader_identifies_the_invalid_file_and_field(
    tmp_path: Path, field: str, value: Any
) -> None:
    """Report schema failures as the template-specific exception."""
    record = load_loop_templates()["flow"]
    record[field] = value
    template = tmp_path / "invalid.json"
    template.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(LoopTemplateError, match="invalid.json") as caught:
        load_loop_templates(tmp_path)
    assert field in str(caught.value)


@pytest.mark.parametrize("content", ['{', '[]', '{"key": "flow"}', '\ufffd'])
def test_loader_rejects_malformed_or_incomplete_records(tmp_path: Path, content: str) -> None:
    """Reject JSON syntax, root type and required-field errors."""
    (tmp_path / "broken.json").write_text(content, encoding="utf-8")
    with pytest.raises(LoopTemplateError, match="broken.json"):
        load_loop_templates(tmp_path)


def test_loader_rejects_a_range_whose_minimum_is_above_its_maximum(tmp_path: Path) -> None:
    """The schema cannot compare two properties, so the loader checks the pair."""
    record = load_loop_templates()["flow"]
    record["dynamics"]["gain_min"] = record["dynamics"]["gain_max"] + 1.0
    (tmp_path / "bad_range.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(LoopTemplateError, match="Swap the bounds"):
        load_loop_templates(tmp_path)


def test_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    """Avoid silently replacing one loop type with another file."""
    content = json.dumps(load_loop_templates()["flow"])
    (tmp_path / "first.json").write_text(content, encoding="utf-8")
    (tmp_path / "second.json").write_text(content, encoding="utf-8")
    with pytest.raises(LoopTemplateError, match="Duplicate"):
        load_loop_templates(tmp_path)


def test_loader_rejects_an_empty_directory(tmp_path: Path) -> None:
    """Missing templates must not silently empty the library."""
    with pytest.raises(LoopTemplateError, match="No loop template"):
        load_loop_templates(tmp_path)


def test_loader_rejects_a_missing_directory(tmp_path: Path) -> None:
    """Give a useful exception for an unreadable template directory."""
    with pytest.raises(LoopTemplateError, match="Cannot read loop templates"):
        load_loop_templates(tmp_path / "missing")


def test_loader_rejects_invalid_utf8(tmp_path: Path) -> None:
    """Keep decoding failures in the same file-specific error contract."""
    (tmp_path / "encoding.json").write_bytes(b"\xff")
    with pytest.raises(LoopTemplateError, match="encoding.json"):
        load_loop_templates(tmp_path)


def test_validate_returns_the_record_unchanged() -> None:
    """The API and the loader share one validation path."""
    record = load_loop_templates()["flow"]
    assert validate_loop_template(record) is record

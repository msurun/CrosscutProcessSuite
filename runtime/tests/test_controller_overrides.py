"""Operator overrides of a controller: file round trip and effect on the document."""

from __future__ import annotations

from pathlib import Path

from crosscut_runtime.controllers.overrides import apply_overrides, read_overrides, write_overrides

DOC = {
    "id": "C1",
    "variables": [
        {"id": "mv1", "limits": {"operator": {"lo": 1, "hi": 9}}},
        {"id": "cv1", "enabled_default": True},
    ],
}


def test_missing_or_corrupt_file_gives_no_overrides(tmp_path: Path) -> None:
    """No file, and a file that is not JSON, both mean no overrides."""
    assert read_overrides(tmp_path, "C1") == {}
    write_overrides(tmp_path, "C1", {"cv1": {"enabled": False}})
    path = tmp_path / "_runtime" / "controllers" / "C1.operator.json"
    path.write_text("{oops", encoding="utf-8")
    assert read_overrides(tmp_path, "C1") == {}


def test_override_replaces_operator_limits_and_default(tmp_path: Path) -> None:
    """An override replaces enabled_default and operator limits; the input stays untouched."""
    write_overrides(
        tmp_path, "C1", {"mv1": {"operator": {"lo": 2, "hi": 5}}, "cv1": {"enabled": False}}
    )
    out = apply_overrides(DOC, read_overrides(tmp_path, "C1"))
    assert out["variables"][0]["limits"]["operator"] == {"lo": 2, "hi": 5}
    assert out["variables"][1]["enabled_default"] is False
    assert DOC["variables"][0]["limits"]["operator"] == {"lo": 1, "hi": 9}
    assert DOC["variables"][1]["enabled_default"] is True


def test_economics_override_round_trip_and_reset(tmp_path: Path) -> None:
    from crosscut_runtime.controllers.overrides import read_economics, write_economics

    assert read_economics(tmp_path, "c") is None
    write_economics(tmp_path, "c", {"cv_value": {"y": 2.0}})
    assert read_economics(tmp_path, "c") == {"cv_value": {"y": 2.0}}
    write_economics(tmp_path, "c", None)
    assert read_economics(tmp_path, "c") is None

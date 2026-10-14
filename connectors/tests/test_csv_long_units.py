# connectors/tests/test_csv_long_units.py
"""Tests for the optional quality and unit columns of the long-format CSV importer.

Header words decide which column is which; without them the fourth column is the quality.
Units end up in the dataset's tags document, which every test reads back with json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from crosscut_connectors.csv_long import import_csv_long, read_long_file, read_long_rows
from crosscut_connectors.import_target import ImportTarget

DATASET_ID = "historian"
WARSAW = "Europe/Warsaw"


def _write_csv(csv_text: str, tmp_path: Path, name: str = "history.csv") -> Path:
    """Write ``csv_text`` into ``tmp_path`` and return the path of the new file."""
    csv_path = tmp_path / name
    csv_path.write_text(csv_text, encoding="utf-8")
    return csv_path


def _import(csv_text: str, tmp_path: Path, tz: str | None = None) -> Path:
    """Write the CSV, import it into a dataset and return the dataset directory."""
    csv_path = _write_csv(csv_text, tmp_path)
    target = ImportTarget(out_dir=tmp_path / "out", dataset_id=DATASET_ID, tz=tz)
    import_csv_long(csv_path, target)
    return target.out_dir


def _units_in_tags_document(out_dir: Path) -> dict[str, str]:
    """Return ``tag id -> unit`` as written in the dataset's tags.json."""
    tags = json.loads((out_dir / "tags.json").read_text(encoding="utf-8"))["tags"]
    return {tag["id"]: tag["unit"] for tag in tags}


def _unit_of(csv_text: str, tmp_path: Path) -> str:
    """Import ``csv_text`` and return the unit of its only tag, "A"."""
    return _units_in_tags_document(_import(csv_text, tmp_path))["A"]


def test_a_unit_column_is_stored_in_the_tags_document(tmp_path: Path) -> None:
    """A file with a 'unit' header writes 'degC' as the unit of tag A."""
    out_dir = _import(
        "time,tag,value,unit\n"
        "2026-01-01T00:00:00Z,A,1.5,degC\n"
        "2026-01-01T00:01:00Z,A,3.5,degC\n",
        tmp_path,
    )

    assert _units_in_tags_document(out_dir) == {"A": "degC"}


def test_a_file_with_a_unit_column_has_no_quality_field_in_its_rows(tmp_path: Path) -> None:
    """The unit column is not mistaken for the legacy quality column."""
    csv_path = _write_csv("time,tag,value,unit\n2026-01-01T00:00:00Z,A,1.5,degC\n", tmp_path)

    assert read_long_rows(csv_path) == [("2026-01-01T00:00:00Z", "A", 1.5)]


def test_a_quality_and_a_unit_column_are_both_recognised(tmp_path: Path) -> None:
    """'quality' is parsed as a flag and 'unit' still reaches the tags document."""
    csv_path = _write_csv(
        "time,tag,value,quality,unit\n2026-01-01T00:00:00Z,A,1.5,1,bar\n",
        tmp_path,
    )

    assert read_long_rows(csv_path) == [("2026-01-01T00:00:00Z", "A", 1.5, 1)]
    text = "time,tag,value,quality,unit\n2026-01-01T00:00:00Z,A,1.5,1,bar\n"
    assert _unit_of(text, tmp_path) == "bar"


def test_a_semicolon_file_with_decimal_commas_keeps_its_unit(tmp_path: Path) -> None:
    """A ';' file with decimal commas and swapped optional columns imports both extras."""
    csv_text = (
        "time;tag;value;unit;quality\n"
        "2026-01-01T00:00:00Z;A;1,5;m3/h;0\n"
        "2026-01-01T00:01:00Z;A;3,5;m3/h;0\n"
    )
    csv_path = _write_csv(csv_text, tmp_path)

    assert read_long_rows(csv_path) == [
        ("2026-01-01T00:00:00Z", "A", 1.5, 0),
        ("2026-01-01T00:01:00Z", "A", 3.5, 0),
    ]
    assert _unit_of(csv_text, tmp_path) == "m3/h"


def test_a_legacy_quality_column_without_unit_header_leaves_the_unit_empty(tmp_path: Path) -> None:
    """Without a unit header the unit is "" while quality words keep working."""
    csv_text = "time,tag,value,quality\n2026-01-01T00:00:00Z,A,1.5,bad\n"
    csv_path = _write_csv(csv_text, tmp_path)

    assert read_long_rows(csv_path) == [("2026-01-01T00:00:00Z", "A", 1.5, 2)]
    assert _unit_of(csv_text, tmp_path) == ""


def test_a_unit_filled_on_only_some_rows_is_still_found(tmp_path: Path) -> None:
    """The first non-empty unit of a tag is the one that is kept."""
    csv_text = (
        "time,tag,value,unit\n"
        "2026-01-01T00:00:00Z,A,1.5,\n"
        "2026-01-01T00:01:00Z,A,3.5,kPa\n"
        "2026-01-01T00:02:00Z,A,5.5,kPa\n"
    )

    assert _unit_of(csv_text, tmp_path) == "kPa"


def test_two_different_units_for_one_tag_are_rejected(tmp_path: Path) -> None:
    """A tag with two conflicting units raises ValueError naming that tag."""
    csv_path = _write_csv(
        "time,tag,value,unit\n"
        "2026-01-01T00:00:00Z,A,1.5,degC\n"
        "2026-01-01T00:01:00Z,A,3.5,degF\n",
        tmp_path,
    )

    with pytest.raises(ValueError, match="A"):
        read_long_file(csv_path)


def test_a_text_value_in_the_legacy_quality_column_is_rejected(tmp_path: Path) -> None:
    """Without unit header words a unit text in the fourth column reads as an unknown quality."""
    csv_path = _write_csv(
        "time,tag,value\n"
        "2026-01-01T00:00:00Z,A,1.5,degC\n",
        tmp_path,
    )

    with pytest.raises(ValueError, match="unknown quality"):
        read_long_file(csv_path)

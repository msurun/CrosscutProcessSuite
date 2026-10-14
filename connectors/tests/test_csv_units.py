# connectors/tests/test_csv_units.py
"""Tests for unit extraction from CSV headers and its storage in the dataset.

split_unit() is checked on bracketed suffixes such as "Level [m]"; import_csv()
is checked end to end: a semicolon file is imported and the written tags
document must carry the units, while the numeric values stay untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from crosscut_connectors.csv_import import import_csv, split_unit
from crosscut_sim.dataset import read_dataset, to_wide

# A semicolon-separated file with a bracketed unit on two of its three columns.
# The values are whole and well separated so that "unaffected numbers" is easy to assert.
CSV_TEXT = (
    "time;Level [m];Flow (t/h);Plain\n"
    "2024-05-01T00:00:00Z;1.5;10.0;100\n"
    "2024-05-01T00:01:00Z;2.5;20.0;200\n"
    "2024-05-01T00:02:00Z;3.5;30.0;300\n"
)


@pytest.mark.parametrize(
    ("header_cell", "expected"),
    [
        ("Level [m]", ("Level", "m")),
        ("Flow (t/h)", ("Flow", "t/h")),
        ("Plain", ("Plain", "")),
        ("  Pressure  [ bar ] ", ("Pressure", "bar")),
        ("Temp(C)", ("Temp", "C")),
    ],
)
def test_a_bracketed_suffix_is_split_into_name_and_unit(
    header_cell: str, expected: tuple[str, str]
) -> None:
    """A header like "Level [m]" yields the bare name and the bracketed unit."""
    assert split_unit(header_cell) == expected


def test_a_header_that_is_only_a_bracket_keeps_its_whole_text_as_name() -> None:
    """Without a name in front of the bracket there is no unit to extract."""
    assert split_unit("[m]") == ("[m]", "")


def _find_tags_document(out_dir: Path) -> dict:
    """Return the parsed dataset tag document written below ``out_dir``.

    Looks for tags*.json first, then falls back to any *.json holding a "tags" key.
    """
    candidates = sorted(out_dir.rglob("tags*.json"))
    if not candidates:
        candidates = [
            path
            for path in sorted(out_dir.rglob("*.json"))
            if "tags" in json.loads(path.read_text(encoding="utf-8"))
        ]
    assert candidates, f"no tags document found below {out_dir}"
    return json.loads(candidates[0].read_text(encoding="utf-8"))


def _import_units_csv(tmp_path: Path) -> Path:
    """Write the sample CSV to ``tmp_path``, import it and return the dataset directory."""
    csv_path = tmp_path / "units.csv"
    csv_path.write_text(CSV_TEXT, encoding="utf-8")
    out_dir = tmp_path / "dataset"
    import_csv(csv_path, out_dir, dataset_id="units", tz="UTC")
    return out_dir


def test_imported_tags_carry_the_units_from_the_header(tmp_path: Path) -> None:
    """Each tag keeps the header's bracketed unit, or "" when the header had none."""
    out_dir = _import_units_csv(tmp_path)
    tags = _find_tags_document(out_dir)["tags"]

    assert [tag["id"] for tag in tags] == ["Level", "Flow", "Plain"]
    assert [tag["unit"] for tag in tags] == ["m", "t/h", ""]


def test_imported_tags_keep_the_header_names_without_the_unit_suffix(tmp_path: Path) -> None:
    """The display name is the header text with the bracketed suffix removed."""
    out_dir = _import_units_csv(tmp_path)

    assert [tag["name"] for tag in _find_tags_document(out_dir)["tags"]] == [
        "Level",
        "Flow",
        "Plain",
    ]


def test_imported_values_are_unaffected_by_the_unit_suffixes(tmp_path: Path) -> None:
    """The numbers in the CSV arrive unchanged, column by column and in file order."""
    out_dir = _import_units_csv(tmp_path)
    _t_ns, columns = to_wide(read_dataset(out_dir))

    assert list(columns) == ["Level", "Flow", "Plain"]
    np.testing.assert_allclose(columns["Level"], [1.5, 2.5, 3.5])
    np.testing.assert_allclose(columns["Flow"], [10.0, 20.0, 30.0])
    np.testing.assert_allclose(columns["Plain"], [100.0, 200.0, 300.0])

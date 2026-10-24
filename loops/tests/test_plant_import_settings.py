"""Behaviour tests: ReadSettings controls how the plant import reads missing codes, numbers and times.

Each test writes a tiny wide CSV (one time column plus tag columns) to tmp_path and reads it
back with read_plant_table and an explicit ReadSettings, so the real reader runs end to end.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from crosscut_loops.plant_import import ReadSettings, read_plant_table
from crosscut_loops.plant_import_time import TimeZoneSpec

UTC_SPEC = TimeZoneSpec("utc")
ROWS = 5
STEP_S = 10


def _timestamps_utc() -> list[str]:
    """UTC wall-clock texts for five rows, 10 s apart, starting at 11:00 on 2026-10-09."""
    start = datetime(2026, 10, 9, 11, 0, 0, tzinfo=UTC)
    return [
        (start + timedelta(seconds=position * STEP_S)).strftime("%Y-%m-%d %H:%M:%S")
        for position in range(ROWS)
    ]


def _write_wide_csv(path: Path, header: list[str], cells: dict[str, list[str]],
                    delimiter: str = ",") -> Path:
    """Write a wide CSV whose rows are taken cell by cell from `cells` per column."""
    lines = [delimiter.join(header)]
    for row in range(ROWS):
        lines.append(delimiter.join(cells[column][row] for column in header))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_missing_codes_masks_the_given_code_and_keeps_minus_9999(tmp_path: Path) -> None:
    path = _write_wide_csv(
        tmp_path / "codes.csv",
        ["timestamp", "tag.a"],
        {"timestamp": _timestamps_utc(), "tag.a": ["-999", "-9999", "1.0", "2.0", "3.0"]},
    )
    settings = ReadSettings(missing_codes=(-999.0,))

    table = read_plant_table(path, UTC_SPEC, settings)

    assert np.isnan(table.columns["tag.a"][0])
    assert table.columns["tag.a"][1] == -9999.0


def test_default_settings_mask_minus_9999(tmp_path: Path) -> None:
    path = _write_wide_csv(
        tmp_path / "default.csv",
        ["timestamp", "tag.a"],
        {"timestamp": _timestamps_utc(), "tag.a": ["-9999", "-999", "1.0", "2.0", "3.0"]},
    )

    table = read_plant_table(path, UTC_SPEC, ReadSettings())

    assert np.isnan(table.columns["tag.a"][0])
    assert table.columns["tag.a"][1] == -999.0


def test_decimal_comma_reads_comma_as_decimal_point(tmp_path: Path) -> None:
    path = _write_wide_csv(
        tmp_path / "comma.csv",
        ["timestamp", "tag.a"],
        {"timestamp": _timestamps_utc(), "tag.a": ["1,5", "2,0", "3,0", "4,0", "5,0"]},
        delimiter=";",
    )
    settings = ReadSettings(decimal_comma=True, delimiter=";")

    table = read_plant_table(path, UTC_SPEC, settings)

    assert table.columns["tag.a"][0] == 1.5


def test_without_decimal_comma_a_comma_number_is_missing(tmp_path: Path) -> None:
    path = _write_wide_csv(
        tmp_path / "plain.csv",
        ["timestamp", "tag.a"],
        {"timestamp": _timestamps_utc(), "tag.a": ["1,5", "2,0", "3,0", "4,0", "5,0"]},
        delimiter=";",
    )
    settings = ReadSettings(decimal_comma=False, delimiter=";")

    table = read_plant_table(path, UTC_SPEC, settings)

    assert np.isnan(table.columns["tag.a"][0])


def test_time_names_accept_a_custom_time_column(tmp_path: Path) -> None:
    path = _write_wide_csv(
        tmp_path / "czas.csv",
        ["Czas", "tag.a"],
        {"Czas": _timestamps_utc(), "tag.a": ["1.0", "2.0", "3.0", "4.0", "5.0"]},
    )
    settings = ReadSettings(time_names=frozenset({"czas"}))

    table = read_plant_table(path, UTC_SPEC, settings)

    assert table.ts_ns.size == ROWS
    assert list(table.columns) == ["tag.a"]


def test_a_time_column_outside_time_names_is_not_the_time_column(tmp_path: Path) -> None:
    path = _write_wide_csv(
        tmp_path / "czas.csv",
        ["Czas", "tag.a"],
        {"Czas": _timestamps_utc(), "tag.a": ["1.0", "2.0", "3.0", "4.0", "5.0"]},
    )

    with pytest.raises(ValueError):
        read_plant_table(path, UTC_SPEC, ReadSettings())

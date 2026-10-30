"""Behaviour tests: the plant import reads -9999 as a missing cell only when asked to.

Each test writes a tiny wide CSV (one time column plus tag columns) to tmp_path and reads it
back with read_plant_table, so the real reader runs end to end on a real file.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from crosscut_loops.plant_import import ReadSettings, read_plant_table
from crosscut_loops.plant_import_time import TimeZoneSpec

UTC_SPEC = TimeZoneSpec("utc")
SENTINEL_SETTINGS = ReadSettings(missing_codes=(-9999.0,))

HEADER_COLUMNS = ["timestamp", "sentinel.tag", "clean.tag", "bad.text.tag"]

SENTINEL_COLUMN_CELLS = ["-9999", "-9999.0", "-9998.5", "42.0", "43.5"]
CLEAN_COLUMN_CELLS = ["1.0", "2.0", "3.0", "4.0", "5.0"]
BAD_TEXT_COLUMN_CELLS = ["Bad", "Bad", "Bad", "Bad", "Bad"]


def _timestamps_utc() -> list[str]:
    """UTC wall-clock texts for five rows, 10 s apart, starting at 11:00 on 2026-10-09."""
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 10, 9, 11, 0, 0, tzinfo=UTC)
    return [
        (start + timedelta(seconds=position * 10)).strftime("%Y-%m-%d %H:%M:%S")
        for position in range(len(SENTINEL_COLUMN_CELLS))
    ]


def _write_wide_csv(path: Path) -> Path:
    """Write the synthetic wide CSV (one row per timestamp, one cell per column)."""
    cells_by_column = {
        "timestamp": _timestamps_utc(),
        "sentinel.tag": SENTINEL_COLUMN_CELLS,
        "clean.tag": CLEAN_COLUMN_CELLS,
        "bad.text.tag": BAD_TEXT_COLUMN_CELLS,
    }
    lines = [",".join(HEADER_COLUMNS)]
    for row in range(len(SENTINEL_COLUMN_CELLS)):
        lines.append(",".join(cells_by_column[column][row] for column in HEADER_COLUMNS))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_plant_import_sentinel_reads_minus_9999_as_missing(tmp_path: Path) -> None:
    path = _write_wide_csv(tmp_path / "sentinel.csv")

    table = read_plant_table(path, UTC_SPEC, SENTINEL_SETTINGS)

    assert np.isnan(table.columns["sentinel.tag"][0])
    assert np.isnan(table.columns["sentinel.tag"][1])


def test_plant_import_sentinel_keeps_a_value_just_above_the_sentinel(tmp_path: Path) -> None:
    path = _write_wide_csv(tmp_path / "sentinel.csv")

    table = read_plant_table(path, UTC_SPEC, SENTINEL_SETTINGS)

    assert table.columns["sentinel.tag"][2] == -9998.5


def test_plant_import_sentinel_keeps_normal_values(tmp_path: Path) -> None:
    path = _write_wide_csv(tmp_path / "sentinel.csv")

    table = read_plant_table(path, UTC_SPEC, SENTINEL_SETTINGS)

    assert table.columns["sentinel.tag"][3] == 42.0
    assert table.columns["sentinel.tag"][4] == 43.5


def test_plant_import_sentinel_leaves_a_column_without_sentinels_unchanged(tmp_path: Path) -> None:
    path = _write_wide_csv(tmp_path / "sentinel.csv")

    table = read_plant_table(path, UTC_SPEC, SENTINEL_SETTINGS)

    assert table.columns["clean.tag"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_plant_import_sentinel_still_reads_bad_text_as_missing(tmp_path: Path) -> None:
    path = _write_wide_csv(tmp_path / "sentinel.csv")

    table = read_plant_table(path, UTC_SPEC, SENTINEL_SETTINGS)

    assert np.all(np.isnan(table.columns["bad.text.tag"]))


def test_plant_import_reads_minus_9999_as_a_number_by_default(tmp_path: Path) -> None:
    path = _write_wide_csv(tmp_path / "sentinel.csv")

    table = read_plant_table(path, UTC_SPEC)

    assert table.columns["sentinel.tag"][0] == -9999.0

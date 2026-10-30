"""Tests for the public flotation CSV loader: decimal commas, hourly labels, missing hours.

The loader rebuilds 20 s sampling times from hour labels that the file repeats, and it must keep
missing hours visible in ``t_s`` instead of silently closing the gap. These tests pin that
behaviour on tiny hand-written CSV files, so no real dataset is needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from flotation_public import load_flotation_csv  # noqa: E402

HEADER = "date,% Iron Feed,Ore Pulp pH"


def _write_csv(path: Path, rows: list[str]) -> Path:
    """Write a flotation CSV with the standard header and the given data rows."""
    path.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_a_decimal_comma_becomes_a_float(tmp_path: Path) -> None:
    """A text value like "55,2" is loaded as the float 55.2."""
    csv_path = _write_csv(tmp_path / "one_row.csv", ['2017-03-10 01:00:00,"55,2","10,06"'])

    data = load_flotation_csv(csv_path)

    assert data.columns["% Iron Feed"][0] == pytest.approx(55.2)
    assert data.columns["Ore Pulp pH"][0] == pytest.approx(10.06)


def test_rows_of_one_hour_are_twenty_seconds_apart(tmp_path: Path) -> None:
    """Three rows sharing an hour label get t_s 0, 20, 40; the next hour starts at 3600."""
    rows = [
        '2017-03-10 01:00:00,"55,2","10,06"',
        '2017-03-10 01:00:00,"55,2","10,06"',
        '2017-03-10 01:00:00,"55,2","10,06"',
        '2017-03-10 02:00:00,"56,0","10,10"',
        '2017-03-10 02:00:00,"56,0","10,10"',
    ]
    csv_path = _write_csv(tmp_path / "two_hours.csv", rows)

    data = load_flotation_csv(csv_path)

    assert data.t_s[0] == pytest.approx(0.0)
    assert data.t_s[1] == pytest.approx(20.0)
    assert data.t_s[2] == pytest.approx(40.0)
    assert data.t_s[3] == pytest.approx(3600.0)
    assert data.t_s[4] == pytest.approx(3620.0)


def test_a_missing_hour_is_counted_and_leaves_a_gap_in_time(tmp_path: Path) -> None:
    """Labels 01:00 and 03:00 give hours_missing 1 and the 03:00 block starts at 7200 s."""
    rows = [
        '2017-03-10 01:00:00,"55,2","10,06"',
        '2017-03-10 01:00:00,"55,2","10,06"',
        '2017-03-10 03:00:00,"57,4","10,20"',
        '2017-03-10 03:00:00,"57,4","10,20"',
    ]
    csv_path = _write_csv(tmp_path / "gap.csv", rows)

    data = load_flotation_csv(csv_path)

    assert data.hours_missing == 1
    assert data.t_s[2] == pytest.approx(7200.0)
    assert data.t_s[3] == pytest.approx(7220.0)


def test_consecutive_hours_report_no_missing_hour(tmp_path: Path) -> None:
    """Two consecutive hour labels give hours_missing 0."""
    rows = [
        '2017-03-10 01:00:00,"55,2","10,06"',
        '2017-03-10 02:00:00,"56,0","10,10"',
    ]
    csv_path = _write_csv(tmp_path / "consecutive.csv", rows)

    data = load_flotation_csv(csv_path)

    assert data.hours_missing == 0


def test_the_timestamp_column_is_not_a_data_column(tmp_path: Path) -> None:
    """The timestamp stays in t_s and never appears inside the columns dictionary."""
    csv_path = _write_csv(tmp_path / "one_row.csv", ['2017-03-10 01:00:00,"55,2","10,06"'])

    data = load_flotation_csv(csv_path)

    assert "date" not in data.columns
    assert set(data.columns) == {"% Iron Feed", "Ore Pulp pH"}

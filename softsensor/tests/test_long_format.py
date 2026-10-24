"""Tests for `crosscut_softsensor.long_format`.

Each test builds a tiny synthetic historian CSV with the required header and checks one
behaviour of the loader, the lab-results adapter or the grid resampler.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_softsensor.long_format import (
    LongFormatError,
    TagSeries,
    load_long_csv,
    resample_to_grid,
    to_lab_results,
)

HEADER = "timestamp,tag,value,raw_value\n"


def _write_csv(tmp_path, body: str) -> str:
    """Write a CSV file with the standard header plus `body` and return its path as text."""
    file_path = tmp_path / "historian.csv"
    file_path.write_text(HEADER + body, encoding="utf-8")
    return str(file_path)


def test_long_format_parses_stamps_with_and_without_fraction(tmp_path):
    body = (
        "2024-01-01 00:00:00.500,lab_a,1.0,\n"
        "2024-01-01 00:00:02.000,lab_a,2.0,\n"
    )
    series = load_long_csv(_write_csv(tmp_path, body))["lab_a"]
    assert series.t_s - 1704067200.0 == pytest.approx([0.5, 2.0])


def test_long_format_parses_stamp_with_iso_t_separator(tmp_path):
    body = "2024-01-01T00:00:01.000,lab_a,5.0,\n"
    series = load_long_csv(_write_csv(tmp_path, body))["lab_a"]
    assert series.values.tolist() == [5.0]
    assert series.t_s[0] == pytest.approx(1704067201.0)


def test_long_format_utc_offset_minus_three_adds_three_hours(tmp_path):
    body = "2024-01-01 00:00:00.000,lab_a,1.0,\n"
    series = load_long_csv(_write_csv(tmp_path, body), utc_offset_h=-3.0)["lab_a"]
    wall_seconds = 1704067200.0  # 2024-01-01 00:00:00 UTC as a POSIX epoch
    assert series.t_s[0] == pytest.approx(wall_seconds + 3.0 * 3600.0)


def test_long_format_tags_filter_keeps_only_named_tags(tmp_path):
    body = (
        "2024-01-01 00:00:00.000,lab_a,1.0,\n"
        "2024-01-01 00:00:00.000,lab_b,2.0,\n"
    )
    result = load_long_csv(_write_csv(tmp_path, body), tags=["lab_a"])
    assert set(result) == {"lab_a"}


def test_long_format_skips_rows_with_empty_or_non_numeric_value(tmp_path):
    body = (
        "2024-01-01 00:00:00.000,lab_a,,\n"
        "2024-01-01 00:00:01.000,lab_a,not_a_number,\n"
        "2024-01-01 00:00:02.000,lab_a,7.0,\n"
    )
    series = load_long_csv(_write_csv(tmp_path, body))["lab_a"]
    assert series.values.tolist() == [7.0]


def test_long_format_duplicate_stamps_keep_last_row(tmp_path):
    body = (
        "2024-01-01 00:00:00.000,lab_a,1.0,\n"
        "2024-01-01 00:00:00.000,lab_a,9.0,\n"
    )
    series = load_long_csv(_write_csv(tmp_path, body))["lab_a"]
    assert series.values.tolist() == [9.0]


def test_long_format_unsorted_input_is_sorted_ascending(tmp_path):
    body = (
        "2024-01-01 00:00:02.000,lab_a,2.0,\n"
        "2024-01-01 00:00:00.000,lab_a,0.0,\n"
        "2024-01-01 00:00:01.000,lab_a,1.0,\n"
    )
    series = load_long_csv(_write_csv(tmp_path, body))["lab_a"]
    assert np.all(np.diff(series.t_s) >= 0)
    assert series.values.tolist() == [0.0, 1.0, 2.0]


def test_long_format_missing_column_raises_naming_it(tmp_path):
    file_path = tmp_path / "broken.csv"
    file_path.write_text("timestamp,tag,raw_value\n", encoding="utf-8")
    with pytest.raises(LongFormatError, match="value"):
        load_long_csv(str(file_path))


def test_long_format_bom_header_is_accepted(tmp_path):
    file_path = tmp_path / "bom.csv"
    file_path.write_text(
        "\ufefftimestamp,tag,value,raw_value\n"
        "2024-01-01 00:00:00.000,lab_a,3.0,\n",
        encoding="utf-8",
    )
    series = load_long_csv(str(file_path))["lab_a"]
    assert series.values.tolist() == [3.0]


def test_long_format_to_lab_results_sets_available_s_from_shift_and_delay():
    series = TagSeries(
        tag="lab_a",
        t_s=np.array([10.0, 20.0]),
        values=np.array([1.0, 2.0]),
    )
    results = to_lab_results(series, lab_delay_s=5.0, shift_s=2.0)
    assert np.array_equal(results.available_s, series.t_s + 2.0 + 5.0)
    assert np.array_equal(results.values, series.values)


def test_long_format_resample_holds_last_value_on_grid():
    series = TagSeries(
        tag="lab_a",
        t_s=np.array([0.0, 10.0]),
        values=np.array([1.0, 2.0]),
    )
    grid = np.array([0.0, 5.0, 10.0, 15.0])
    resampled = resample_to_grid(series, grid, max_age_s=100.0)
    assert np.array_equal(resampled, np.array([1.0, 1.0, 2.0, 2.0]))


def test_long_format_resample_is_nan_before_first_sample_and_when_stale():
    series = TagSeries(
        tag="lab_a",
        t_s=np.array([10.0]),
        values=np.array([5.0]),
    )
    grid = np.array([0.0, 10.0, 15.0])
    resampled = resample_to_grid(series, grid, max_age_s=4.0)
    assert np.isnan(resampled[0])
    assert resampled[1] == pytest.approx(5.0)
    assert np.isnan(resampled[2])

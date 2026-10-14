"""Tests for the long-format CSV importer: delimiter, decimal, bad values, duplicates and timezone.

Every test writes a small CSV into a temporary directory, imports it into a dataset, and reads
the dataset back with ``crosscut_sim.dataset`` to check the values a user would actually see.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from crosscut_connectors.csv_long import import_csv_long
from crosscut_connectors.import_target import ImportTarget
from crosscut_sim.dataset import read_dataset, to_wide

DATASET_ID = "historian"
WARSAW = "Europe/Warsaw"


def _import(csv_text: str, tmp_path: Path, tz: str | None = None):
    """Write ``csv_text`` to a temp file, import it and return the report and the wide columns."""
    csv_path = tmp_path / "history.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    target = ImportTarget(out_dir=tmp_path / "out", dataset_id=DATASET_ID, tz=tz)
    report = import_csv_long(csv_path, target)
    time_ns, columns = to_wide(read_dataset(target.out_dir))
    return report, time_ns, columns


def test_semicolon_file_with_decimal_commas_is_imported(tmp_path: Path) -> None:
    """A ';' file with decimal commas gives both tags with their comma-decoded floats."""
    report, _, columns = _import(
        "time;tag;value\n"
        "2026-01-01T00:00:00Z;A;1,5\n"
        "2026-01-01T00:00:00Z;B;2,5\n"
        "2026-01-01T00:01:00Z;A;3,5\n"
        "2026-01-01T00:01:00Z;B;4,5\n",
        tmp_path,
    )

    assert report.n_tags == 2
    assert set(columns) == {"A", "B"}
    assert columns["A"].tolist() == [1.5, 3.5]
    assert columns["B"].tolist() == [2.5, 4.5]


def test_comma_file_with_decimal_points_is_imported(tmp_path: Path) -> None:
    """A ',' file with decimal points gives the same values as the semicolon variant."""
    report, _, columns = _import(
        "time,tag,value\n"
        "2026-01-01T00:00:00Z,A,1.5\n"
        "2026-01-01T00:01:00Z,A,3.5\n",
        tmp_path,
    )

    assert report.n_tags == 1
    assert columns["A"].tolist() == [1.5, 3.5]


def test_a_non_numeric_value_becomes_nan_and_is_counted(tmp_path: Path) -> None:
    """A text value cell turns into NaN and shows up once in n_bad_values."""
    report, _, columns = _import(
        "time,tag,value\n"
        "2026-01-01T00:00:00Z,A,1.5\n"
        "2026-01-01T00:01:00Z,A,not_a_number\n",
        tmp_path,
    )

    assert report.n_bad_values == 1
    assert np.isnan(columns["A"][1])


def test_a_tag_missing_at_one_timestamp_is_nan_there(tmp_path: Path) -> None:
    """A tag with no row at a timestamp gets NaN at that timestamp in the wide frame."""
    _, _, columns = _import(
        "time,tag,value\n"
        "2026-01-01T00:00:00Z,A,1.5\n"
        "2026-01-01T00:01:00Z,A,3.5\n"
        "2026-01-01T00:00:00Z,B,2.5\n",
        tmp_path,
    )

    assert columns["B"].tolist()[0] == 2.5
    assert np.isnan(columns["B"][1])


def test_a_repeated_timestamp_and_tag_is_dropped_once(tmp_path: Path) -> None:
    """A repeated (timestamp, tag) row is counted once and the later row replaces the earlier."""
    report, _, columns = _import(
        "time,tag,value\n"
        "2026-01-01T00:00:00Z,A,1.5\n"
        "2026-01-01T00:00:00Z,A,9.9\n"
        "2026-01-01T00:01:00Z,A,3.5\n",
        tmp_path,
    )

    assert report.n_duplicates_dropped == 1
    assert columns["A"].tolist() == [9.9, 3.5]  # the last row of a repeated pair wins


def test_a_file_with_too_few_columns_is_rejected(tmp_path: Path) -> None:
    """A CSV without a value column raises ValueError instead of importing garbage."""
    with pytest.raises(ValueError):
        _import(
            "time,tag\n"
            "2026-01-01T00:00:00Z,A\n",
            tmp_path,
        )


def test_naive_timestamps_are_located_in_the_target_timezone(tmp_path: Path) -> None:
    """A 01:00 naive timestamp with tz='Europe/Warsaw' lands at 00:00 UTC (winter, UTC+1)."""
    _, time_ns, _ = _import(
        "time,tag,value\n"
        "2026-01-01 01:00:00,A,1.5\n",
        tmp_path,
        tz=WARSAW,
    )

    assert time_ns[0] == np.datetime64("2026-01-01T00:00:00")


def test_an_optional_quality_column_is_accepted(tmp_path: Path) -> None:
    """A fourth quality column (0 = good) is imported without error."""
    report, _, columns = _import(
        "time,tag,value,quality\n"
        "2026-01-01T00:00:00Z,A,1.5,0\n"
        "2026-01-01T00:01:00Z,A,3.5,0\n",
        tmp_path,
    )

    assert report.n_rows == 2
    assert columns["A"].tolist() == [1.5, 3.5]

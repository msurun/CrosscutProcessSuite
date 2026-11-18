"""Compare compatibility entry points with the original import pipelines.

The reference helpers retain the pre-interface read, normalise and write sequence.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import numpy as np
from crosscut_connectors import csv_import, csv_long, sql_import
from crosscut_connectors.csv_connector import CsvConnector
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.sql_connector import SqlConnector
from crosscut_sim.dataset import read_dataset

DATASET_ID = "compatibility"
SELECT_HISTORY = "SELECT timestamp, tag, value, quality FROM history"
LONG_ROWS = [
    ("2026-01-01T00:00:01Z", "A", 3.0, 1),
    ("2026-01-01T00:00:00Z", "B", 2.0, 0),
    ("2026-01-01T00:00:00Z", "A", 1.0, 0),
    ("2026-01-01T00:00:00Z", "A", 4.0, 2),
]


def _legacy_wide_import(path: Path, target: ImportTarget) -> csv_import.ImportReport:
    """Run the wide import's original source-read and array-normalisation sequence."""
    delimiter, header, rows = csv_import._read_table(path)
    timestamps, timestamp_format, dst_repeats = csv_import._parse_timestamps(rows, target.tz)
    decimal = csv_import._detect_decimal_separator(rows, delimiter)
    values, qualities, bad_count = csv_import._parse_value_matrices(rows, len(header) - 1, decimal)
    timestamps, values, qualities, duplicates, was_unsorted = csv_import._normalise_order(
        timestamps, values, qualities
    )
    csv_import._write_csv_dataset(
        target.out_dir, target.dataset_id, header[1:], (timestamps, values, qualities)
    )
    return csv_import.ImportReport(
        len(timestamps), duplicates, was_unsorted, bad_count, delimiter, decimal,
        timestamp_format, dst_repeats,
    )


def _assert_same_dataset(actual: Path, legacy: Path) -> None:
    """Compare values, UTC nanoseconds, quality flags and complete tag metadata."""
    actual_table = read_dataset(actual)
    legacy_table = read_dataset(legacy)
    assert actual_table.drop(["value"]).equals(legacy_table.drop(["value"]))
    np.testing.assert_array_equal(
        actual_table["value"].to_numpy(), legacy_table["value"].to_numpy()
    )
    assert json.loads((actual / "tags.json").read_text()) == json.loads(
        (legacy / "tags.json").read_text()
    )


def _create_database(path: Path) -> None:
    """Create a synthetic historian with duplicates, uncertain quality and missing cells."""
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE history(timestamp TEXT, tag TEXT, value REAL, quality INT)"
        )
        connection.executemany("INSERT INTO history VALUES (?, ?, ?, ?)", LONG_ROWS)


def test_wide_import_through_history_matches_the_legacy_dataset(tmp_path: Path) -> None:
    """Routing preserves messy parsing, row order, duplicate policy, units and bad cells."""
    source = tmp_path / "wide.csv"
    source.write_text(
        "time;A [m];B\n2026-01-01T00:00:01Z;3,5;bad\n"
        "2026-01-01T00:00:00Z;1,5;2,5\n2026-01-01T00:00:00Z;4,5;5,5\n"
    )
    legacy = ImportTarget(tmp_path / "legacy", DATASET_ID)
    legacy_report = _legacy_wide_import(source, legacy)
    with patch.object(
        CsvConnector, "history", autospec=True, side_effect=CsvConnector.history
    ) as read_history:
        report = csv_import.import_csv(source, tmp_path / "actual", dataset_id=DATASET_ID)
    read_history.assert_called_once()
    assert report == legacy_report
    _assert_same_dataset(tmp_path / "actual", legacy.out_dir)


def test_long_import_through_history_matches_the_legacy_dataset(tmp_path: Path) -> None:
    """Routing preserves duplicate replacement, long-format units and explicit quality."""
    source = tmp_path / "long.csv"
    source.write_text(
        "time;tag;value;quality;unit\n2026-01-01T00:00:01Z;A;3,5;uncertain;m\n"
        "2026-01-01T00:00:00Z;B;2,5;good;bar\n"
        "2026-01-01T00:00:00Z;A;1,5;good;m\n"
        "2026-01-01T00:00:00Z;A;4,5;bad;m\n"
    )
    parsed = csv_long.read_long_file(source)
    legacy = ImportTarget(tmp_path / "legacy", DATASET_ID)
    legacy_report = sql_import._import_rows(parsed.rows, legacy, parsed.units)
    target = ImportTarget(tmp_path / "actual", DATASET_ID)
    with patch.object(
        CsvConnector, "history", autospec=True, side_effect=CsvConnector.history
    ) as read_history:
        report = csv_long.import_csv_long(source, target)
    read_history.assert_called_once()
    assert report == legacy_report
    _assert_same_dataset(target.out_dir, legacy.out_dir)


def test_sql_file_import_through_history_matches_the_legacy_dataset(tmp_path: Path) -> None:
    """Routing retains the original read-only query, pivot and quality behavior."""
    database = tmp_path / "history.sqlite"
    _create_database(database)
    legacy = ImportTarget(tmp_path / "legacy", DATASET_ID)
    legacy_report = sql_import._import_rows(sql_import._read_rows(database, SELECT_HISTORY), legacy)
    target = ImportTarget(tmp_path / "actual", DATASET_ID)
    with patch.object(
        SqlConnector, "history", autospec=True, side_effect=SqlConnector.history
    ) as read_history:
        report = sql_import.import_sql(database, SELECT_HISTORY, target)
    read_history.assert_called_once()
    assert report == legacy_report
    _assert_same_dataset(target.out_dir, legacy.out_dir)


def test_sql_connection_import_through_history_matches_the_legacy_dataset(tmp_path: Path) -> None:
    """Routing uses the caller's connection and leaves it available after the import."""
    database = tmp_path / "history.sqlite"
    _create_database(database)
    legacy = ImportTarget(tmp_path / "legacy", DATASET_ID)
    target = ImportTarget(tmp_path / "actual", DATASET_ID)
    with sqlite3.connect(database) as connection:
        rows = sql_import.fetch_rows(connection, SELECT_HISTORY)
        legacy_report = sql_import._import_rows(rows, legacy)
        with patch.object(
            SqlConnector, "history", autospec=True, side_effect=SqlConnector.history
        ) as read_history:
            report = sql_import.import_sql_connection(connection, SELECT_HISTORY, target)
        assert connection.execute("SELECT COUNT(*) FROM history").fetchone() == (4,)
    read_history.assert_called_once()
    assert report == legacy_report
    _assert_same_dataset(target.out_dir, legacy.out_dir)

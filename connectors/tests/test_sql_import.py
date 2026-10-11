"""Tests for crosscut_connectors.sql_import: build a temporary sqlite DB, import, compare."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from crosscut_connectors.sql_import import SqlImportReport, import_sql
from crosscut_sim.core import BAD, GOOD, UNCERTAIN
from crosscut_sim.dataset import read_dataset, to_wide

UTC_TZ = "UTC"
LOCAL_TZ = "Europe/Warsaw"

START_EPOCH_S = 1_767_225_600  # 2026-01-01T00:00:00Z as epoch seconds
START_NS = START_EPOCH_S * 1_000_000_000
N_ROWS = 50
STEP_S = 1
TAGS = ["sim.wb.top_comp", "sim.wb.bottom_comp", "sim.wb.steam"]
VALUE_OFFSETS = {"sim.wb.top_comp": 0.0, "sim.wb.bottom_comp": 10.0, "sim.wb.steam": 20.0}


def expected_value(tag: str, step: int) -> float:
    """Return the synthetic value for one tag at one step, matching the seeded rows."""
    return VALUE_OFFSETS[tag] + step


def iso_text(step: int) -> str:
    """Return the UTC ISO-8601 text for the given step, e.g. '2026-01-01T00:00:03Z'."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return (base + timedelta(seconds=step)).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_iso(step: int) -> str:
    """Return the naive Warsaw-local ISO text for a step (01:00 local == 00:00Z in winter)."""
    base = datetime(2026, 1, 1, 1, 0, 0) + timedelta(seconds=step)
    return base.strftime("%Y-%m-%dT%H:%M:%S")


def placeholders(columns: str) -> str:
    """Return '?, ?, ?' with one placeholder per comma-separated column name."""
    return ", ".join("?" for _ in columns.split(","))


def build_database(
    path: Path,
    rows: Sequence[tuple[object, ...]],
    extra_columns: str = "",
) -> None:
    """Create a sqlite file with a `t` table holding the given (ts, tag, value[, quality]) rows."""
    columns = "ts, tag, value" + (f", {extra_columns}" if extra_columns else "")
    with sqlite3.connect(path) as connection:
        connection.execute(f"CREATE TABLE t ({columns})")
        connection.executemany(
            f"INSERT INTO t ({columns}) VALUES ({placeholders(columns)})",
            rows,
        )


def seed_all_tags(connection: sqlite3.Connection, ts_for_step: Callable[[int], object]) -> None:
    """Insert one row per (tag, step) using a callable that maps a step to a stored ts."""
    rows = [
        (ts_for_step(step), tag, expected_value(tag, step))
        for step in range(N_ROWS)
        for tag in TAGS
    ]
    connection.executemany("INSERT INTO t (ts, tag, value) VALUES (?, ?, ?)", rows)


def build_full_database(path: Path, ts_for_step: Callable[[int], object]) -> None:
    """Create a DB with every (tag, step) present and no quality column."""
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE t (ts, tag, value)")
        seed_all_tags(connection, ts_for_step)


def import_query(
    database: Path, query: str, out_dir: Path, tz: str = UTC_TZ
) -> tuple[np.ndarray, dict[str, np.ndarray], SqlImportReport]:
    """Run import_sql, read the dataset back and return (timestamps, wide frame, report)."""
    report = import_sql(database, query, out_dir, dataset_id="sql", tz=tz)
    timestamps, wide = to_wide(read_dataset(out_dir))
    return timestamps.astype(np.int64), wide, report


def table_snapshot(database: Path) -> list[tuple[object, ...]]:
    """Return the full contents of table `t` so a test can prove it was not modified."""
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        return connection.execute("SELECT ts, tag, value FROM t ORDER BY rowid").fetchall()


SELECT_ALL = "SELECT ts, tag, value FROM t"
SELECT_QUALITY = "SELECT ts, tag, value, quality FROM t"
SELECT_IN_ROWID_ORDER = "SELECT ts, tag, value FROM t ORDER BY rowid"


@pytest.fixture
def iso_database(tmp_path: Path) -> Path:
    """Return a database whose timestamps are UTC ISO-8601 text."""
    database = tmp_path / "sim.sqlite"
    build_full_database(database, iso_text)
    return database


@pytest.fixture
def epoch_database(tmp_path: Path) -> Path:
    """Return a database whose timestamps are numeric epoch seconds in UTC."""
    database = tmp_path / "sim.sqlite"
    build_full_database(database, lambda step: START_EPOCH_S + step * STEP_S)
    return database


def test_import_recovers_iso_timestamps_and_values(iso_database: Path, tmp_path: Path) -> None:
    timestamps, wide, _ = import_query(iso_database, SELECT_ALL, tmp_path / "ds")
    assert timestamps.tolist() == (START_NS + np.arange(N_ROWS) * 1_000_000_000).tolist()
    for tag in TAGS:
        expected = np.array([expected_value(tag, step) for step in range(N_ROWS)])
        np.testing.assert_allclose(wide[tag], expected)


def test_import_recovers_epoch_seconds_timestamps_and_values(
    epoch_database: Path, tmp_path: Path
) -> None:
    timestamps, wide, _ = import_query(epoch_database, SELECT_ALL, tmp_path / "ds")
    assert timestamps.tolist() == (START_NS + np.arange(N_ROWS) * 1_000_000_000).tolist()
    expected_steam = [expected_value("sim.wb.steam", step) for step in range(N_ROWS)]
    np.testing.assert_allclose(wide["sim.wb.steam"], expected_steam)


def test_naive_local_time_is_interpreted_in_the_given_timezone(tmp_path: Path) -> None:
    database = tmp_path / "sim.sqlite"
    build_full_database(database, local_iso)
    timestamps, _, _ = import_query(database, SELECT_ALL, tmp_path / "ds", tz=LOCAL_TZ)
    assert timestamps.tolist() == (START_NS + np.arange(N_ROWS) * 1_000_000_000).tolist()


def test_missing_cells_become_nan_with_bad_quality(tmp_path: Path) -> None:
    database = tmp_path / "sim.sqlite"
    build_full_database(database, iso_text)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM t WHERE tag = ? AND ts = ?", (TAGS[0], iso_text(5)))
    _, wide, _ = import_query(database, SELECT_ALL, tmp_path / "ds")
    assert np.isnan(wide[TAGS[0]][5])
    table = read_dataset(tmp_path / "ds")
    values = table["value"].to_numpy()
    assert np.all(table["quality"].to_numpy()[np.isnan(values)] == BAD)


def test_null_value_becomes_nan_with_bad_quality(tmp_path: Path) -> None:
    database = tmp_path / "sim.sqlite"
    build_full_database(database, iso_text)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE t SET value = NULL WHERE tag = ? AND ts = ?",
            (TAGS[1], iso_text(7)),
        )
    _, wide, _ = import_query(database, SELECT_ALL, tmp_path / "ds")
    assert np.isnan(wide[TAGS[1]][7])
    table = read_dataset(tmp_path / "ds")
    tag_ids = np.array(table["tag_id"].to_pylist())
    is_null_cell = (tag_ids == TAGS[1]) & np.isnan(table["value"].to_numpy())
    assert is_null_cell.sum() == 1
    assert np.all(table["quality"].to_numpy()[is_null_cell] == BAD)


def test_import_uses_the_given_quality_column(tmp_path: Path) -> None:
    database = tmp_path / "sim.sqlite"
    rows = [
        (iso_text(0), TAGS[0], 1.0, GOOD),
        (iso_text(1), TAGS[0], 2.0, UNCERTAIN),
        (iso_text(2), TAGS[0], 3.0, BAD),
    ]
    build_database(database, rows, extra_columns="quality")
    _, _, report = import_query(database, SELECT_QUALITY, tmp_path / "ds")
    table = read_dataset(tmp_path / "ds")
    assert table.sort_by("ts")["quality"].to_pylist() == [GOOD, UNCERTAIN, BAD]
    assert report.n_bad_values == 0  # n_bad_values counts NaN values, not BAD quality


def test_null_value_forces_bad_even_with_a_quality_column(tmp_path: Path) -> None:
    database = tmp_path / "sim.sqlite"
    rows = [(iso_text(0), TAGS[0], None, GOOD)]
    build_database(database, rows, extra_columns="quality")
    _, wide, report = import_query(database, SELECT_QUALITY, tmp_path / "ds")
    assert np.isnan(wide[TAGS[0]][0])
    assert report.n_bad_values == 1


def test_duplicate_rows_keep_the_last_one_in_query_order(tmp_path: Path) -> None:
    database = tmp_path / "sim.sqlite"
    rows = [
        (iso_text(0), TAGS[0], 1.0),
        (iso_text(0), TAGS[0], 9.0),
    ]
    build_database(database, rows)
    _, wide, report = import_query(database, SELECT_IN_ROWID_ORDER, tmp_path / "ds")
    assert wide[TAGS[0]][0] == 9.0
    assert report.n_duplicates_dropped == 1


def test_unsorted_rows_are_pivoted_into_a_sorted_timeline(tmp_path: Path) -> None:
    database = tmp_path / "sim.sqlite"
    rows = [
        (iso_text(2), TAGS[0], 3.0),
        (iso_text(0), TAGS[0], 1.0),
        (iso_text(1), TAGS[0], 2.0),
    ]
    build_database(database, rows)
    timestamps, wide, _ = import_query(database, SELECT_IN_ROWID_ORDER, tmp_path / "ds")
    assert np.array_equal(timestamps, START_NS + np.arange(3, dtype=np.int64) * 1_000_000_000)
    assert wide[TAGS[0]].tolist() == [1.0, 2.0, 3.0]


def test_a_non_select_statement_is_rejected_and_leaves_the_database_unchanged(
    iso_database: Path, tmp_path: Path
) -> None:
    before = table_snapshot(iso_database)
    with pytest.raises(ValueError):
        import_sql(iso_database, "DROP TABLE t", tmp_path / "ds", dataset_id="sql")
    assert table_snapshot(iso_database) == before


def test_an_empty_result_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "sim.sqlite"
    build_database(database, [])
    with pytest.raises(ValueError):
        import_sql(database, SELECT_ALL, tmp_path / "ds", dataset_id="sql")


def test_fewer_than_three_columns_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "sim.sqlite"
    build_database(database, [(iso_text(0), TAGS[0], 1.0)])
    with pytest.raises(ValueError):
        import_sql(database, "SELECT ts, tag FROM t", tmp_path / "ds", dataset_id="sql")


def test_an_unparseable_timestamp_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "sim.sqlite"
    build_database(database, [("not-a-timestamp", TAGS[0], 1.0)])
    with pytest.raises(ValueError):
        import_sql(database, SELECT_ALL, tmp_path / "ds", dataset_id="sql")


def test_report_counts_rows_tags_and_bad_values(tmp_path: Path) -> None:
    database = tmp_path / "sim.sqlite"
    build_full_database(database, iso_text)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE t SET value = NULL WHERE ts = ?", (iso_text(0),))
    _, _, report = import_query(database, SELECT_ALL, tmp_path / "ds")
    assert report.n_rows == N_ROWS
    assert report.n_tags == len(TAGS)
    assert report.n_duplicates_dropped == 0
    assert report.n_bad_values == len(TAGS)

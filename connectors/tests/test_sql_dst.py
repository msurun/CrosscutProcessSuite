"""Rows whose naive local time occurs twice at the DST fall-back stay two instants.

Europe/Warsaw sets the clocks back on 2026-10-25 at 03:00 to 02:00, so 02:00-02:59
happens twice; the importer must read the second pass per tag and count it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.sql_import import import_sql
from crosscut_sim.dataset import read_dataset, to_wide

ZONE = "Europe/Warsaw"
NS_PER_HOUR = 3_600_000_000_000
SELECT_ALL = "SELECT ts, tag, value FROM t"

# 2026-10-25 03:30 local (CET) is 02:30 UTC; 01:30 local (CEST) is 23:30 UTC the day before.
UTC_OF_FIRST_0230_NS = 1_792_885_800 * 1_000_000_000
UTC_OF_SECOND_0230_NS = 1_792_889_400 * 1_000_000_000


def make_database(path: Path, rows: list[tuple[object, ...]]) -> Path:
    """Create a sqlite file with a `t` table holding the given (ts, tag, value) rows."""
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE t (ts, tag, value)")
        connection.executemany("INSERT INTO t (ts, tag, value) VALUES (?, ?, ?)", rows)
    return path


def import_and_read(database: Path, out_dir: Path) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Import via SQL and return (int64 nanosecond timestamps, wide frame keyed by tag)."""
    import_sql(database, SELECT_ALL, ImportTarget(out_dir, "dst", tz=ZONE))
    timestamps, wide = to_wide(read_dataset(out_dir))
    return timestamps.astype("datetime64[ns]").astype(np.int64), wide


def test_a_repeated_local_time_is_kept_as_a_second_pass(tmp_path: Path) -> None:
    """One tag with 02:00, 02:30, 02:30, 03:00 keeps four increasing instants."""
    rows = [
        ("2026-10-25 02:00:00", "sim.p", 1.0),
        ("2026-10-25 02:30:00", "sim.p", 2.0),
        ("2026-10-25 02:30:00", "sim.p", 3.0),
        ("2026-10-25 03:00:00", "sim.p", 4.0),
    ]
    database = make_database(tmp_path / "sim.sqlite", rows)
    report = import_sql(database, SELECT_ALL, ImportTarget(tmp_path / "ds", "dst", tz=ZONE))
    instants, _ = import_and_read(database, tmp_path / "ds2")
    assert report.n_dst_repeats_resolved == 1
    assert report.n_duplicates_dropped == 0
    assert np.all(np.diff(instants) > 0)


def test_the_second_pass_is_one_hour_after_the_first(tmp_path: Path) -> None:
    """02:30 appears at 00:30 UTC and again at 01:30 UTC."""
    rows = [
        ("2026-10-25 02:30:00", "sim.p", 1.0),
        ("2026-10-25 02:30:00", "sim.p", 2.0),
    ]
    database = make_database(tmp_path / "sim.sqlite", rows)
    instants, _ = import_and_read(database, tmp_path / "ds")
    assert instants[1] - instants[0] == NS_PER_HOUR


def test_each_tag_resolves_its_own_repeated_hour(tmp_path: Path) -> None:
    """Two tags with their own repeated 02:30 each count one repeat and keep four samples."""
    rows = [
        ("2026-10-25 02:00:00", "sim.a", 1.0),
        ("2026-10-25 02:30:00", "sim.a", 2.0),
        ("2026-10-25 02:30:00", "sim.a", 3.0),
        ("2026-10-25 03:00:00", "sim.a", 4.0),
        ("2026-10-25 02:00:00", "sim.b", 5.0),
        ("2026-10-25 02:30:00", "sim.b", 6.0),
        ("2026-10-25 02:30:00", "sim.b", 7.0),
        ("2026-10-25 03:00:00", "sim.b", 8.0),
    ]
    database = make_database(tmp_path / "sim.sqlite", rows)
    report = import_sql(database, SELECT_ALL, ImportTarget(tmp_path / "ds", "dst", tz=ZONE))
    _, wide = import_and_read(database, tmp_path / "ds2")
    assert report.n_dst_repeats_resolved == 2
    assert not np.isnan(wide["sim.a"]).any()
    assert not np.isnan(wide["sim.b"]).any()


def test_an_explicit_offset_is_never_a_repeat(tmp_path: Path) -> None:
    """A timestamp carrying its own offset is unambiguous."""
    rows = [
        ("2026-10-25T02:30:00+02:00", "sim.p", 1.0),
        ("2026-10-25T02:30:00+01:00", "sim.p", 2.0),
    ]
    database = make_database(tmp_path / "sim.sqlite", rows)
    report = import_sql(database, SELECT_ALL, ImportTarget(tmp_path / "ds", "dst", tz=ZONE))
    assert report.n_dst_repeats_resolved == 0


def test_a_spring_forward_day_reports_no_repeats(tmp_path: Path) -> None:
    """On 2026-03-29 clocks skip forward, so no local time occurs twice."""
    rows = [
        ("2026-03-29 01:30:00", "sim.p", 1.0),
        ("2026-03-29 03:30:00", "sim.p", 2.0),
        ("2026-03-29 04:30:00", "sim.p", 3.0),
    ]
    database = make_database(tmp_path / "sim.sqlite", rows)
    report = import_sql(database, SELECT_ALL, ImportTarget(tmp_path / "ds", "dst", tz=ZONE))
    assert report.n_dst_repeats_resolved == 0


def test_repeats_are_resolved_for_naive_text_but_not_for_numeric_epoch(tmp_path: Path) -> None:
    """A naive repeat resolves; the same instants as REAL epoch seconds are already absolute."""
    naive_rows = [
        ("2026-10-25 02:30:00", "sim.p", 1.0),
        ("2026-10-25 02:30:00", "sim.p", 2.0),
    ]
    naive_db = make_database(tmp_path / "naive.sqlite", naive_rows)
    naive_report = import_sql(naive_db, SELECT_ALL, ImportTarget(tmp_path / "d1", "dst", tz=ZONE))
    numeric_rows = [
        (UTC_OF_FIRST_0230_NS / 1e9, "sim.p", 1.0),
        (UTC_OF_SECOND_0230_NS / 1e9, "sim.p", 2.0),
    ]
    numeric_db = make_database(tmp_path / "numeric.sqlite", numeric_rows)
    numeric_report = import_sql(
        numeric_db, SELECT_ALL, ImportTarget(tmp_path / "d2", "dst", tz=ZONE)
    )
    assert naive_report.n_dst_repeats_resolved == 1
    assert numeric_report.n_dst_repeats_resolved == 0
    assert numeric_report.n_duplicates_dropped == 0

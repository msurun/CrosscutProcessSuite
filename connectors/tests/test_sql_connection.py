# connectors/tests/test_sql_connection.py
"""Tests for the connection-based SQL import path.

``import_sql_connection`` and ``fetch_rows`` accept any DB-API 2.0 connection, so
these tests cover both the sqlite happy path and a stand-in for an ODBC driver
whose rows are not plain tuples.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.sql_import import fetch_rows, import_sql_connection
from crosscut_sim.dataset import read_dataset, to_wide

ROWS = [
    ("2026-01-01T00:00:00Z", "A", 1.0),
    ("2026-01-01T00:00:00Z", "B", 2.0),
    ("2026-01-01T00:00:10Z", "A", 3.0),
]
SELECT_ALL = "SELECT ts, tag, value FROM t"


class Row(list):
    """A query row shaped like an ODBC row: a sequence, but not a tuple."""


class FakeOdbcConnection:
    """A DB-API 2.0 connection that returns rows as ``Row`` objects instead of tuples."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def cursor(self) -> FakeOdbcCursor:
        """Return a cursor whose ``fetchall`` yields ``Row`` objects."""
        return FakeOdbcCursor(self._connection.cursor())


class FakeOdbcCursor:
    """A cursor wrapping a sqlite cursor and re-wrapping every row as a ``Row``."""

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    def execute(self, query: str) -> None:
        """Run the query on the wrapped sqlite cursor."""
        self._cursor.execute(query)

    def fetchall(self) -> list[Row]:
        """Return the result rows as ``Row`` objects."""
        return [Row(row) for row in self._cursor.fetchall()]

    def close(self) -> None:
        """Close the wrapped sqlite cursor."""
        self._cursor.close()


@pytest.fixture
def connection() -> sqlite3.Connection:
    """An in-memory sqlite database holding table ``t(ts, tag, value)``."""
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE t (ts TEXT, tag TEXT, value REAL)")
    connection.executemany("INSERT INTO t VALUES (?, ?, ?)", ROWS)
    return connection


@pytest.fixture
def target(tmp_path: Path) -> ImportTarget:
    """An import target writing dataset ``ds`` under a temporary output directory."""
    return ImportTarget(tmp_path / "out", "ds")


def test_import_writes_two_timestamps_and_both_tags(
    connection: sqlite3.Connection, target: ImportTarget
) -> None:
    """The dataset written from the connection has both timestamps and both tags."""
    import_sql_connection(connection, SELECT_ALL, target)

    timestamps_ns, columns = to_wide(read_dataset(target.out_dir))

    assert timestamps_ns.shape[0] == 2
    assert sorted(columns) == ["A", "B"]


def test_tag_b_has_no_sample_at_the_second_timestamp(
    connection: sqlite3.Connection, target: ImportTarget
) -> None:
    """Tag B is NaN at the second timestamp because only A was measured then."""
    import_sql_connection(connection, SELECT_ALL, target)

    _, columns = to_wide(read_dataset(target.out_dir))

    assert np.isnan(columns["B"][1])


def test_connection_is_still_usable_after_the_import(
    connection: sqlite3.Connection, target: ImportTarget
) -> None:
    """The import leaves the caller's connection open for further queries."""
    import_sql_connection(connection, SELECT_ALL, target)

    remaining = connection.execute("SELECT COUNT(*) FROM t").fetchone()

    assert remaining == (3,)


def test_rows_that_are_not_tuples_are_accepted(target: ImportTarget) -> None:
    """A driver returning list-like rows still imports, because rows become tuples."""
    sqlite_connection = sqlite3.connect(":memory:")
    sqlite_connection.execute("CREATE TABLE t (ts TEXT, tag TEXT, value REAL)")
    sqlite_connection.executemany("INSERT INTO t VALUES (?, ?, ?)", ROWS)

    report = import_sql_connection(FakeOdbcConnection(sqlite_connection), SELECT_ALL, target)

    assert report.n_rows == 2
    assert report.n_tags == 2


def test_a_statement_that_is_not_a_select_is_rejected(connection: sqlite3.Connection) -> None:
    """``fetch_rows`` refuses anything that does not start with SELECT."""
    with pytest.raises(ValueError, match="single SELECT"):
        fetch_rows(connection, "DELETE FROM t")


def test_a_query_chaining_two_statements_is_rejected(connection: sqlite3.Connection) -> None:
    """``fetch_rows`` refuses a semicolon, which would allow a second statement."""
    with pytest.raises(ValueError, match="single statement"):
        fetch_rows(connection, "SELECT 1; DROP TABLE t")


def test_a_query_returning_no_rows_is_rejected(connection: sqlite3.Connection) -> None:
    """``fetch_rows`` needs at least one row to build a dataset from."""
    with pytest.raises(ValueError, match="no rows"):
        fetch_rows(connection, "SELECT ts, tag, value FROM t WHERE tag = 'Z'")


def test_a_query_with_too_few_columns_is_rejected(connection: sqlite3.Connection) -> None:
    """``fetch_rows`` needs ts, tag and value, so two columns are not enough."""
    with pytest.raises(ValueError, match="three columns"):
        fetch_rows(connection, "SELECT ts, tag FROM t")

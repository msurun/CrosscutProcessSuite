"""Tests of the SQLite HistoryStore for live samples (Phase 1, #44).

Each test uses its own temporary database, so the tests are independent and need no server.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from crosscut_runtime.history import HistoryError, HistoryStore, history_path


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    """A fresh history store in a temporary root."""
    return HistoryStore(history_path(tmp_path))


def test_history_path_lives_under_runtime_folder(tmp_path: Path) -> None:
    assert history_path(tmp_path) == tmp_path / "_runtime" / "history.sqlite3"


def test_append_returns_inserted_count(store: HistoryStore) -> None:
    rows = [("FIC101.pv", 100.0, 1.0), ("FIC101.sp", 100.0, 2.0)]
    assert store.append(rows) == 2
    assert store.count() == 2


def test_append_ignores_duplicate_tag_and_timestamp(store: HistoryStore) -> None:
    store.append([("FIC101.pv", 100.0, 1.0)])
    inserted = store.append([("FIC101.pv", 100.0, 9.0), ("FIC101.pv", 101.0, 2.0)])
    assert inserted == 1
    assert store.query("FIC101.pv") == [(100.0, 1.0), (101.0, 2.0)]


def test_query_filters_by_tag_and_time_range_in_order(store: HistoryStore) -> None:
    store.append([("A", 3.0, 30.0), ("A", 1.0, 10.0), ("A", 2.0, 20.0), ("B", 2.0, 99.0)])
    assert store.query("A") == [(1.0, 10.0), (2.0, 20.0), (3.0, 30.0)]
    assert store.query("A", since_ts=2.0, until_ts=2.0) == [(2.0, 20.0)]


def test_query_unknown_tag_is_empty(store: HistoryStore) -> None:
    assert store.query("NOPE") == []


def test_tags_lists_distinct_tags_sorted(store: HistoryStore) -> None:
    store.append([("B", 1.0, 1.0), ("A", 1.0, 1.0), ("B", 2.0, 2.0)])
    assert store.tags() == ["A", "B"]


def test_prune_deletes_only_rows_older_than_cutoff(store: HistoryStore) -> None:
    store.append([("A", 1.0, 1.0), ("A", 2.0, 2.0), ("A", 3.0, 3.0)])
    assert store.prune(older_than_ts=2.0) == 1
    assert store.query("A") == [(2.0, 2.0), (3.0, 3.0)]


def test_count_is_zero_for_new_store(store: HistoryStore) -> None:
    assert store.count() == 0


def test_database_errors_are_wrapped_in_history_error(store: HistoryStore, tmp_path: Path) -> None:
    db_path = history_path(tmp_path)
    db_path.unlink()
    db_path.mkdir()  # sqlite cannot open a directory as a database file
    with pytest.raises(HistoryError):
        store.append([("A", 1.0, 1.0)])

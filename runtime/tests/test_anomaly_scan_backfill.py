"""pytest suite for the anomaly scan history backfill (``AnomalyScanJob._backfill``).

Covers the window request, the stored samples (floored, GOOD only), the gap-based start and the
error and no-capability paths, using a fake PI-style connector that records history requests.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from crosscut_connectors.base import (
    CAP_HISTORY,
    CAP_READ_LIVE,
    SourceConnectionError,
)
from crosscut_runtime.history import HistoryStore
from crosscut_runtime.jobs.anomaly_scan import AnomalyScanJob

NOW_S = 1_700_000_000.0
WINDOW_S = 3600.0
PERIOD_S = 60.0
TAGS = ["T1", "T2"]

HistoryRow = dict[str, object]


def _iso(epoch_s: float) -> str:
    """Epoch seconds as the UTC ISO text the connector receives."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_s))


def _row(epoch_s: float, value: float, quality: int = 0) -> HistoryRow:
    """One PI-style history row at the given UTC instant."""
    return {"timestamp_utc": _iso(epoch_s), "value": value, "quality": quality}


class FakeConnector:
    """A read-only connector with history that records every history request."""

    def __init__(
        self,
        history_rows: dict[str, list[HistoryRow]] | None = None,
        *,
        history_error: Exception | None = None,
    ) -> None:
        """Hold canned history rows per tag and an optional error to raise on history()."""
        self.history_rows = history_rows or {}
        self.history_error = history_error
        self.history_calls: list[tuple[list[str], str, str, float]] = []

    def capabilities(self) -> set[str]:
        """Advertise read_live and history, as a PI-style source does."""
        return {CAP_READ_LIVE, CAP_HISTORY}

    def history(
        self,
        tag_ids: Sequence[str],
        start_utc: str,
        end_utc: str,
        period_s: float | None = None,
    ) -> dict[str, list[HistoryRow]]:
        """Record the requested window, then answer with the canned rows (or raise)."""
        self.history_calls.append((list(tag_ids), start_utc, end_utc, float(period_s or 0.0)))
        if self.history_error is not None:
            raise self.history_error
        return {tag: self.history_rows.get(tag, []) for tag in tag_ids}

    def read_live(self, tag_ids: Sequence[str]) -> dict[str, Any]:
        """No live values: these tests only exercise the history path."""
        return {}


class _NoCapabilities:
    """A source without capabilities(): its history() must never be called."""

    def history(self, *args: Any) -> dict[str, Any]:
        """Fail the test if the backfill asks for history."""
        raise AssertionError("history() must not be called")


def _job(connector: Any, store: HistoryStore) -> AnomalyScanJob:
    """An anomaly scan job for the two test tags, with the fixed clock."""
    doc = {"id": "a1", "tags": TAGS, "period_s": PERIOD_S, "window_s": WINDOW_S}
    return AnomalyScanJob(doc, connector, store, clock=lambda: NOW_S)


def _store(tmp_path: Path) -> HistoryStore:
    """An empty history store in the test's temporary folder."""
    return HistoryStore(tmp_path / "h.sqlite3")


def test_empty_store_reads_the_whole_window_once(tmp_path: Path) -> None:
    """An empty store triggers one history call spanning [now - window_s, now] in UTC text."""
    connector = FakeConnector()
    job = _job(connector, _store(tmp_path))

    job._backfill(NOW_S)

    assert len(connector.history_calls) == 1
    tag_ids, start_utc, end_utc, period_s = connector.history_calls[0]
    assert set(tag_ids) == set(TAGS)
    assert start_utc == _iso(NOW_S - WINDOW_S)
    assert end_utc == _iso(NOW_S)
    assert period_s == PERIOD_S


def test_good_samples_are_stored_floored_to_the_period(tmp_path: Path) -> None:
    """GOOD history samples land in the store with timestamps floored to 60 s."""
    stamp = NOW_S - 1000.0 + 7.0
    store = _store(tmp_path)
    connector = FakeConnector({"T1": [_row(stamp, 12.5)], "T2": [_row(stamp, 3.0)]})
    job = _job(connector, store)

    job._backfill(NOW_S)

    expected_ts = (int(stamp) // 60) * 60.0
    assert store.query("T1") == [(expected_ts, 12.5)]
    assert store.query("T2") == [(expected_ts, 3.0)]


def test_bad_quality_samples_are_not_stored(tmp_path: Path) -> None:
    """A quality-2 (bad) history sample is dropped and never reaches the store."""
    store = _store(tmp_path)
    connector = FakeConnector({"T1": [_row(NOW_S - 500.0, 99.0, quality=2)]})
    job = _job(connector, store)

    job._backfill(NOW_S)

    assert store.query("T1") == []


def test_fresh_store_triggers_no_history_call(tmp_path: Path) -> None:
    """A stored sample 30 s old is inside the gap limit: the window is fresh, no call."""
    store = _store(tmp_path)
    store.append([("T1", NOW_S - 30.0, 1.0), ("T2", NOW_S - 30.0, 2.0)])
    connector = FakeConnector()
    job = _job(connector, store)

    result = job._backfill(NOW_S)

    assert connector.history_calls == []
    assert result is None


def test_gap_starts_the_read_at_the_newest_stored_sample(tmp_path: Path) -> None:
    """A newest stored sample 600 s old makes the read start at that sample, not the window edge."""
    store = _store(tmp_path)
    store.append([("T1", NOW_S - 600.0, 1.0), ("T2", NOW_S - 600.0, 2.0)])
    connector = FakeConnector()
    job = _job(connector, store)

    job._backfill(NOW_S)

    assert len(connector.history_calls) == 1
    assert connector.history_calls[0][1] == _iso(NOW_S - 600.0)


def test_connector_without_capabilities_is_skipped(tmp_path: Path) -> None:
    """A source that cannot report history gets no call and the backfill returns None."""
    job = _job(_NoCapabilities(), _store(tmp_path))

    assert job._backfill(NOW_S) is None


def test_history_error_is_reported_and_run_survives(tmp_path: Path) -> None:
    """A SourceConnectionError becomes {"error": ...} in _backfill and run() does not raise."""
    connector = FakeConnector(history_error=SourceConnectionError("comm loss"))
    job = _job(connector, _store(tmp_path))

    result = job._backfill(NOW_S)
    response = job.run()

    assert result is not None
    assert result["error"] == "comm loss"
    assert result["samples"] == 0
    assert "scan" in response

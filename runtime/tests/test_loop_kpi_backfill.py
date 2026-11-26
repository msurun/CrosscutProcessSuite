"""pytest suite for the runtime history backfill (issue #203).

Covers the pure planning helpers (``plan``, ``has_history``, ``good_samples``) and the
``LoopKpiJob`` integration with a fake PI-style connector whose window requests are asserted.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from crosscut_connectors.base import (
    CAP_HISTORY,
    CAP_READ_LIVE,
    ConnectorError,
    LiveValue,
    SourceConnectionError,
)
from crosscut_runtime.jobs.backfill import (
    MIN_GAP_S,
    BackfillPlan,
    backfill,
    good_samples,
    has_history,
    plan,
)
from crosscut_runtime.jobs.loop_kpi import CHANNELS, LoopKpiJob

WINDOW_S = 120.0
PERIOD_S = 1.0
NOW_S = 1_700_000_000.0
STEP_S = 6.0
ROW_COUNT = 10

# One PI-style history row: UTC ISO timestamp, value in tag units and quality code (0 GOOD).
HistoryRow = dict[str, object]


def _iso(epoch_s: float) -> str:
    """Epoch seconds as the UTC ISO text connectors use for history windows and live stamps."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_s))


def _job_doc() -> dict[str, Any]:
    """A minimal jobs.json document: one loop, one-second period, two-minute window."""
    return {"window_s": WINDOW_S, "period_s": PERIOD_S, "loops": ["loop1"]}


def _loop_doc() -> dict[str, str]:
    """A site catalogue loop document naming the four channel tags of one loop."""
    return {channel: f"{channel}1" for channel in CHANNELS}


def _rows(start_s: float) -> list[HistoryRow]:
    """``ROW_COUNT`` GOOD rows spaced ``STEP_S`` seconds from ``start_s``, all at 50 units."""
    return [
        {"timestamp_utc": _iso(start_s + index * STEP_S), "value": 50.0, "quality": 0}
        for index in range(ROW_COUNT)
    ]


def _window_rows() -> dict[str, list[HistoryRow]]:
    """History rows for all four tags, ending 6 s before the test's now instant."""
    start_s = NOW_S - (ROW_COUNT - 1) * STEP_S - STEP_S
    return {tag: _rows(start_s) for tag in _loop_doc().values()}


@dataclass(frozen=True)
class _CellTable:
    """Duck-typed stand-in for ``HistoryTable``: the four arrays ``good_samples`` reads."""

    tag_ids: np.ndarray
    ts_ns: np.ndarray
    values: np.ndarray
    qualities: np.ndarray


def _cell_table(
    times_s: list[float], values: list[float], qualities: list[int]
) -> _CellTable:
    """A one-tag table; ``ts_ns`` is epoch seconds * 1e9, values are in tag units."""
    return _CellTable(
        tag_ids=np.array(["pv1"]),
        ts_ns=np.asarray([int(stamp * 1e9) for stamp in times_s], dtype=np.int64),
        values=np.asarray(values, dtype=float).reshape(-1, 1),
        qualities=np.asarray(qualities, dtype=np.int16).reshape(-1, 1),
    )


class FakeConnector:
    """A read-only connector with optional history that records every history request."""

    def __init__(
        self,
        history_rows: dict[str, list[HistoryRow]],
        *,
        supports_history: bool = True,
        live_values: dict[str, LiveValue] | None = None,
    ) -> None:
        """Hold canned PI-style history rows and, optionally, canned live values per tag."""
        self.history_rows = history_rows
        self.supports_history = supports_history
        self.live_values = live_values or {}
        self.history_calls: list[tuple[list[str], str, str, float]] = []
        self.history_error: ConnectorError | None = None

    def capabilities(self) -> set[str]:
        """Advertise read_live and, when asked, history (OPC UA without HistoryRead lacks it)."""
        caps = {CAP_READ_LIVE}
        if self.supports_history:
            caps.add(CAP_HISTORY)
        return caps

    def history(
        self,
        tag_ids: Sequence[str],
        start_utc: str,
        end_utc: str,
        period_s: float | None = None,
    ) -> dict[str, list[HistoryRow]]:
        """Record the requested window, then answer with the canned rows of those tags."""
        self.history_calls.append((list(tag_ids), start_utc, end_utc, float(period_s or 0.0)))
        if self.history_error is not None:
            raise self.history_error
        return {tag: self.history_rows.get(tag, []) for tag in tag_ids}

    def read_live(self, tag_ids: Sequence[str]) -> dict[str, LiveValue]:
        """Return the canned live value of each requested tag; absent tags are not reported."""
        return {tag: self.live_values[tag] for tag in tag_ids if tag in self.live_values}


class _NoCapabilities:
    """A source without a capabilities() method: history must be treated as unsupported."""

    def history(self, *args: Any) -> dict[str, Any]:
        """Would read history if asked; the test asserts it is never asked."""
        raise AssertionError("history() must not be called")


class _WithCapabilities:
    """A source that advertises exactly the capability set given to the constructor."""

    def __init__(self, capabilities: set[str]) -> None:
        """Remember the capabilities this source claims."""
        self._capabilities = capabilities

    def capabilities(self) -> set[str]:
        """Return the capabilities given to the constructor."""
        return self._capabilities


def _live(value: float, ts: float, quality: int = 0) -> LiveValue:
    """A live reading with the given value, UTC stamp and quality code (0 GOOD)."""
    return LiveValue(value=value, quality=quality, timestamp_utc=_iso(ts))


def test_plan_empty_window_reads_the_whole_window() -> None:
    """A window with no sample at all is filled from now - window_s."""
    assert plan(None, NOW_S, WINDOW_S, PERIOD_S) == NOW_S - WINDOW_S


def test_plan_recent_sample_needs_no_backfill() -> None:
    """A newest sample within max(3 * period, 60 s) leaves the window fresh: nothing to do."""
    assert plan(NOW_S - MIN_GAP_S, NOW_S, WINDOW_S, PERIOD_S) is None


def test_plan_uses_the_period_when_it_exceeds_the_minimum_gap() -> None:
    """A slow source widens the gap limit to 3 * period_s, so an 80 s old sample is fresh."""
    assert plan(NOW_S - 80.0, NOW_S, WINDOW_S, 30.0) is None


def test_plan_old_sample_starts_at_the_sample() -> None:
    """An old sample inside the window starts the read at that sample, not at the window edge."""
    assert plan(NOW_S - 100.0, NOW_S, WINDOW_S, PERIOD_S) == NOW_S - 100.0


def test_plan_sample_older_than_the_window_starts_at_the_window_edge() -> None:
    """Nothing older than the window is fetched: a stale sample clamps the start to the edge."""
    assert plan(NOW_S - 300.0, NOW_S, WINDOW_S, PERIOD_S) == NOW_S - WINDOW_S


def test_has_history_is_false_without_capabilities() -> None:
    """A connector that does not expose capabilities() is treated as history-less."""
    assert has_history(_NoCapabilities()) is False


def test_has_history_is_true_with_the_history_capability() -> None:
    """A connector that lists "history" in its capabilities can be backfilled."""
    assert has_history(_WithCapabilities({CAP_HISTORY, CAP_READ_LIVE})) is True


def test_has_history_is_false_when_history_is_not_listed() -> None:
    """Advertising only read_live is not enough: the history read stays off."""
    assert has_history(_WithCapabilities({CAP_READ_LIVE})) is False


def test_good_samples_skips_bad_quality() -> None:
    """Only quality 0 (GOOD) cells are yielded; uncertain and bad cells are dropped."""
    table = _cell_table([NOW_S, NOW_S], [1.0, 3.0], [0, 1])

    assert list(good_samples(table)) == [("pv1", NOW_S, 1.0)]


def test_good_samples_skips_nan() -> None:
    """A GOOD cell holding NaN is dropped: a missing value is not a sample of zero."""
    table = _cell_table([NOW_S], [float("nan")], [0])

    assert list(good_samples(table)) == []


def test_good_samples_skips_infinity() -> None:
    """Infinities are dropped too: only finite GOOD values become samples."""
    table = _cell_table([NOW_S], [math.inf], [0])

    assert list(good_samples(table)) == []


def test_backfill_reports_a_source_error_instead_of_raising() -> None:
    """A connector error becomes a state entry for the job, never a raised exception."""
    connector = FakeConnector({})
    connector.history_error = SourceConnectionError("comm loss")
    accepted: list[tuple[str, float, float]] = []

    result = backfill(
        connector,
        BackfillPlan(["pv1"], NOW_S - WINDOW_S, NOW_S, PERIOD_S),
        lambda tag, ts, value: accepted.append((tag, ts, value)),
    )

    assert result["error"] == "comm loss"
    assert result["samples"] == 0
    assert accepted == []


def test_loop_kpi_job_backfill_fills_the_window_on_the_first_run() -> None:
    """The first run reads history and reports the number of accepted history samples."""
    job = LoopKpiJob(_job_doc(), {"loop1": _loop_doc()}, FakeConnector(_window_rows()))
    job.clock = lambda: NOW_S

    result = job.run()

    assert result["backfill"]["samples"] > 0
    assert result["backfill"]["error"] is None


def test_loop_kpi_job_backfill_hands_history_samples_to_on_sample() -> None:
    """Every accepted history sample is offered to on_sample so it can be persisted."""
    accepted: list[str] = []
    job = LoopKpiJob(
        _job_doc(),
        {"loop1": _loop_doc()},
        FakeConnector(_window_rows()),
        on_sample=lambda tag, ts, value: accepted.append(tag),
    )
    job.clock = lambda: NOW_S

    job.run()

    assert set(accepted) == set(_loop_doc().values())


def test_loop_kpi_job_backfill_reads_exactly_the_rolling_window() -> None:
    """The history request spans [now - window_s, now) in UTC ISO for every channel tag."""
    connector = FakeConnector(_window_rows())
    job = LoopKpiJob(_job_doc(), {"loop1": _loop_doc()}, connector)
    job.clock = lambda: NOW_S

    job.run()

    tag_ids, start_utc, end_utc, period_s = connector.history_calls[0]
    assert start_utc == _iso(NOW_S - WINDOW_S)
    assert end_utc == _iso(NOW_S)
    assert period_s == PERIOD_S
    assert set(tag_ids) == set(_loop_doc().values())


def test_loop_kpi_job_does_not_backfill_twice_without_a_gap() -> None:
    """A second run straight away finds a fresh window: no history call, no backfill entry."""
    connector = FakeConnector(_window_rows())
    job = LoopKpiJob(_job_doc(), {"loop1": _loop_doc()}, connector)
    job.clock = lambda: NOW_S

    job.run()
    result = job.run()

    assert len(connector.history_calls) == 1
    assert "backfill" not in result


def test_loop_kpi_job_backfills_from_the_last_sample_after_a_gap() -> None:
    """Once the gap limit passes, the read starts at the newest sample of the window."""
    connector = FakeConnector(_window_rows())
    job = LoopKpiJob(_job_doc(), {"loop1": _loop_doc()}, connector)
    now_s = NOW_S
    job.clock = lambda: now_s

    job.run()
    now_s = NOW_S + MIN_GAP_S + 1.0
    latest_s = job.window.latest
    assert latest_s is not None
    job.run()

    start_utc = connector.history_calls[-1][1]
    assert start_utc == _iso(latest_s)
    assert len(connector.history_calls) == 2


def test_loop_kpi_job_backfill_error_keeps_the_run_alive() -> None:
    """A failing history read is reported in backfill.error and never breaks run()."""
    connector = FakeConnector(_window_rows())
    connector.history_error = SourceConnectionError("comm loss")
    connector.live_values = {tag: _live(50.0, NOW_S) for tag in _loop_doc().values()}
    job = LoopKpiJob(_job_doc(), {"loop1": _loop_doc()}, connector)
    job.clock = lambda: NOW_S

    result = job.run()

    assert "samples" in result
    assert "kpi" in result
    assert result["backfill"]["error"] is not None
    assert result["backfill"]["samples"] == 0


def test_loop_kpi_job_without_history_capability_skips_backfill() -> None:
    """A connector without history keeps the live-only path: no backfill key, no history call."""
    connector = FakeConnector(_window_rows(), supports_history=False)
    job = LoopKpiJob(_job_doc(), {"loop1": _loop_doc()}, connector)
    job.clock = lambda: NOW_S

    result = job.run()

    assert "backfill" not in result
    assert connector.history_calls == []

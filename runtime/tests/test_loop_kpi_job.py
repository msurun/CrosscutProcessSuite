"""Tests for the live loop-KPI job (Phase 1, #44): window, live/offline equality, job run.

No network and no real OPC UA: a fake read_live source replays one canned sample of each tag per
call, and the series are pure deterministic math (no RNG).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from crosscut_connectors.base import LiveValue
from crosscut_loops import monitor
from crosscut_runtime.jobs.loop_kpi import (
    LoopKpiJob,
    RollingWindow,
    kpi_from_series,
    settings_for_loop,
)

# --- The synthetic oscillating loop: 601 samples, 1 s period, 60 s cycle -------------------

N_SAMPLES = 601
CYCLE_S = 60.0
N_CHANNELS = 4

LOOP_DOC: dict[str, Any] = {
    "id": "FIC-101",
    "pv": "FIC101.pv",
    "sp": "FIC101.sp",
    "out": "FIC101.out",
    "mode": "FIC101.mode",
    "out_limits": {"min": 0.0, "max": 100.0},
}

JOB_DOC: dict[str, Any] = {
    "id": "kpi-fic101",
    "kind": "loop_kpi",
    "source": "opcua-test",
    "loops": ["FIC-101"],
    "period_s": 1.0,
    "window_s": 3600.0,
    "enabled": True,
}


def synthetic_series() -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    """One oscillating loop: PV chases a 60 s cycle, OUT leads it by a quarter cycle.

    The "noise" on the PV is a deterministic incommensurate sine, so the series is reproducible
    without an RNG seed. All values in engineering units; mode 1 = AUTO (0 is MAN).
    """
    t = [float(i) for i in range(N_SAMPLES)]
    pv = [
        50.0
        + 5.0 * math.sin(2.0 * math.pi * i / CYCLE_S)
        + 0.1 * math.sin(2.0 * math.pi * i / 7.3)
        for i in t
    ]
    sp = [50.0] * N_SAMPLES
    out = [40.0 + 15.0 * math.sin(2.0 * math.pi * i / CYCLE_S - math.pi / 2.0) for i in t]
    mode = [1.0] * N_SAMPLES
    return t, pv, sp, out, mode


# --- RollingWindow --------------------------------------------------------------------------


def test_window_keeps_only_the_last_window_seconds() -> None:
    window = RollingWindow(window_s=300.0)
    # 1 s period over 1001 s: ts 0..1000.
    for i in range(1001):
        window.add("tag1", float(i), float(i))
    # The edge is latest_ts - window_s = 700; samples with ts >= 700 are kept: 700..1000.
    assert window.total() == 301
    rows = window.rows("tag1")
    assert rows[0] == (700.0, 700.0)
    assert rows[-1] == (1000.0, 1000.0)


def test_window_ignores_none_values_and_unknown_tags() -> None:
    window = RollingWindow(window_s=100.0)
    window.add("tag1", 10.0, None)
    window.add("tag1", 20.0, 5.0)
    window.add("tag1", 30.0, None)
    window.add("tag2", 40.0, 7.0)
    assert window.total() == 2
    assert window.rows("tag1") == [(20.0, 5.0)]
    assert window.rows("never_seen") == []


def test_window_sorts_rows_by_timestamp() -> None:
    window = RollingWindow(window_s=1000.0)
    window.add("tag1", 50.0, 5.0)
    window.add("tag1", 10.0, 1.0)
    window.add("tag1", 30.0, 3.0)
    window.add("tag1", 20.0, 2.0)
    assert window.rows("tag1") == [(10.0, 1.0), (20.0, 2.0), (30.0, 3.0), (50.0, 5.0)]


# --- Live KPI equals offline KPI --------------------------------------------------------------


def test_live_kpi_equals_offline_kpi() -> None:
    t, pv, sp, out, mode = synthetic_series()
    settings = settings_for_loop(LOOP_DOC)
    offline = kpi_from_series(t, pv, sp, out, mode, settings=settings)

    # The contract pins exactly these keys, and the sample count must carry through.
    assert set(offline) == {
        "n_samples",
        "service_factor",
        "saturation_fraction",
        "harris_index",
        "flatline_fraction",
        "stiction_advice",
        "oscillation_period_s",
        "classification",
        "findings",
    }
    assert offline["n_samples"] == N_SAMPLES

    # LIVE: the same series arrives sample by sample on the read_live ticks. The window is as
    # wide as the whole span, so it keeps every sample and the live rows are the full arrays.
    window = RollingWindow(window_s=float(N_SAMPLES))
    for i in range(N_SAMPLES):
        window.add(LOOP_DOC["pv"], t[i], pv[i])
        window.add(LOOP_DOC["sp"], t[i], sp[i])
        window.add(LOOP_DOC["out"], t[i], out[i])
        window.add(LOOP_DOC["mode"], t[i], mode[i])

    def channel(tag: str) -> list[float]:
        return [value for _, value in window.rows(tag)]

    live = kpi_from_series(
        [stamp for stamp, _ in window.rows(LOOP_DOC["pv"])],
        channel(LOOP_DOC["pv"]),
        channel(LOOP_DOC["sp"]),
        channel(LOOP_DOC["out"]),
        channel(LOOP_DOC["mode"]),
        settings=settings,
    )
    # Same series, same settings: the two dicts must be exactly equal.
    assert live == offline


# --- LoopKpiJob with a fake connector ---------------------------------------------------------


class FakeConnector:
    """A read_live source replaying one canned sample of each tag per call (no network)."""

    def __init__(self, tags: dict[str, tuple[list[float], list[float]]]) -> None:
        # tag -> (timestamps in epoch seconds, values in tag units).
        self._tags = tags
        self._index = 0

    def read_live(self, tag_ids: list[str]) -> dict[str, LiveValue]:
        values: dict[str, LiveValue] = {}
        for tag in tag_ids:
            stamps, vals = self._tags.get(tag, ([], []))
            if self._index < len(vals):
                values[tag] = LiveValue(
                    value=float(vals[self._index]),
                    quality=0,
                    timestamp_utc=datetime.fromtimestamp(
                        float(stamps[self._index]), tz=UTC
                    ).isoformat(),
                )
        self._index += 1
        return values


def _series_map(
    t: list[float], pv: list[float], sp: list[float], out: list[float], mode: list[float]
) -> dict[str, tuple[list[float], list[float]]]:
    return {
        LOOP_DOC["pv"]: (t, pv),
        LOOP_DOC["sp"]: (t, sp),
        LOOP_DOC["out"]: (t, out),
        LOOP_DOC["mode"]: (t, mode),
    }


def _make_job() -> LoopKpiJob:
    t, pv, sp, out, mode = synthetic_series()
    connector = FakeConnector(_series_map(t, pv, sp, out, mode))
    return LoopKpiJob(JOB_DOC, {LOOP_DOC["id"]: LOOP_DOC}, connector)


def test_job_reports_no_kpi_below_threshold() -> None:
    job = _make_job()
    result = None
    for _ in range(monitor.MIN_KPI_SAMPLES - 1):  # one sample short of the threshold
        result = job.run()
    assert result is not None
    assert result["kpi"] is None
    assert result["samples"] == N_CHANNELS * (monitor.MIN_KPI_SAMPLES - 1)


def test_job_reports_kpi_at_threshold() -> None:
    job = _make_job()
    result = None
    for _ in range(monitor.MIN_KPI_SAMPLES):  # the last tick reaches the threshold
        result = job.run()
    assert result is not None
    assert result["samples"] == N_CHANNELS * monitor.MIN_KPI_SAMPLES
    kpi = result["kpi"]
    assert set(kpi) == {LOOP_DOC["id"]}
    loop_kpi = kpi[LOOP_DOC["id"]]
    assert loop_kpi is not None
    assert "classification" in loop_kpi
    assert loop_kpi["n_samples"] == monitor.MIN_KPI_SAMPLES
    assert "flatline_fraction" in loop_kpi and "stiction_advice" in loop_kpi


def test_job_keeps_earlier_loops_as_none_below_threshold() -> None:
    # A second, data-starved loop: the map is not None once one loop qualifies, and the loop
    # still below the threshold maps to None inside it.
    t, pv, sp, out, mode = synthetic_series()
    starved = {
        "id": "FIC-202",
        "pv": "FIC202.pv",
        "sp": "FIC202.sp",
        "out": "FIC202.out",
        "mode": "FIC202.mode",
        "out_limits": {"min": 0.0, "max": 100.0},
    }
    job_doc = {**JOB_DOC, "id": "kpi-two", "loops": ["FIC-101", "FIC-202"]}
    connector = FakeConnector(_series_map(t, pv, sp, out, mode))  # only FIC-101 tags exist
    job = LoopKpiJob(job_doc, {LOOP_DOC["id"]: LOOP_DOC, starved["id"]: starved}, connector)
    for _ in range(monitor.MIN_KPI_SAMPLES):
        result = job.run()
    assert result is not None
    assert set(result["kpi"]) == {"FIC-101", "FIC-202"}
    assert result["kpi"]["FIC-202"] is None
    assert result["kpi"]["FIC-101"] is not None

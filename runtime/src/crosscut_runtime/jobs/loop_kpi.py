"""Live loop-KPI job: rolling read_live window analysed by the offline loop monitor (Phase 1, #44).

The job pulls one fresh sample of every loop's PV/SP/OUT/MODE tags on each run, keeps the last
``window_s`` seconds in a per-tag rolling buffer, and reuses ``crosscut_loops.monitor.analyze_loop``
on that buffer. Because live and offline run the same analysis code, the KPI of a live window and
of the offline record of the same series are exactly equal (the property the tests pin down).
"""

from __future__ import annotations

import time
from bisect import bisect_left
from collections.abc import Callable
from datetime import datetime
from typing import Any

import numpy as np
from crosscut_loops import monitor
from crosscut_loops.overview import (
    DELAY_S,
    FALLBACK_AMPLITUDE_LIMIT,
    OUT_HIGH,
    OUT_LOW,
    ULTIMATE_PERIOD_S,
)

from crosscut_runtime.jobs import backfill

GOOD_QUALITY = 0  # connector quality code: 0 good, 1 uncertain, 2 bad; only GOOD is analysed

# The four channels of one loop, in the order the site loop document names its tags.
CHANNELS = ("pv", "sp", "out", "mode")

DEFAULT_PROCESS_KIND = "self_regulating"  # "integrating" (a level loop) must be stated in the doc


class RollingWindow:
    """Per-tag rolling buffer: keeps only the samples of the last ``window_s`` seconds."""

    def __init__(self, window_s: float) -> None:
        """Create a window that keeps ``window_s`` seconds of samples per tag."""
        self.window_s = float(window_s)
        # tag -> (ts, value) pairs in insertion order; ts in epoch seconds, value in tag units.
        self._samples: dict[str, list[tuple[float, float]]] = {}
        # The newest timestamp added overall: the window edge is latest_ts - window_s.
        self._latest_ts: float | None = None

    def _trim(self) -> None:
        """Drop, for every tag, the samples older than the window edge (lazy, on read)."""
        if self._latest_ts is None:
            return
        cutoff = self._latest_ts - self.window_s
        for tag, rows in self._samples.items():
            kept = [row for row in rows if row[0] >= cutoff]
            if len(kept) != len(rows):
                self._samples[tag] = kept

    def add(self, tag: str, ts: float, value: float | None) -> None:
        """Append one sample of a tag; a ``None`` value is ignored (bad or missing reading)."""
        if value is None:
            return
        self._samples.setdefault(tag, []).append((float(ts), float(value)))
        if self._latest_ts is None or ts > self._latest_ts:
            self._latest_ts = float(ts)

    @property
    def latest(self) -> float | None:
        """Newest sample time in epoch seconds, None while the window is empty."""
        return self._latest_ts

    def rows(self, tag: str) -> list[tuple[float, float]]:
        """The kept samples of one tag as (ts, value), sorted by ts."""
        self._trim()
        return sorted(self._samples.get(tag, []), key=lambda row: row[0])

    def total(self) -> int:
        """Number of kept samples across all tags."""
        self._trim()
        return sum(len(rows) for rows in self._samples.values())


def _nearest(rows: list[tuple[float, float]], ts: float, tol_s: float) -> float | None:
    """Value of the row (sorted by ts) nearest to ``ts`` within ``tol_s``, else None."""
    stamps = [stamp for stamp, _ in rows]
    i = bisect_left(stamps, ts)
    near = [j for j in (i - 1, i) if 0 <= j < len(rows) and abs(stamps[j] - ts) <= tol_s]
    if not near:
        return None
    return rows[min(near, key=lambda j: abs(stamps[j] - ts))][1]


def _good_stamp(live: Any) -> float | None:
    """Epoch seconds of a GOOD live sample with a value, else None (connector stamps UTC ISO)."""
    if live is None or live.value is None or live.quality != GOOD_QUALITY:
        return None
    return datetime.fromisoformat(live.timestamp_utc).timestamp()


def align_channels(
    rows: dict[str, list[tuple[float, float]]], tol_s: float
) -> tuple[list[float], dict[str, list[float]]]:
    """Pair PV, SP, OUT and MODE by timestamp, never by position.

    Every PV sample is an anchor; each other channel contributes its nearest sample within
    ``tol_s`` (half a sample period). An anchor with a missing channel is dropped, so a dropped
    (BAD) sample of one tag removes that instant instead of shifting the other series.
    Returns the common timestamps (PV stamps) and the aligned value lists per channel.
    """
    stamps: list[float] = []
    values: dict[str, list[float]] = {channel: [] for channel in CHANNELS}
    for ts, pv in rows["pv"]:
        others = {c: _nearest(rows[c], ts, tol_s) for c in CHANNELS if c != "pv"}
        if any(v is None for v in others.values()):
            continue
        stamps.append(ts)
        values["pv"].append(pv)
        for channel, value in others.items():
            values[channel].append(float(value))  # type: ignore[arg-type]
    return stamps, values


def settings_for_loop(loop_doc: dict[str, Any]) -> monitor.LoopSettings:
    """The monitor settings of one site catalogue loop document (``$defs/loop``).

    The OUT engineering range (``out_limits.min/max``, in the OUT unit) is real knowledge from the
    catalogue, so it maps to ``out_low``/``out_high`` and is named in ``known``: the saturation and
    valve conclusions run on it. The dead time, ultimate period and amplitude limit have no per-loop
    source in the catalogue yet, so they take the overview.py placeholder constants and are NOT in
    ``known``: the monitor then withholds the Harris and Hagglund conclusions resting on them.
    """
    out_limits = loop_doc.get("out_limits") or {}
    has_range = "min" in out_limits and "max" in out_limits
    return monitor.LoopSettings(
        delay_s=DELAY_S,
        ultimate_period_s=ULTIMATE_PERIOD_S,
        amplitude_limit=FALLBACK_AMPLITUDE_LIMIT,
        # OUT tag limits in the OUT unit; the catalogue default 0..100 when not stated.
        out_low=float(out_limits["min"]) if "min" in out_limits else OUT_LOW,
        out_high=float(out_limits["max"]) if "max" in out_limits else OUT_HIGH,
        process_kind=str(loop_doc.get("process_kind", DEFAULT_PROCESS_KIND)),
        # Only knowledge the catalogue actually provides counts as "known".
        known=frozenset({monitor.OUT_RANGE}) if has_range else frozenset(),
    )


def _json_number(value: float, digits: int) -> float | None:
    """A report fraction rounded for JSON: None when NaN (withheld, not zero)."""
    if np.isnan(value):
        return None
    return round(float(value), digits)


def kpi_from_series(
    t_s: Any,
    pv: Any,
    sp: Any,
    out: Any,
    mode: Any,
    *,
    settings: monitor.LoopSettings,
) -> dict[str, Any]:
    """The monitor KPI of one loop series as a JSON-safe dict (pure: same input, same dict).

    This is the live/offline equivalence point: the offline module and the live job both reduce a
    series to this dict, so the two can be compared for exact equality.
    """
    report = monitor.analyze_loop(
        np.asarray(t_s, dtype=float),
        np.asarray(pv, dtype=float),
        np.asarray(sp, dtype=float),
        np.asarray(out, dtype=float),
        np.asarray(mode, dtype=float),
        settings=settings,
    )
    return {
        # Number of samples of the analysed stretch (dimensionless count).
        "n_samples": int(report.n_samples),
        # Share of the time the loop is in AUTO with valid data, 0..1, 4 decimals.
        "service_factor": round(float(report.service_factor), 4),
        # Share of the time OUT sits at a limit, 0..1; None when the OUT range is unknown.
        "saturation_fraction": _json_number(report.saturation_fraction, 4),
        # Minimum-variance benchmark ratio, 1.0 is best; None when the dead time is not known.
        "harris_index": _json_number(report.harris_index, 3),
        # Share of PV samples that sit frozen, 0..1; None when withheld.
        "flatline_fraction": _json_number(report.flatline_fraction, 4),
        # Valve-test advice from the stiction check: "test_valve", "unlikely", "not_ranked", ...
        "stiction_advice": report.stiction_advice,
        # Dominant oscillation period in seconds, or None when no cycle was found.
        "oscillation_period_s": report.oscillation_period_s,
        # One label: "manual", "saturated", "oscillating", "poor_performance" or "ok".
        "classification": report.classification,
        # One human-readable sentence per problem; empty list for a healthy loop.
        "findings": list(report.findings),
    }


class LoopKpiJob:
    """One live loop-KPI job: pull the live samples, buffer them, report the KPI per loop."""

    def __init__(
        self,
        job_doc: dict[str, Any],
        loop_docs: dict[str, dict[str, Any]],
        connector: Any,
        on_sample: Callable[[str, float, float], None] | None = None,
    ) -> None:
        """Create the job from its jobs.json document, the site loop docs and a read connector.

        ``connector`` is anything with ``read_live(tag_ids) -> dict[str, LiveValue]`` (a
        ``crosscut_connectors.base.Connector``); ``loop_docs`` maps a loop id to its site
        catalogue loop document. ``on_sample(tag, ts, value)``, when given, is called for every
        accepted sample (epoch seconds, tag units), e.g. to persist it to the history store.
        """
        self.job_doc = job_doc
        self.loop_docs = loop_docs
        self.connector = connector
        self.on_sample = on_sample
        self.window = RollingWindow(float(job_doc["window_s"]))
        # Wall clock for the history backfill (#203); tests replace it.
        self.clock: Callable[[], float] = time.time

    def _all_tags(self) -> list[str]:
        """Every channel tag of every loop of the job that names all four channels."""
        docs = (self.loop_docs.get(loop_id) for loop_id in self.job_doc["loops"])
        sets = (self._tag_ids(doc) for doc in docs if doc is not None)
        return list(dict.fromkeys(tag for tags in sets if tags for tag in tags.values()))

    def _accept(self, tag: str, ts: float, value: float) -> None:
        """Add one good sample to the window and hand it to ``on_sample`` (history store)."""
        self.window.add(tag, ts, value)
        if self.on_sample is not None:
            self.on_sample(tag, ts, value)

    def _backfill(self) -> dict[str, Any] | None:
        """Fill the window from history when it is empty or has a gap; None when not needed."""
        if not backfill.has_history(self.connector):
            return None
        now = self.clock()
        period = float(self.job_doc.get("period_s", 1.0))
        start = backfill.plan(self.window.latest, now, self.window.window_s, period)
        tags = self._all_tags()
        if start is None or not tags:
            return None
        todo = backfill.BackfillPlan(tags, start, now, period)
        return backfill.backfill(self.connector, todo, self._accept)

    def _tag_ids(self, loop_doc: dict[str, Any]) -> dict[str, str] | None:
        """The four tag ids of one loop doc, or None when a channel tag is not stated."""
        tags = {channel: loop_doc.get(channel) for channel in CHANNELS}
        if any(tag is None for tag in tags.values()):
            return None
        return {channel: str(tag) for channel, tag in tags.items()}

    def _pull(self, loop_doc: dict[str, Any], tags: dict[str, str]) -> None:
        """Read the four live values of one loop and append the good ones to the window."""
        values = self.connector.read_live(list(tags.values()))
        anchor = _good_stamp(values.get(tags["pv"]))
        for _channel, tag in tags.items():
            ts = _good_stamp(values.get(tag))
            if ts is None:
                continue  # missing, or not GOOD (uncertain/bad): never analysed or stored
            if anchor is not None and ts < anchor:
                # OPC UA keeps the source timestamp of the last value CHANGE: a setpoint or mode
                # that has not changed arrives with an old stamp. Read GOOD now, it is valid now,
                # so it is stamped at this read's PV instant (else alignment never pairs it).
                ts = anchor
            value = values[tag].value
            self.window.add(tag, ts, value)
            if self.on_sample is not None:
                self.on_sample(tag, ts, float(value))

    def _loop_kpi(self, loop_doc: dict[str, Any], tags: dict[str, str]) -> dict[str, Any] | None:
        """The KPI of one loop from the window, or None while below the sample threshold."""
        rows = {channel: self.window.rows(tags[channel]) for channel in CHANNELS}
        # Align by timestamp (nearest within half a sample period), not by position.
        tol_s = float(self.job_doc.get("period_s", 1.0)) / 2.0
        stamps, values = align_channels(rows, tol_s)
        if len(stamps) < monitor.MIN_KPI_SAMPLES:
            return None
        return kpi_from_series(
            stamps,
            values["pv"],
            values["sp"],
            values["out"],
            values["mode"],
            settings=settings_for_loop(loop_doc),
        )

    def run(self) -> dict[str, Any]:
        """Pull one fresh sample of every tag, then return the KPI of every loop with enough data.

        Returns ``{"samples": window.total(), "kpi": None | {loop_id: kpi dict | None}}``; the KPI
        map is None while no loop has enough samples yet, and lists loops still below the threshold
        (or with an incomplete tag set) as None inside the map.
        """
        filled = self._backfill()
        # Pass 1: every loop pulls its own fresh samples, so all tags share one read_live tick.
        for loop_id in self.job_doc["loops"]:
            loop_doc = self.loop_docs.get(loop_id)
            if loop_doc is None:
                continue
            tags = self._tag_ids(loop_doc)
            if tags is not None:
                self._pull(loop_doc, tags)
        # Pass 2: analyse every loop from the window after all tags were pulled.
        kpi: dict[str, dict[str, Any] | None] = {}
        for loop_id in self.job_doc["loops"]:
            loop_doc = self.loop_docs.get(loop_id)
            if loop_doc is None:
                continue
            tags = self._tag_ids(loop_doc)
            kpi[loop_id] = self._loop_kpi(loop_doc, tags) if tags is not None else None
        found = kpi if any(value is not None for value in kpi.values()) else None
        result: dict[str, Any] = {"samples": self.window.total(), "kpi": found}
        if filled is not None:
            result["backfill"] = filled
        return result

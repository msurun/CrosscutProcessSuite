"""Anomaly findings as variable-status flags for a controller host (ADR 015).

The anomaly_scan job publishes its events under ``jobs.<id>.scan.events`` of the runtime state,
with the time of the run in ``last_run_utc``. A finding counts only while it is active (the
event is not closed) and fresh (its job ran within ``STALE_RUNS`` periods); otherwise a dead scan
would keep a variable bad, or a silent one would hide a problem.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_runtime.store import RuntimeStore
from crosscut_runtime.variable_status import flags_from_anomaly

STALE_RUNS = 3  # a scan older than this many job periods is stale
DEFAULT_SCAN_PERIOD_S = 60.0

AnomalyFlags = Callable[[datetime], Mapping[str, set[str]]]


def _age_s(stamp: Any, now: datetime) -> float | None:
    """Seconds since an ISO time stamp, or ``None`` when it cannot be read."""
    try:
        when = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    when = when if when.tzinfo else when.replace(tzinfo=UTC)
    return (now - when).total_seconds()


def _fresh_events(
    entry: Any, period_s: float, now: datetime
) -> list[Mapping[str, Any]]:
    """Active events of one scan job state entry; none when the scan is stale or failed."""
    scan = entry.get("scan") if isinstance(entry, dict) else None
    if not isinstance(scan, dict) or scan.get("status") != "ok":
        return []
    age = _age_s(entry.get("last_run_utc"), now)
    if age is None or age > STALE_RUNS * period_s:
        return []
    return [e for e in scan.get("events", []) if isinstance(e, dict) and not e.get("closed")]


def make_anomaly_flags(root: Path) -> AnomalyFlags:
    """Port: tag -> {"anomaly"} from the active, fresh findings of every anomaly_scan job."""
    store = RuntimeStore(root)

    def flags(now: datetime) -> Mapping[str, set[str]]:
        periods = {
            job.get("id"): float(job.get("period_s", DEFAULT_SCAN_PERIOD_S))
            for job in store.load_jobs().get("jobs", [])
            if job.get("kind") == "anomaly_scan"
        }
        events: list[Mapping[str, Any]] = []
        for job_id, entry in store.load_state().get("jobs", {}).items():
            if job_id in periods:
                events += _fresh_events(entry, periods[job_id], now)
        return flags_from_anomaly(events)

    return flags

"""Tests that RuntimeService persists live samples and keeps the KPI window across runs.

A deterministic connector stamps each sample with the fake clock, so timestamps are exact and
the history rows can be checked one by one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_connectors.base import LiveValue
from crosscut_runtime.history import HistoryError, HistoryStore, history_path
from crosscut_runtime.service import RuntimeService
from crosscut_runtime.store import RuntimeStore

PERIOD_S = 1.0
START_S = 1_700_000_000.0
TAGS = ["FIC101.pv", "FIC101.sp", "FIC101.out", "FIC101.mode"]


class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        """Start the clock at a fixed epoch time."""
        self.now = START_S

    def __call__(self) -> float:
        """Return the current epoch seconds."""
        return self.now


class ClockedConnector:
    """A read_live source stamping every sample with the fake clock's current time."""

    def __init__(self, clock: FakeClock) -> None:
        """Keep the clock whose time the samples carry."""
        self._clock = clock

    def read_live(self, tag_ids: list[str]) -> dict[str, LiveValue]:
        """Return a constant good value for every tag at the clock's time."""
        stamp = datetime.fromtimestamp(self._clock.now, UTC).isoformat()
        return {tag: LiveValue(value=1.0, quality=0, timestamp_utc=stamp) for tag in tag_ids}


def _write_site(root: Path) -> None:
    """Write a minimal site with one loop FIC-101 whose four tags come from one source."""
    tags = [{"id": tag, "source": "opcua-ok"} for tag in TAGS]
    loop = {"id": "FIC-101", "pv": TAGS[0], "sp": TAGS[1], "out": TAGS[2], "mode": TAGS[3],
            "out_limits": {"min": 0.0, "max": 100.0}}
    site = {
        "schema_version": 1,
        "site": {"name": "test plant"},
        "sources": [{"id": "opcua-ok", "driver": "opcua"}],
        "tags": tags,
        "loops": [loop],
    }
    folder = root / "_site"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "site.json").write_text(json.dumps(site), encoding="utf-8")


def _setup(tmp_path: Path) -> tuple[RuntimeService, FakeClock]:
    """Write a site and one enabled loop_kpi job, then build the service on the fake clock."""
    _write_site(tmp_path)
    job = {"id": "kpi-101", "kind": "loop_kpi", "source": "opcua-ok", "loops": ["FIC-101"],
           "period_s": PERIOD_S, "window_s": 3600.0, "enabled": True}
    RuntimeStore(tmp_path).save_jobs({"schema_version": 1, "jobs": [job]})
    clock = FakeClock()

    def factory(_source_doc: dict[str, Any]) -> ClockedConnector:
        """Every source gets the clocked connector."""
        return ClockedConnector(clock)

    return RuntimeService(tmp_path, connector_factory=factory, clock=clock), clock


def _run_passes(service: RuntimeService, clock: FakeClock, passes: int) -> None:
    """Run the service for a number of passes, advancing the clock by one period each."""
    for _ in range(passes):
        service.run_once()
        clock.now += PERIOD_S


def test_live_samples_are_written_to_history(tmp_path: Path) -> None:
    service, clock = _setup(tmp_path)
    _run_passes(service, clock, 3)
    history = HistoryStore(history_path(tmp_path))
    assert history.count() == 3 * len(TAGS)
    assert history.query("FIC101.pv") == [(START_S + k, 1.0) for k in range(3)]


def test_kpi_window_accumulates_across_runs(tmp_path: Path) -> None:
    service, clock = _setup(tmp_path)
    _run_passes(service, clock, 3)
    assert _job_samples(tmp_path) == 3 * len(TAGS)


def test_history_write_failure_is_logged_and_run_continues(
    tmp_path: Path, monkeypatch: Any
) -> None:
    service, clock = _setup(tmp_path)

    def broken_append(_rows: Any) -> int:
        """Simulate a database that refuses the write."""
        raise HistoryError("disk full")

    monkeypatch.setattr(service._history, "append", broken_append)
    _run_passes(service, clock, 2)
    errors = [entry for entry in RuntimeStore(tmp_path).read_log() if entry["level"] == "error"]
    assert any("History write failed" in entry["message"] for entry in errors)
    assert _job_samples(tmp_path) == 2 * len(TAGS)


def _job_samples(root: Path) -> int:
    """The sample count the KPI job last reported in the state file."""
    return RuntimeStore(root).load_state()["jobs"]["kpi-101"]["samples"]

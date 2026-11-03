"""Failure and lifecycle tests of RuntimeService (Phase 1, #44).

A fake connector factory replaces the real OPC UA source, and a fake clock advances by the job
period on each pass, so the service runs its real scheduling logic without network or waiting.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from crosscut_connectors.base import LiveValue
from crosscut_runtime.service import RuntimeService
from crosscut_runtime.store import RuntimeStore

PERIOD_S = 1.0


class FakeClock:
    """A clock the test moves by hand; calling it returns the current epoch seconds."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        """Start the clock at a fixed epoch time."""
        self.now = start

    def __call__(self) -> float:
        """Return the current time in epoch seconds."""
        return self.now


class FakeConnector:
    """A read_live source returning one good sample per requested tag."""

    def read_live(self, tag_ids: list[str]) -> dict[str, LiveValue]:
        """Return a constant good value for every tag, stamped with the current UTC time."""
        stamp = datetime.now(UTC).isoformat()
        return {tag: LiveValue(value=1.0, quality=0, timestamp_utc=stamp) for tag in tag_ids}


class FailingConnector:
    """A read_live source whose every read raises, like a dropped OPC UA session."""

    def read_live(self, tag_ids: list[str]) -> dict[str, LiveValue]:
        """Always raise a connection error."""
        raise ConnectionError("opc ua session lost")


def _loop(loop_id: str) -> dict[str, Any]:
    """A loop whose PV, SP, OUT and mode tags exist in the site file."""
    prefix = loop_id.replace("-", "")
    return {
        "id": loop_id,
        "pv": f"{prefix}.pv",
        "sp": f"{prefix}.sp",
        "out": f"{prefix}.out",
        "mode": f"{prefix}.mode",
        "out_limits": {"min": 0.0, "max": 100.0},
    }


def _write_site(root: Path) -> None:
    """Write a minimal site.json that load_site and validate_site accept."""
    tags = []
    for loop_id in ("FIC-101", "FIC-202"):
        prefix = loop_id.replace("-", "")
        tags += [{"id": f"{prefix}.{name}", "source": source}
                 for name, source in (("pv", "opcua-ok"), ("sp", "opcua-ok"),
                                      ("out", "opcua-ok"), ("mode", "opcua-ok"))]
    site = {
        "schema_version": 1,
        "site": {"name": "test plant"},
        "sources": [{"id": "opcua-ok", "driver": "opcua"},
                    {"id": "opcua-bad", "driver": "opcua"}],
        "tags": tags,
        "loops": [_loop("FIC-101"), _loop("FIC-202")],
    }
    folder = root / "_site"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "site.json").write_text(json.dumps(site), encoding="utf-8")


def _job(job_id: str, loop_id: str, source: str, enabled: bool = True) -> dict[str, Any]:
    """A loop_kpi job document reading one loop from one source."""
    return {
        "id": job_id,
        "kind": "loop_kpi",
        "source": source,
        "loops": [loop_id],
        "period_s": PERIOD_S,
        "window_s": 3600.0,
        "enabled": enabled,
    }


def _fake_factory(source_doc: dict[str, Any]) -> Any:
    """Connector factory: the 'opcua-bad' source fails on every read, the others are healthy."""
    if source_doc.get("id") == "opcua-bad":
        return FailingConnector()
    return FakeConnector()


def _setup(
    tmp_path: Path, jobs: list[dict[str, Any]]
) -> tuple[RuntimeService, FakeClock, Path]:
    """Write site and jobs under tmp_path and build a service with the fake clock and factory."""
    _write_site(tmp_path)
    RuntimeStore(tmp_path).save_jobs({"schema_version": 1, "jobs": jobs})
    clock = FakeClock()
    service = RuntimeService(tmp_path, connector_factory=_fake_factory, clock=clock)
    return service, clock, tmp_path


def _run_passes(service: RuntimeService, clock: FakeClock, passes: int) -> None:
    """Run the service for a number of passes, advancing the clock by one job period each."""
    for _ in range(passes):
        service.run_once()
        clock.now += PERIOD_S


def _state(root: Path) -> dict[str, Any]:
    """The state document as the runtime wrote it."""
    return RuntimeStore(root).load_state()


def test_enabled_loop_job_reports_ok_with_samples(tmp_path: Path) -> None:
    service, clock, root = _setup(tmp_path, [_job("kpi-ok", "FIC-101", "opcua-ok")])
    _run_passes(service, clock, 3)
    state = _state(root)
    job_state = state["jobs"]["kpi-ok"]
    assert job_state["status"] == "ok"
    assert job_state["samples"] > 0
    assert state["service"] == "running"


def test_failing_connector_marks_job_error_and_logs(tmp_path: Path) -> None:
    jobs = [_job("kpi-bad", "FIC-101", "opcua-bad"), _job("kpi-ok", "FIC-202", "opcua-ok")]
    service, clock, root = _setup(tmp_path, jobs)
    _run_passes(service, clock, 2)
    state = _state(root)
    assert state["jobs"]["kpi-bad"]["status"] == "error"
    assert state["jobs"]["kpi-bad"]["error"]
    assert state["jobs"]["kpi-ok"]["status"] == "ok"
    errors = [entry for entry in RuntimeStore(root).read_log() if entry["level"] == "error"]
    assert any(entry.get("job") == "kpi-bad" for entry in errors)


def test_disabled_job_gets_no_run(tmp_path: Path) -> None:
    service, clock, root = _setup(tmp_path, [_job("kpi-off", "FIC-101", "opcua-ok", False)])
    _run_passes(service, clock, 2)
    job_state = _state(root)["jobs"]["kpi-off"]
    assert "status" not in job_state
    assert "last_run_utc" not in job_state


def test_anomaly_scan_job_runs_and_reports_learning_scan(tmp_path: Path) -> None:
    job = {
        "id": "scan-1",
        "kind": "anomaly_scan",
        "source": "opcua-ok",
        "tags": ["FIC101.pv", "FIC101.sp", "FIC101.out"],
        "period_s": PERIOD_S,
        "window_s": 600.0,
        "enabled": True,
    }
    service, clock, root = _setup(tmp_path, [job])
    _run_passes(service, clock, 1)
    job_state = _state(root)["jobs"]["scan-1"]
    assert job_state["status"] == "ok"
    assert job_state["scan"]["status"] == "learning"


def test_stop_marks_service_stopped(tmp_path: Path) -> None:
    service, clock, root = _setup(tmp_path, [_job("kpi-ok", "FIC-101", "opcua-ok")])
    _run_passes(service, clock, 1)
    service.stop()
    state = _state(root)
    assert state["service"] == "stopped"
    assert "updated_at_utc" in state


@pytest.mark.parametrize("passes", [1, 2])
def test_stop_after_any_pass_is_idempotent(tmp_path: Path, passes: int) -> None:
    service, clock, root = _setup(tmp_path, [_job("kpi-ok", "FIC-101", "opcua-ok")])
    _run_passes(service, clock, passes)
    service.stop()
    service.stop()
    assert _state(root)["service"] == "stopped"

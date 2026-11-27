"""Runtime state fields behind the Health page (issue #170): start, success, error, overruns."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from crosscut_runtime.service import _note_run

from .test_service_failure import _job, _run_passes, _setup, _state

T0 = "2026-11-26T10:00:00+00:00"


def test_state_carries_the_start_time_and_the_success_time(tmp_path: Path) -> None:
    jobs = [_job("kpi-ok", "FIC-101", "opcua-ok"), _job("kpi-bad", "FIC-202", "opcua-bad")]
    service, clock, root = _setup(tmp_path, jobs)
    _run_passes(service, clock, 2)
    state = _state(root)
    assert state["started_at_utc"]
    assert state["jobs"]["kpi-ok"]["last_success_utc"] == state["jobs"]["kpi-ok"]["last_run_utc"]
    bad = state["jobs"]["kpi-bad"]
    assert bad["last_error_utc"] == bad["last_run_utc"] and "last_success_utc" not in bad


def test_a_run_more_than_two_periods_after_the_last_is_an_overrun() -> None:
    st: dict[str, Any] = {"last_run_utc": T0}
    job = {"period_s": 10}
    _note_run(st, job, "2026-11-26T10:00:15+00:00", ok=True)  # 1.5 periods: on time
    assert "overrun_count" not in st
    _note_run(st, job, "2026-11-26T10:01:00+00:00", ok=True)  # 4.5 periods: overrun
    assert st["overrun_count"] == 1
    _note_run(st, job, "2026-11-26T10:03:00+00:00", ok=False)
    assert st["overrun_count"] == 2 and st["last_error_utc"] == "2026-11-26T10:03:00+00:00"

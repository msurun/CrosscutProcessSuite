"""Service integration of the tuning_review job kind (ADR 014 section 5).

The service builds the job without a connector, runs it on the fake clock and reports a
``review`` summary and status in the runtime state file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from crosscut_runtime.history import HistoryStore, history_path
from crosscut_runtime.jobs.tuning_review import epoch_to_utc
from crosscut_runtime.service import RUNNABLE_KINDS, RuntimeService
from crosscut_runtime.store import RuntimeStore, job_problems

START_S = 1_700_000_000.0
STEP_S = 10.0
WINDOW_S = 3600.0
TAGS = ["FIC101.pv", "FIC101.sp", "FIC101.out", "FIC101.mode"]
PROPOSAL_ID = "0b9f5a52-4c1e-4c63-9d5e-6f3a1e2b7c10"
JOB: dict[str, Any] = {"id": "rev", "kind": "tuning_review", "source": "dcs",
                       "loops": ["FIC-101"], "period_s": 60.0, "enabled": True}


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now: float) -> None:
        """Start at ``now`` epoch seconds."""
        self.now = now

    def __call__(self) -> float:
        """Return the current epoch seconds."""
        return self.now


def _utc(epoch_s: float) -> str:
    """ISO UTC text of epoch seconds."""
    return epoch_to_utc(epoch_s)


def _record(applied_s: float) -> dict[str, Any]:
    """An applied proposal record applied at ``applied_s``."""
    return {
        "id": PROPOSAL_ID, "version": 1, "loop_id": "FIC-101", "created_by": "alice",
        "created_at": "2026-11-05T09:00:00Z", "expires_at": "2026-11-05T17:00:00Z",
        "vendor_form": {"key": "k", "evidence": "verified"},
        "source": {"method": "simc", "robustness": 0.5,
                   "model": {"K": 1.0, "tau_s": 120.0, "theta_s": 60.0,
                             "process_kind": "self_regulating"},
                   "window": {"history": True, "start": "2026-11-05T00:00:00Z",
                              "end": "2026-11-05T06:00:00Z"},
                   "report_digest": "a" * 64},
        "confidence": {"level": "low", "reasons": ["x"]}, "caveats": [],
        "items": [{"param": "gain", "target": "FIC101.KP", "unit": "1", "from": 1.0, "to": 1.4}],
        "preview": {"label": "model prediction", "iae_ratio": 0.8,
                    "overshoot_pct": {"current": None, "proposed": None},
                    "settling_time_s": {"current": None, "proposed": None},
                    "ms": {"current": None, "proposed": None}},
        "rollback_of": None, "status": "applied", "gateway_key": "b" * 64,
        "applied": {"from_read": {"FIC101.KP": 1.0}, "to_read": {"FIC101.KP": 1.4},
                    "t": _utc(applied_s), "approver": "bob"},
        "review": None,
    }


def _fill(history: HistoryStore, start: float, end: float, std: float, seed: int) -> None:
    """Closed-loop samples every STEP_S with PV noise of the given std."""
    stamps = np.arange(start, end, STEP_S)
    err = np.random.default_rng(seed).normal(0.0, std, len(stamps))
    rows = []
    for ts, e in zip(stamps, err, strict=True):
        rows += [(TAGS[0], float(ts), 50.0 + float(e)), (TAGS[1], float(ts), 50.0),
                 (TAGS[2], float(ts), 40.0 + 0.5 * float(e)), (TAGS[3], float(ts), 1.0)]
    history.append(rows)


def _setup(root: Path, jobs: list[dict[str, Any]]) -> tuple[RuntimeService, Clock]:
    """Write site, jobs and an applied record with complete windows; clock after them."""
    loop = {"id": "FIC-101", "pv": TAGS[0], "sp": TAGS[1], "out": TAGS[2], "mode": TAGS[3]}
    site = {"schema_version": 1, "site": {"name": "t"}, "tags": [], "loops": [loop]}
    (root / "_site").mkdir(parents=True)
    (root / "_site" / "site.json").write_text(json.dumps(site), encoding="utf-8")
    RuntimeStore(root).save_jobs({"schema_version": 1, "jobs": jobs})
    history = HistoryStore(history_path(root))
    _fill(history, START_S - WINDOW_S, START_S, 1.0, 1)
    _fill(history, START_S + 540.0, START_S + 540.0 + WINDOW_S, 0.4, 2)
    folder = root / "_tuning" / "proposals"
    folder.mkdir(parents=True)
    (folder / f"{PROPOSAL_ID}.json").write_text(json.dumps(_record(START_S)), encoding="utf-8")
    clock = Clock(START_S + 540.0 + WINDOW_S + 60.0)
    return RuntimeService(root, connector_factory=_no_connector, clock=clock), clock


def _no_connector(_source: dict[str, Any]) -> Any:
    """A tuning_review job must not need a connector."""
    raise AssertionError("tuning_review asked for a connector")


def _state(root: Path) -> dict[str, Any]:
    """The state entry of the review job."""
    entry: dict[str, Any] = RuntimeStore(root).load_state()["jobs"]["rev"]
    return entry


def test_kind_is_runnable_and_job_without_window_is_valid() -> None:
    assert "tuning_review" in RUNNABLE_KINDS
    assert job_problems({"schema_version": 1, "jobs": [JOB]}) == []


def test_job_schema_still_demands_window_for_other_kinds() -> None:
    kpi = {"id": "k", "kind": "loop_kpi", "source": "s", "loops": ["a"], "period_s": 1.0,
           "enabled": True}
    assert job_problems({"schema_version": 1, "jobs": [kpi]})
    review = {key: value for key, value in JOB.items() if key != "loops"}
    assert job_problems({"schema_version": 1, "jobs": [review]})


def test_service_reviews_and_reports_ok(tmp_path: Path) -> None:
    service, _clock = _setup(tmp_path, [JOB])
    service.run_once()
    state = _state(tmp_path)
    assert state["status"] == "ok" and state["error"] is None
    assert state["review"] == {"reviewed": [PROPOSAL_ID], "pending": [], "errors": 0}
    stored = json.loads(
        (tmp_path / "_tuning" / "proposals" / f"{PROPOSAL_ID}.json").read_text(encoding="utf-8"))
    assert stored["status"] == "reviewed:improved"


def test_service_reports_idle_when_nothing_is_open(tmp_path: Path) -> None:
    service, clock = _setup(tmp_path, [JOB])
    service.run_once()
    clock.now += 120.0
    service.run_once()
    assert _state(tmp_path)["status"] == "idle"


def test_service_reports_error_for_corrupt_record(tmp_path: Path) -> None:
    service, _clock = _setup(tmp_path, [JOB])
    (tmp_path / "_tuning" / "proposals" / "broken.json").write_text("{", encoding="utf-8")
    service.run_once()
    state = _state(tmp_path)
    assert state["status"] == "error" and state["review"]["errors"] == 1
    assert state["review"]["reviewed"] == [PROPOSAL_ID]


def test_disabled_job_does_not_run(tmp_path: Path) -> None:
    service, _clock = _setup(tmp_path, [{**JOB, "enabled": False}])
    service.run_once()
    stored = json.loads(
        (tmp_path / "_tuning" / "proposals" / f"{PROPOSAL_ID}.json").read_text(encoding="utf-8"))
    assert stored["status"] == "applied"

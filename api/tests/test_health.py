"""Health aggregation with fake sources (issue #170): ok, warning and error per item."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from crosscut_api.health import HealthSources, build_report

NOW = datetime(2026, 11, 26, 12, 0, 0, tzinfo=UTC)
GIB = 2**30


def _ago(seconds: float) -> str:
    return (NOW - timedelta(seconds=seconds)).isoformat()


def _runtime(age_s: float = 2, **extra: Any) -> dict[str, Any]:
    return {"service": "running", "updated_at_utc": _ago(age_s), "started_at_utc": _ago(3600),
            "jobs": {}, **extra}


def _gateway(age_s: float = 1, **extra: Any) -> dict[str, Any]:
    return {"updated_at_utc": _ago(age_s), "mode": "advisory", "chain_ok": True,
            "audit_tail": [], "liveness": {}, **extra}


def _report(runtime: Any = None, jobs: Any = None, gateway: Any = "default", free: int = 50 * GIB,
            versions: Any = None, auth_last: Any = None) -> dict[str, Any]:
    sources = HealthSources(
        now=lambda: NOW,
        runtime_state=lambda: _runtime() if runtime is None else runtime,
        jobs=lambda: jobs or [],
        gateway_state=lambda: _gateway() if gateway == "default" else gateway,
        auth_audit_last=lambda: auth_last,
        disk=lambda: (free, 100 * GIB),
        versions=lambda: versions or {"crosscut-api": "0.0.1", "crosscut-runtime": "0.0.1"},
    )
    return build_report(sources)


def _by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["id"]: i for i in report["items"]}


def test_everything_fine_is_ok_with_uptime() -> None:
    report = _report(gateway=_gateway(liveness={"runtime": {"age_s": 1, "lost": False}}))
    items = _by_id(report)
    assert report["status"] == "ok"
    assert items["runtime"]["details"]["uptime_s"] == 3600
    assert items["gateway"]["details"]["mode"] == "advisory"
    assert all(i["reason"] and i["code"] for i in report["items"])


def test_runtime_states() -> None:
    assert _by_id(_report(runtime={"x": 1}))["runtime"]["status"] == "warning"
    stopped = _runtime(service="stopped")
    assert _by_id(_report(runtime=stopped))["runtime"]["code"] == "runtime_stopped"
    stale = _by_id(_report(runtime=_runtime(age_s=120)))["runtime"]
    assert (stale["status"], stale["code"]) == ("error", "runtime_stale")


def _job_state(runtime_jobs: dict[str, Any], period: float = 10) -> tuple[Any, Any]:
    job = {"id": "j1", "kind": "loop_kpi", "period_s": period, "enabled": True}
    return _runtime(jobs=runtime_jobs), [job, {"id": "off", "enabled": False}]


def test_job_on_time_is_ok_and_disabled_jobs_are_skipped() -> None:
    runtime, jobs = _job_state({"j1": {"status": "ok", "last_run_utc": _ago(5),
                                       "last_success_utc": _ago(5), "overrun_count": 3}})
    items = _by_id(_report(runtime=runtime, jobs=jobs))
    assert "job:off" not in items
    assert items["job:j1"]["status"] == "ok"
    assert items["job:j1"]["details"]["overrun_count"] == 3


def test_job_late_overdue_and_error() -> None:
    late, jobs = _job_state({"j1": {"status": "ok", "last_run_utc": _ago(30)}})
    assert _by_id(_report(runtime=late, jobs=jobs))["job:j1"]["status"] == "warning"
    overdue, jobs = _job_state({"j1": {"status": "ok", "last_run_utc": _ago(80)}})
    item = _by_id(_report(runtime=overdue, jobs=jobs))["job:j1"]
    assert (item["status"], item["code"]) == ("error", "job_overdue")
    assert item["details"]["lag_s"] == 70
    failed, jobs = _job_state({"j1": {"status": "error", "error": "boom",
                                      "last_run_utc": _ago(5), "last_error_utc": _ago(5)}})
    item = _by_id(_report(runtime=failed, jobs=jobs))["job:j1"]
    assert item["status"] == "error" and "boom" in item["reason"]
    assert item["details"]["last_error_utc"] == _ago(5)


def test_job_never_run_and_runtime_down_are_warnings() -> None:
    fresh, jobs = _job_state({})
    assert _by_id(_report(runtime=fresh, jobs=jobs))["job:j1"]["code"] == "job_never_run"
    stale = _runtime(age_s=300, jobs={"j1": {"last_run_utc": _ago(300)}})
    item = _by_id(_report(runtime=stale, jobs=jobs))["job:j1"]
    assert item["code"] == "job_runtime_down" and item["status"] == "warning"


def test_gateway_missing_stale_and_off() -> None:
    assert _by_id(_report(gateway=None))["gateway"]["code"] == "gateway_unreachable"
    stale = _by_id(_report(gateway=_gateway(age_s=60)))["gateway"]
    assert (stale["status"], stale["code"]) == ("error", "gateway_stale")
    off = _by_id(_report(gateway=_gateway(mode="off")))["gateway"]
    assert (off["status"], off["code"]) == ("warning", "gateway_mode_off")


def test_liveness_as_the_gateway_sees_it() -> None:
    block = {"runtime": {"age_s": 3, "lost": False, "state": "on"},
             "controllers": {"C1": {"age_s": 400, "lost": True}, "C2": {"age_s": 5, "lost": False}}}
    items = _by_id(_report(gateway=_gateway(liveness=block)))
    assert items["liveness:runtime"]["status"] == "ok"
    assert items["liveness:runtime"]["details"]["age_s"] == 3
    assert items["liveness:controller:C1"]["status"] == "error"
    assert items["liveness:controller:C2"]["status"] == "ok"


def test_missing_runtime_beat_is_a_warning_only_while_the_runtime_runs() -> None:
    assert _by_id(_report())["liveness:runtime"]["status"] == "warning"
    down = _by_id(_report(runtime=_runtime(age_s=300)))["liveness:runtime"]
    assert down["status"] == "ok"


def test_audit_last_write_and_broken_chain() -> None:
    t_ns = str(int((NOW - timedelta(seconds=90)).timestamp() * 1e9))
    gateway = _gateway(audit_tail=[{"t_ns": t_ns}])
    item = _by_id(_report(gateway=gateway))["audit"]
    assert item["status"] == "ok" and item["details"]["age_s"] == 90
    auth = _by_id(_report(auth_last=NOW - timedelta(seconds=10)))["audit"]
    assert auth["details"]["age_s"] == 10
    broken = _by_id(_report(gateway=_gateway(chain_ok=False)))
    assert broken["audit:chain"]["status"] == "error"
    assert _by_id(_report())["audit"]["code"] == "audit_empty"


def test_disk_thresholds() -> None:
    assert _by_id(_report(free=50 * GIB))["disk"]["status"] == "ok"
    assert _by_id(_report(free=8 * GIB))["disk"]["status"] == "warning"
    assert _by_id(_report(free=GIB // 2))["disk"]["status"] == "error"
    assert _by_id(_report(free=20 * GIB))["disk"]["details"]["free_bytes"] == 20 * GIB


def test_versions_differ_is_a_warning_and_missing_is_tolerated() -> None:
    mixed = _by_id(_report(versions={"crosscut-api": "1.0", "crosscut-runtime": "0.9"}))
    assert mixed["versions"]["status"] == "warning"
    none = _by_id(_report(versions={"crosscut-api": None}))
    assert none["versions"]["status"] == "ok"


def test_report_status_is_the_worst_item() -> None:
    assert _report(gateway=None)["status"] == "error"
    assert _report(gateway=_gateway(mode="off"))["status"] == "warning"

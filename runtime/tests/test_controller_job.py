"""Job wiring of the controller kind with fakes: no gateway, no plant (Phase 2.5, step 6)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from crosscut_connectors.base import LiveValue, Snapshot
from crosscut_runtime.controllers.commands import (
    commands_path,
    enqueue_command,
    pick_command,
    take_commands,
)
from crosscut_runtime.controllers.gateway_adapter import proposal_args
from crosscut_runtime.controllers.protocol import Move
from crosscut_runtime.service import RuntimeService
from crosscut_runtime.store import RuntimeStore, job_problems

TERMS_IN = [
    {"name": "low", "shape": "trap", "params": [0, 0, 2, 4]},
    {"name": "high", "shape": "trap", "params": [6, 8, 10, 10]},
]
RULE_BASE = {
    "name": "t",
    "inputs": [{"id": "cv1", "low": 0, "high": 10, "terms": TERMS_IN}],
    "outputs": [{"id": "mv1", "low": -10, "high": 10, "terms": [
        {"name": "up", "shape": "tri", "params": [5, 10, 10]}]}],
    "rules": [{"id": "r1", "if": [{"variable": "cv1", "is": "high"}],
               "then": {"variable": "mv1", "is": "up"}}],
}
CONTROLLER = {"id": "c1", "type": "fuzzy", "rule_base": "rb", "cycle_s": 30, "variables": [
    {"id": "cv1", "role": "CV", "binding": {"tag": "t.cv1"}},
    {"id": "mv1", "role": "MV", "binding": {"loop": "L1"}, "limits": {"move_max": 2.0}},
]}
SITE = {
    "schema_version": 1, "site": {"name": "t"},
    "sources": [{"id": "s1", "type": "opcua", "endpoint": "x"}],
    "tags": [{"id": "t.cv1", "source": "s1"}, {"id": "t.pv", "source": "s1"},
             {"id": "t.sp", "source": "s1"}],
    "loops": [{"id": "L1", "pv": "t.pv", "sp": "t.sp", "out": "t.pv"}],
    "controllers": [CONTROLLER],
}
JOB = {"id": "j1", "kind": "controller", "controller": "c1", "source": "s1",
       "period_s": 1, "enabled": True}


class Clock:
    """Advances 1 s per reading."""

    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


class FakeConnector:
    """Fresh good values; the CV is high, the setpoint is 50."""

    def read_snapshot(self, tag_ids: Any) -> Snapshot:
        now = datetime.now(UTC).isoformat()
        data = {"t.cv1": 9.0, "t.pv": 49.0, "t.sp": 50.0}
        return Snapshot(now, {t: LiveValue(data[t], 0, now) for t in tag_ids}, True)


def _ports(proposed: list[Move]) -> Any:
    """Gateway ports factory with a fake availability and a recording propose."""

    def make(root: Path, controller_id: str, now_ns: Any) -> Any:
        def availability(targets: list[str]) -> dict[str, dict[str, Any]]:
            return {t: {"available": True, "reasons": []} for t in targets}

        return availability, proposed.append

    return make


def _service(
    root: Path, proposed: list[Move], site: dict[str, Any] | None = None
) -> RuntimeService:
    """A service on a temp root with site, rule base and the controller job."""
    (root / "_site").mkdir()
    (root / "_site" / "site.json").write_text(json.dumps(site or SITE), encoding="utf-8")
    (root / "_fuzzy").mkdir()
    (root / "_fuzzy" / "rb.json").write_text(json.dumps(RULE_BASE), encoding="utf-8")
    RuntimeStore(root).save_jobs({"schema_version": 1, "jobs": [JOB]})
    return RuntimeService(root, lambda source: FakeConnector(), Clock(), _ports(proposed))


def _state(root: Path) -> dict[str, Any]:
    """The state entry of the controller job."""
    entry: dict[str, Any] = RuntimeStore(root).load_state()["jobs"]["j1"]
    return entry


def _site_with(change: Any) -> dict[str, Any]:
    """A deep copy of SITE changed by ``change``."""
    site = json.loads(json.dumps(SITE))
    change(site)
    return site


def test_job_schema_accepts_controller_kind() -> None:
    assert job_problems({"schema_version": 1, "jobs": [JOB]}) == []
    bad = {k: v for k, v in JOB.items() if k != "controller"}
    assert job_problems({"schema_version": 1, "jobs": [bad]})
    kpi = {"id": "k", "kind": "loop_kpi", "source": "s1", "loops": ["L1"], "period_s": 1,
           "enabled": True}
    assert job_problems({"schema_version": 1, "jobs": [kpi]})  # window_s still required


def test_controller_proposes_only_after_switch_on(tmp_path: Path) -> None:
    proposed: list[Move] = []
    service = _service(tmp_path, proposed)
    service.run_once()
    assert proposed == [] and _state(tmp_path)["status"] == "ok"
    enqueue_command(tmp_path, "c1", "switch_on")
    service.run_once()
    service.run_once()
    assert proposed and proposed[0].target_tag == "t.sp"
    assert proposed[0].value == pytest.approx(52.0)  # move_max 2
    assert _state(tmp_path)["controller"]["state"] == "on"


def test_unsupported_controller_type_is_a_job_error(tmp_path: Path) -> None:
    service = _service(tmp_path, [], _site_with(lambda s: s["controllers"][0].update(type="mpc")))
    service.run_once()
    assert "unsupported_type" in _state(tmp_path)["error"]


def test_unknown_controller_is_a_job_error(tmp_path: Path) -> None:
    service = _service(tmp_path, [], _site_with(lambda s: s.update(controllers=[])))
    service.run_once()
    assert "unknown_controller" in _state(tmp_path)["error"]


def test_binding_error_is_a_job_error(tmp_path: Path) -> None:
    def rename(site: dict[str, Any]) -> None:
        site["controllers"][0]["variables"][0]["id"] = "other"

    service = _service(tmp_path, [], _site_with(rename))
    service.run_once()
    assert "binding" in _state(tmp_path)["error"]


def test_commands_are_taken_once_and_off_wins(tmp_path: Path) -> None:
    for command in ("switch_on", "switch_off", "standby"):
        enqueue_command(tmp_path, "c1", command)
    assert commands_path(tmp_path, "c1").exists()
    taken = take_commands(tmp_path, "c1")
    assert taken == ["switch_on", "switch_off", "standby"]
    assert pick_command(taken) == "switch_off"
    assert take_commands(tmp_path, "c1") == [] and pick_command([]) is None
    with pytest.raises(ValueError):
        enqueue_command(tmp_path, "c1", "explode")


def test_corrupt_command_file_is_ignored(tmp_path: Path) -> None:
    path = commands_path(tmp_path, "c1")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert take_commands(tmp_path, "c1") == []


def test_proposal_args_carry_source_and_reason() -> None:
    args = proposal_args(Move("mv1", "t.sp", 52.0, "x" * 500), "c1", 7)
    assert args["proposer"] == "controller:c1" and args["t_ns"] == 7
    assert len(args["reason"]) == 300 and args["target_tag"] == "t.sp"

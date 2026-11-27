"""A job or controller on a tag the catalogue removed or changed refuses to run (#166).

Jobs report the reason in their status and never fall back; a controller sheds through the
existing guard path (state ``shed``, reason ``stale_dependency``) and proposes nothing more.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crosscut_connectors.dependency_index import register
from crosscut_runtime.controllers.commands import enqueue_command
from crosscut_runtime.controllers.protocol import Move
from crosscut_runtime.service import RuntimeService
from crosscut_runtime.store import RuntimeStore

from .test_controller_job import SITE, _service
from .test_controller_job import _state as controller_state
from .test_service_failure import FakeClock, _fake_factory, _job, _run_passes, _setup
from .test_service_failure import _state as job_state


def _edit_site(root: Path, change: Any) -> None:
    """Rewrite the published site file after ``change`` modified its document."""
    path = root / "_site" / "site.json"
    site = json.loads(path.read_text(encoding="utf-8"))
    change(site)
    path.write_text(json.dumps(site), encoding="utf-8")


def _tag(site: dict[str, Any], tag_id: str) -> dict[str, Any]:
    """The tag entry with that id."""
    return next(tag for tag in site["tags"] if tag["id"] == tag_id)


def test_loop_job_refuses_on_changed_unit_with_reason(tmp_path: Path) -> None:
    service, clock, root = _setup(tmp_path, [_job("kpi", "FIC-101", "opcua-ok")])
    _run_passes(service, clock, 2)
    assert job_state(root)["jobs"]["kpi"]["status"] == "ok"
    _edit_site(root, lambda s: _tag(s, "FIC101.pv").update(unit="bar"))
    _run_passes(service, clock, 1)
    state = job_state(root)["jobs"]["kpi"]
    assert state["status"] == "stale"
    assert "stale_dependency" in state["error"] and "FIC101.pv" in state["error"]
    assert "unit_changed" in state["error"]


def test_loop_job_refuses_when_loop_is_repointed_to_another_tag(tmp_path: Path) -> None:
    service, clock, root = _setup(tmp_path, [_job("kpi", "FIC-101", "opcua-ok")])
    _run_passes(service, clock, 1)
    _edit_site(root, lambda s: s["loops"][0].update(pv="FIC202.pv"))
    _run_passes(service, clock, 1)
    state = job_state(root)["jobs"]["kpi"]
    assert state["status"] == "stale"
    assert "removed" not in state["error"] and "rebound" in state["error"]


def test_removed_tag_stops_the_job_and_edit_restores_nothing_silently(tmp_path: Path) -> None:
    service, clock, root = _setup(tmp_path, [_job("kpi", "FIC-101", "opcua-ok")])
    _run_passes(service, clock, 1)
    _edit_site(root, lambda s: s["tags"].remove(_tag(s, "FIC101.sp")))
    _run_passes(service, clock, 2)
    assert job_state(root)["jobs"]["kpi"]["status"] == "stale"


def test_recorded_baseline_catches_a_change_made_before_the_runtime_saw_the_job(
    tmp_path: Path,
) -> None:
    _, _, root = _setup(tmp_path, [])
    site = json.loads((root / "_site" / "site.json").read_text(encoding="utf-8"))
    job = _job("kpi", "FIC-101", "opcua-ok")
    RuntimeStore(root).save_jobs({"schema_version": 1, "jobs": [job]})
    tags = ["FIC101.pv", "FIC101.sp", "FIC101.out", "FIC101.mode"]
    register(root, site, {"kind": "job", "id": "kpi", "tags": tags}, 1)
    _edit_site(root, lambda s: _tag(s, "FIC101.out").update(address="ns=2;s=NEW"))
    clock = FakeClock()
    service = RuntimeService(root, connector_factory=_fake_factory, clock=clock)
    _run_passes(service, clock, 1)
    state = job_state(root)["jobs"]["kpi"]
    assert state["status"] == "stale" and "remapped" in state["error"]


def test_anomaly_job_refuses_while_its_model_needs_relearn(tmp_path: Path) -> None:
    anomaly = {"id": "an", "kind": "anomaly_scan", "source": "opcua-ok", "period_s": 1.0,
               "window_s": 60.0, "enabled": True, "anomaly_id": "m1",
               "tags": ["FIC101.pv", "FIC202.pv"]}
    service, clock, root = _setup(tmp_path, [anomaly])
    site = json.loads((root / "_site" / "site.json").read_text(encoding="utf-8"))
    register(root, site, {"kind": "anomaly", "id": "m1", "tags": ["FIC101.pv", "FIC202.pv"]}, 1)
    _edit_site(root, lambda s: _tag(s, "FIC202.pv").update(unit="mm"))
    _run_passes(service, clock, 1)
    state = job_state(root)["jobs"]["an"]
    assert state["status"] == "stale" and "FIC202.pv" in state["error"]


def test_controller_sheds_and_stops_proposing_when_a_tag_changes(tmp_path: Path) -> None:
    proposed: list[Move] = []
    service = _service(tmp_path, proposed)
    service.run_once()
    enqueue_command(tmp_path, "c1", "switch_on")
    service.run_once()
    service.run_once()
    assert controller_state(tmp_path)["controller"]["state"] == "on" and proposed
    _edit_site(tmp_path, lambda s: _tag(s, "t.pv").update(unit="bar"))
    before = len(proposed)
    service.run_once()
    record = controller_state(tmp_path)["controller"]
    assert record["state"] == "shed" and record["reason"] == "stale_dependency"
    assert len(proposed) == before
    assert "t.pv" in " ".join(record["stale_reasons"])


def test_controller_with_a_removed_tag_never_runs(tmp_path: Path) -> None:
    proposed: list[Move] = []
    service = _service(tmp_path, proposed)
    service.run_once()
    enqueue_command(tmp_path, "c1", "switch_on")
    service.run_once()
    _edit_site(tmp_path, lambda s: s["tags"].remove(_tag(s, "t.cv1")))
    before = len(proposed)
    service.run_once()
    service.run_once()
    assert len(proposed) == before
    assert controller_state(tmp_path)["controller"]["state"] in ("shed", "standby")


def test_site_fixture_is_the_one_the_controller_tests_use() -> None:
    assert SITE["controllers"][0]["id"] == "c1"


def test_corrupt_index_stops_jobs_and_sheds_controllers(tmp_path: Path) -> None:
    service, clock, root = _setup(tmp_path, [_job("kpi", "FIC-101", "opcua-ok")])
    _run_passes(service, clock, 1)
    (root / "_site" / "dependencies.json").write_text("{broken", encoding="utf-8")
    _run_passes(service, clock, 1)
    state = job_state(root)["jobs"]["kpi"]
    assert state["status"] == "stale" and "dependency_index_unreadable" in state["error"]


def test_corrupt_index_sheds_a_running_controller(tmp_path: Path) -> None:
    proposed: list[Move] = []
    service = _service(tmp_path, proposed)
    service.run_once()
    enqueue_command(tmp_path, "c1", "switch_on")
    service.run_once()
    service.run_once()
    (tmp_path / "_site" / "dependencies.json").write_text("[]", encoding="utf-8")
    before = len(proposed)
    service.run_once()
    record = controller_state(tmp_path)["controller"]
    assert record["state"] == "shed" and record["reason"] == "stale_dependency"
    assert len(proposed) == before

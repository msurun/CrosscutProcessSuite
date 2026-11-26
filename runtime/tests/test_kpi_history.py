"""Tests for durable live KPI observations.

Synthetic runs pin down retention and uninterrupted finding timestamps.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from crosscut_runtime.kpi_history import record_kpi_run
from crosscut_runtime.service import RuntimeService
from crosscut_runtime.store import RuntimeStore


def test_each_loop_gets_an_observation(tmp_path: Path) -> None:
    """Missing KPI values are observations too."""
    store = RuntimeStore(tmp_path)
    state = {}
    record_kpi_run(store, {"id": "job", "loops": ["a", "b"]}, state, "first")
    entry = json.loads((tmp_path / "_runtime/kpi/a.jsonl").read_text())
    assert entry == {"utc": "first", "job": "job", "kpi": None}
    assert (tmp_path / "_runtime/kpi/b.jsonl").exists()


def test_findings_start_continue_disappear_and_survive_missing_kpi(tmp_path: Path) -> None:
    """Only an observed absence ends a finding's uninterrupted run."""
    store = RuntimeStore(tmp_path)
    job = {"id": "job", "loops": ["a"]}
    state = {"kpi": {"a": {"findings": ["old", {"code": "kept"}]}}}
    record_kpi_run(store, job, state, "first")
    state["kpi"] = {"a": {"findings": ["kept", "new"]}}
    record_kpi_run(store, job, state, "second")
    state["kpi"] = {"a": None}
    record_kpi_run(store, job, state, "third")
    assert state["findings_since"] == {"a": {"kept": "first", "new": "second"}}


def test_history_is_trimmed_only_after_the_slack_is_exceeded(tmp_path: Path) -> None:
    """Batch trimming avoids rewriting on every append."""
    path = tmp_path / "_runtime/kpi/a.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"utc":"old"}\n' * 12000)
    record_kpi_run(RuntimeStore(tmp_path), {"id": "job", "loops": ["a"]}, {}, "new")
    lines = path.read_text().splitlines()
    assert len(lines) == 10000
    assert json.loads(lines[-1])["utc"] == "new"


def test_history_io_failure_does_not_break_state_updates(tmp_path: Path) -> None:
    """A blocked history directory is logged without losing the current result."""
    store = RuntimeStore(tmp_path)
    store.state_path().parent.mkdir(parents=True)
    (tmp_path / "_runtime/kpi").write_text("blocked")
    service = RuntimeService(tmp_path)
    job = {"id": "job", "kind": "loop_kpi", "enabled": True, "loops": ["a"]}
    result = SimpleNamespace(job_id="job", ok=True, result={"kpi": {"a": {"findings": []}}})
    service._update_state([job], [result])
    assert store.load_state()["jobs"]["job"]["status"] == "ok"
    assert "history" in store.read_log()[0]["message"].lower()

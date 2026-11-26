"""Tests for catalogue-backed live loop endpoints.

Handwritten runtime files model the separate runtime process.
"""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from crosscut_api.app import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Provide catalogue loops with fresh, stale, and absent runtime jobs."""
    site = tmp_path / "_site/site.json"
    site.parent.mkdir()
    site.write_text(json.dumps({"loops": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}))
    runtime = tmp_path / "_runtime"
    runtime.mkdir()
    jobs = [{"id": "fresh", "kind": "loop_kpi", "enabled": True,
             "loops": ["a"], "period_s": 60},
            {"id": "stale", "kind": "loop_kpi", "enabled": True,
             "loops": ["b"], "period_s": 1}]
    runtime.joinpath("jobs.json").write_text(json.dumps({"jobs": jobs}))
    now = datetime.now(UTC)
    state = {"fresh": {"status": "ok", "last_run_utc": now.isoformat()},
             "stale": {"status": "ok", "last_run_utc": (now - timedelta(seconds=121)).isoformat(),
                       "kpi": {"b": {"findings": ["bad"]}},
                       "findings_since": {"b": {"bad": "first"}}}}
    runtime.joinpath("state.json").write_text(json.dumps({"jobs": state}))
    _write_history(runtime)
    return TestClient(create_app(tmp_path, auth_enabled=False))


def _write_history(runtime: Path) -> None:
    """Write two ordered observations from the separate runtime process."""
    runtime.joinpath("kpi").mkdir()
    runtime.joinpath("kpi/b.jsonl").write_text(
        '{"utc":"first","job":"stale","kpi":null}\n'
        '{"utc":"second","job":"stale","kpi":{"n_samples":10}}\n')


def test_findings_sort_before_healthy_loops(client: TestClient) -> None:
    """A finding makes its loop actionable even when its last run is stale."""
    rows = client.get("/live/loops").json()["loops"]
    assert [row["id"] for row in rows] == ["b", "a", "c"]
    assert rows[0]["findings"] == [{"code": "bad", "since_utc": "first"}]


def test_freshness_uses_job_period_and_minimum_age(client: TestClient) -> None:
    """Freshness is false for unassigned loops and old runs."""
    rows = client.get("/live/loops").json()["loops"]
    assert [row["fresh"] for row in rows] == [False, True, False]
    assert rows[2]["job"] is None


def test_detail_returns_only_the_newest_requested_history(client: TestClient) -> None:
    """History is chronological and excludes the runtime job identifier."""
    response = client.get("/live/loops/b?limit=1")
    assert response.json()["history"] == [{"utc": "second", "kpi": {"n_samples": 10}}]


def test_unknown_loop_is_not_found(client: TestClient) -> None:
    """Runtime files cannot create catalogue loops."""
    assert client.get("/live/loops/unknown").status_code == 404


def test_history_limit_is_bounded(client: TestClient) -> None:
    """The detail endpoint rejects excessive reads."""
    assert client.get("/live/loops/b?limit=5001").status_code == 422


def test_no_site_has_an_empty_worklist(tmp_path: Path) -> None:
    """An unconfigured site is a valid empty worklist."""
    client = TestClient(create_app(tmp_path, auth_enabled=False))
    assert client.get("/live/loops").json() == {"loops": []}


def test_open_equipment_event_adds_a_loop_finding(client: TestClient, tmp_path: Path) -> None:
    """An affected loop links to the equipment event's original opening time."""
    event = {"equipment": "pump", "opened_utc": "2026-11-23T10:00:00Z",
             "closed_utc": None, "loops_affected": ["a"]}
    tmp_path.joinpath("_runtime/equipment_events.jsonl").write_text(json.dumps(event) + "\n")

    row = client.get("/live/loops/a").json()

    assert row["findings"] == [{"code": "equipment_anomaly",
                                "since_utc": event["opened_utc"]}]


def test_closed_equipment_event_removes_the_loop_finding(
    client: TestClient, tmp_path: Path,
) -> None:
    """The closing journal record supersedes its earlier opening record."""
    event = {"equipment": "pump", "opened_utc": "2026-11-23T10:00:00Z",
             "closed_utc": None, "loops_affected": ["a"]}
    closed = {**event, "closed_utc": "2026-11-23T10:05:00Z"}
    tmp_path.joinpath("_runtime/equipment_events.jsonl").write_text(
        json.dumps(event) + "\n" + json.dumps(closed) + "\n")

    row = client.get("/live/loops/a").json()

    assert row["findings"] == []


def _write_ranked_runtime(tmp_path: Path) -> None:
    """Replace fixture observations with equally severe loops of different consequence."""
    site = {"loops": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "equipment": [{"id": "pump", "level": "equipment", "loops": ["a"],
                           "criticality": "critical"}]}
    tmp_path.joinpath("_site/site.json").write_text(json.dumps(site))
    observation = {"status": "warning", "health_percent": 50, "classification": "oscillating",
                   "same_period_as": ["source"], "stiction_advice": "test_valve",
                   "findings": ["external_disturbance"], "benefit": 2}
    jobs = {"fresh": {"status": "ok", "kpi": {"a": observation}},
            "stale": {"status": "ok", "kpi": {"b": observation}}}
    tmp_path.joinpath("_runtime/state.json").write_text(json.dumps({"jobs": jobs}))


def test_live_worklist_uses_catalogue_criticality_and_exposes_rank_factors(
    client: TestClient, tmp_path: Path,
) -> None:
    """A critical owner raises rank while preserving the runtime observation."""
    _write_ranked_runtime(tmp_path)

    rows = client.get("/live/loops").json()["loops"]

    assert rows[0]["id"] == "a"
    assert rows[0]["rank_factors"]["criticality"] == 4
    assert rows[0]["rank_factors"]["benefit"] == 2
    assert rows[0]["rank_score"] == rows[1]["rank_score"] * 4
    assert rows[0]["kpi"]["classification"] == "oscillating"


def test_live_detail_recommends_external_source_before_a_suspected_valve_test(
    client: TestClient, tmp_path: Path,
) -> None:
    """The exp37 disturbance case retains the first supported diagnosis in detail."""
    _write_ranked_runtime(tmp_path)

    row = client.get("/live/loops/a").json()

    assert row["diagnosis_step"] == "external_cause"
    assert row["next_action"]["code"] == "find_common_source"
    assert row["priority_rank"] == 1


def test_live_worklist_preserves_structured_valve_evidence(
    client: TestClient, tmp_path: Path,
) -> None:
    """Direct evidence metadata reaches the shared diagnosis rules unchanged."""
    _write_ranked_runtime(tmp_path)
    path = tmp_path / "_runtime/state.json"
    state = json.loads(path.read_text())
    state["jobs"]["fresh"]["kpi"]["a"]["findings"] = [
        {"code": "stiction", "evidence": "direct", "params": {"measured": True}}]
    path.write_text(json.dumps(state))

    row = client.get("/live/loops/a").json()

    assert row["findings"][0]["evidence"] == "direct"
    assert row["findings"][0]["params"] == {"measured": True}

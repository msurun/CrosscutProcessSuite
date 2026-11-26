"""Tests for per-finding user outcomes: storage, audit, worklist effect and usefulness summary.

Uses the live-loops fixture shape: loop "b" has the finding "bad" since "first".
"""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from crosscut_api.app import create_app
from crosscut_api.finding_outcomes import usefulness_summary
from fastapi.testclient import TestClient

URL = "/live/loops/b/findings/bad/outcome"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Two loops, each with one runtime finding."""
    tmp_path.joinpath("_site").mkdir()
    tmp_path.joinpath("_site/site.json").write_text(
        json.dumps({"loops": [{"id": "a"}, {"id": "b"}]}))
    runtime = tmp_path / "_runtime"
    runtime.mkdir()
    jobs = [{"id": "j", "kind": "loop_kpi", "enabled": True, "loops": ["a", "b"], "period_s": 60}]
    runtime.joinpath("jobs.json").write_text(json.dumps({"jobs": jobs}))
    state = {"j": {"status": "ok", "last_run_utc": datetime.now(UTC).isoformat(),
                   "kpi": {"a": {"findings": ["bad"]}, "b": {"findings": ["bad"]}},
                   "findings_since": {"a": {"bad": "t0"}, "b": {"bad": "first"}}}}
    runtime.joinpath("state.json").write_text(json.dumps({"jobs": state}))
    return TestClient(create_app(tmp_path, auth_enabled=False))


def _row(client: TestClient, loop_id: str) -> dict:
    """The live worklist row of one loop."""
    return client.get(f"/live/loops/{loop_id}").json()


def _later(days: float = 1) -> str:
    """An aware UTC instant in the future."""
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def test_outcome_is_stored_audited_and_attached(client: TestClient, tmp_path: Path) -> None:
    """A maintenance outcome keeps its work order and shows on the finding."""
    body = {"since_utc": "first", "outcome": "maintenance_raised", "work_order": "WO-7"}
    response = client.put(URL, json=body)
    assert response.status_code == 200
    finding = _row(client, "b")["findings"][0]
    assert finding["outcome"] == "maintenance_raised"
    assert finding["outcome_detail"]["work_order"] == "WO-7"
    assert "finding_outcome" in "".join(p.read_text() for p in tmp_path.rglob("*audit*"))
    assert len(client.get("/live/finding-outcomes").json()) == 1


def test_unknown_finding_or_stale_first_seen_time_is_rejected(client: TestClient) -> None:
    """Only a finding currently on the worklist, with its exact first-seen time, can be judged."""
    assert client.put(URL, json={"since_utc": "other", "outcome": "fixed"}).status_code == 404
    unknown = "/live/loops/zz/findings/bad/outcome"
    assert client.put(unknown, json={"since_utc": "first", "outcome": "fixed"}).status_code == 404


@pytest.mark.parametrize("extra", [
    {"outcome": "deferred"},
    {"outcome": "deferred", "until_utc": "2020-01-01T00:00:00+00:00"},
    {"outcome": "deferred", "until_utc": "2999-01-01T00:00:00"},
    {"outcome": "fixed", "until_utc": "2999-01-01T00:00:00+00:00"},
    {"outcome": "fixed", "work_order": "WO-1"},
])
def test_invalid_field_combinations_are_422(client: TestClient, extra: dict) -> None:
    """A deferral needs a future aware date; other outcomes carry no date or work order."""
    assert client.put(URL, json={"since_utc": "first", **extra}).status_code == 422


def test_deferred_finding_ranks_last_until_its_date(client: TestClient) -> None:
    """A deferral drops the loop's rank score to zero; the other loop moves first."""
    before = client.get("/live/loops").json()["loops"]
    assert {row["id"]: row["rank_score"] > 0 for row in before} == {"a": True, "b": True}
    body = {"since_utc": "first", "outcome": "deferred", "until_utc": _later()}
    assert client.put(URL, json=body).status_code == 200
    rows = client.get("/live/loops").json()["loops"]
    assert [row["id"] for row in rows] == ["a", "b"]
    assert rows[1]["rank_score"] == 0.0


def test_expired_deferral_restores_the_rank(client: TestClient, tmp_path: Path) -> None:
    """Once until_utc has passed the finding is judged by its normal rank again."""
    client.put(URL, json={"since_utc": "first", "outcome": "deferred", "until_utc": _later()})
    path = tmp_path / "_runtime/finding_outcomes.json"
    records = json.loads(path.read_text())
    for record in records.values():
        record["until_utc"] = "2020-01-01T00:00:00+00:00"
    path.write_text(json.dumps(records))
    row = _row(client, "b")
    assert "outcome" not in row["findings"][0] and row["rank_score"] > 0


def test_not_a_problem_stops_driving_the_action_and_a_new_occurrence_is_open(
    client: TestClient, tmp_path: Path,
) -> None:
    """The verdict binds to the first-seen time; a re-appearing finding has no outcome."""
    client.put(URL, json={"since_utc": "first", "outcome": "not_a_problem"})
    assert _row(client, "b")["findings"][0]["outcome"] == "not_a_problem"
    state_path = tmp_path / "_runtime/state.json"
    state = json.loads(state_path.read_text())
    state["jobs"]["j"]["findings_since"]["b"]["bad"] = "second"
    state_path.write_text(json.dumps(state))
    assert "outcome" not in _row(client, "b")["findings"][0]


def test_usefulness_summary_shares_per_code() -> None:
    """Shares are counts over all outcomes of the same finding code."""
    records = {str(i): {"code": "stiction", "outcome": outcome} for i, outcome in
               enumerate(["fixed", "fixed", "not_a_problem", "deferred"])}
    records["x"] = {"code": "saturated", "outcome": "maintenance_raised"}
    summary = {row["code"]: row for row in usefulness_summary(records)}
    assert summary["stiction"]["total"] == 4
    assert summary["stiction"]["shares"]["fixed"] == 0.5
    assert summary["saturated"]["shares"]["maintenance_raised"] == 1.0


def test_usefulness_route(client: TestClient) -> None:
    """The route summarises what was stored through PUT."""
    client.put(URL, json={"since_utc": "first", "outcome": "fixed"})
    summary = client.get("/live/finding-outcomes/usefulness").json()
    assert summary[0]["code"] == "bad" and summary[0]["shares"]["fixed"] == 1.0

"""Check equipment events and operator actions through real authorization.

Synthetic catalogue records keep runtime/API file contracts reproducible.
"""

import json
from pathlib import Path

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users
from crosscut_api.auth.audit import read_records
from crosscut_api.auth.deps import AUDIT_FILE, AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth.store import auth_dir
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.equipment_live_routes import build_equipment_live_router
from crosscut_connectors.site import save_site
from crosscut_runtime.store import write_json_atomic
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

OPENED = "2026-01-01T00:00:00+00:00"
UNTIL = "2030-01-01T00:00:00+00:00"
SITE = {"schema_version": 1, "site": {"name": "test"}, "tags": [], "loops": [],
        "equipment": [{"id": "plant", "level": "site"},
                      {"id": "pump", "level": "equipment", "parent": "plant"}],
        "sources": [{"id": "source", "driver": "opcua", "endpoint": "opc.tcp://test"}]}
EVENT = {"equipment": "pump", "opened_utc": OPENED, "closed_utc": None,
         "peak": 2.0, "contributions": [{"tag": "flow", "share": 1.0}],
         "residuals": [], "loops_affected": ["flow-loop"]}


@pytest.fixture
def world(tmp_path: Path) -> tuple[FastAPI, Path]:
    """Build authenticated routes over one synthetic equipment entry."""
    save_site(tmp_path, SITE)
    seed_users(tmp_path, DEFAULT_USERS)
    clock = FakeClock()
    context = build_auth_context(tmp_path, TEST_CONFIG, clock)
    app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(context), context))])
    app.include_router(build_auth_router_for(context))
    app.include_router(build_equipment_live_router(tmp_path, clock))
    return app, tmp_path


def as_user(app: FastAPI, username: str) -> tuple[TestClient, dict[str, str]]:
    """Return a logged-in client and its CSRF header."""
    client = TestClient(app)
    return client, csrf(login(client, username))


def write_event(root: Path, event: dict) -> None:
    """Append one event snapshot as the runtime does."""
    path = root / "_runtime" / "equipment_events.jsonl"
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")


def test_anomalies_join_model_runtime_state_and_events(world: tuple[FastAPI, Path]) -> None:
    """A viewer sees saved model status, live state and one deduplicated event."""
    app, root = world
    write_json_atomic(root / "_anomaly/equipment/pump.model.json", {"status": "learned"})
    write_json_atomic(root / "_runtime/state.json", {"jobs": {
        "scan": {"equipment": {"pump": {"status": "anomaly", "open_event": EVENT}}}}})
    write_event(root, EVENT)
    write_event(root, {**EVENT, "peak": 3.0})
    client, _ = as_user(app, "view1")
    row = client.get("/equipment/anomalies").json()[0]
    assert row["model_status"] == "learned"
    assert row["live_state"]["status"] == "anomaly"
    assert row["open_event"]["peak"] == 3.0
    assert len(row["events"]) == 1


def test_shelving_and_unshelving_are_audited(world: tuple[FastAPI, Path]) -> None:
    """An operator can set and remove an expiry without a step-up."""
    app, root = world
    client, headers = as_user(app, "op1")
    assert client.post("/equipment/pump/shelve", json={"until_utc": UNTIL},
                       headers=headers).status_code == 200
    assert json.loads((root / "_runtime/shelved.json").read_text())["pump"] == UNTIL
    assert client.delete("/equipment/pump/shelve", headers=headers).status_code == 200
    assert json.loads((root / "_runtime/shelved.json").read_text()) == {}
    records = read_records(auth_dir(root) / AUDIT_FILE)
    actions = [record["event"] for record in records if record["event"].startswith("equipment_")]
    assert actions == ["equipment_shelve", "equipment_unshelve"]


def test_an_outcome_is_saved_in_a_sidecar(world: tuple[FastAPI, Path]) -> None:
    """Feedback updates only the sidecar, preserving runtime event history."""
    app, root = world
    write_event(root, EVENT)
    client, headers = as_user(app, "op1")
    response = client.put(f"/equipment/events/{OPENED}/pump/outcome",
                          json={"outcome": "false_alarm"}, headers=headers)
    assert response.status_code == 200
    outcomes = json.loads((root / "_runtime/outcomes.json").read_text())
    assert outcomes[f"{OPENED}/pump"] == "false_alarm"
    assert client.get("/equipment/anomalies").json()[0]["events"][0]["outcome"] == "false_alarm"


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/equipment/pump/shelve", {"until_utc": UNTIL}),
    ("DELETE", "/equipment/pump/shelve", None),
    ("PUT", f"/equipment/events/{OPENED}/pump/outcome", {"outcome": "real"}),
])
def test_viewers_cannot_change_equipment_actions(
    world: tuple[FastAPI, Path], method: str, path: str, body: dict | None,
) -> None:
    """Read permission never authorizes an operator action."""
    client, headers = as_user(world[0], "view1")
    assert client.request(method, path, json=body, headers=headers).status_code == 403


@pytest.mark.parametrize("until", ["2026-01-01T00:00:00", "2020-01-01T00:00:00Z"])
def test_shelving_requires_a_future_aware_timestamp(
    world: tuple[FastAPI, Path], until: str,
) -> None:
    """Ambiguous or expired shelving requests are rejected before writing."""
    client, headers = as_user(world[0], "op1")
    assert client.post("/equipment/pump/shelve", json={"until_utc": until},
                       headers=headers).status_code == 422


def test_unknown_events_cannot_receive_an_outcome(world: tuple[FastAPI, Path]) -> None:
    """A typo must not create feedback for an event that never happened."""
    client, headers = as_user(world[0], "op1")
    assert client.put(f"/equipment/events/{OPENED}/pump/outcome", json={"outcome": "real"},
                      headers=headers).status_code == 404


def test_closed_snapshots_remove_the_open_event(world: tuple[FastAPI, Path]) -> None:
    """An append-only close replaces the opening snapshot in the worklist."""
    app, root = world
    write_event(root, EVENT)
    write_event(root, {**EVENT, "closed_utc": "2026-01-01T00:10:00+00:00"})
    client, _ = as_user(app, "view1")
    row = client.get("/equipment/anomalies").json()[0]
    assert row["open_event"] is None
    assert len(row["events"]) == 1
    assert row["events"][0]["closed_utc"] is not None


def test_missing_models_are_visible_for_catalogue_equipment(world: tuple[FastAPI, Path]) -> None:
    """A never-configured equipment remains visible without implying healthy operation."""
    client, _ = as_user(world[0], "view1")
    row = client.get("/equipment/anomalies").json()[0]
    assert row["model_status"] == "none"
    assert row["live_state"]["status"] == "no_model"


def _equipment_job() -> dict:
    """Return a minimally configured equipment scan against the synthetic catalogue."""
    return {"id": "scan", "kind": "equipment_scan", "source": "source", "enabled": True,
            "period_s": 1, "equipment": ["pump"]}


def test_equipment_jobs_require_a_saved_model(tmp_path: Path) -> None:
    """The runtime validator rejects equipment that has never been learned."""
    from crosscut_api.runtime_routes import job_problems

    assert any("model" in problem
               for problem in job_problems(_equipment_job(), SITE, set(), tmp_path))


def test_equipment_jobs_reject_unknown_equipment(tmp_path: Path) -> None:
    """A scan cannot monitor an ID absent from the catalogue."""
    from crosscut_api.runtime_routes import job_problems

    unknown = {**_equipment_job(), "equipment": ["missing"]}
    assert any("unknown equipment" in problem
               for problem in job_problems(unknown, SITE, set(), tmp_path))


def test_equipment_jobs_accept_equipment_with_a_model(tmp_path: Path) -> None:
    """A catalogue equipment with a saved learned model passes job validation."""
    from crosscut_api.runtime_routes import job_problems

    write_json_atomic(tmp_path / "_anomaly/equipment/pump.model.json", {"status": "learned"})
    assert job_problems(_equipment_job(), SITE, set(), tmp_path) == []


def test_only_the_last_fifty_events_are_returned(world: tuple[FastAPI, Path]) -> None:
    """The worklist bounds history after replaying all event identities."""
    app, root = world
    events = [{**EVENT, "opened_utc": f"2026-01-01T00:00:{second:02d}+00:00"}
              for second in range(55)]
    path = root / "_runtime/equipment_events.jsonl"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    client, _ = as_user(app, "view1")
    rows = client.get("/equipment/anomalies").json()[0]["events"]
    assert len(rows) == 50
    assert rows[-1]["opened_utc"] == "2026-01-01T00:00:05+00:00"


def test_an_unknown_outcome_is_rejected(world: tuple[FastAPI, Path]) -> None:
    """Feedback categories stay within the documented operator choices."""
    app, root = world
    write_event(root, EVENT)
    client, headers = as_user(app, "op1")
    response = client.put(f"/equipment/events/{OPENED}/pump/outcome",
                          json={"outcome": "ignore"}, headers=headers)
    assert response.status_code == 422
    assert not (root / "_runtime/outcomes.json").exists()

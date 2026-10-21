"""Tests of the supervisor routes: config storage, advice, replay, audit log and acks."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.app import create_app
from crosscut_sim.run import main as run_simulation
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
RECORD_SCHEMA = json.loads(
    (ROOT / "schemas" / "advisory-record.schema.json").read_text(encoding="utf-8")
)
DATASET = "sim-mill_circuit"
CONFIG: dict[str, Any] = {
    "schema_version": "1.0.0",
    "id": "mill-feed",
    "fuzzy_system_id": "mill_feed_supervisor",
    "output_id": "feed_change",
    "target_loop": "mill_feed",
    "mode": "advisory",
    "gates": [{"loop": "mill_feed", "block_on": ["manual", "saturated"], "warn_on": []}],
    "silent_band": 0.0,
    "min_activation": 0.0,
    "min_interval_s": 0,
    "display_clamp": [-10, 10],
}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """A client on a fresh 1-hour mill_circuit simulation (fresh, as the tests write logs)."""
    argv = ["--plant", "mill_circuit", "--duration", "1h", "--sample-period", "10"]
    assert run_simulation([*argv, "--out", str(tmp_path)]) == 0
    return TestClient(create_app(tmp_path))


def _dataset_id(client: TestClient) -> str:
    """The id of the one simulated dataset."""
    return client.get("/datasets").json()[0]["id"]


def _assert_schema_valid(record: dict[str, Any]) -> None:
    """The record validates against schemas/advisory-record.schema.json."""
    Draft202012Validator(RECORD_SCHEMA).validate(record)


def _replay_body(**changes: Any) -> dict[str, Any]:
    """A replay request that yields advices on the simulated hour."""
    return {"window_s": 600, "step_s": 600, **changes}


def _saved(client: TestClient) -> str:
    """Save the standard config; return the dataset id."""
    assert client.put("/supervisors/mill-feed", json=CONFIG).status_code == 200
    return _dataset_id(client)


def test_config_round_trip_and_listing(client: TestClient) -> None:
    assert client.get("/supervisors").json() == []
    assert client.put("/supervisors/mill-feed", json=CONFIG).json() == CONFIG
    assert client.get("/supervisors/mill-feed").json() == CONFIG
    assert client.get("/supervisors").json() == ["mill-feed"]


def test_unknown_supervisor_is_404(client: TestClient) -> None:
    assert client.get("/supervisors/nope").status_code == 404
    assert client.get("/supervisors/nope/log").status_code == 404


def test_bad_config_is_422_with_the_message(client: TestClient) -> None:
    response = client.put("/supervisors/mill-feed", json={**CONFIG, "mode": "closed_loop"})
    assert response.status_code == 422 and "mode" in response.json()["detail"]
    assert client.get("/supervisors").json() == []


def test_output_missing_in_the_fuzzy_system_is_422(client: TestClient) -> None:
    response = client.put("/supervisors/mill-feed", json={**CONFIG, "output_id": "nope"})
    assert response.status_code == 422 and "nope" in response.json()["detail"]


def test_id_must_equal_the_path(client: TestClient) -> None:
    assert client.put("/supervisors/other", json=CONFIG).status_code == 422


@pytest.mark.parametrize("sid", ["..", "a.b", "a b", "x" * 65, "..%2Fevil", "%2E%2E"])
def test_unsafe_sids_are_refused_and_write_nothing(
    client: TestClient, tmp_path: Path, sid: str
) -> None:
    response = client.put(f"/supervisors/{sid}", json={**CONFIG, "id": sid})
    assert response.status_code in {404, 422}
    assert not list(tmp_path.glob("**/evil*"))
    assert client.get("/supervisors").json() == []


def test_advise_returns_a_schema_valid_record_and_does_not_log(client: TestClient) -> None:
    dataset = _saved(client)
    body = client.post(f"/datasets/{dataset}/supervisor/mill-feed/advise", json={}).json()
    assert body["gate"]["state"] in {"open", "degraded", "blocked"}
    assert body["advice"] is not None
    _assert_schema_valid(body["advice"])
    assert client.get("/supervisors/mill-feed/log").json()["total"] == 0


def test_advise_with_unknown_dataset_or_loop(client: TestClient) -> None:
    dataset = _saved(client)
    assert client.post("/datasets/nope/supervisor/mill-feed/advise", json={}).status_code == 404
    assert client.post(f"/datasets/{dataset}/supervisor/zzz/advise", json={}).status_code == 404
    other = {**CONFIG, "target_loop": "ghost", "gates": []}
    assert client.put("/supervisors/mill-feed", json=other).status_code == 200
    response = client.post(f"/datasets/{dataset}/supervisor/mill-feed/advise", json={})
    assert response.status_code == 404 and "ghost" in response.json()["detail"]


def test_replay_without_record_leaves_the_log_empty(client: TestClient) -> None:
    dataset = _saved(client)
    url = f"/datasets/{dataset}/supervisor/mill-feed/replay"
    body = client.post(url, json=_replay_body()).json()
    assert body["advices"] and body["recorded"] == 0
    assert client.get("/supervisors/mill-feed/log").json()["total"] == 0


def test_replay_with_record_gives_an_intact_chain_and_acks_appear(client: TestClient) -> None:
    dataset = _saved(client)
    url = f"/datasets/{dataset}/supervisor/mill-feed/replay"
    advices = client.post(url, json=_replay_body(record=True)).json()["advices"]
    log = client.get("/supervisors/mill-feed/log").json()
    assert log["chain"]["ok"] and log["total"] == len(advices) > 0
    for record in log["records"]:
        _assert_schema_valid(record)
    ack_url = f"/supervisors/mill-feed/log/{advices[0]['advice_id']}/ack"
    sent = {"decision": "accepted", "reason_code": "ok", "who": "operator", "note": "n"}
    stored = client.post(ack_url, json=sent).json()
    _assert_schema_valid(stored)
    after = client.get("/supervisors/mill-feed/log", params={"since_index": log["total"]}).json()
    assert [record["kind"] for record in after["records"]] == ["ack"]
    assert after["chain"]["ok"] and after["total"] == log["total"] + 1


def test_ack_of_an_unknown_advice_is_404(client: TestClient) -> None:
    _saved(client)
    sent = {"decision": "accepted", "reason_code": "ok", "who": "operator"}
    response = client.post(f"/supervisors/mill-feed/log/{'0' * 64}/ack", json=sent)
    assert response.status_code == 404


def test_ack_with_a_bad_decision_or_empty_who_is_422(client: TestClient) -> None:
    dataset = _saved(client)
    url = f"/datasets/{dataset}/supervisor/mill-feed/replay"
    advice_id = client.post(url, json=_replay_body(record=True)).json()["advices"][0]["advice_id"]
    ack_url = f"/supervisors/mill-feed/log/{advice_id}/ack"
    good = {"decision": "accepted", "reason_code": "ok", "who": "operator"}
    for bad in ({"decision": "maybe"}, {"who": "  "}, {"reason_code": ""}):
        assert client.post(ack_url, json={**copy.deepcopy(good), **bad}).status_code == 422
    assert client.get("/supervisors/mill-feed/log").json()["total"] > 0

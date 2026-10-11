"""Tests of the fuzzy routes: library, what-if inference and replay on a simulated dataset."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from crosscut_api.app import create_app
from crosscut_fuzzy.library import load_document
from crosscut_sim.run import main as run_simulation
from fastapi.testclient import TestClient

EXAMPLE_ID = "mill_feed_supervisor"
INPUTS = {"mill_power": 3300.0, "p80": 150.0}


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("fuzzy")
    argv = ["--plant", "mill_circuit", "--duration", "1h", "--sample-period", "10"]
    assert run_simulation([*argv, "--out", str(root)]) == 0
    return root


@pytest.fixture(scope="module")
def client(data_root: Path) -> TestClient:
    return TestClient(create_app(data_root))


@pytest.fixture(scope="module")
def document(data_root: Path) -> dict:
    return load_document(EXAMPLE_ID, data_root / "_fuzzy")


def test_the_bundled_example_is_listed_and_can_be_loaded(client: TestClient) -> None:
    listed = client.get("/fuzzy").json()
    assert {"id": EXAMPLE_ID, "name": listed[0]["name"], "source": "example"} in listed
    assert client.get(f"/fuzzy/{EXAMPLE_ID}").json()["inputs"][0]["id"] == "mill_power"


def test_an_unknown_system_is_a_404_and_a_path_like_id_is_refused(client: TestClient) -> None:
    assert client.get("/fuzzy/nope").status_code == 404
    assert client.put("/fuzzy/..%2Fevil", json={}).status_code in {404, 422}


def test_saving_creates_a_user_copy_that_is_listed_as_user(
    client: TestClient, document: dict, data_root: Path
) -> None:
    edited = copy.deepcopy(document)
    edited["name"] = "My copy"
    assert client.put("/fuzzy/my_copy", json=edited).status_code == 200
    listed = {item["id"]: item for item in client.get("/fuzzy").json()}
    assert listed["my_copy"] == {"id": "my_copy", "name": "My copy", "source": "user"}
    assert (data_root / "_fuzzy" / "my_copy.json").exists()


def test_saving_an_invalid_system_is_refused_and_writes_nothing(
    client: TestClient, document: dict, data_root: Path
) -> None:
    broken = copy.deepcopy(document)
    broken["rules"][0]["then"]["is"] = "no_such_term"
    response = client.put("/fuzzy/broken", json=broken)
    assert response.status_code == 422 and "no_such_term" in response.json()["detail"]
    assert not (data_root / "_fuzzy" / "broken.json").exists()


def test_what_if_inference_explains_the_decision(client: TestClient, document: dict) -> None:
    body = client.post("/fuzzy/infer", json={"document": document, "inputs": INPUTS}).json()
    assert body["outputs"]["feed_change"]["crisp"] < -5.0
    assert body["dominant"][0] == "r1" and body["firing"]["r1"] == pytest.approx(1.0)
    assert body["degrees"]["mill_power"]["high"] == pytest.approx(1.0)
    assert len(body["outputs"]["feed_change"]["universe"]) == len(
        body["outputs"]["feed_change"]["aggregated"]
    )


def test_what_if_with_no_rule_firing_has_no_crisp_value(client: TestClient, document: dict) -> None:
    far = {"mill_power": 2500.0, "p80": 300.0}
    body = client.post("/fuzzy/infer", json={"document": document, "inputs": far}).json()
    assert body["outputs"]["feed_change"]["crisp"] is None and body["dominant"] == []


def test_what_if_rejects_missing_inputs(client: TestClient, document: dict) -> None:
    response = client.post("/fuzzy/infer", json={"document": document, "inputs": {"p80": 150.0}})
    assert response.status_code == 422


def test_replay_returns_inputs_outputs_and_the_actual_tag(
    client: TestClient, document: dict, data_root: Path
) -> None:
    dataset = client.get("/datasets").json()[0]["id"]
    request = {"document": document, "max_points": 100}
    body = client.post(f"/datasets/{dataset}/fuzzy/replay", json=request).json()
    assert len(body["t"]) == 100
    assert set(body["inputs"]) == {"mill_power", "p80"}
    assert len(body["outputs"]["feed_change"]) == 100
    assert len(body["actual"]["feed_change"]) == 100


def test_replay_reports_a_missing_tag(client: TestClient, document: dict) -> None:
    dataset = client.get("/datasets").json()[0]["id"]
    wrong = copy.deepcopy(document)
    wrong["inputs"][0]["tag"] = "sim.mc.nothing"
    response = client.post(f"/datasets/{dataset}/fuzzy/replay", json={"document": wrong})
    assert response.status_code == 422 and "sim.mc.nothing" in response.json()["detail"]


def test_every_save_adds_a_version_that_can_be_read_back(
    client: TestClient, document: dict
) -> None:
    edited = copy.deepcopy(document)
    edited["rules"][0]["weight"] = 0.5
    assert client.put("/fuzzy/versioned", json=document).status_code == 200
    assert client.put("/fuzzy/versioned", json=edited).status_code == 200

    versions = client.get("/fuzzy/versioned/versions").json()

    assert len(versions) == 2
    newest = client.get(f"/fuzzy/versioned/versions/{versions[0]}").json()
    assert newest["rules"][0]["weight"] == 0.5


def test_unknown_and_malformed_version_ids_are_refused(client: TestClient) -> None:
    assert client.get("/fuzzy/versioned/versions/20200101T000000000000Z").status_code == 404
    assert client.get("/fuzzy/versioned/versions/not-a-version").status_code == 422


def test_the_diff_route_reports_a_changed_rule_weight(client: TestClient, document: dict) -> None:
    edited = copy.deepcopy(document)
    edited["rules"][0]["weight"] = 0.5

    changes = client.post("/fuzzy/diff", json={"old": document, "new": edited}).json()

    assert changes == [
        {"code": "rule_changed", "rule": document["rules"][0]["id"], "fields": ["weight"]}
    ]

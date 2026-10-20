"""Tests for the per-loop knowledge routes (GET and PUT .../knowledge).

Every test gets its own copy of the simulated dataset so a PUT that writes project.json
never leaks into another test.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from crosscut_api.app import create_app
from crosscut_sim.run import main as run_simulation
from fastapi.testclient import TestClient

DATASET = "mill_circuit_nominal_seed42"
PROJECT_FILE = "project.json"
KNOWLEDGE_KEYS = {"delay_s", "ultimate_period_s", "amplitude_limit", "process_kind"}


@pytest.fixture(scope="module")
def recorded_dataset_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Simulate a 1-hour mill circuit run once and return its dataset directory."""
    root = tmp_path_factory.mktemp("recorded")
    argv = [
        "--plant",
        "mill_circuit",
        "--scenario",
        "nominal",
        "--duration",
        "1h",
        "--sample-period",
        "10",
    ]
    assert run_simulation([*argv, "--out", str(root)]) == 0
    return root / DATASET


@pytest.fixture()
def data_root(recorded_dataset_dir: Path, tmp_path: Path) -> Path:
    """Copy the recorded dataset into a fresh root so a test can write its project file."""
    fresh_root = tmp_path / "datasets"
    fresh_root.mkdir()
    shutil.copytree(recorded_dataset_dir, fresh_root / DATASET)
    # The simulator writes its own project.json; the tests start from "no project file yet".
    (fresh_root / DATASET / PROJECT_FILE).unlink(missing_ok=True)
    return fresh_root


@pytest.fixture()
def client(data_root: Path) -> TestClient:
    """Create a test HTTP client over the fresh data root."""
    return TestClient(create_app(data_root))


@pytest.fixture()
def loop_name(client: TestClient) -> str:
    """Return the name of the first loop the loops endpoint discovers."""
    body = client.get(f"/datasets/{DATASET}/loops").json()
    return body["loops"][0]["name"]


def _knowledge_url(loop_name: str) -> str:
    """Return the knowledge route for one loop of the recorded dataset."""
    return f"/datasets/{DATASET}/loops/{loop_name}/knowledge"


def test_get_returns_the_document_with_a_knowledge_block(
    client: TestClient, loop_name: str
) -> None:
    body = client.get(_knowledge_url(loop_name)).json()
    assert set(body) == {"loop", "knowledge", "saved", "ranges"}
    assert body["loop"] == loop_name


def test_get_knowledge_holds_the_four_editable_keys(client: TestClient, loop_name: str) -> None:
    knowledge = client.get(_knowledge_url(loop_name)).json()["knowledge"]
    assert set(knowledge) == KNOWLEDGE_KEYS


def test_a_discovered_loop_is_self_regulating(client: TestClient, loop_name: str) -> None:
    knowledge = client.get(_knowledge_url(loop_name)).json()["knowledge"]
    assert knowledge["process_kind"] == "self_regulating"


def test_knowledge_is_not_saved_before_any_put(client: TestClient, loop_name: str) -> None:
    body = client.get(_knowledge_url(loop_name)).json()
    assert body["saved"] is False


def test_put_returns_the_new_delay(client: TestClient, loop_name: str) -> None:
    response = client.put(_knowledge_url(loop_name), json={"delay_s": 4.0})
    assert response.status_code == 200
    assert response.json()["knowledge"]["delay_s"] == 4.0


def test_put_marks_the_knowledge_as_saved(client: TestClient, loop_name: str) -> None:
    response = client.put(_knowledge_url(loop_name), json={"delay_s": 4.0})
    assert response.json()["saved"] is True


def test_put_creates_a_project_file_holding_every_loop(
    client: TestClient, loop_name: str, data_root: Path
) -> None:
    client.put(_knowledge_url(loop_name), json={"delay_s": 4.0})
    project = json.loads((data_root / DATASET / PROJECT_FILE).read_text())
    stored_names = {loop["name"] for loop in project["loops"]}
    discovered_names = {
        loop["name"] for loop in client.get(f"/datasets/{DATASET}/loops").json()["loops"]
    }
    assert stored_names == discovered_names


def test_a_get_after_a_put_returns_the_saved_delay(client: TestClient, loop_name: str) -> None:
    client.put(_knowledge_url(loop_name), json={"delay_s": 4.0})
    knowledge = client.get(_knowledge_url(loop_name)).json()["knowledge"]
    assert knowledge["delay_s"] == 4.0


def test_put_accepts_several_keys_at_once(client: TestClient, loop_name: str) -> None:
    update = {"delay_s": 2.5, "ultimate_period_s": 9.0, "amplitude_limit": 3.0}
    knowledge = client.put(_knowledge_url(loop_name), json=update).json()["knowledge"]
    assert (knowledge["delay_s"], knowledge["ultimate_period_s"]) == (2.5, 9.0)
    assert knowledge["amplitude_limit"] == 3.0


def test_a_null_delay_clears_the_value(client: TestClient, loop_name: str) -> None:
    client.put(_knowledge_url(loop_name), json={"delay_s": 4.0})
    knowledge = client.put(_knowledge_url(loop_name), json={"delay_s": None}).json()["knowledge"]
    assert knowledge["delay_s"] is None


def test_setting_the_delay_removes_the_missing_delay_finding(
    client: TestClient, loop_name: str
) -> None:
    client.put(_knowledge_url(loop_name), json={"delay_s": 4.0})
    loops = client.get(f"/datasets/{DATASET}/loops").json()["loops"]
    codes = {finding["code"] for finding in loops[0]["findings"]}
    assert "harris" not in codes


def test_an_unknown_key_is_rejected(client: TestClient, loop_name: str) -> None:
    response = client.put(_knowledge_url(loop_name), json={"not_a_key": 1.0})
    assert response.status_code == 422


def test_a_negative_delay_is_rejected(client: TestClient, loop_name: str) -> None:
    response = client.put(_knowledge_url(loop_name), json={"delay_s": -1.0})
    assert response.status_code == 422


def test_a_delay_given_as_a_string_is_rejected(client: TestClient, loop_name: str) -> None:
    response = client.put(_knowledge_url(loop_name), json={"delay_s": "four"})
    assert response.status_code == 422


def test_an_unknown_process_kind_is_rejected(client: TestClient, loop_name: str) -> None:
    response = client.put(_knowledge_url(loop_name), json={"process_kind": "magic"})
    assert response.status_code == 422


def test_get_returns_404_for_an_unknown_loop(client: TestClient) -> None:
    assert client.get(_knowledge_url("nope")).status_code == 404


def test_put_returns_404_for_an_unknown_loop(client: TestClient) -> None:
    response = client.put(_knowledge_url("nope"), json={"delay_s": 4.0})
    assert response.status_code == 404


def test_get_returns_404_for_an_unknown_dataset(client: TestClient) -> None:
    url = "/datasets/nope/loops/hpgr_press/knowledge"
    assert client.get(url).status_code == 404


def test_put_returns_404_for_an_unknown_dataset(client: TestClient) -> None:
    url = "/datasets/nope/loops/hpgr_press/knowledge"
    assert client.put(url, json={"delay_s": 4.0}).status_code == 404


def test_a_failed_put_creates_no_project_file(
    client: TestClient, loop_name: str, data_root: Path
) -> None:
    client.put(_knowledge_url(loop_name), json={"not_a_key": 1.0})
    assert not (data_root / DATASET / PROJECT_FILE).exists()

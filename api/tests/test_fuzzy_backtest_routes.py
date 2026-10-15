"""Tests of the fuzzy backtest and matrix routes on a simulated dataset."""

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
METRIC_KEYS = {"n_moves", "sign_agreement", "correlation", "majority_share", "silent_share"}
DEAD_BAND_ALWAYS_SILENT = 1e9


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide the output directory of one shared 1-hour mill_circuit simulation."""
    root = tmp_path_factory.mktemp("fuzzy")
    argv = ["--plant", "mill_circuit", "--duration", "1h", "--sample-period", "10"]
    assert run_simulation([*argv, "--out", str(root)]) == 0
    return root


@pytest.fixture(scope="module")
def client(data_root: Path) -> TestClient:
    """Provide a FastAPI test client wired to the app built from the given data root."""
    return TestClient(create_app(data_root))


@pytest.fixture(scope="module")
def document(data_root: Path) -> dict:
    """Load the example fuzzy-test document from the test data directory."""
    return load_document(EXAMPLE_ID, data_root / "_fuzzy")


def test_backtest_returns_the_three_blocks_with_the_five_metric_keys(
    client: TestClient, document: dict
) -> None:
    dataset = client.get("/datasets").json()[0]["id"]
    request = {"document": document, "output_id": "feed_change"}
    body = client.post(f"/datasets/{dataset}/fuzzy/backtest", json=request).json()
    assert body["output"] == "feed_change"
    for block in ("all", "first_half", "second_half"):
        assert set(body[block]) == METRIC_KEYS


def test_a_huge_dead_band_leaves_no_moves_and_no_sign_agreement(
    client: TestClient, document: dict
) -> None:
    dataset = client.get("/datasets").json()[0]["id"]
    request = {
        "document": document,
        "output_id": "feed_change",
        "dead_band": DEAD_BAND_ALWAYS_SILENT,
    }
    body = client.post(f"/datasets/{dataset}/fuzzy/backtest", json=request).json()
    assert body["all"]["n_moves"] == 0 and body["all"]["sign_agreement"] is None


def test_an_unknown_output_id_is_refused_with_its_name(
    client: TestClient, document: dict
) -> None:
    dataset = client.get("/datasets").json()[0]["id"]
    request = {"document": document, "output_id": "no_such_output"}
    response = client.post(f"/datasets/{dataset}/fuzzy/backtest", json=request)
    assert response.status_code == 422 and "no_such_output" in response.json()["detail"]


def test_an_output_tag_that_is_not_in_the_data_is_refused(
    client: TestClient, document: dict
) -> None:
    dataset = client.get("/datasets").json()[0]["id"]
    wrong = copy.deepcopy(document)
    wrong["outputs"][0]["tag"] = "sim.mc.nothing"
    request = {"document": wrong, "output_id": "feed_change"}
    response = client.post(f"/datasets/{dataset}/fuzzy/backtest", json=request)
    assert response.status_code == 422 and "sim.mc.nothing" in response.json()["detail"]


def test_matrix_of_two_inputs_has_three_rows_three_columns_and_nine_cells(
    client: TestClient, document: dict
) -> None:
    request = {
        "document": document,
        "row_id": "mill_power",
        "column_id": "p80",
        "output_id": "feed_change",
    }
    body = client.post("/fuzzy/matrix", json=request).json()
    assert body["row_variable"] == "mill_power" and body["column_variable"] == "p80"
    assert body["output"] == "feed_change"
    assert len(body["rows"]) == 3 and len(body["columns"]) == 3
    assert len(body["cells"]) == 3 and len(body["cells"][0]) == 3


def test_a_matrix_of_one_variable_against_itself_is_refused(
    client: TestClient, document: dict
) -> None:
    request = {
        "document": document,
        "row_id": "mill_power",
        "column_id": "mill_power",
        "output_id": "feed_change",
    }
    response = client.post("/fuzzy/matrix", json=request)
    assert response.status_code == 422


def test_a_matrix_with_an_unknown_output_is_refused_with_its_name(
    client: TestClient, document: dict
) -> None:
    request = {
        "document": document,
        "row_id": "mill_power",
        "column_id": "p80",
        "output_id": "no_such_output",
    }
    response = client.post("/fuzzy/matrix", json=request)
    assert response.status_code == 422 and "no_such_output" in response.json()["detail"]

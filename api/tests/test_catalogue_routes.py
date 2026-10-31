"""Tests for the catalogue mapping routes (Phase 1, #37).

Verifies role suggestion, mapping persistence, validation, and that a single mapping drives
loops in Loops, inputs in Anomalies, and targets in Soft sensor.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from crosscut_api.app import create_app
from crosscut_connectors.site import load_site
from crosscut_sim.run import main as run_simulation
from fastapi.testclient import TestClient


@pytest.fixture
def test_root(tmp_path: Path) -> Path:
    """Create a temporary data root with a synthetic dataset."""
    argv = [
        "--plant", "mill_circuit",
        "--duration", "1h",
        "--sample-period", "10",
        "--out", str(tmp_path),
    ]
    assert run_simulation(argv) == 0
    return tmp_path


@pytest.fixture
def client(test_root: Path) -> TestClient:
    """FastAPI test client bound to the test data root."""
    return TestClient(create_app(test_root))


def test_catalogue_suggest_with_tag_list(client: TestClient) -> None:
    body = {
        "tags": [
            "TIC101.PV",
            "TIC101.SP",
            "TIC101.OUT",
            "TIC101.MODE",
            "FEED_INLET",
            "DENSITY_TARGET",
        ]
    }
    response = client.post("/catalogue/suggest", json=body)
    assert response.status_code == 200
    data = response.json()
    assert "signals" in data
    assert "loops" in data
    assert len(data["loops"]) == 1
    assert data["loops"][0]["id"] == "TIC101"
    assert data["loops"][0]["pv"] == "TIC101.PV"
    roles = {sig["tag"]: sig["role"] for sig in data["signals"]}
    assert roles["FEED_INLET"] == "input"
    assert roles["DENSITY_TARGET"] == "target"


def test_catalogue_suggest_with_custom_naming(client: TestClient) -> None:
    body = {
        "tags": ["V_P101_POS", "P101_AUTO"],
        "naming": {"valve_pattern": "V_{loop}_POS", "mode_suffix": "_AUTO"},
    }
    response = client.post("/catalogue/suggest", json=body)
    assert response.status_code == 200
    data = response.json()
    signals = data["signals"]
    assert len(signals) == 2
    assert signals[0] == {"tag": "V_P101_POS", "role": "out", "loop": "P101"}
    assert signals[1] == {"tag": "P101_AUTO", "role": "mode", "loop": "P101"}


def test_catalogue_mapping_put_and_get(client: TestClient, test_root: Path) -> None:
    body = {
        "signals": [
            {"tag": "LIC1.PV", "role": "pv", "loop": "LIC1"},
            {"tag": "LIC1.SP", "role": "sp", "loop": "LIC1"},
            {"tag": "LIC1.OUT", "role": "out", "loop": "LIC1"},
            {"tag": "LIC1.MODE", "role": "mode", "loop": "LIC1"},
            {"tag": "FEED_RATE", "role": "input"},
        ],
        "loops": [
            {"id": "LIC1", "pv": "LIC1.PV", "sp": "LIC1.SP", "out": "LIC1.OUT", "mode": "LIC1.MODE"}
        ],
    }
    put_res = client.put("/catalogue/mapping", json=body)
    assert put_res.status_code == 200

    # Verify site.json on disk
    site_doc = load_site(test_root)
    assert len(site_doc["loops"]) == 1
    assert site_doc["loops"][0]["id"] == "LIC1"

    # GET /catalogue/mapping round trip
    get_res = client.get("/catalogue/mapping")
    assert get_res.status_code == 200
    data = get_res.json()
    assert len(data["loops"]) == 1
    assert len(data["signals"]) == 5


def test_catalogue_mapping_rejects_slot_mismatch(client: TestClient) -> None:
    body = {
        "signals": [
            {"tag": "LIC1.PV", "role": "pv", "loop": "LIC1"},
            {"tag": "LIC1.OUT", "role": "out", "loop": "LIC1"},
        ],
        "loops": [
            {"id": "LIC1", "pv": "WRONG_TAG.PV", "out": "LIC1.OUT"}
        ],
    }
    response = client.put("/catalogue/mapping", json=body)
    assert response.status_code == 422
    assert "WRONG_TAG.PV" in str(response.json())


def test_mapping_drives_loop_anomaly_and_softsensor(client: TestClient) -> None:
    # Get the dataset id created by run_simulation
    ds_res = client.get("/datasets")
    assert ds_res.status_code == 200
    dataset_id = ds_res.json()[0]["id"]

    # Read tags from dataset
    tags_res = client.get(f"/datasets/{dataset_id}/tags")
    assert tags_res.status_code == 200
    tag_ids = [t["id"] for t in tags_res.json()]

    # Pick 4 tags for a loop, 3 tags for anomaly input, and 1 tag for soft sensor target
    loop_tags = tag_ids[:4]
    input_tags = tag_ids[4:7]
    target_tag = tag_ids[7]

    body = {
        "signals": [
            {"tag": loop_tags[0], "role": "pv", "loop": "L_TEST"},
            {"tag": loop_tags[1], "role": "sp", "loop": "L_TEST"},
            {"tag": loop_tags[2], "role": "out", "loop": "L_TEST"},
            {"tag": loop_tags[3], "role": "mode", "loop": "L_TEST"},
            {"tag": input_tags[0], "role": "input"},
            {"tag": input_tags[1], "role": "input"},
            {"tag": input_tags[2], "role": "input"},
            {"tag": target_tag, "role": "target"},
        ],
        "loops": [
            {
                "id": "L_TEST",
                "pv": loop_tags[0],
                "sp": loop_tags[1],
                "out": loop_tags[2],
                "mode": loop_tags[3],
            }
        ],
    }
    mapping_res = client.put("/catalogue/mapping", json=body)
    assert mapping_res.status_code == 200

    # 1. Drives a loop in Loops view
    loops_res = client.get(f"/datasets/{dataset_id}/loops")
    assert loops_res.status_code == 200
    loops = [loop["name"] for loop in loops_res.json()["loops"]]
    assert "L_TEST" in loops

    # 2. Drives an input in Anomalies
    anomaly_res = client.get("/anomaly")
    assert anomaly_res.status_code == 200
    anomaly_ids = anomaly_res.json()
    assert len(anomaly_ids) >= 1
    cfg_res = client.get(f"/anomaly/{anomaly_ids[0]}")
    assert cfg_res.status_code == 200
    anomaly_cfg = cfg_res.json()
    for inp in input_tags:
        assert inp in anomaly_cfg["tags"]

    # 3. Drives a target in Soft sensor
    soft_res = client.get("/softsensor")
    assert soft_res.status_code == 200
    soft_ids = soft_res.json()
    assert len(soft_ids) >= 1
    scfg_res = client.get(f"/softsensor/{soft_ids[0]}")
    assert scfg_res.status_code == 200
    soft_cfg = scfg_res.json()
    assert soft_cfg["target_tag"] == target_tag
    for inp in input_tags:
        assert inp in soft_cfg["input_tags"]

"""Exercise equipment learning through the dataset API.

Synthetic pump records keep the HTTP and stored-model contracts reproducible.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from crosscut_sim.dataset import DatasetInfo, Samples, write_dataset
from fastapi.testclient import TestClient
from open_app import create_app_without_auth

START_UTC = "2026-01-01T00:00:00Z"
START_NS = 1767225600000000000  # Unix timestamp, nanoseconds.
TAGS = ["flow", "target", "speed", "mode", "current"]
LEARN_URL = "/datasets/pump-data/equipment/pump/learn"


def _site() -> dict:
    """Return a hand-written catalogue with one monitored pump."""
    return {
        "schema_version": 1, "site": {"id": "test", "name": "Test"},
        "tags": [{"id": tag} for tag in TAGS],
        "equipment": [{"id": "pump", "level": "equipment", "loops": ["flow-loop"],
                       "signals": [{"tag": "current", "kind": "current", "confirmed": True}]}],
        "loops": [{"id": "flow-loop", "pv": "flow", "sp": "target", "out": "speed",
                   "mode": "mode", "out_limits": {"low": 0, "high": 100}}],
    }


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Write one quiet, variable-speed pump dataset and its catalogue."""
    random = np.random.default_rng(215)
    speed = random.uniform(20, 80, 300)
    values = np.column_stack((speed + random.normal(0, .2, 300), speed,
                              speed, np.ones(300), 2 * speed + random.normal(0, .1, 300)))
    samples = Samples(START_NS + np.arange(300) * 10**9, TAGS, values,
                      np.zeros_like(values, dtype=np.uint8))
    tags = {"schema_version": "1.0.0", "tags": [
        {"id": tag, "name": tag, "unit": "", "type": "float", "role": "other"}
        for tag in TAGS]}
    info = DatasetInfo("pump-data", {"kind": "sim", "plant": "pump", "seed": 215},
                       START_UTC, tags)
    write_dataset(tmp_path / "pump-data", samples, info)
    (tmp_path / "_site").mkdir()
    (tmp_path / "_site" / "site.json").write_text(json.dumps(_site()), encoding="utf-8")
    return tmp_path


def test_learning_saves_a_model_and_lists_catalogue_status(root: Path) -> None:
    """Learning persists the same variables and windows exposed by the list route."""
    client = TestClient(create_app_without_auth(root))
    assert client.get("/equipment/models").json()[0]["status"] == "none"
    response = client.post(LEARN_URL, json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "learned"
    saved = json.loads((root / "_anomaly/equipment/pump.model.json").read_text())
    listing = client.get("/equipment/models").json()[0]
    assert listing["variables"] == saved["variables"]
    assert listing["windows"] == saved["windows"]


def test_utc_exclusions_remove_samples_from_training(root: Path) -> None:
    """UTC request timestamps are converted to the dataset's elapsed seconds."""
    client = TestClient(create_app_without_auth(root))
    response = client.post(LEARN_URL, json={"exclusions": [[
        START_UTC, "2026-01-01T00:01:39Z"]]})
    assert response.status_code == 200, response.text
    assert response.json()["windows"][0][0] >= 100


def test_unknown_equipment_is_not_found(root: Path) -> None:
    """An absent catalogue entry cannot create a model file."""
    client = TestClient(create_app_without_auth(root))
    response = client.post(LEARN_URL.replace("pump/learn", "absent/learn"), json={})
    assert response.status_code == 404


def test_reversed_exclusion_is_rejected(root: Path) -> None:
    """An exclusion with its end before its start reports a useful client error."""
    client = TestClient(create_app_without_auth(root))
    response = client.post(LEARN_URL, json={"exclusions": [[
        "2026-01-01T00:01:39Z", START_UTC]]})
    assert response.status_code == 422


def test_excluding_the_record_saves_not_enough_data_status(root: Path) -> None:
    """A refusal to learn remains visible in equipment summaries."""
    client = TestClient(create_app_without_auth(root))
    response = client.post(LEARN_URL, json={"exclusions": [[
        START_UTC, "2026-01-01T00:05:00Z"]]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "not_enough_data"
    assert client.get("/equipment/models").json()[0]["status"] == "not_enough_data"


def test_an_unknown_dataset_cannot_be_learned(root: Path) -> None:
    """The common dataset loader preserves its not-found HTTP response."""
    client = TestClient(create_app_without_auth(root))
    response = client.post(LEARN_URL.replace("pump-data", "missing"), json={})
    assert response.status_code == 404

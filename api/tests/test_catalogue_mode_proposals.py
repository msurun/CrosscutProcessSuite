"""Route tests for the operating-mode and equipment-group proposals (#145).

The simulated mill dataset of the knowledge tests is the history; the route is read-only.
"""

from pathlib import Path

import test_knowledge_routes as fixtures
from crosscut_api.auth.route_permissions import ROUTE_PERMISSIONS
from fastapi.testclient import TestClient

DATASET = fixtures.DATASET
recorded_dataset_dir = fixtures.recorded_dataset_dir
data_root = fixtures.data_root
client = fixtures.client
URL = f"/datasets/{DATASET}/catalogue/proposals/modes"
KEY = ("GET", "/datasets/{dataset_id}/catalogue/proposals/modes")


def test_proposals_carry_evidence_and_confidence(client: TestClient) -> None:
    """Every proposal has an id, a catalogue entry, a confidence and a full evidence record."""
    response = client.get(URL)
    assert response.status_code == 200
    body = response.json()
    assert body["dataset"] == DATASET and set(body) == {"dataset", "modes", "equipment"}
    for item in body["modes"] + body["equipment"]:
        assert set(item) >= {"id", "entry", "confidence", "evidence"}
        assert item["confidence"] in {"high", "medium", "low"}
        assert set(item["evidence"]) == {
            "kind",
            "share",
            "thresholds",
            "windows",
            "events",
            "detail",
        }


def test_unknown_dataset_is_not_found(client: TestClient) -> None:
    """The dataset is resolved before any calculation."""
    assert client.get("/datasets/nope/catalogue/proposals/modes").status_code == 404


def test_proposals_do_not_change_the_catalogue(client: TestClient, data_root: Path) -> None:
    """Only the site route may save accepted proposals."""
    client.get(URL)
    assert not (data_root / "_site" / "site.json").exists()


def test_route_needs_the_analysis_permission() -> None:
    """Like the loop knowledge proposals: read-only, but it runs an analysis."""
    assert ROUTE_PERMISSIONS[KEY] == "analysis.run"

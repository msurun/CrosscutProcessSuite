"""Exercise read-only loop knowledge proposals over a simulated dataset.

Reuse the knowledge editor fixtures so both endpoints see the same history layout.
"""

from pathlib import Path

import test_knowledge_routes as knowledge_fixtures
from fastapi.testclient import TestClient

DATASET = knowledge_fixtures.DATASET
KNOWLEDGE_KEYS = knowledge_fixtures.KNOWLEDGE_KEYS
recorded_dataset_dir = knowledge_fixtures.recorded_dataset_dir
data_root = knowledge_fixtures.data_root
client = knowledge_fixtures.client
loop_name = knowledge_fixtures.loop_name


def _proposal_url(loop_name: str) -> str:
    """Return the proposal endpoint for a loop in the simulated dataset."""
    return f"/datasets/{DATASET}/loops/{loop_name}/knowledge/proposal"


def test_proposals_include_every_editable_knowledge_value(
    client: TestClient, loop_name: str
) -> None:
    """A successful response carries the loop, all proposals and excitation status."""
    response = client.get(_proposal_url(loop_name))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"loop", "proposals", "needs_step_test"}
    assert body["loop"] == loop_name
    assert set(body["proposals"]) == KNOWLEDGE_KEYS
    assert isinstance(body["needs_step_test"], bool)


def test_a_proposal_reports_its_evidence_and_confidence(
    client: TestClient, loop_name: str
) -> None:
    """A proposed range explains both its source and confidence."""
    proposal = client.get(_proposal_url(loop_name)).json()["proposals"]["pv_eng_min"]
    assert set(proposal) == {"value", "evidence", "confidence"}
    assert set(proposal["evidence"]) == {"kind", "window", "events", "detail"}
    assert proposal["confidence"] in {"high", "medium", "low"}


def test_an_unknown_loop_has_no_proposal(client: TestClient) -> None:
    """An unknown loop remains a normal not-found response."""
    assert client.get(_proposal_url("nope")).status_code == 404


def test_an_unknown_dataset_has_no_proposal(client: TestClient) -> None:
    """Dataset lookup happens before any proposal calculation."""
    response = client.get("/datasets/nope/loops/nope/knowledge/proposal")
    assert response.status_code == 404


def test_requesting_proposals_does_not_save_knowledge(
    client: TestClient, loop_name: str, data_root: Path
) -> None:
    """Only the existing PUT route may persist accepted values."""
    client.get(_proposal_url(loop_name))
    assert not (data_root / DATASET / "project.json").exists()
    assert not (data_root / "_site" / "site.json").exists()

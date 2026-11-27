"""Exercise immutable MPC model edits through the HTTP permission boundary.

Synthetic artifacts prove lineage, audit durability and refusal of unsafe edits.
"""

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users
from crosscut_api.auth.audit import read_records, verify_chain
from crosscut_api.auth.deps import AUDIT_FILE, AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth.store import auth_dir
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.mpc_model_routes import build_model_router
from crosscut_mpc.artifact import load_ident_model, save_ident_model
from crosscut_mpc.identification import IdentifiedModel, PairQuality
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

MODEL_ID = "identified"
MODEL_URL = f"/mpc/models/{MODEL_ID}"


class World:
    """Bind one artifact and a real authenticated API to a temporary data root."""

    def __init__(self, root: Path) -> None:
        """Create a signed-in engineer and a one-CV, two-input synthetic artifact."""
        self.root = root
        self.directory = root / "_mpc" / "models" / MODEL_ID
        quality = PairQuality(0.95, 4, True, ())
        model = IdentifiedModel(("mv", "dv"), ("cv",), np.array([[2.0, -1.0]]),
                                np.array([[10.0, 20.0]]), np.array([[1.0, 2.0]]),
                                1.0, ((quality, quality),), {})
        self.sha256 = save_ident_model(self.directory, model)
        seed_users(root, DEFAULT_USERS)
        context = build_auth_context(root, TEST_CONFIG, FakeClock())
        self.app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(context), context))])
        self.app.include_router(build_auth_router_for(context))
        self.app.include_router(build_model_router(root))
        self.as_user("eng1")

    def as_user(self, username: str) -> None:
        """Start a fresh authenticated client for one role."""
        self.client = TestClient(self.app)
        self.headers = csrf(login(self.client, username))

    def body(self) -> dict[str, Any]:
        """Return a complete grid with one gain override and one disabled path."""
        return {"parent_sha256": self.sha256, "author": "Engineer", "reason": "Reviewed step test",
                "pairs": [{"input_name": "mv", "cv_name": "cv", "gain": 3.0,
                           "time_constant_s": 12.0, "dead_time_s": 2.0, "enabled": True},
                          {"input_name": "dv", "cv_name": "cv", "gain": -1.0,
                           "time_constant_s": 20.0, "dead_time_s": 2.0, "enabled": False}]}

    def save(self, body: dict[str, Any] | None = None) -> Any:
        """Submit an edited copy through the CSRF-protected route."""
        return self.client.post(f"{MODEL_URL}/versions", json=body or self.body(),
                                headers=self.headers)


@pytest.fixture
def world(tmp_path: Path) -> World:
    """Provide isolated model storage and users for every behavior."""
    return World(tmp_path)


def test_read_returns_verified_pairs_without_changing_the_artifact(world: World) -> None:
    original = (world.directory / "model.json").read_bytes()
    response = world.client.get(MODEL_URL)
    assert response.status_code == 200
    assert response.json()["sha256"] == world.sha256
    assert response.json()["pairs"][0]["gain"] == 2.0
    assert response.json()["pairs"][1]["quality"]["passed"] is True
    assert (world.directory / "model.json").read_bytes() == original


def test_edit_creates_a_new_verified_version_with_lineage_and_audit(world: World) -> None:
    original = {path.name: path.read_bytes() for path in world.directory.iterdir()}
    response = world.save()
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["model_id"] != MODEL_ID
    assert document["sha256"] != world.sha256
    assert document["parent_model_id"] == MODEL_ID
    assert document["parent_sha256"] == world.sha256
    child = load_ident_model(world.directory.parent / document["model_id"], document["sha256"])
    assert child.gains[0, 0] == 3.0
    assert child.enabled == ((True, False),)
    assert {path.name: path.read_bytes() for path in world.directory.iterdir()} == original
    assert world.client.get(f"/mpc/models/{document['model_id']}").json() == document


def test_a_saved_version_is_attributed_in_the_hash_chained_audit(world: World) -> None:
    document = world.save().json()
    records = read_records(auth_dir(world.root) / AUDIT_FILE)
    assert verify_chain(records)
    event = next(record for record in records if record["event"] == "mpc_model_version_created")
    assert event["actor"] == "eng1"
    assert event["author"] == "Engineer"
    assert event["reason"] == "Reviewed step test"
    assert event["parent_sha256"] == world.sha256
    assert event["model_id"] == document["model_id"]


@pytest.mark.parametrize("field,value", [("reason", " "), ("author", " ")])
def test_an_override_without_nonblank_attribution_is_refused(
    world: World, field: str, value: str,
) -> None:
    body = {**world.body(), field: value}
    response = world.save(body)
    assert response.status_code == 422
    assert list(world.directory.parent.iterdir()) == [world.directory]


def test_an_override_without_a_reason_field_is_refused(world: World) -> None:
    body = world.body()
    del body["reason"]
    assert world.save(body).status_code == 422


def test_tampered_parent_is_refused_without_creating_a_version(world: World) -> None:
    (world.directory / "model.json").write_text("{}", encoding="utf-8")
    assert world.save().status_code == 422
    assert list(world.directory.parent.iterdir()) == [world.directory]


def test_a_tampered_model_cannot_be_read(world: World) -> None:
    (world.directory / "model.json").write_text("{}", encoding="utf-8")
    assert world.client.get(MODEL_URL).status_code == 422


@pytest.mark.parametrize("field", ["gain", "time_constant_s", "dead_time_s"])
def test_nonfinite_parameters_are_refused(world: World, field: str) -> None:
    body = world.body()
    body["pairs"][0][field] = "NaN"
    assert world.save(body).status_code == 422
    assert list(world.directory.parent.iterdir()) == [world.directory]


def test_a_stale_parent_hash_is_refused(world: World) -> None:
    assert world.save({**world.body(), "parent_sha256": "0" * 64}).status_code == 422
    assert list(world.directory.parent.iterdir()) == [world.directory]


def test_duplicate_pairs_cannot_replace_a_missing_pair(world: World) -> None:
    body = world.body()
    body["pairs"][1] = body["pairs"][0]
    assert world.save(body).status_code == 422


@pytest.mark.parametrize("field,value", [("time_constant_s", 0), ("dead_time_s", -1)])
def test_nonphysical_dynamics_are_refused(world: World, field: str, value: float) -> None:
    body = world.body()
    body["pairs"][0][field] = value
    assert world.save(body).status_code == 422


def test_a_viewer_can_read_but_cannot_save_a_model(world: World) -> None:
    world.as_user("view1")
    assert world.client.get(MODEL_URL).status_code == 200
    assert world.save().status_code == 403


def test_a_broken_audit_chain_prevents_publishing_a_version(world: World) -> None:
    (auth_dir(world.root) / AUDIT_FILE).write_text('{"seq":"wrong"}\n', encoding="utf-8")
    assert world.save().status_code == 503
    assert list(world.directory.parent.iterdir()) == [world.directory]


def test_unknown_models_are_reported_explicitly(world: World) -> None:
    assert world.client.get("/mpc/models/missing").status_code == 404

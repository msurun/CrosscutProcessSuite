"""Check the soft sensor mode change: gate refusal text, audit trail and runtime payload."""

import json
from pathlib import Path

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users
from crosscut_api.auth.audit import read_records
from crosscut_api.auth.deps import AUDIT_FILE, AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth.store import auth_dir
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.softsensor_runtime_routes import build_softsensor_runtime_router
from crosscut_runtime.store import write_json_atomic
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

REFUSAL = "Deployment refused: no validated advantage over the available lab baseline."
CONFIG = {"schema_version": "1.0.0", "id": "s1", "target_tag": "Y", "input_tags": ["A"],
          "mode": "advisory",
          "backup": {"enabled": True, "measured_tag": "Y", "frozen_s": 600, "range_lo": 0,
                     "range_hi": 100, "return_hold_s": 300}}
GOOD = {"preset": "belt_scale_backup", "rmse_model": 1.0, "rmse_baseline": 2.0,
        "scored_coverage": 0.9, "n_samples": 600, "baseline": "last_good_instrument_value"}


@pytest.fixture
def world(tmp_path: Path) -> tuple[FastAPI, Path]:
    """Authenticated routes over one configured soft sensor."""
    seed_users(tmp_path, DEFAULT_USERS)
    write_json_atomic(tmp_path / "_softsensor" / "s1.json", CONFIG)
    clock = FakeClock()
    context = build_auth_context(tmp_path, TEST_CONFIG, clock)
    app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(context), context))])
    app.include_router(build_auth_router_for(context))
    app.include_router(build_softsensor_runtime_router(tmp_path, clock))
    return app, tmp_path


def as_user(app: FastAPI, username: str) -> tuple[TestClient, dict[str, str]]:
    """A logged-in client and its CSRF header."""
    client = TestClient(app)
    return client, csrf(login(client, username))


def _events(root: Path) -> list[str]:
    """Audit event names of soft sensor actions."""
    records = read_records(auth_dir(root) / AUDIT_FILE)
    return [r["event"] for r in records if r["event"].startswith("softsensor_")]


def test_shadow_needs_no_gate_and_is_audited(world: tuple[FastAPI, Path]) -> None:
    """Shadow is allowed without validation; the change is audited with the actor."""
    app, root = world
    client, headers = as_user(app, "eng1")
    response = client.put("/softsensor/s1/mode", json={"mode": "shadow"}, headers=headers)
    assert response.status_code == 200 and response.json()["mode"] == "shadow"
    assert response.json()["changed_by"] == "eng1"
    assert _events(root) == ["softsensor_mode"]


@pytest.mark.parametrize("mode", ["backup", "primary"])
def test_backup_and_primary_are_refused_without_validation(
    world: tuple[FastAPI, Path], mode: str
) -> None:
    """No stored validation: HTTP 409 with the exact gate text, mode unchanged, refusal audited."""
    app, root = world
    client, headers = as_user(app, "eng1")
    response = client.put("/softsensor/s1/mode", json={"mode": mode}, headers=headers)
    assert response.status_code == 409 and response.json()["detail"] == REFUSAL
    assert client.get("/softsensor/s1/runtime").json()["mode"] == "off"
    assert _events(root) == ["softsensor_mode_refused"]


def test_a_weak_validation_is_refused_and_a_strong_one_passes(
    world: tuple[FastAPI, Path]
) -> None:
    """The stored validation decides: no advantage refuses (reasons shown), advantage deploys."""
    app, root = world
    client, headers = as_user(app, "eng1")
    weak = {**GOOD, "rmse_model": 2.0}
    assert client.put("/softsensor/s1/validation", json=weak, headers=headers).status_code == 200
    view = client.get("/softsensor/s1/runtime").json()
    assert view["gate"]["deploy"] is False and view["gate"]["message"] == REFUSAL
    refused = client.put("/softsensor/s1/mode", json={"mode": "primary"}, headers=headers)
    assert refused.status_code == 409 and refused.json()["detail"] == REFUSAL
    client.put("/softsensor/s1/validation", json=GOOD, headers=headers)
    done = client.put("/softsensor/s1/mode", json={"mode": "primary"}, headers=headers)
    assert done.status_code == 200 and done.json()["gate"]["deploy"] is True
    stored = json.loads((root / "_softsensor" / "s1.deployment.json").read_text())
    assert stored["mode"] == "primary"
    assert _events(root)[-2:] == ["softsensor_validation", "softsensor_mode"]


def test_runtime_payload_carries_the_job_state(world: tuple[FastAPI, Path]) -> None:
    """The view merges the runtime job's output, last lab residual and events."""
    app, root = world
    output = {"value": 1.0, "status": "good", "reason": ""}
    write_json_atomic(root / "_runtime/softsensor/s1.state.json", {
        "output": output, "last_lab": {"residual": 0.5}, "events": [{"reason": "stale"}]})
    client, _ = as_user(app, "view1")
    view = client.get("/softsensor/s1/runtime").json()
    assert view["output"] == output and view["last_lab"] == {"residual": 0.5}
    assert view["events"] == [{"reason": "stale"}] and view["gate"]["available"] is False


def test_viewers_cannot_change_the_mode(world: tuple[FastAPI, Path]) -> None:
    """Read permission never authorizes a mode change."""
    client, headers = as_user(world[0], "view1")
    assert client.put("/softsensor/s1/mode", json={"mode": "shadow"},
                      headers=headers).status_code == 403

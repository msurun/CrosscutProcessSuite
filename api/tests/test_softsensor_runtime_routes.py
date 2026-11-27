"""Check the soft sensor mode change: server-side validation, gate refusal text and audit trail."""

import json
from pathlib import Path

import numpy as np
import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users
from crosscut_api.auth.audit import read_records
from crosscut_api.auth.deps import AUDIT_FILE, AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth.store import auth_dir
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.softsensor_runtime_routes import build_softsensor_runtime_router
from crosscut_runtime.store import write_json_atomic
from crosscut_softsensor.config import load_config
from crosscut_softsensor.pls import fit_pls
from crosscut_softsensor.reference import build_model_features
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

REFUSAL = "Deployment refused: no validated advantage over the available lab baseline."
CONFIG = {"schema_version": "1.0.0", "id": "s1", "target_tag": "Y", "input_tags": ["A"],
          "mode": "advisory", "lags_s": [0], "sample_period_s": 60.0, "lab_delay_s": 3600,
          "backup": {"enabled": True, "measured_tag": "Y", "frozen_s": 600, "range_lo": -500,
                     "range_hi": 500, "return_hold_s": 300}}
BINS = 24 * 60 * 10  # ten days of one-minute bins
SUBMITTED = {"preset": "belt_scale_backup", "rmse_model": 0.1, "rmse_baseline": 9.0,
             "scored_coverage": 1.0, "n_samples": 9999, "baseline": "last_good_instrument_value"}


def _dataset(persistent: bool) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Synthetic record: Y follows A (real process signal) or is a slow walk A cannot explain."""
    rng = np.random.default_rng(156)
    a = rng.normal(0, 1, BINS)
    walk = np.cumsum(rng.normal(0, 0.05, BINS))
    y = walk + 0.1 * a if persistent else 3 * a
    return np.arange(BINS) * 60.0, {"A": a, "Y": y}


@pytest.fixture(params=[False, True], ids=["signal", "persistent"])
def world(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[FastAPI, Path]:
    """Authenticated routes, a stored dataset loader, hourly labs and a fitted model."""
    persistent = bool(request.param)
    t_s, columns = _dataset(persistent)
    folder = tmp_path / "_softsensor"
    seed_users(tmp_path, DEFAULT_USERS)
    write_json_atomic(folder / "s1.json", CONFIG)
    stamps = t_s[120::60]
    (folder / "s1.lab.csv").write_text("sample_time,value\n" + "".join(
        f"{float(t)!r},{float(columns['Y'][int(t // 60)])!r}\n" for t in stamps))
    config = load_config(CONFIG)
    x = build_model_features(columns, config).x
    write_json_atomic(folder / "s1.model.json", fit_pls(x, columns["Y"], config).to_dict())
    clock = FakeClock()
    context = build_auth_context(tmp_path, TEST_CONFIG, clock)
    quality = {tag: np.zeros(BINS) for tag in columns}
    app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(context), context))])
    app.include_router(build_auth_router_for(context))
    app.include_router(build_softsensor_runtime_router(
        tmp_path, lambda _id: (t_s, columns), lambda _id: quality, clock))
    app.state.persistent = persistent
    return app, tmp_path


def as_user(app: FastAPI, username: str) -> tuple[TestClient, dict[str, str]]:
    """A logged-in client and its CSRF header."""
    client = TestClient(app)
    return client, csrf(login(client, username))


def _events(root: Path) -> list[str]:
    """Audit event names of soft sensor actions."""
    records = read_records(auth_dir(root) / AUDIT_FILE)
    return [r["event"] for r in records if r["event"].startswith("softsensor_")]


def _validate(client: TestClient, headers: dict[str, str]) -> dict:
    """Run the server-side validation on the stored dataset."""
    response = client.post("/datasets/ds/softsensor/s1/validate", json={}, headers=headers)
    assert response.status_code == 200, response.text
    view: dict = response.json()
    return view


def test_shadow_needs_no_gate_and_is_audited(world: tuple[FastAPI, Path]) -> None:
    """Shadow is allowed without validation; the change is audited with the actor."""
    app, root = world
    client, headers = as_user(app, "eng1")
    response = client.put("/softsensor/s1/mode", json={"mode": "shadow"}, headers=headers)
    assert response.status_code == 200 and response.json()["changed_by"] == "eng1"
    assert _events(root) == ["softsensor_mode"]


@pytest.mark.parametrize("mode", ["backup", "primary"])
def test_refused_without_a_validation_with_the_exact_text(
    world: tuple[FastAPI, Path], mode: str
) -> None:
    """No stored validation: HTTP 409 with the exact gate text, mode unchanged, refusal audited."""
    app, root = world
    client, headers = as_user(app, "eng1")
    response = client.put("/softsensor/s1/mode", json={"mode": mode}, headers=headers)
    assert response.status_code == 409 and response.json()["detail"] == REFUSAL
    assert client.get("/softsensor/s1/runtime").json()["mode"] == "off"
    assert _events(root) == ["softsensor_mode_refused"]


def test_submitted_numbers_cannot_pass_the_gate(world: tuple[FastAPI, Path]) -> None:
    """The submit route is gone and a hand-written validation file is refused (hash)."""
    app, root = world
    client, headers = as_user(app, "eng1")
    gone = client.put("/softsensor/s1/validation", json=SUBMITTED, headers=headers)
    assert gone.status_code in (404, 405)
    forged = {"preset": "lab_quality_inference", "structure": "pls", "hash": "x",
              "results": {"rmse_model": 0.1, "rmse_baseline": 9.0, "scored_coverage": 1.0,
                          "n_samples": 9999, "baseline": "age_aware_lab_persistence"}}
    write_json_atomic(root / "_softsensor" / "s1.validation.json", forged)
    refused = client.put("/softsensor/s1/mode", json={"mode": "primary"}, headers=headers)
    assert refused.status_code == 409 and refused.json()["detail"] == REFUSAL


def test_server_validation_decides(world: tuple[FastAPI, Path]) -> None:
    """Real signal passes and unlocks primary; a persistent target is refused with the text."""
    app, root = world
    client, headers = as_user(app, "eng1")
    view = _validate(client, headers)
    record = json.loads((root / "_softsensor" / "s1.validation.json").read_text())
    assert {"dataset_id", "window", "code_version", "hash", "model_file_sha256"} <= set(record)
    response = client.put("/softsensor/s1/mode", json={"mode": "primary"}, headers=headers)
    if app.state.persistent:
        assert view["gate"]["deploy"] is False
        assert response.status_code == 409 and response.json()["detail"] == REFUSAL
    else:
        assert view["gate"]["deploy"] is True and response.status_code == 200
        assert _events(root)[-2:] == ["softsensor_validate", "softsensor_mode"]


def test_a_refit_invalidates_the_stored_validation(world: tuple[FastAPI, Path]) -> None:
    """The validation must match the current model; after a refit the gate refuses again."""
    app, root = world
    if app.state.persistent:
        pytest.skip("only meaningful for a passing validation")
    client, headers = as_user(app, "eng1")
    _validate(client, headers)
    model = root / "_softsensor" / "s1.model.json"
    document = json.loads(model.read_text())
    document["intercept"] += 1.0
    write_json_atomic(model, document)
    refused = client.put("/softsensor/s1/mode", json={"mode": "primary"}, headers=headers)
    assert refused.status_code == 409 and refused.json()["detail"] == REFUSAL
    assert client.get("/softsensor/s1/runtime").json()["gate"]["deploy"] is False


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


def test_viewers_cannot_change_the_mode_or_validate(world: tuple[FastAPI, Path]) -> None:
    """Read permission never authorizes a mode change or a validation run."""
    client, headers = as_user(world[0], "view1")
    assert client.put("/softsensor/s1/mode", json={"mode": "shadow"},
                      headers=headers).status_code == 403
    assert client.post("/datasets/ds/softsensor/s1/validate", json={},
                       headers=headers).status_code == 403

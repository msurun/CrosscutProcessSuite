"""Objective editor routes: the operator objective of an MPC controller (P8 8.1, #187)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users
from crosscut_api.auth.audit import read_records
from crosscut_api.auth.deps import AUDIT_FILE, AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth.store import auth_dir
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.controller_routes import build_controller_router
from crosscut_connectors.site import save_site
from crosscut_runtime.controllers.overrides import read_economics
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

CATALOGUE = {"currency": "USD", "cv_value": {"cv1": 3.0}}
SITE: dict[str, Any] = {
    "schema_version": 1, "site": {"name": "t"},
    "tags": [{"id": "t.pv"}, {"id": "t.sp"}, {"id": "t.out"}, {"id": "t.mode"}, {"id": "t.cv"}],
    "loops": [{"id": "L1", "pv": "t.pv", "sp": "t.sp", "out": "t.out", "mode": "t.mode"}],
    "sources": [{"id": "s1", "driver": "opcua", "endpoint": "opc.tcp://127.0.0.1:4840"}],
    "controllers": [
        {"id": "M1", "type": "mpc",
         "mpc": {"model": {"artifact": "m", "sha256": "a" * 64}, "economics": CATALOGUE},
         "variables": [
             {"id": "mv1", "role": "MV", "binding": {"loop": "L1"},
              "limits": {"eng": {"lo": 0, "hi": 100}, "move_max": 5}},
             {"id": "cv1", "role": "CV", "binding": {"tag": "t.cv"},
              "limits": {"eng": {"lo": 0, "hi": 100}}}]},
        {"id": "F1", "type": "fuzzy", "rule_base": "rb",
         "variables": [{"id": "mv1", "role": "MV", "binding": {"loop": "L1"}},
                       {"id": "cv1", "role": "CV", "binding": {"tag": "t.cv"}}]},
    ],
}
BODY = {"currency": "EUR", "cv_value": {"cv1": 5.0}, "mv_cost": {"mv1": 0.25},
        "soft_limits": {"cv1": {"hi": 80.0}}}


@pytest.fixture
def world(tmp_path: Path) -> tuple[FastAPI, Path]:
    """A mini app over a saved site with one MPC and one fuzzy controller."""
    save_site(tmp_path, copy.deepcopy(SITE))
    seed_users(tmp_path, DEFAULT_USERS)
    clock = FakeClock()
    ctx = build_auth_context(tmp_path, TEST_CONFIG, clock)
    app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(ctx), ctx))])
    app.include_router(build_auth_router_for(ctx))
    app.include_router(build_controller_router(tmp_path, clock))
    return app, tmp_path


def as_user(app: FastAPI, name: str) -> tuple[TestClient, dict[str, str]]:
    """A logged-in client and its CSRF header."""
    client = TestClient(app)
    return client, csrf(login(client, name))


def test_detail_shows_the_catalogue_objective(world: tuple[FastAPI, Path]) -> None:
    client, _ = as_user(world[0], "view1")
    economics = client.get("/controllers/M1").json()["economics"]
    assert economics == {**CATALOGUE, "source": "catalogue"}
    assert client.get("/controllers/F1").json()["economics"] is None


def test_engineer_replaces_the_objective_and_it_is_audited(world: tuple[FastAPI, Path]) -> None:
    app, root = world
    client, headers = as_user(app, "eng1")
    response = client.put("/controllers/M1/economics", json=BODY, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["economics"]["source"] == "operator"
    assert response.json()["economics"]["cv_value"] == {"cv1": 5.0}
    stored = json.loads((root / "_runtime/controllers/M1.economics.json").read_text("utf-8"))
    assert stored["economics"]["soft_limits"] == {"cv1": {"hi": 80.0}}
    assert read_economics(root, "M1") is not None
    events = [r["event"] for r in read_records(auth_dir(root) / AUDIT_FILE)]
    assert "controller_economics" in events


def test_reset_restores_the_catalogue_objective(world: tuple[FastAPI, Path]) -> None:
    app, root = world
    client, headers = as_user(app, "eng1")
    client.put("/controllers/M1/economics", json=BODY, headers=headers)
    response = client.delete("/controllers/M1/economics", headers=headers)
    assert response.status_code == 200
    assert response.json()["economics"]["source"] == "catalogue"
    assert read_economics(root, "M1") is None


def test_operator_and_viewer_may_not_edit_the_objective(world: tuple[FastAPI, Path]) -> None:
    app, root = world
    for name in ("op1", "view1"):
        client, headers = as_user(app, name)
        assert client.put("/controllers/M1/economics", json=BODY,
                          headers=headers).status_code == 403
    assert read_economics(root, "M1") is None


def test_bad_keys_and_non_mpc_controllers_are_refused(world: tuple[FastAPI, Path]) -> None:
    client, headers = as_user(world[0], "eng1")
    wrong = {"cv_value": {"mv1": 1.0}}
    assert client.put("/controllers/M1/economics", json=wrong, headers=headers).status_code == 422
    unknown = {"profit": 1}
    assert client.put("/controllers/M1/economics", json=unknown,
                      headers=headers).status_code == 422
    assert client.put("/controllers/F1/economics", json=BODY, headers=headers).status_code == 409
    assert client.put("/controllers/zz/economics", json=BODY, headers=headers).status_code == 404

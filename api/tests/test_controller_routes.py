"""Operator console routes (Phase 2.5, step 7) behind the real app-level enforcer.

Checks list and detail over a site and host records, the command queue, the operator limit
rules, the audit trail and who may do what (ADR 013).
"""

from __future__ import annotations

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
from crosscut_runtime.controllers.commands import take_commands
from crosscut_runtime.controllers.overrides import read_overrides
from crosscut_runtime.store import write_json_atomic, write_variable_status
from crosscut_runtime.variable_status import VariableStatus
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

SITE: dict[str, Any] = {
    "schema_version": 1,
    "site": {"name": "t"},
    "tags": [{"id": "t.pv"}, {"id": "t.sp"}, {"id": "t.out"}, {"id": "t.mode"}, {"id": "t.cv"}],
    "loops": [{"id": "L1", "pv": "t.pv", "sp": "t.sp", "out": "t.out", "mode": "t.mode"}],
    "sources": [{"id": "s1", "driver": "opcua", "endpoint": "opc.tcp://127.0.0.1:4840"}],
    "controllers": [
        {
            "id": "C1",
            "type": "fuzzy",
            "variables": [
                {
                    "id": "mv1",
                    "role": "MV",
                    "binding": {"loop": "L1"},
                    "limits": {"eng": {"lo": 0, "hi": 100}, "operator": {"lo": 10, "hi": 90}},
                },
                {"id": "cv1", "role": "CV", "binding": {"tag": "t.cv"}},
            ],
        }
    ],
}


@pytest.fixture
def world(tmp_path: Path) -> tuple[FastAPI, Path]:
    """A mini app: enforcer, auth router and controller router over a saved site."""
    save_site(tmp_path, SITE)
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


def _write_record(root: Path) -> None:
    """A record as the host would leave it, with one status for the CV."""
    write_json_atomic(
        root / "_runtime" / "controllers" / "C1.json",
        {
            "state": "on",
            "reason": "running",
            "last_cycle_utc": "2026-01-01T00:00:00+00:00",
            "last_duration_s": 0.2,
            "overruns": 2,
            "consecutive_overruns": 1,
            "liveness_utc": "2026-01-01T00:00:01+00:00",
            "last_explanation": "mv1: +1",
        },
    )
    status = VariableStatus("cv1", "t.cv", "bad", ("stale",), 4.5, None)
    write_variable_status(root, "C1", [status])


def test_list_without_record_is_off(world: tuple[FastAPI, Path]) -> None:
    """A controller the host never ran shows as off/new."""
    client, _ = as_user(world[0], "view1")
    rows = client.get("/controllers").json()["controllers"]
    assert [(r["id"], r["state"], r["reason"]) for r in rows] == [("C1", "off", "new")]


def test_list_and_detail_join_record_and_status(world: tuple[FastAPI, Path]) -> None:
    """The list carries the record; the detail adds variables with status and limits."""
    app, root = world
    _write_record(root)
    client, _ = as_user(app, "view1")
    row = client.get("/controllers").json()["controllers"][0]
    assert (row["state"], row["consecutive_overruns"], row["last_explanation"]) == (
        "on",
        1,
        "mv1: +1",
    )
    detail = client.get("/controllers/C1").json()
    cv = next(v for v in detail["variables"] if v["id"] == "cv1")
    assert (cv["status"], cv["reasons"], cv["value"]) == ("bad", ["stale"], 4.5)
    mv = next(v for v in detail["variables"] if v["id"] == "mv1")
    assert mv["limits"]["eng"] == {"lo": 0, "hi": 100}
    assert client.get("/controllers/nope").status_code == 404


def test_operator_queues_command_and_it_is_audited(world: tuple[FastAPI, Path]) -> None:
    """switch_on is queued once and leaves one audit line naming the actor."""
    app, root = world
    client, headers = as_user(app, "op1")
    response = client.post(
        "/controllers/C1/command", json={"command": "switch_on"}, headers=headers
    )
    assert response.status_code == 200
    assert take_commands(root, "C1") == ["switch_on"]
    lines = [
        r for r in read_records(auth_dir(root) / AUDIT_FILE) if r["event"] == "controller_command"
    ]
    assert [(r["actor"], r["command"]) for r in lines] == [("op1", "switch_on")]


def test_switch_off_needs_no_stepup(world: tuple[FastAPI, Path]) -> None:
    """An operator without a step-up switches off; an unknown command is 422."""
    app, root = world
    client, headers = as_user(app, "op1")
    off = client.post("/controllers/C1/command", json={"command": "switch_off"}, headers=headers)
    assert off.status_code == 200
    assert take_commands(root, "C1") == ["switch_off"]
    bad = client.post("/controllers/C1/command", json={"command": "boom"}, headers=headers)
    assert bad.status_code == 422


def test_viewer_reads_but_cannot_command_or_override(world: tuple[FastAPI, Path]) -> None:
    """A viewer holds ctl.view only: both writes are 403 and nothing is queued."""
    app, root = world
    client, headers = as_user(app, "view1")
    assert client.get("/controllers").status_code == 200
    command = client.post(
        "/controllers/C1/command", json={"command": "switch_off"}, headers=headers
    )
    assert command.status_code == 403
    put = client.put("/controllers/C1/variables/cv1", json={"enabled": False}, headers=headers)
    assert put.status_code == 403
    assert take_commands(root, "C1") == []
    assert read_overrides(root, "C1") == {}


def test_operator_limits_outside_engineering_are_422(world: tuple[FastAPI, Path]) -> None:
    """Operator limits must lie inside eng limits and lo must be below hi."""
    app, root = world
    client, headers = as_user(app, "eng1")
    url = "/controllers/C1/variables/mv1"
    wide = client.put(
        url, json={"enabled": True, "operator": {"lo": -5, "hi": 50}}, headers=headers
    )
    assert wide.status_code == 422
    flipped = client.put(
        url, json={"enabled": True, "operator": {"lo": 60, "hi": 50}}, headers=headers
    )
    assert flipped.status_code == 422
    assert read_overrides(root, "C1") == {}


def test_override_is_stored_audited_and_shown(world: tuple[FastAPI, Path]) -> None:
    """A valid override replaces the operator limits and the enabled flag in the detail."""
    app, root = world
    client, headers = as_user(app, "op1")
    body = {"enabled": False, "operator": {"lo": 20, "hi": 80}}
    response = client.put("/controllers/C1/variables/mv1", json=body, headers=headers)
    assert response.status_code == 200
    mv = next(v for v in response.json()["variables"] if v["id"] == "mv1")
    assert (mv["enabled"], mv["limits"]["operator"]) == (False, {"lo": 20, "hi": 80})
    assert mv["limits"]["operator_catalogue"] == {"lo": 10, "hi": 90}
    assert response.json()["disabled"] == ["mv1"]
    stored = json.loads((root / "_runtime" / "controllers" / "C1.operator.json").read_text("utf-8"))
    assert stored["variables"]["mv1"]["operator"] == {"lo": 20.0, "hi": 80.0}
    events = [r["event"] for r in read_records(auth_dir(root) / AUDIT_FILE)]
    assert "controller_override" in events
    assert (
        client.put(
            "/controllers/C1/variables/zz", json={"enabled": True}, headers=headers
        ).status_code
        == 404
    )

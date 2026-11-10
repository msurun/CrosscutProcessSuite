"""Tests for parameter write-intent routes (ADR 014 addendum).

Validates GET /tuning/intents and POST /tuning/intents/{key}/resolve across
authorization refusal (403), step-up missing (428), successful resolution with
audited actor, read failure refusal (409), and damaged store handling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from auth_support import stepup
from crosscut_api.auth.actor import STEPUP_ROUTES
from crosscut_api.auth.audit import read_records
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.route_permissions import ROUTE_PERMISSIONS
from crosscut_api.auth.store import auth_dir
from tuning_fakes import FakeGateway, Session, World, build_world, patch_report

INTENT_KEY = "test-intent-key-42"


def make_open_intent(key: str = INTENT_KEY, loop_id: str = "FIC1") -> dict[str, Any]:
    """Build one open intent record structure for testing."""
    item = {
        "target": "FIC1.KP",
        "from_value": 2.0,
        "to_value": 3.0,
        "current_value": 2.0,
    }
    return {
        "key": key,
        "loop_id": loop_id,
        "proposal_id": "p1",
        "proposer": "alice",
        "created_at": "2026-11-05T10:00:00Z",
        "state": "open",
        "items": [item],
    }


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """A mini app with auth enabled over a fake gateway supporting write intents."""
    patch_report(monkeypatch)
    gw = FakeGateway()
    gw.open_intents = [make_open_intent()]
    return build_world(tmp_path, gw)


def resolve(
    world: World, key: str = INTENT_KEY, user: str = "eng2", step: bool = True
) -> Any:
    """POST to resolve an open intent as user (with fresh step-up unless step is False)."""
    session = Session(world, user)
    if step:
        stepup(session.client, session.payload)
    return session.call("POST", f"/tuning/intents/{key}/resolve")


def test_routes_are_gated_by_permissions_and_stepup() -> None:
    """Verify route permissions table and step-up route registration."""
    resolve_key = ("POST", "/tuning/intents/{key}/resolve")
    assert ROUTE_PERMISSIONS[resolve_key] == "gw.approve.tuning"
    assert resolve_key in STEPUP_ROUTES
    get_key = ("GET", "/tuning/intents")
    assert ROUTE_PERMISSIONS[get_key] == "gw.view"


def test_get_intents_lists_open_intents(world: World) -> None:
    """GET /tuning/intents returns store_state ok and open intents for viewer."""
    session = Session(world, "view1")
    response = session.call("GET", "/tuning/intents")
    assert response.status_code == 200
    data = response.json()
    assert data["store_state"] == "ok"
    assert data["damaged"] is False
    assert len(data["intents"]) == 1
    assert data["intents"][0]["key"] == INTENT_KEY


def test_resolve_intent_authorization_refusal_for_operator(world: World) -> None:
    """An operator without gw.approve.tuning gets HTTP 403 on resolve."""
    response = resolve(world, user="op1")
    assert response.status_code == 403


def test_resolve_intent_step_up_missing_returns_428(world: World) -> None:
    """An authorized engineer without a fresh step-up challenge gets HTTP 428."""
    response = resolve(world, user="eng2", step=False)
    assert response.status_code == 428


def test_resolve_intent_success_resolves_and_audits_actor(world: World) -> None:
    """A valid step-up resolve closes the intent and records the actor in API audit."""
    response = resolve(world, user="eng2")
    assert response.status_code == 200
    assert response.json()["reason_code"] == "resolved"

    lines = read_records(auth_dir(world.root) / AUDIT_FILE)
    records = [r for r in lines if r["event"] == "intent_resolved"]
    assert len(records) >= 1
    assert any(r["actor"] == "eng2" and r["outcome"] == "resolved" for r in records)


def test_resolve_intent_read_failure_refuses_and_keeps_intent_open(world: World) -> None:
    """Plant read failure during resolve returns HTTP 409 read_failed."""
    world.gateway.resolve_refusal = "read_failed"
    response = resolve(world, user="eng2")
    assert response.status_code == 409
    assert response.json()["detail"] == "read_failed"


def test_get_intents_damaged_store_returns_state_damaged(world: World) -> None:
    """A damaged store is reported as store_state damaged without crashing."""
    world.gateway.store_damaged = True
    session = Session(world, "view1")
    response = session.call("GET", "/tuning/intents")
    assert response.status_code == 200
    data = response.json()
    assert data["store_state"] == "damaged"
    assert data["damaged"] is True
    assert data["intents"] == []


def test_resolve_intent_damaged_store_refuses_with_409(world: World) -> None:
    """Resolving against a damaged store refuses with HTTP 409 intent_store_unreadable."""
    world.gateway.store_damaged = True
    response = resolve(world, user="eng2")
    assert response.status_code == 409
    assert response.json()["detail"] == "intent_store_unreadable"

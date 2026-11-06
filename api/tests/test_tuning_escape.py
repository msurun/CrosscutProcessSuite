"""Operator escape of a stalled applying tuning record, and rollback of a rollback (ADR 014).

The escape settles a record only from gateway evidence (applied ledger, terminal decision in the
audit, long-past expiry with the key no longer pending); otherwise 409 gateway_state_unknown.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from auth_support import stepup
from crosscut_api.auth.actor import STEPUP_ROUTES
from crosscut_api.auth.audit import read_records
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.route_permissions import ROUTE_PERMISSIONS
from crosscut_api.auth.store import auth_dir
from test_tuning_proposal_routes import approve, propose, record_file
from tuning_fakes import (
    KP,
    START_VALUES,
    FakeGateway,
    Session,
    World,
    build_world,
    patch_report,
)

REASON = "gateway restarted during approve"


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """A mini app with auth enabled over a fake gateway, and a fixed model report."""
    patch_report(monkeypatch)
    return build_world(tmp_path, FakeGateway())


def edit_record(world: World, proposal_id: str, **changes: Any) -> None:
    """Rewrite fields of the stored record (simulates an interrupted approve)."""
    path = world.root / "_tuning" / "proposals" / f"{proposal_id}.json"
    path.write_text(json.dumps({**record_file(world, proposal_id), **changes}), encoding="utf-8")


def iso_ago(seconds: float) -> str:
    """The ISO time ``seconds`` before now."""
    return (datetime.now(UTC) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def stalled(world: World, expired_s: float = 0.0, held: bool = True) -> dict[str, Any]:
    """A proposal left applying, expired ``expired_s`` ago; the gateway holds its key or not."""
    created = propose(world)
    edit_record(world, created["id"], status="applying", expires_at=iso_ago(expired_s))
    if not held:
        world.gateway.pending.clear()
    return created


def escape(
    world: World, proposal_id: str, user: str = "eng2", reason: str = REASON, step: bool = True
) -> Any:
    """POST the escape as ``user`` (after a fresh step-up unless ``step`` is False)."""
    session = Session(world, user)
    if step:
        stepup(session.client, session.payload)
    return session.call("POST", f"/tuning/proposals/{proposal_id}/escape", {"reason": reason})


def test_applied_rollback_cannot_be_rolled_back(world: World) -> None:
    created = propose(world)
    approve(world, created["id"])
    engineer = Session(world, "eng1")
    back = engineer.call("POST", f"/tuning/proposals/{created['id']}/rollback").json()
    assert approve(world, back["id"], "lead1").status_code == 200
    again = engineer.call("POST", f"/tuning/proposals/{back['id']}/rollback")
    assert again.status_code == 409 and again.json()["detail"] == "rollback_of_rollback"


def test_lagging_ledger_after_a_504_is_unknown_then_applied(world: World) -> None:
    created = propose(world)
    world.gateway.timeout_after_apply = True
    world.gateway.hide_applied = True
    assert approve(world, created["id"]).status_code == 504
    assert record_file(world, created["id"])["status"] == "applying"
    unknown = escape(world, created["id"])
    assert unknown.status_code == 409 and unknown.json()["detail"] == "gateway_state_unknown"
    assert record_file(world, created["id"])["status"] == "applying"
    world.gateway.hide_applied = False  # the ledger caught up: the set WAS applied
    done = escape(world, created["id"])
    assert done.status_code == 200 and done.json()["status"] == "applied"
    stored = record_file(world, created["id"])
    assert stored["status"] == "applied" and stored["applied"]["source"] == "audit"
    assert stored["escape"]["evidence"] == "ledger_applied"


def test_no_evidence_is_refused(world: World) -> None:
    created = stalled(world)
    for held in (True, False):  # pending at the gateway, or gone but not expired
        if not held:
            world.gateway.pending.clear()
        res = escape(world, created["id"])
        assert res.status_code == 409 and res.json()["detail"] == "gateway_state_unknown"
    assert record_file(world, created["id"])["status"] == "applying"


def test_expiry_margin_needs_the_key_to_be_gone(world: World) -> None:
    created = stalled(world, expired_s=700)  # past expires_at + 600 s but still pending
    assert escape(world, created["id"]).json()["detail"] == "gateway_state_unknown"
    world.gateway.pending.clear()
    done = escape(world, created["id"])
    assert done.status_code == 200, done.text
    assert record_file(world, created["id"])["escape"]["evidence"] == "expired_not_listed"


def test_inside_the_expiry_margin_is_refused(world: World) -> None:
    created = stalled(world, expired_s=100, held=False)
    assert escape(world, created["id"]).status_code == 409


def test_terminal_gateway_decision_rejects(world: World) -> None:
    created = stalled(world)
    key = record_file(world, created["id"])["gateway_key"]
    world.gateway.pending.clear()
    world.gateway.audit_log.append(
        {"seq": "9", "t_ns": "1", "event": "param_decision", "tag": KP, "key": key,
         "reason_code": "from_mismatch"}
    )  # fmt: skip
    done = escape(world, created["id"])
    assert done.status_code == 200, done.text
    evidence = record_file(world, created["id"])["escape"]["evidence"]
    assert evidence == "gateway_refused:from_mismatch"


def test_applied_evidence_returns_the_applied_record(world: World) -> None:
    created = propose(world)
    assert approve(world, created["id"]).status_code == 200
    edit_record(world, created["id"], status="applying", applied=None)
    done = escape(world, created["id"])
    assert done.status_code == 200 and done.json()["status"] == "applied"
    assert done.json()["applied"]["from_read"] == START_VALUES


def test_escape_records_actor_reason_time_and_writes_an_audit_line(world: World) -> None:
    created = stalled(world, expired_s=700, held=False)
    assert escape(world, created["id"], user="lead1").status_code == 200
    block = record_file(world, created["id"])["escape"]
    assert block["actor"] == "lead1" and block["reason"] == REASON and block["t"]
    lines = read_records(auth_dir(world.root) / AUDIT_FILE)
    mine = [r for r in lines if r["event"] == "tuning_escape"]
    assert len(mine) == 1 and mine[0]["actor"] == "lead1" and mine[0]["reason"] == REASON
    assert mine[0]["proposal_id"] == created["id"] and mine[0]["outcome"] == "rejected"


def test_escape_needs_permission_a_reason_and_an_applying_record(world: World) -> None:
    created = stalled(world, expired_s=700, held=False)
    assert escape(world, created["id"], user="op1").status_code == 403
    assert escape(world, created["id"], reason="too short").status_code == 422
    assert record_file(world, created["id"])["status"] == "applying"
    other = propose(world)
    res = escape(world, other["id"])
    assert res.status_code == 409 and res.json()["detail"] == "not_applying"


def test_escape_without_a_fresh_step_up_is_refused(world: World) -> None:
    created = stalled(world, expired_s=700, held=False)
    res = escape(world, created["id"], step=False)
    assert res.status_code == 428
    assert record_file(world, created["id"])["status"] == "applying"


def test_escape_operator_is_403_even_without_a_stepup(world: World) -> None:
    created = stalled(world, expired_s=700, held=False)
    res = escape(world, created["id"], user="op1", step=False)
    assert res.status_code == 403
    assert record_file(world, created["id"])["status"] == "applying"


def test_escape_route_is_gated_by_approve_and_stepup() -> None:
    key = ("POST", "/tuning/proposals/{proposal_id}/escape")
    assert ROUTE_PERMISSIONS[key] == "gw.approve.tuning"
    assert key in STEPUP_ROUTES


def test_reject_never_settles_an_applying_record(world: World) -> None:
    created = stalled(world, expired_s=700, held=False)
    res = Session(world, "op1").call("POST", f"/tuning/proposals/{created['id']}/reject")
    assert res.status_code == 409 and res.json()["detail"] == "applying"


def test_wrong_escape_rejection_is_corrected_by_the_audit(world: World) -> None:
    created = stalled(world, expired_s=700, held=False)
    assert escape(world, created["id"]).json()["status"] == "rejected"
    record = record_file(world, created["id"])
    for item in record["items"]:  # the gateway had applied it after all
        row = world.gateway._write_record(record["gateway_key"], item, created["id"], "eng2")
        world.gateway.audit_log.append(row)
    seen = Session(world, "view1").call("GET", f"/tuning/proposals/{created['id']}").json()
    assert seen["status"] == "applied" and seen["corrected_from"] == "rejected"
    assert seen["escape"]["actor"] == "eng2" and seen["applied"]["source"] == "audit"


def test_plain_rejection_is_never_flipped_by_the_ledger(world: World) -> None:
    created = propose(world)
    key = created["gateway_key"]
    rejected = Session(world, "op1").call("POST", f"/tuning/proposals/{created['id']}/reject")
    assert rejected.status_code == 200
    for item in created["items"]:
        row = world.gateway._write_record(key, item, created["id"], "eng2")
        world.gateway.audit_log.append(row)
    seen = Session(world, "view1").call("GET", f"/tuning/proposals/{created['id']}").json()
    assert seen["status"] == "rejected" and "corrected_from" not in seen

"""Hardening of the tuning proposal API after the Opus review (ADR 014): safety-critical cases.

A tuning that was really written must never end as ``expired``; applied values come only from
the verified gateway audit; generic gateway routes do not touch tuning keys; GET lists do little
work; the lock cannot be held twice. The gateway is the fake of tuning_fakes (see FakeGateway).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from crosscut_api import tuning_build, tuning_gateway
from crosscut_api import tuning_proposal_routes as routes
from crosscut_api.auth.actor import ActorContext
from crosscut_api.gateway_client import FileGatewayClient
from crosscut_api.gateway_routes import build_gateway_router
from crosscut_api.tuning_store import ProposalStore
from crosscut_connectors.base import LiveValue
from fastapi import HTTPException
from tuning_fakes import (
    BODY,
    KP,
    LOOP,
    TI,
    FakeGateway,
    Session,
    World,
    build_world,
    patch_report,
    site_document,
)

PROPOSE = f"/loops/{LOOP}/tuning/proposals"
NINE_HOURS = 9 * 3600.0


@pytest.fixture
def skewed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[World, list[float]]:
    """A world whose clock the test can move forward (seconds)."""
    patch_report(monkeypatch)
    skew = [0.0]
    world = build_world(tmp_path, FakeGateway(), clock=lambda: time.time() + skew[0])
    return world, skew


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """A world over a fake gateway with a fixed model report."""
    patch_report(monkeypatch)
    return build_world(tmp_path, FakeGateway())


def stored(world: World, proposal_id: str) -> dict[str, Any]:
    """The record file as written on disk."""
    path = world.root / "_tuning" / "proposals" / f"{proposal_id}.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def propose(world: World, user: str = "eng1") -> dict[str, Any]:
    """Create a proposal (expects 201)."""
    response = Session(world, user).call("POST", PROPOSE, BODY)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def approve(world: World, proposal_id: str, user: str = "eng2") -> Any:
    """Approve as ``user``."""
    return Session(world, user).call("POST", f"/tuning/proposals/{proposal_id}/approve")


def get(world: World, proposal_id: str) -> dict[str, Any]:
    """GET one proposal as a viewer."""
    response = Session(world, "view1").call("GET", f"/tuning/proposals/{proposal_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- 1. a written tuning is never expired -------------------------------------------------------


def test_approve_timeout_leaves_applying_and_get_reconciles_it_to_applied(
    skewed: tuple[World, list[float]],
) -> None:
    world, skew = skewed
    created = propose(world)
    world.gateway.timeout_after_apply = True
    assert approve(world, created["id"]).status_code == 504
    assert stored(world, created["id"])["status"] == "applying"
    skew[0] = NINE_HOURS  # far past expiry: still never expired
    world.gateway.hide_applied = True  # state.json has not caught up yet
    assert get(world, created["id"])["status"] == "applying"
    world.gateway.hide_applied = False
    shown = get(world, created["id"])
    assert shown["status"] == "applied" and shown["applied"]["source"] == "audit"
    assert shown["applied"]["to_read"][KP] == pytest.approx(1.25)
    assert shown["applied"]["chain_ok"] is True and "invalid" not in shown["applied"]
    assert stored(world, created["id"])["status"] == "applied"


def test_an_applying_record_cannot_be_approved_again_and_never_expires(
    skewed: tuple[World, list[float]],
) -> None:
    world, skew = skewed
    created = propose(world)
    world.gateway.timeout_after_apply = True
    approve(world, created["id"])
    world.gateway.hide_applied = True
    again = approve(world, created["id"], "lead1")
    assert again.status_code == 409 and again.json()["detail"] == "applying"
    world.gateway.pending.clear()
    skew[0] = NINE_HOURS
    assert get(world, created["id"])["status"] == "applying"
    reject = Session(world, "lead1").call("POST", f"/tuning/proposals/{created['id']}/reject")
    assert reject.status_code == 409
    assert world.gateway.apply_count == 1


def test_save_failure_after_the_gateway_applied_does_not_expire_the_record(
    skewed: tuple[World, list[float]], monkeypatch: pytest.MonkeyPatch
) -> None:
    world, skew = skewed
    created = propose(world)
    real_write = ProposalStore.write

    def failing(self: ProposalStore, proposal_id: str, record: dict[str, Any]) -> None:
        if record["status"] in ("applied", "applying"):
            raise PermissionError("record is open in another process")
        real_write(self, proposal_id, record)

    monkeypatch.setattr(ProposalStore, "write", failing)
    with pytest.raises(PermissionError):
        approve(world, created["id"])
    monkeypatch.undo()
    assert world.gateway.apply_count == 1 and stored(world, created["id"])["status"] == "queued"
    skew[0] = NINE_HOURS
    shown = get(world, created["id"])
    assert shown["status"] == "applied" and shown["applied"]["source"] == "audit"


def test_unreadable_gateway_state_never_expires_a_queued_record(
    skewed: tuple[World, list[float]],
) -> None:
    world, skew = skewed
    created = propose(world)
    world.gateway.pending.clear()
    skew[0] = NINE_HOURS
    world.gateway.state_down = True
    assert get(world, created["id"])["status"] == "queued"
    refused = approve(world, created["id"])
    assert refused.status_code == 503 and stored(world, created["id"])["status"] == "queued"
    world.gateway.state_down = False
    assert get(world, created["id"])["status"] == "expired"


def test_unknown_key_at_approve_but_applied_in_the_audit_returns_the_applied_record(
    world: World,
) -> None:
    created = propose(world)
    # the set is applied at the gateway behind the API's back (a retry after a lost reply)
    world.gateway.approve(created["gateway_key"], actor=_actor("eng2"))
    response = approve(world, created["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "applied" and body["applied"]["source"] == "audit"
    assert stored(world, created["id"])["status"] == "applied"
    assert world.gateway.apply_count == 1


def _actor(name: str) -> Any:
    """An engineer actor for direct calls on the fake gateway."""
    return ActorContext(name, ("engineer",), "s", "127.0.0.1", False, None)


def test_accepted_approve_with_a_lagging_state_is_applying_not_made_up(
    world: World,
) -> None:
    created = propose(world)
    world.gateway.hide_applied = True
    response = approve(world, created["id"])
    assert response.status_code == 200
    assert response.json()["status"] == "applying" and response.json()["applied"] is None
    assert get(world, created["id"])["status"] == "applying"
    world.gateway.hide_applied = False
    assert get(world, created["id"])["status"] == "applied"


# --- 3 and 4. unverified and untrusted applied blocks -------------------------------------------


def test_applied_unaudited_is_applied_but_invalid_with_null_values(world: World) -> None:
    created = propose(world)
    world.gateway.unaudited = True
    shown = approve(world, created["id"]).json()
    applied = shown["applied"]
    assert shown["status"] == "applied" and applied["invalid"] == "audit_unverified"
    nulls = {KP: None, TI: None}
    assert applied["from_read"] == nulls and applied["to_read"] == nulls
    assert applied["source"] == "gateway_reply"
    rollback = Session(world, "eng1").call("POST", f"/tuning/proposals/{created['id']}/rollback")
    assert rollback.status_code == 409 and rollback.json()["detail"] == "applied_unverified"


def test_broken_audit_chain_gives_no_values_and_blocks_rollback(world: World) -> None:
    created = propose(world)
    world.gateway.chain_ok = False
    applied = approve(world, created["id"]).json()["applied"]
    assert applied["invalid"] == "audit_chain_broken" and applied["chain_ok"] is False
    assert applied["to_read"] == {KP: None, TI: None}
    rollback = Session(world, "eng1").call("POST", f"/tuning/proposals/{created['id']}/rollback")
    assert rollback.status_code == 409 and rollback.json()["detail"] == "applied_unverified"


def test_rollback_needs_an_audit_sourced_block(world: World) -> None:
    created = propose(world)
    approve(world, created["id"])
    path = world.root / "_tuning" / "proposals" / f"{created['id']}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["applied"]["source"] = "gateway_reply"
    path.write_text(json.dumps(record), encoding="utf-8")
    rollback = Session(world, "eng1").call("POST", f"/tuning/proposals/{created['id']}/rollback")
    assert rollback.status_code == 409 and rollback.json()["detail"] == "applied_unverified"


# --- 5. the API reads the gateway ledger, not the audit tail ------------------------------------


def test_applied_values_do_not_depend_on_the_audit_tail(world: World) -> None:
    created = propose(world)
    world.gateway.audit = lambda limit: {"records": [], "chain_ok": True}  # type: ignore[method-assign]
    shown = approve(world, created["id"]).json()
    assert shown["status"] == "applied" and shown["applied"]["source"] == "audit"
    world.gateway.external_change(KP, 3.0)
    assert get(world, created["id"])["applied"]["invalid"] == "param_changed_externally"


# --- 2. the generic gateway routes refuse tuning keys -------------------------------------------


def test_generic_gateway_routes_refuse_keys_of_parameter_sets(world: World) -> None:
    world.gateway.mode = lambda: "confirm"  # type: ignore[attr-defined]
    world.app.include_router(build_gateway_router(world.provider))
    created = propose(world)
    lead = Session(world, "lead1")
    key = created["gateway_key"]
    for action in ("approve", "reject"):
        response = lead.call("POST", f"/gateway/pending/{key}/{action}")
        assert response.status_code == 409 and response.json()["detail"] == "use_tuning_endpoint"
    assert key in world.gateway.pending and world.gateway.apply_count == 0
    assert stored(world, created["id"])["status"] == "queued"
    assert approve(world, created["id"]).status_code == 200


# --- 6. reject without a key, draft expiry ------------------------------------------------------


def hidden_queue_draft(world: World) -> dict[str, Any]:
    """A proposal the gateway queued although the API saw no key in time (record stays draft)."""
    real = world.gateway.pending_params
    world.gateway.pending_params = lambda: []  # type: ignore[method-assign]
    try:
        created = propose(world)
    finally:
        world.gateway.pending_params = real  # type: ignore[method-assign]
    assert created["status"] == "draft" and created["gateway_key"] is None
    return created


def test_reject_of_a_draft_without_key_rejects_the_set_the_gateway_holds(world: World) -> None:
    created = hidden_queue_draft(world)
    assert len(world.gateway.pending) == 1
    response = Session(world, "lead1").call("POST", f"/tuning/proposals/{created['id']}/reject")
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    assert world.gateway.pending == {}


def test_reject_of_a_draft_without_key_needs_a_readable_gateway(world: World) -> None:
    created = hidden_queue_draft(world)
    world.gateway.state_down = True
    response = Session(world, "lead1").call("POST", f"/tuning/proposals/{created['id']}/reject")
    assert response.status_code == 503
    assert stored(world, created["id"])["status"] == "draft" and len(world.gateway.pending) == 1


def test_draft_without_key_and_without_pending_expires_after_ten_minutes(
    skewed: tuple[World, list[float]],
) -> None:
    world, skew = skewed
    created = hidden_queue_draft(world)
    world.gateway.pending.clear()
    skew[0] = 300.0
    assert get(world, created["id"])["status"] == "draft"
    skew[0] = 11 * 60.0
    assert get(world, created["id"])["status"] == "expired"


def test_late_key_of_a_draft_is_picked_up_on_get(world: World) -> None:
    created = hidden_queue_draft(world)
    shown = get(world, created["id"])
    assert shown["status"] == "queued" and shown["gateway_key"] in world.gateway.pending


# --- 10. foreign pending sets -------------------------------------------------------------------


@pytest.mark.parametrize("field", ["loop_id", "proposer", "items"])
def test_pending_set_with_our_id_but_other_content_is_foreign(world: World, field: str) -> None:
    real = world.gateway.pending_params

    def forged() -> list[dict[str, Any]]:
        rows = real()
        for row in rows:
            row[field] = "someone-else" if field != "items" else [{**row["items"][0], "to": 9.0}]
        return rows

    world.gateway.pending_params = forged  # type: ignore[method-assign]
    response = Session(world, "eng1").call("POST", PROPOSE, BODY)
    assert response.status_code == 409 and response.json()["detail"] == "foreign_pending"
    records = list((world.root / "_tuning" / "proposals").glob("*.json"))
    assert [json.loads(p.read_text("utf-8"))["status"] for p in records] == [
        "refused:foreign_pending"
    ]
    assert world.gateway.apply_count == 0


# --- 8. list: pagination, bounded work, short locks ---------------------------------------------


def test_list_is_paginated(world: World) -> None:
    ids = [propose(world)["id"] for _ in range(3)]
    viewer = Session(world, "view1")
    assert len(viewer.call("GET", "/tuning/proposals").json()) == 3
    page = viewer.call("GET", "/tuning/proposals?limit=2&offset=1").json()
    assert len(page) == 2
    everything = [r["id"] for r in viewer.call("GET", "/tuning/proposals").json()]
    assert [r["id"] for r in page] == everything[1:3] and set(everything) == set(ids)
    assert viewer.call("GET", "/tuning/proposals?limit=0").status_code == 422
    assert viewer.call("GET", "/tuning/proposals?limit=201").status_code == 422
    assert viewer.call("GET", "/tuning/proposals?offset=-1").status_code == 422


def test_list_reconciles_at_most_the_cap_per_request(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    drafts = [hidden_queue_draft(world) for _ in range(4)]
    monkeypatch.setattr(routes, "MAX_RECONCILE", 2)
    listed = Session(world, "view1").call("GET", "/tuning/proposals").json()
    assert sorted(r["status"] for r in listed) == ["draft", "draft", "queued", "queued"]
    assert {r["id"] for r in listed} == {d["id"] for d in drafts}


def test_list_skips_a_locked_record_quickly_and_does_not_write(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = hidden_queue_draft(world)
    monkeypatch.setattr(routes, "GET_LOCK_TIMEOUT_S", 0.1)
    before = (world.root / "_tuning" / "proposals" / f"{created['id']}.json").read_bytes()
    started = time.monotonic()
    with world.deps.store.exclusive(created["id"]):
        listed = Session(world, "view1").call("GET", "/tuning/proposals").json()
    assert time.monotonic() - started < 2.0
    assert listed[0]["status"] == "draft"  # the stored state: the record was busy
    after = (world.root / "_tuning" / "proposals" / f"{created['id']}.json").read_bytes()
    assert before == after


def test_list_without_work_takes_no_lock(world: World) -> None:
    created = propose(world)
    approve(world, created["id"])
    with world.deps.store.exclusive(created["id"]):  # a held lock would block a GET that locks
        started = time.monotonic()
        listed = Session(world, "view1").call("GET", "/tuning/proposals").json()
    assert time.monotonic() - started < 1.0 and listed[0]["status"] == "applied"


# --- pure helpers: queued_key, read_current, client snapshot ------------------------------------


def make_record() -> dict[str, Any]:
    """The few record fields the key match and the applied block use."""
    items = [{"param": "gain", "target": KP, "unit": "OUT/PV", "from": 0.5, "to": 1.25}]
    return {"id": "p1", "loop_id": LOOP, "created_by": "eng1", "items": items,
            "vendor_form": {"key": "siemens_pid_compact"}, "gateway_key": "k" * 64}  # fmt: skip


def summary(record: dict[str, Any], **over: Any) -> dict[str, Any]:
    """The pending_params summary the gateway would show for the record."""
    items = [{**i, "vendor_form": "siemens_pid_compact"} for i in record["items"]]
    base = {
        "key": "k" * 64, "kind": "pid_param", "proposal_id": record["id"],
        "loop_id": record["loop_id"], "proposer": record["created_by"], "items": items,
    }  # fmt: skip
    return {**base, **over}


def test_queued_key_needs_matching_loop_proposer_and_items() -> None:
    record = make_record()
    assert tuning_gateway.queued_key([summary(record)], record) == "k" * 64
    assert tuning_gateway.queued_key([summary(record, proposal_id="other")], record) is None
    for over in ({"loop_id": "X"}, {"proposer": "mallory"}, {"items": []}):
        with pytest.raises(tuning_gateway.ForeignPending):
            tuning_gateway.queued_key([summary(record, **over)], record)
    reordered = summary(record, items=list(reversed(summary(record)["items"])))
    assert tuning_gateway.queued_key([reordered], record) == "k" * 64


def test_read_current_refuses_a_tag_that_is_not_in_the_sources_tag_list() -> None:
    site = site_document()
    reads: list[list[str]] = []

    class Connector:
        def read_live(self, tags: list[str]) -> dict[str, Any]:
            reads.append(tags)
            return {t: LiveValue(1.0, 0, "2026-11-06T00:00:00Z") for t in tags}

    def factory(_source: dict[str, Any]) -> Any:
        return Connector()

    targets = {"gain": KP}
    assert tuning_build.read_current(site, "dcs", targets, factory) == {"gain": 1.0}
    site["tags"] = [t for t in site["tags"] if t["id"] != KP]
    reads.clear()
    with pytest.raises(HTTPException) as unknown:
        tuning_build.read_current(site, "dcs", targets, factory)
    assert unknown.value.detail == "no_live_values" and reads == []
    site["tags"].append({"id": KP, "source": "other_source"})
    with pytest.raises(HTTPException) as foreign:
        tuning_build.read_current(site, "dcs", targets, factory)
    assert foreign.value.detail == "no_live_values" and reads == []


def test_file_client_snapshot_is_one_read_of_state_json(tmp_path: Path) -> None:
    gateway_dir = tmp_path / "_gateway"
    gateway_dir.mkdir()
    state = {"pending_params": [{"key": "a"}], "applied_params": {"p1": {"key": "a"}},
             "param_events": [{"event": "param_write"}], "chain_ok": True,
             "audit_tail": [], "mode": "confirm"}  # fmt: skip
    (gateway_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    snap = FileGatewayClient(tmp_path).snapshot()
    assert snap == {"pending_params": [{"key": "a"}], "applied_params": {"p1": {"key": "a"}},
                    "param_events": [{"event": "param_write"}], "chain_ok": True}  # fmt: skip
    state.pop("applied_params")
    state["chain_ok"] = "yes"
    (gateway_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    snap = FileGatewayClient(tmp_path).snapshot()
    assert snap["applied_params"] == {} and snap["chain_ok"] is False

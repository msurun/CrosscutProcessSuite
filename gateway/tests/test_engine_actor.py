"""Actor attribution and accessor tests for the write gateway engine.

Pin how the gateway stamps audit records with the acting principal, how the actor context
is restored after calls (including failures), and the actor-aware accessors and controls.
Sources: the engine, actor and audit modules as they exist; no src file is modified.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.audit import AuditLog, verify_chain
from crosscut_gateway.policy import proposal_key
from test_engine_hardening import make
from test_gateway_scenarios import POLICY, TAG, S, SimPlant, proposal, run

ALICE = ActorContext(
    actor="alice",
    roles=("engineer", "operator"),
    session="abcd",
    source_ip="1.2.3.4",
    cmd_id="cmd1",
)
BOB = ActorContext(actor="bob", roles=("operator",), session="beef")

GATEWAY_FIELDS = {
    "actor": "gateway",
    "roles": "",
    "session": "",
    "source_ip": "",
    "cmd_id": "",
}
NEW_TAG = "TIC102.SP"


def test_propose_records_carry_the_acting_actor() -> None:
    """A propose with an actor context stamps every record it writes with that actor."""
    plant = SimPlant()
    gw = make("confirm", plant)
    gw.tick(0)
    gw.propose(proposal(55.0), actor_ctx=ALICE)
    records = gw.audit_records()
    assert [rec["event"] for rec in records] == ["proposal", "queued"]
    for record in records:
        assert record["actor"] == "alice"
        assert record["roles"] == "engineer,operator"
        assert record["session"] == "abcd"
        assert record["source_ip"] == "1.2.3.4"
        assert record["cmd_id"] == "cmd1"
        assert all(isinstance(value, str) for value in record.values())
    assert verify_chain(records)


def test_calls_without_actor_are_attributed_to_the_gateway() -> None:
    """A propose without an actor context stamps the gateway identity on each record."""
    plant = SimPlant()
    gw = make("confirm", plant)
    gw.tick(0)
    gw.propose(proposal(55.0))
    for record in gw.audit_records():
        assert {key: record[key] for key in GATEWAY_FIELDS} == GATEWAY_FIELDS


def test_tick_records_use_the_gateway_actor_after_a_context_call() -> None:
    """The actor context is restored after each call, so tick records read gateway."""
    plant = SimPlant()
    gw = make("supervised", plant)
    gw.propose(proposal(55.0), actor_ctx=ALICE)
    plant.set_setpoint_by_operator(TAG, 40.0)
    run(gw, plant, 1)
    records = gw.audit_records()
    assert any(rec["event"] == "operator_override" and rec["actor"] == "gateway" for rec in records)


def test_actor_context_is_restored_when_a_call_raises() -> None:
    """A KeyError from approve leaves no residual actor on later gateway records."""
    gw = make("confirm")
    with pytest.raises(KeyError):
        gw.approve("missing-key", actor_ctx=ALICE)
    gw.tick(0)
    gw.propose(proposal(55.0))
    records = gw.audit_records()
    assert records
    for record in records:
        assert {key: record[key] for key in GATEWAY_FIELDS} == GATEWAY_FIELDS


def test_legacy_and_actor_records_chain_together(tmp_path: Path) -> None:
    """Old records without actor fields and new ones with them form one valid chain."""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    legacy_fields = {"tag": TAG, "value": "55.0", "proposer": "sup", "mode": "supervised"}
    log.append("legacy", {**legacy_fields, "reason_code": "old"}, 0)
    log.append("actor", {**GATEWAY_FIELDS, "reason_code": "new"}, S)
    assert verify_chain(log.records())
    reloaded = AuditLog(path)
    assert verify_chain(reloaded.records())


def test_tampering_with_an_actor_field_breaks_the_chain() -> None:
    """Changing the actor of a record after the fact invalidates the chain."""
    log = AuditLog()
    log.append("actor", {**GATEWAY_FIELDS, "reason_code": "new"}, 0)
    records = log.records()
    records[0]["actor"] = "mallory"
    assert not verify_chain(records)


def test_self_approval_is_refused_and_keeps_the_proposal_pending() -> None:
    """A proposer may not approve their own queued proposal."""
    plant = SimPlant()
    gw = make("confirm", plant)
    gw.tick(0)
    queued = proposal(55.0)
    gw.propose(queued, actor_ctx=ALICE)
    key = proposal_key(queued)
    decision = gw.approve(key, actor_ctx=ALICE)
    assert not decision.accepted
    assert decision.reason_code == "self_approval"
    assert key in [proposal_key(item) for item in gw.pending()]
    assert any(
        rec["event"] == "self_approval" and rec["actor"] == "alice" for rec in gw.audit_records()
    )
    assert gw.pending_proposer(key) == "alice"
    approved = gw.approve(key, actor_ctx=BOB)
    assert approved.accepted
    assert len(plant.writes) == 1


def test_approval_without_actor_is_allowed_for_a_proposal_without_actor() -> None:
    """Legacy approval without any actor context still executes an anonymous proposal."""
    plant = SimPlant()
    gw = make("confirm", plant)
    gw.tick(0)
    queued = proposal(55.0)
    gw.propose(queued)
    decision = gw.approve(proposal_key(queued))
    assert decision.accepted
    assert len(plant.writes) == 1


def test_approval_without_actor_is_allowed_for_an_actor_proposal() -> None:
    """An approver without a context cannot match the proposer, so the write goes through."""
    plant = SimPlant()
    gw = make("confirm", plant)
    gw.tick(0)
    queued = proposal(55.0)
    gw.propose(queued, actor_ctx=ALICE)
    decision = gw.approve(proposal_key(queued))
    assert decision.accepted
    assert len(plant.writes) == 1


def test_accessors_report_mode_cap_kill_state_and_target_state() -> None:
    """The read-only accessors expose the cap, the kill latch and per-tag state."""
    plant = SimPlant()
    gw = make("confirm", plant)
    assert gw.mode_cap == "supervised"
    assert not gw.killed
    assert gw.target_state(TAG) == "enabled"
    assert gw.target_state(123) is None
    assert gw.target_state("unknown") is None
    gw.kill(actor_ctx=ALICE)
    assert gw.killed
    assert gw.target_state(TAG) == "killed"
    assert any(rec["event"] == "kill" and rec["actor"] == "alice" for rec in gw.audit_records())
    assert gw.pending_proposer(None) is None
    assert gw.pending_proposer("unknown") is None


def test_pending_proposer_names_the_actor_that_queued_the_proposal() -> None:
    """A queued proposal remembers who proposed it, read back through pending_proposer."""
    plant = SimPlant()
    gw = make("confirm", plant)
    gw.tick(0)
    queued = proposal(55.0)
    gw.propose(queued, actor_ctx=ALICE)
    assert gw.pending_proposer(proposal_key(queued)) == "alice"


def test_reset_kill_clears_the_latch_and_reattaches_the_actor() -> None:
    """reset_kill and re_enable restore the target and stamp the acting actor."""
    plant = SimPlant()
    gw = make("confirm", plant)
    gw.kill(actor_ctx=ALICE)
    gw.reset_kill(actor_ctx=ALICE)
    assert not gw.killed
    assert gw.mode == "advisory"
    assert gw.target_state(TAG) == "stopped:kill"
    gw.re_enable(TAG, actor_ctx=ALICE)
    assert gw.target_state(TAG) == "enabled"
    records = gw.audit_records()
    assert any(rec["event"] == "kill_reset" and rec["actor"] == "alice" for rec in records)
    assert any(rec["event"] == "re_enable" and rec["actor"] == "alice" for rec in records)


def test_reset_kill_without_a_prior_kill_stops_targets() -> None:
    """Calling reset_kill when never killed still stops every target and drops to advisory."""
    gw = make("supervised")
    gw.reset_kill(actor_ctx=ALICE)
    assert not gw.killed
    assert gw.mode == "advisory"
    assert gw.status() == {TAG: "stopped:kill"}


def test_swap_policies_is_refused_above_advisory() -> None:
    """A policy reload cannot happen while the gateway is in confirm mode."""
    gw = make("confirm")
    with pytest.raises(ValueError):
        gw.swap_policies({TAG: POLICY}, "dry_run", actor_ctx=ALICE)


def test_swap_policies_adds_tags_and_lowers_the_cap() -> None:
    """In advisory mode a reload may add a tag and tighten the mode cap."""
    gw = make("advisory")
    gw.swap_policies({TAG: POLICY, NEW_TAG: POLICY}, "dry_run", digest="abc", actor_ctx=ALICE)
    assert gw.status()[NEW_TAG] == "enabled"
    assert gw.mode_cap == "dry_run"
    assert gw.mode == "advisory"
    assert any(
        rec["event"] == "policy_reload" and rec["value"] == "abc" and rec["actor"] == "alice"
        for rec in gw.audit_records()
    )


def test_swap_policies_keeps_a_gateway_that_is_off_off() -> None:
    """A reload in mode off does not raise the mode above off."""
    gw = make("off")
    gw.swap_policies({TAG: POLICY}, "advisory")
    assert gw.mode == "off"
    assert gw.mode_cap == "advisory"


def test_swap_policies_drops_removed_tags() -> None:
    """A tag absent from the new policy map disappears from the status."""
    gw = make("advisory")
    gw.swap_policies({NEW_TAG: POLICY}, "dry_run")
    assert NEW_TAG in gw.status()
    assert TAG not in gw.status()


def test_record_event_appends_the_given_fields() -> None:
    """record_event writes an audit record with the event, reason, value and actor."""
    gw = make("advisory")
    gw.record_event("auth_reject", ALICE, "bad_signature", value="propose")
    record = gw.audit_records()[-1]
    assert record["event"] == "auth_reject"
    assert record["reason_code"] == "bad_signature"
    assert record["value"] == "propose"
    assert record["actor"] == "alice"

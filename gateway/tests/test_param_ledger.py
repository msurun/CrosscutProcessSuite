"""state.json carries a bounded persistent map of applied parameter sets and the param events.

The audit tail of state.json holds only 200 rows, so a param_write or a
param_changed_externally can fall out of it. ``applied_params`` and ``param_events`` do not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from auth_helpers import outbox, send
from crosscut_gateway.param_ledger import EVENT_EXTERNAL, MAX_APPLIED, MAX_EVENTS, ParamLedger
from test_service_params import (
    KP,
    SECOND_ENGINEER,
    make_param_env,
    pending_key,
    propose,
    state,
)


def write_row(pid: str, tag: str, seq: int, **over: str) -> dict[str, str]:
    """An audit record of event param_write as the engine writes it."""
    base = {
        "seq": str(seq), "t_ns": str(1000 + seq), "event": "param_write", "tag": tag,
        "proposal_id": pid, "key": f"key-{pid}", "applied_from": "2.0", "applied_to": "3.0",
        "actor": "ed",
    }  # fmt: skip
    return {**base, **over}


def test_ledger_groups_items_by_proposal_and_parses_values() -> None:
    ledger = ParamLedger()
    ledger.update([write_row("p1", "A", 1), write_row("p1", "B", 2, applied_to="4.5")])
    entry = ledger.applied["p1"]
    assert entry["key"] == "key-p1" and entry["approver"] == "ed"
    assert entry["applied_from"] == {"A": 2.0, "B": 2.0}
    assert entry["applied_to"] == {"A": 3.0, "B": 4.5}
    assert entry["t_ns"] == 1002 and entry["status"] == "applied"


def test_ledger_is_incremental_and_rebuilds_from_the_whole_log() -> None:
    rows = [write_row("p1", "A", 1), write_row("p2", "A", 2)]
    live = ParamLedger()
    live.update(rows[:1])
    live.update(rows)
    live.update(rows)  # no row is counted twice
    rebuilt = ParamLedger()
    rebuilt.update(rows)
    assert live.applied == rebuilt.applied and list(live.events) == list(rebuilt.events)
    assert len(live.events) == 2


def test_ledger_is_bounded() -> None:
    rows = [write_row(f"p{i}", "A", i) for i in range(MAX_APPLIED + 30)]
    ledger = ParamLedger()
    ledger.update(rows)
    assert len(ledger.applied) == MAX_APPLIED and "p0" not in ledger.applied
    assert f"p{MAX_APPLIED + 29}" in ledger.applied
    noise = [{"seq": "1", "t_ns": "1", "event": "param_changed_externally", "tag": "A"}]
    ledger.update(rows + noise * (MAX_EVENTS + 20))
    assert len(ledger.events) == MAX_EVENTS


def test_external_change_event_keeps_target_and_loop_and_other_events_are_ignored() -> None:
    ledger = ParamLedger()
    ledger.update(
        [
            {"seq": "1", "t_ns": "5", "event": "mode_change", "tag": ""},
            {"seq": "2", "t_ns": "6", "event": EVENT_EXTERNAL, "tag": "A", "loop": "L1"},
        ]
    )
    assert len(ledger.events) == 1
    event = ledger.events[0]
    assert event["event"] == "param_changed_externally"
    assert event["target"] == "A" and event["loop"] == "L1"


def test_unparsable_applied_values_are_none_not_invented() -> None:
    ledger = ParamLedger()
    ledger.update([write_row("p1", "A", 1, applied_to="nan?")])
    assert ledger.applied["p1"]["applied_to"] == {"A": None}


def test_service_state_has_the_ledger_after_an_approve(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    assert state(env)["applied_params"] == {} and state(env)["param_events"] == []
    propose(env)
    sent = send(env, "approve", {"key": pending_key(env)}, **SECOND_ENGINEER)
    assert (outbox(env.root, sent["id"]) or {}).get("ok") is True
    env.service.poll_once()
    shown: dict[str, Any] = state(env)
    entry = shown["applied_params"]["tp1"]
    assert entry["applied_to"] == {KP: 3.0} and entry["approver"] == "ed"
    assert entry["key"] and shown["param_events"][-1]["event"] == "param_write"


def test_service_rebuilds_the_ledger_at_start_from_the_audit_log(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    propose(env)
    send(env, "approve", {"key": pending_key(env)}, **SECOND_ENGINEER)
    env.service.poll_once()
    from crosscut_gateway.service import GatewayService  # a restart: same gateway/audit

    restarted = GatewayService(env.root, env.gateway, clock=env.clock)
    restarted.poll_once()
    assert "tp1" in state(env)["applied_params"]


def test_service_state_keeps_the_external_change_with_target_and_loop(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    propose(env)
    send(env, "approve", {"key": pending_key(env)}, **SECOND_ENGINEER)
    env.plant.params[KP] = 2.5  # type: ignore[attr-defined]  # an operator retunes at the DCS
    for _ in range(3):
        env.service.poll_once()
    events = [e for e in state(env)["param_events"] if e["event"] == "param_changed_externally"]
    assert events and events[0]["target"] == KP and events[0]["loop"] == "L1"

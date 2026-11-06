"""End to end: pinned policy with a setpoint and a PID parameter target, real OPC UA plant.

Policy file + pin -> start_from_policy_file -> GatewayService -> signed propose_params and
approve through the inbox -> a local asyncua server holds the new value (ADR 014, wiring).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from auth_helpers import KEY, AuthEnv, SignOpts, audit_events, outbox, rejected_reason, send
from crosscut_gateway import engine, keyfile, policy_file, policy_pin
from crosscut_gateway import service as gateway_service
from crosscut_gateway.opcua_plant import OpcUaPlant
from test_gateway_scenarios import S
from test_gateway_service import FakeClock
from test_opcua_params import _add_param_nodes, _param_entry, _set_param
from test_opcua_plant import (
    TAG,
    ServerControl,
    _close_plant,
    get_free_port,
    make_map,
)

KP = "FIC101.KP"
HOUR = 3600 * S
ENGINEER = {"actor": "erin", "roles": ("engineer",)}
SECOND_ENGINEER = {"actor": "ed", "roles": ("engineer",)}
LEAD = {"actor": "lena", "roles": ("lead",)}
OPERATOR = {"actor": "olga", "roles": ("operator",)}
START_VALUE = 2.5  # the initial value of the server node "PD"


@pytest.fixture(scope="module")
def server() -> Iterator[ServerControl]:
    """One asyncua server for the module; skipped when it cannot bind."""
    ctrl = ServerControl(get_free_port())
    try:
        try:
            ctrl.start()
            _add_param_nodes(ctrl)
        except OSError as error:
            pytest.skip(f"local asyncua server cannot bind: {error}")
        yield ctrl
    finally:
        ctrl.stop()


def policy_document(mode: str = "confirm", kp_max: float = 10.0) -> dict[str, Any]:
    """A policy with the setpoint FIC101.SP and the gain target FIC101.KP."""
    setpoint = {
        "limits": [0.0, 100.0], "max_step": 10.0, "max_rate_per_s": 5.0, "min_interval_s": 1.0,
        "allowed_loop_modes": ["CAS"], "hold_off_s": 60.0, "watchdog_s": 5.0,
        "readback_tolerance": 0.5,
    }
    gain = {
        "kind": "pid_param", "loop": "FIC101", "param": "gain", "unit": "1",
        "vendor_form": "siemens_pid_compact", "limits": [0.1, kp_max], "max_ratio": 2.0,
        "readback_tolerance": 0.001, "min_interval_s": 0.0, "allowed_loop_modes": ["CAS"],
    }
    return {"version": 1, "mode": mode, "targets": {TAG: setpoint, KP: gain}}


def write_policy(root: Path, document: dict[str, Any], clock: FakeClock) -> Path:
    """Write the policy file and its pin (author1/approver1); return the policy path."""
    path = root / "policy" / "write-policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    signers = policy_pin.PinSigners("author1", "approver1")
    policy_pin.create_pin(path, KEY, signers, now=datetime.fromtimestamp(clock(), UTC))
    return path


@dataclass
class Rig:
    """The wired system under test."""

    env: AuthEnv
    ctrl: ServerControl
    plant: OpcUaPlant


@pytest.fixture
def rig(tmp_path: Path, server: ServerControl) -> Iterator[Rig]:
    """Start the gateway service on the pinned policy and a plant map with both target kinds."""
    server.reset()
    _set_param(server, "PD", START_VALUE)
    plant_map = make_map(server)
    plant_map["targets"][KP] = _param_entry(server, "PD", "Double")
    plant = OpcUaPlant(plant_map, timeout_s=2.0)
    clock = FakeClock()
    policy_path = write_policy(tmp_path, policy_document(), clock)
    gateway = engine.start_from_policy_file(policy_path, plant, "confirm", key=KEY)
    key_path = tmp_path / "_secrets" / keyfile.KEY_FILE_NAME
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(KEY)
    options = gateway_service.ServiceOptions(
        auth_required=True, key_path=key_path, policy_path=policy_path, enforce_start_floor=False
    )
    service = gateway_service.GatewayService(tmp_path, gateway, clock=clock, options=options)
    service.poll_once()
    env = AuthEnv(tmp_path, clock, plant, gateway, service, key_path, policy_path)  # type: ignore[arg-type]
    try:
        yield Rig(env, server, plant)
    finally:
        _close_plant(plant)


def propose_args(env: AuthEnv, to: float = 3.0) -> dict[str, Any]:
    """propose_params arguments: raise the gain from the start value to ``to``."""
    now = int(env.clock() * S)
    item = {
        "param": "gain", "target": KP, "unit": "1", "vendor_form": "siemens_pid_compact",
        "from": START_VALUE, "to": to,
    }
    return {
        "proposal_id": "tp1", "loop_id": "FIC101", "items": [item], "proposer": "erin",
        "t_ns": now, "expires_ns": now + 8 * HOUR, "reason": "tune", "rollback_of": None,
    }


def state(env: AuthEnv) -> dict[str, Any]:
    """The persisted state.json."""
    path = env.root / "_gateway" / "state.json"
    parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return parsed


def propose_and_get_key(env: AuthEnv) -> str:
    """Send propose_params as an engineer; return the key of the queued set."""
    sent = send(env, "propose_params", propose_args(env), **ENGINEER)
    reply = outbox(env.root, sent["id"])
    assert reply is not None and reply["result"]["reason_code"] == "queued"
    return str(state(env)["pending_params"][0]["key"])


def test_policy_view_in_state_carries_the_parameter_target(rig: Rig) -> None:
    document = state(rig.env)["policy"]["document"]
    assert document["targets"][KP]["kind"] == "pid_param"
    assert document["targets"][KP]["param"] == "gain"
    assert state(rig.env)["targets"][KP] == "enabled"


def test_second_engineer_approval_writes_the_server_node(rig: Rig) -> None:
    env = rig.env
    key = propose_and_get_key(env)
    assert rig.ctrl.get_node("PD") == START_VALUE  # queued, nothing written yet
    approved = send(env, "approve", {"key": key}, **SECOND_ENGINEER)
    result = outbox(env.root, approved["id"])
    assert result is not None and result["result"]["reason_code"] == "applied"
    assert rig.ctrl.get_node("PD") == 3.0
    assert rig.plant.read_param(KP) == 3.0
    written = audit_events(env, "param_write")[0]
    assert written["actor"] == "ed" and written["tag"] == KP
    assert (written["applied_from"], written["applied_to"]) == ("2.5", "3.0")


def test_operator_approval_is_refused_and_nothing_is_written(rig: Rig) -> None:
    env = rig.env
    key = propose_and_get_key(env)
    denied = send(env, "approve", {"key": key}, **OPERATOR)
    assert rejected_reason(env.root, denied["id"]) == "missing_permission:gw.approve.tuning"
    assert rig.ctrl.get_node("PD") == START_VALUE
    assert len(state(env)["pending_params"]) == 1


def test_external_change_on_the_server_puts_the_target_in_hold_off(rig: Rig) -> None:
    env = rig.env
    send(env, "approve", {"key": propose_and_get_key(env)}, **SECOND_ENGINEER)
    assert state(env)["targets"][KP] == "enabled"
    _set_param(rig.ctrl, "PD", 4.0)  # an operator changes the tuning at the DCS
    env.service.poll_once()
    assert state(env)["targets"][KP] == "hold_off"
    assert audit_events(env, "param_changed_externally")[0]["tag"] == KP
    assert rig.ctrl.get_node("PD") == 4.0  # the gateway never writes it back


def pin_next_policy(env: AuthEnv, document: dict[str, Any]) -> None:
    """Lower the mode to advisory, then save and pin ``document`` as the next policy."""
    send(env, "set_mode", {"mode": "advisory"}, **LEAD)
    send(env, "policy_draft", {"document": document}, actor="alice", roles=("lead",))
    digest = policy_file.policy_digest(document)
    send(env, "policy_pin", {"digest": digest}, actor="bob", roles=("lead",),
         extra=SignOpts(stepup=True))


def test_reload_is_refused_while_a_parameter_set_is_pending(rig: Rig) -> None:
    env = rig.env
    key = propose_and_get_key(env)
    pin_next_policy(env, policy_document("confirm", kp_max=8.0))
    blocked = send(env, "policy_reload", {}, **LEAD)
    reply = outbox(env.root, blocked["id"])
    assert reply is not None and reply["ok"] is False
    assert reply["error"] == "reload_blocked_param_pending"
    assert len(state(env)["pending_params"]) == 1
    send(env, "reject", {"key": key}, **OPERATOR)
    done = send(env, "policy_reload", {}, **LEAD)
    assert (outbox(env.root, done["id"]) or {}).get("ok") is True
    assert audit_events(env, "policy_reload")


def test_reload_that_drops_a_mapped_parameter_target_is_refused(rig: Rig) -> None:
    env = rig.env
    without_param = policy_document("confirm")
    del without_param["targets"][KP]
    pin_next_policy(env, without_param)
    before = env.gateway.status()
    refused = send(env, "policy_reload", {}, **LEAD)
    reply = outbox(env.root, refused["id"])
    assert reply is not None and reply["ok"] is False
    assert KP in reply["error"] and "plant map" in reply["error"]
    assert env.gateway.status() == before

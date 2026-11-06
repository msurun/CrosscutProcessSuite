"""propose_params through the signed inbox: roles, two persons, strict args (ADR 014 step 3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from auth_helpers import (
    KEY,
    AuthEnv,
    audit_events,
    outbox,
    rejected_reason,
    send,
    write_key_file,
)
from crosscut_gateway import engine, keyfile
from crosscut_gateway import service as gateway_service
from crosscut_gateway.engine_params import ParamConfig
from test_engine_params import KP, PARAMS, TI, ParamPlant
from test_gateway_scenarios import POLICY, TAG, S
from test_gateway_service import FakeClock

HOUR = 3600 * S
ENGINEER = {"actor": "erin", "roles": ("engineer",)}
SECOND_ENGINEER = {"actor": "ed", "roles": ("engineer",)}
LEAD = {"actor": "lena", "roles": ("lead",)}
OPERATOR = {"actor": "olga", "roles": ("operator",)}


def make_param_env(tmp_path: Path, mode: str = "confirm") -> AuthEnv:
    """A signed-auth service on a gateway with setpoint and PID parameter targets."""
    clock, plant = FakeClock(), ParamPlant()
    key_path = tmp_path / "_secrets" / keyfile.KEY_FILE_NAME
    write_key_file(key_path, KEY)
    gateway = engine.WriteGateway(
        plant, {TAG: POLICY}, mode, params=ParamConfig(dict(PARAMS))  # type: ignore[arg-type]
    )
    options = gateway_service.ServiceOptions(
        auth_required=True, key_path=key_path, enforce_start_floor=False
    )
    service = gateway_service.GatewayService(tmp_path, gateway, clock=clock, options=options)
    service.poll_once()
    return AuthEnv(tmp_path, clock, plant, gateway, service, key_path, None)


def item(**over: Any) -> dict[str, Any]:
    base = {"param": "gain", "target": KP, "unit": "1", "vendor_form": "siemens_pid",
            "from": 2.0, "to": 3.0}
    return {**base, **over}


def args(env: AuthEnv, **over: Any) -> dict[str, Any]:
    now = int(env.clock() * S)
    base: dict[str, Any] = {
        "proposal_id": "tp1", "loop_id": "L1", "items": [item()], "proposer": "erin",
        "t_ns": now, "expires_ns": now + 8 * HOUR, "reason": "tune", "rollback_of": None,
    }
    return {**base, **over}


def state(env: AuthEnv) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(
        (env.root / "_gateway" / "state.json").read_text(encoding="utf-8")
    )
    return parsed


def propose(env: AuthEnv, who: dict[str, Any] = ENGINEER, **over: Any) -> dict[str, Any]:
    return send(env, "propose_params", args(env, **over), **who)


def pending_key(env: AuthEnv) -> str:
    return str(state(env)["pending_params"][0]["key"])


def test_engineer_proposes_and_second_person_approves(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    sent = propose(env)
    reply = outbox(env.root, sent["id"])
    assert reply is not None and reply["ok"] is True
    assert reply["result"] == {"accepted": True, "reason_code": "queued", "clamped_value": None}
    summary = state(env)["pending_params"]
    assert len(summary) == 1 and state(env)["pending"] == []
    assert summary[0]["kind"] == "pid_param" and summary[0]["loop_id"] == "L1"
    assert summary[0]["items"][0] == item() and summary[0]["proposer"] == "erin"
    assert state(env)["targets"][KP] == "enabled"
    assert env.plant.writes == [] and env.plant.params[KP] == 2.0  # type: ignore[attr-defined]

    approved = send(env, "approve", {"key": pending_key(env)}, **SECOND_ENGINEER)
    result = outbox(env.root, approved["id"])
    assert result is not None and result["ok"] is True
    assert result["result"]["reason_code"] == "applied"
    assert env.plant.params[KP] == 3.0  # type: ignore[attr-defined]
    written = audit_events(env, "param_write")[0]
    assert written["actor"] == "ed" and written["applied_to"] == "3.0"
    assert state(env)["pending_params"] == []


def test_lead_can_approve_too(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    propose(env)
    sent = send(env, "approve", {"key": pending_key(env)}, **LEAD)
    reply = outbox(env.root, sent["id"])
    assert reply is not None and reply["result"]["reason_code"] == "applied"


def test_operator_cannot_approve_but_can_reject(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    propose(env)
    key = pending_key(env)
    denied = send(env, "approve", {"key": key}, **OPERATOR)
    assert rejected_reason(env.root, denied["id"]) == "missing_permission:gw.approve.tuning"
    reply = outbox(env.root, denied["id"])
    assert reply is not None and reply["ok"] is False
    assert reply["error"] == "missing_permission:gw.approve.tuning"
    assert env.plant.params[KP] == 2.0  # type: ignore[attr-defined]
    assert len(state(env)["pending_params"]) == 1
    rejected = send(env, "reject", {"key": key}, **OPERATOR)
    assert (outbox(env.root, rejected["id"]) or {}).get("ok") is True
    assert state(env)["pending_params"] == []


def test_engineer_cannot_approve_own_set(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    propose(env)
    sent = send(env, "approve", {"key": pending_key(env)}, **ENGINEER)
    assert rejected_reason(env.root, sent["id"]) == "self_approval"
    reply = outbox(env.root, sent["id"])
    assert reply is not None and reply["error"] == "self_approval"
    assert env.plant.params[KP] == 2.0  # type: ignore[attr-defined]
    assert len(state(env)["pending_params"]) == 1


def test_operator_and_viewer_cannot_propose(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    for who in (OPERATOR, {"actor": "vic", "roles": ("viewer",)}):
        sent = propose(env, who)
        assert rejected_reason(env.root, sent["id"]) == "missing_permission:gw.propose"
    assert state(env)["pending_params"] == []


@pytest.mark.parametrize(
    "who",
    [
        {"actor": "svc:runtime", "roles": ("service",)},
        {"actor": "svc:runtime", "roles": ("engineer",)},
    ],
)
def test_service_principal_cannot_propose_tuning(tmp_path: Path, who: dict[str, Any]) -> None:
    env = make_param_env(tmp_path)
    sent = propose(env, who)
    assert rejected_reason(env.root, sent["id"]) == "service_cannot_propose_tuning"
    reply = outbox(env.root, sent["id"])
    assert reply is not None and reply["ok"] is False
    assert reply["error"] == "service_cannot_propose_tuning"
    assert state(env)["pending_params"] == []
    denied = [r for r in audit_events(env, "auth_reject")]
    assert denied[-1]["reason_code"] == "service_cannot_propose_tuning"


def test_service_may_still_propose_setpoints(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    now = int(env.clock() * S)
    setpoint = {"target_tag": TAG, "value": 55.0, "proposer": "svc", "t_ns": now, "reason": "t"}
    sent = send(env, "propose", setpoint, actor="svc:runtime", roles=("service",))
    reply = outbox(env.root, sent["id"])
    assert reply is not None and reply["ok"] is True


def test_engine_refusals_reach_the_caller(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    sent = propose(env, items=[item(to=20.0)])
    reply = outbox(env.root, sent["id"])
    assert reply is not None and reply["ok"] is True
    assert reply["result"]["accepted"] is False
    assert reply["result"]["reason_code"] == "out_of_limits"
    assert reply["result"]["clamped_value"] is None
    assert state(env)["pending_params"] == []


def test_legacy_mode_without_gate_refuses_proposal_without_actor(tmp_path: Path) -> None:
    clock, plant = FakeClock(), ParamPlant()
    gateway = engine.WriteGateway(
        plant, {TAG: POLICY}, "confirm", params=ParamConfig(dict(PARAMS))  # type: ignore[arg-type]
    )
    service = gateway_service.GatewayService(tmp_path, gateway, clock=clock)
    service.poll_once()
    command = {"id": "c1", "cmd": "propose_params", "args": args_for(clock)}
    inbox = tmp_path / "_gateway" / "inbox"
    (inbox / "c1.json").write_text(json.dumps(command), encoding="utf-8")
    service.poll_once()
    reply = json.loads((tmp_path / "_gateway" / "outbox" / "c1.json").read_text(encoding="utf-8"))
    assert reply["result"]["reason_code"] == "proposer_required"


def args_for(clock: FakeClock) -> dict[str, Any]:
    now = int(clock() * S)
    return {"proposal_id": "tp9", "loop_id": "L1", "items": [item()], "proposer": "x",
            "t_ns": now, "expires_ns": now + HOUR, "reason": "t"}


BAD_ARGS = [
    ("items_not_list", {"items": "gain"}),
    ("items_empty", {"items": []}),
    ("items_too_many", {"items": [item(target=f"T{i}") for i in range(9)]}),
    ("item_not_dict", {"items": ["x"]}),
    ("item_missing_key", {"items": [{"param": "gain"}]}),
    ("item_extra_key", {"items": [item(extra=1)]}),
    ("to_bool", {"items": [item(to=True)]}),
    ("from_bool", {"items": [item(**{"from": False})]}),
    ("to_string", {"items": [item(to="3")]}),
    ("to_infinite", {"items": [item(to=1e999)]}),
    ("target_empty", {"items": [item(target="")]}),
    ("target_long", {"items": [item(target="T" * 500)]}),
    ("t_ns_bool", {"t_ns": True}),
    ("t_ns_float", {"t_ns": 1.5}),
    ("t_ns_negative", {"t_ns": -1}),
    ("expires_missing", {"expires_ns": None}),
    ("loop_empty", {"loop_id": ""}),
    ("id_not_str", {"proposal_id": 7}),
    ("reason_huge", {"reason": "r" * 5000}),
    ("rollback_int", {"rollback_of": 5}),
    ("unknown_arg", {"surprise": 1}),
]


@pytest.mark.parametrize(("name", "over"), BAD_ARGS, ids=[name for name, _ in BAD_ARGS])
def test_invalid_args_get_an_invalid_args_reply(
    tmp_path: Path, name: str, over: dict[str, Any]
) -> None:
    env = make_param_env(tmp_path)
    sent = propose(env, **over)
    reply = outbox(env.root, sent["id"])
    assert reply == {"id": sent["id"], "ok": False, "result": None, "error": "invalid_args"}, name
    assert state(env)["pending_params"] == [] and env.plant.writes == []  # type: ignore[attr-defined]
    assert env.plant.params == {KP: 2.0, TI: 100.0, "FIC101.TD": 0.0}  # type: ignore[attr-defined]


def test_missing_argument_is_invalid_args(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    body = args(env)
    del body["items"]
    sent = send(env, "propose_params", body, **ENGINEER)
    reply = outbox(env.root, sent["id"])
    assert reply is not None and reply["error"] == "invalid_args"


@pytest.mark.parametrize("proposer", ["", "   ", None])
def test_blank_or_missing_proposer_is_invalid_args(tmp_path: Path, proposer: str | None) -> None:
    env = make_param_env(tmp_path)
    over: dict[str, Any] = {"proposer": proposer}
    sent = propose(env, **over)
    reply = outbox(env.root, sent["id"])
    assert reply is not None and reply["ok"] is False
    assert state(env)["pending_params"] == []

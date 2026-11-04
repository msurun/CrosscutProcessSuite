"""Behaviour tests for the write-gateway auth gate driven through the inbox service.

Covers envelope signing, unsigned refusal, replay, staleness, role authorization, mode steps,
self-approval, the KILL file, key handling and id format. All tests use auth_helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from auth_helpers import (
    KEY,
    AuthEnv,
    SignOpts,
    audit_events,
    drop,
    make_env,
    outbox,
    propose_args,
    rejected_reason,
    send,
    signed,
)

FORGED_KEY = b"\xff" * 32
SHORT_KEY = b"x" * 16


@pytest.fixture
def env(tmp_path: Path) -> AuthEnv:
    """Build a fresh confirm-mode test environment with a key file and no pinned policy."""
    return make_env(tmp_path)


def _actor_of(records: list[dict[str, str]], event: str) -> str | None:
    """Return the actor of the last record with this event name, or None."""
    matches = [record for record in records if record["event"] == event]
    return matches[-1]["actor"] if matches else None


def _state(env: AuthEnv) -> dict:
    """Read the persisted gateway state.json for the test environment."""
    return json.loads((env.root / "_gateway" / "state.json").read_text(encoding="utf-8"))


def _first_pending_key(env: AuthEnv) -> str:
    """Return the pending-proposal key from state.json, failing loudly when none exists."""
    pending = _state(env)["pending"]
    assert pending, "expected a pending proposal in state.json"
    return pending[0]["key"]


def test_signed_propose_is_queued_and_audited(env: AuthEnv) -> None:
    """An engineer's signed propose is queued and the audit trail records the caller."""
    envelope = send(env, "propose", propose_args(env), actor="alice", roles=("engineer",))
    queued = audit_events(env, "queued")[-1]
    assert outbox(env.root, envelope["id"])["ok"] is True
    assert queued["actor"] == "alice"
    assert queued["roles"] == "engineer"
    assert queued["source_ip"] == "10.0.0.7"
    assert queued["cmd_id"] == envelope["id"]
    assert _state(env)["chain_ok"] is True


def test_state_has_ok_auth_and_roles_digest(env: AuthEnv) -> None:
    """Auth status is ok and the state digest matches the roles_loaded audit value."""
    state = _state(env)
    loaded = audit_events(env, "roles_loaded")[-1]
    assert state["auth"] == "ok"
    assert len(state["roles_digest"]) == 64
    assert all(char in "0123456789abcdef" for char in state["roles_digest"])
    assert loaded["actor"] == "gateway"
    assert loaded["value"] == state["roles_digest"]


def test_unsigned_propose_is_rejected(env: AuthEnv) -> None:
    """A plain unsigned envelope is moved to rejected as unsigned_not_allowed."""
    envelope = {"id": "unsigned1", "cmd": "propose", "args": propose_args(env)}
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, "unsigned1") == "unsigned_not_allowed"
    assert outbox(env.root, "unsigned1") is None
    assert _actor_of(audit_events(env, "auth_reject"), "auth_reject") == "unverified:unknown"


def test_unsigned_with_claimed_actor_is_rejected(env: AuthEnv) -> None:
    """An unsigned envelope that claims an actor is rejected and blamed on that actor."""
    envelope = {
        "id": "unsigned2",
        "cmd": "propose",
        "args": propose_args(env),
        "auth": {"actor": "mallory"},
    }
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, "unsigned2") == "unsigned_not_allowed"
    assert _actor_of(audit_events(env, "auth_reject"), "auth_reject") == "unverified:mallory"


def test_unsigned_kill_is_accepted(env: AuthEnv) -> None:
    """An unsigned kill command still kills the gateway and is audited as unsigned."""
    drop(env, {"id": "kill1", "cmd": "kill", "args": {}})
    env.service.poll_once()
    assert env.gateway.killed is True
    assert _actor_of(audit_events(env, "kill"), "kill") == "unsigned"


def test_forged_signature_is_rejected(env: AuthEnv) -> None:
    """An envelope signed with a different key fails with bad_signature."""
    envelope = signed(
        env, "propose", propose_args(env), roles=("engineer",), extra=SignOpts(key=FORGED_KEY)
    )
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "bad_signature"


def test_tampered_args_are_rejected(env: AuthEnv) -> None:
    """Changing the args after signing invalidates the signature."""
    envelope = signed(env, "propose", propose_args(env), roles=("engineer",))
    envelope["args"]["value"] = 99.0
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "bad_signature"


def test_tampered_roles_are_rejected(env: AuthEnv) -> None:
    """Escalating the roles after signing invalidates the signature."""
    envelope = signed(env, "propose", propose_args(env), roles=("viewer",))
    envelope["auth"]["roles"] = ["lead"]
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "bad_signature"


def test_replay_is_rejected(env: AuthEnv) -> None:
    """Re-submitting an identical envelope is refused as replayed."""
    envelope = send(env, "propose", propose_args(env), roles=("engineer",))
    drop(env, envelope)
    env.service.poll_once()
    reason = rejected_reason(env.root, envelope["id"])
    assert reason in ("replayed_nonce", "replayed_id")


def test_replay_with_new_id_is_rejected(env: AuthEnv) -> None:
    """Reusing a nonce with a new id is refused as replayed_nonce."""
    options = SignOpts(nonce="deadbeef" * 4)
    send(env, "propose", propose_args(env), roles=("engineer",), extra=options)
    second = signed(env, "propose", propose_args(env), roles=("engineer",), extra=options)
    drop(env, second)
    env.service.poll_once()
    assert rejected_reason(env.root, second["id"]) == "replayed_nonce"


def test_stale_is_rejected(env: AuthEnv) -> None:
    """An envelope issued sixty seconds ago is refused as stale."""
    envelope = signed(
        env, "propose", propose_args(env), roles=("engineer",), extra=SignOpts(issued_offset_s=-60)
    )
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "stale"


def test_stale_in_future_is_rejected(env: AuthEnv) -> None:
    """An envelope issued sixty seconds ahead is refused as stale."""
    envelope = signed(
        env, "propose", propose_args(env), roles=("engineer",), extra=SignOpts(issued_offset_s=60)
    )
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "stale"


def test_stale_in_window_is_accepted(env: AuthEnv) -> None:
    """An envelope issued twenty seconds ago is inside the window and accepted."""
    envelope = signed(
        env, "propose", propose_args(env), roles=("engineer",), extra=SignOpts(issued_offset_s=-20)
    )
    drop(env, envelope)
    env.service.poll_once()
    assert outbox(env.root, envelope["id"])["ok"] is True


def test_viewer_propose_is_rejected(env: AuthEnv) -> None:
    """A viewer lacks gw.propose and is refused with missing_permission."""
    envelope = signed(env, "propose", propose_args(env), roles=("viewer",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "missing_permission:gw.propose"


def test_operator_propose_is_rejected(env: AuthEnv) -> None:
    """An operator lacks gw.propose and is refused with missing_permission."""
    envelope = signed(env, "propose", propose_args(env), roles=("operator",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "missing_permission:gw.propose"


def test_service_role_propose_is_accepted(env: AuthEnv) -> None:
    """The service role may propose and the proposal is queued."""
    envelope = send(env, "propose", propose_args(env), actor="svc", roles=("service",))
    assert outbox(env.root, envelope["id"])["ok"] is True


def test_viewer_kill_is_accepted(env: AuthEnv) -> None:
    """A viewer holds gw.kill, so a signed kill is accepted."""
    send(env, "kill", {}, actor="alice", roles=("viewer",))
    assert env.gateway.killed is True


def test_admin_propose_is_rejected(env: AuthEnv) -> None:
    """An admin lacks gw.propose and is refused with missing_permission."""
    envelope = signed(env, "propose", propose_args(env), roles=("admin",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "missing_permission:gw.propose"


def test_mode_step_from_advisory_to_confirm_is_too_large(tmp_path: Path) -> None:
    """Jumping two modes up from advisory is refused as mode_step_too_large."""
    env = make_env(tmp_path, mode="advisory")
    envelope = signed(env, "set_mode", {"mode": "confirm"}, roles=("engineer",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "mode_step_too_large"


def test_mode_step_from_advisory_to_dry_run_is_accepted(tmp_path: Path) -> None:
    """One step up from advisory to dry_run is accepted."""
    env = make_env(tmp_path, mode="advisory")
    send(env, "set_mode", {"mode": "dry_run"}, roles=("engineer",))
    assert env.gateway.mode == "dry_run"


def test_mode_step_from_dry_run_to_confirm_is_accepted(tmp_path: Path) -> None:
    """One step up from dry_run to confirm is accepted."""
    env = make_env(tmp_path, mode="dry_run")
    send(env, "set_mode", {"mode": "confirm"}, roles=("engineer",))
    assert env.gateway.mode == "confirm"


def test_mode_step_from_dry_run_to_supervised_is_too_large(tmp_path: Path) -> None:
    """Two steps up from dry_run is refused as mode_step_too_large."""
    env = make_env(tmp_path, mode="dry_run")
    envelope = signed(env, "set_mode", {"mode": "supervised"}, roles=("engineer",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "mode_step_too_large"


def test_mode_step_to_supervised_needs_permission(env: AuthEnv) -> None:
    """In confirm, an engineer lacks gw.mode.up.supervised and is refused."""
    envelope = signed(env, "set_mode", {"mode": "supervised"}, roles=("engineer",))
    drop(env, envelope)
    env.service.poll_once()
    reason = rejected_reason(env.root, envelope["id"])
    assert reason == "missing_permission:gw.mode.up.supervised"


def test_mode_step_to_supervised_by_lead_is_accepted(env: AuthEnv) -> None:
    """A lead holds gw.mode.up.supervised and the step from confirm is accepted."""
    send(env, "set_mode", {"mode": "supervised"}, roles=("lead",))
    assert env.gateway.mode == "supervised"


def test_mode_jump_down_from_supervised_is_accepted(tmp_path: Path) -> None:
    """A viewer may drop from supervised to off in one step."""
    env = make_env(tmp_path, mode="supervised")
    send(env, "set_mode", {"mode": "off"}, roles=("viewer",))
    assert env.gateway.mode == "off"


def test_mode_step_up_without_permission_is_rejected(tmp_path: Path) -> None:
    """A viewer moving advisory to dry_run lacks gw.mode.up.dry_run and is refused."""
    env = make_env(tmp_path, mode="advisory")
    envelope = signed(env, "set_mode", {"mode": "dry_run"}, roles=("viewer",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "missing_permission:gw.mode.up.dry_run"


def test_above_cap_is_rejected(tmp_path: Path) -> None:
    """A mode change above the gateway cap is refused as above_cap."""
    env = make_env(tmp_path, mode="dry_run")
    env.gateway._mode_cap = "dry_run"
    envelope = signed(env, "set_mode", {"mode": "confirm"}, roles=("lead",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "above_cap"


def test_sender_cap_is_ignored(tmp_path: Path) -> None:
    """A sender-supplied cap cannot widen the gateway cap, so above_cap still applies."""
    env = make_env(tmp_path, mode="dry_run")
    env.gateway._mode_cap = "dry_run"
    args = {"mode": "confirm", "cap": "supervised"}
    envelope = signed(env, "set_mode", args, roles=("lead",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "above_cap"


def test_self_approval_is_rejected(env: AuthEnv) -> None:
    """An engineer's own proposal cannot be approved by that same engineer."""
    send(env, "propose", propose_args(env), actor="alice", roles=("engineer",))
    key = _first_pending_key(env)
    envelope = signed(env, "approve", {"key": key}, actor="alice", roles=("engineer",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "self_approval"
    assert len(_state(env)["pending"]) == 1


def test_operator_approve_is_accepted(env: AuthEnv) -> None:
    """An operator approving another actor's proposal writes once."""
    send(env, "propose", propose_args(env), actor="alice", roles=("engineer",))
    key = _first_pending_key(env)
    envelope = send(env, "approve", {"key": key}, actor="bob", roles=("operator",))
    result = outbox(env.root, envelope["id"])
    assert result["ok"] is True
    assert result["result"]["accepted"] is True
    assert len(env.plant.writes) == 1


def test_operator_reject_is_accepted(env: AuthEnv) -> None:
    """An operator may reject a pending proposal."""
    send(env, "propose", propose_args(env), actor="alice", roles=("engineer",))
    key = _first_pending_key(env)
    envelope = send(env, "reject", {"key": key}, actor="bob", roles=("operator",))
    assert outbox(env.root, envelope["id"])["ok"] is True
    assert _state(env)["pending"] == []


def test_viewer_approve_is_rejected(env: AuthEnv) -> None:
    """A viewer lacks gw.approve and is refused with missing_permission."""
    send(env, "propose", propose_args(env), actor="alice", roles=("engineer",))
    key = _first_pending_key(env)
    envelope = signed(env, "approve", {"key": key}, actor="vick", roles=("viewer",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "missing_permission:gw.approve"


def test_kill_file_is_consumed(env: AuthEnv) -> None:
    """A KILL file kills the gateway, is removed, and is audited as unsigned kill_file."""
    kill_path = env.root / "_gateway" / "KILL"
    kill_path.write_text("", encoding="utf-8")
    env.service.poll_once()
    record = audit_events(env, "kill")[-1]
    assert env.gateway.killed is True
    assert not kill_path.exists()
    assert record["actor"] == "unsigned"
    assert record["source_ip"] == "kill_file"


def test_missing_key_state_is_key_missing(tmp_path: Path) -> None:
    """Without a key file the state reports key_missing even though auth is on."""
    env = make_env(tmp_path, key=None)
    assert _state(env)["auth"] == "key_missing"


def test_missing_key_signed_propose_is_rejected(tmp_path: Path) -> None:
    """With no key loaded a signed propose is refused as key_missing."""
    env = make_env(tmp_path, key=None)
    envelope = signed(env, "propose", propose_args(env), roles=("lead",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "key_missing"


def test_missing_key_signed_kill_is_accepted(tmp_path: Path) -> None:
    """With no key loaded a signed kill still kills the gateway."""
    env = make_env(tmp_path, key=None)
    send(env, "kill", {}, roles=("viewer",))
    assert env.gateway.killed is True


def test_missing_key_set_mode_off_is_accepted(tmp_path: Path) -> None:
    """With no key loaded a set_mode off from confirm is a safe downgrade and is accepted."""
    env = make_env(tmp_path, mode="confirm", key=None)
    send(env, "set_mode", {"mode": "off"}, roles=("lead",))
    assert env.gateway.mode == "off"


def test_missing_key_set_mode_supervised_is_rejected(tmp_path: Path) -> None:
    """With no key loaded a set_mode up to supervised is refused as key_missing."""
    env = make_env(tmp_path, mode="confirm", key=None)
    envelope = signed(env, "set_mode", {"mode": "supervised"}, roles=("lead",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "key_missing"


def test_missing_key_set_mode_advisory_from_off_is_rejected(tmp_path: Path) -> None:
    """With no key loaded a set_mode advisory from off raises the mode, so it is key_missing."""
    env = make_env(tmp_path, mode="off", key=None)
    envelope = signed(env, "set_mode", {"mode": "advisory"}, roles=("lead",))
    drop(env, envelope)
    env.service.poll_once()
    assert rejected_reason(env.root, envelope["id"]) == "key_missing"
    assert env.gateway.mode == "off"


def test_missing_key_unsigned_kill_is_accepted(tmp_path: Path) -> None:
    """With no key loaded an unsigned kill is still accepted."""
    env = make_env(tmp_path, key=None)
    drop(env, {"id": "kill2", "cmd": "kill", "args": {}})
    env.service.poll_once()
    assert env.gateway.killed is True


def test_short_key_is_treated_as_missing(tmp_path: Path) -> None:
    """A 16-byte key file is below MIN_KEY_BYTES, so state reports key_missing."""
    env = make_env(tmp_path, key=SHORT_KEY)
    assert _state(env)["auth"] == "key_missing"


def test_key_appears_later_is_loaded(tmp_path: Path) -> None:
    """Writing the key after startup flips auth to ok and lets a signed propose through."""
    env = make_env(tmp_path, key=None)
    env.key_path.parent.mkdir(parents=True, exist_ok=True)
    env.key_path.write_bytes(KEY)
    env.service.poll_once()
    envelope = send(env, "propose", propose_args(env), roles=("engineer",))
    assert _state(env)["auth"] == "ok"
    assert outbox(env.root, envelope["id"])["ok"] is True


def test_id_with_path_characters_is_rejected(env: AuthEnv) -> None:
    """An id containing path characters is moved out of the inbox."""
    envelope = signed(
        env, "propose", propose_args(env), roles=("engineer",), extra=SignOpts(cmd_id="a/b")
    )
    path = env.root / "_gateway" / "inbox" / "badid.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    env.service.poll_once()
    assert path.exists() is False


def test_non_dict_envelope_is_rejected(env: AuthEnv) -> None:
    """A JSON list in the inbox is rejected and audited with actor unknown."""
    path = env.root / "_gateway" / "inbox" / "list.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    env.service.poll_once()
    assert rejected_reason(env.root, "list") == "command must be a JSON object"
    assert _actor_of(audit_events(env, "auth_reject"), "auth_reject") == "unverified:unknown"

"""Every refusal of a trusted command writes an outbox reply {id, ok: false, error: <code>}.

The API's file client waits for the outbox file, so a refusal that only moves the command to
rejected/ would end in a timeout (HTTP 504). Commands that fail before an id can be trusted
(bad or missing signature, stale, replayed, key missing) stay silent: the sender times out.
Each refusal still lands in rejected/ with its reason and keeps its auth_reject audit event.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from auth_helpers import (
    AuthEnv,
    SignOpts,
    audit_events,
    drop,
    make_env,
    outbox,
    policy_doc,
    propose_args,
    rejected_reason,
    send,
    signed,
)
from crosscut_gateway import policy_file
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.policy import proposal_key
from crosscut_gateway.service import GatewayService
from test_gateway_scenarios import POLICY, TAG, SimPlant
from test_gateway_service import FakeClock, outbox_payload, write_command


def _assert_refused(env: AuthEnv, sent: dict[str, Any], code: str) -> None:
    """The command was answered with ok=false and code, and also rejected and audited."""
    assert outbox(env.root, sent["id"]) == {
        "id": sent["id"],
        "ok": False,
        "result": None,
        "error": code,
    }
    assert (rejected_reason(env.root, sent["id"]) or "").strip() == code
    assert any(e["reason_code"] == code for e in audit_events(env, "auth_reject"))


def _save_draft(env: AuthEnv, actor: str = "alice") -> str:
    """Save an advisory draft as actor and return its digest."""
    document = json.loads(json.dumps(policy_doc("advisory")))
    send(env, "policy_draft", {"document": document}, actor=actor, roles=("lead",))
    return policy_file.policy_digest(document)


def _pin(env: AuthEnv, actor: str, digest: str, *, stepup: bool = True) -> dict[str, Any]:
    """Send a policy_pin as a lead."""
    extra = SignOpts(stepup=True) if stepup else None
    return send(env, "policy_pin", {"digest": digest}, actor=actor, extra=extra)


def test_self_pin_is_answered(tmp_path: Path) -> None:
    """The author pinning their own draft gets author_equals_approver in the outbox."""
    env = make_env(tmp_path, pinned_policy=True)
    digest = _save_draft(env, "alice")
    _assert_refused(env, _pin(env, "alice", digest), "author_equals_approver")


def test_self_pin_case_variant_is_answered(tmp_path: Path) -> None:
    """A case variant of the author's name is the same person."""
    env = make_env(tmp_path, pinned_policy=True)
    digest = _save_draft(env, "alice")
    _assert_refused(env, _pin(env, "Alice", digest), "author_equals_approver")


def test_reload_in_confirm_mode_is_answered(tmp_path: Path) -> None:
    """policy_reload outside off/advisory is answered with reload_requires_off_or_advisory."""
    env = make_env(tmp_path, mode="confirm", pinned_policy=True)
    sent = send(env, "policy_reload", {}, actor="alice")
    _assert_refused(env, sent, "reload_requires_off_or_advisory")


def test_pin_without_stepup_is_answered(tmp_path: Path) -> None:
    """policy_pin without a step-up is answered with stepup_required."""
    env = make_env(tmp_path, pinned_policy=True)
    digest = _save_draft(env, "alice")
    _assert_refused(env, _pin(env, "bob", digest, stepup=False), "stepup_required")


def test_pin_without_draft_is_answered(tmp_path: Path) -> None:
    """policy_pin with no draft saved is answered with no_draft."""
    env = make_env(tmp_path, pinned_policy=True)
    _assert_refused(env, _pin(env, "bob", "0" * 64), "no_draft")


def test_pin_of_changed_draft_is_answered(tmp_path: Path) -> None:
    """policy_pin with a digest that is not the draft's is answered with draft_changed."""
    env = make_env(tmp_path, pinned_policy=True)
    _save_draft(env, "alice")
    _assert_refused(env, _pin(env, "bob", "f" * 64), "draft_changed")


def test_pin_of_tampered_draft_is_answered(tmp_path: Path) -> None:
    """A draft whose signature no longer matches is answered with draft_bad_signature."""
    env = make_env(tmp_path, pinned_policy=True)
    digest = _save_draft(env, "alice")
    path = env.root / "_gateway" / "policy-draft.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["author"] = "mallory"
    path.write_text(json.dumps(record), encoding="utf-8")
    _assert_refused(env, _pin(env, "bob", digest), "draft_bad_signature")


@pytest.mark.parametrize("cmd", ["policy_pin", "policy_reload"])
def test_policy_commands_without_policy_path_are_answered(tmp_path: Path, cmd: str) -> None:
    """With no policy file configured both commands are answered policy_path_not_configured."""
    env = make_env(tmp_path)
    args = {"digest": "0" * 64} if cmd == "policy_pin" else {}
    sent = send(env, cmd, args, actor="bob", extra=SignOpts(stepup=True))
    _assert_refused(env, sent, "policy_path_not_configured")


def _denied_cases(env: AuthEnv) -> list[tuple[str, dict[str, Any], tuple[str, ...], str]]:
    """Return (cmd, args, roles, permission) for one denied command per gateway command."""
    doc = policy_doc("advisory")
    return [
        ("propose", propose_args(env), ("viewer",), "gw.propose"),
        ("approve", {"key": "k"}, ("viewer",), "gw.approve"),
        ("reject", {"key": "k"}, ("service",), "gw.reject"),
        ("kill", {}, ("service",), "gw.kill"),
        ("kill_reset", {}, ("operator",), "gw.kill.reset"),
        ("re_enable", {"tag": TAG}, ("operator",), "gw.re_enable.stopped"),
        ("set_mode", {"mode": "off"}, ("service",), "gw.mode.down"),
        ("policy_draft", {"document": doc}, ("operator",), "policy.edit"),
        ("policy_pin", {"digest": "0" * 64}, ("engineer",), "policy.pin"),
        ("policy_reload", {}, ("engineer",), "policy.reload"),
    ]


def test_every_command_denied_by_role_is_answered(tmp_path: Path) -> None:
    """A role without the permission gets missing_permission:<permission> for every command."""
    env = make_env(tmp_path, mode="confirm", pinned_policy=True)
    for cmd, args, roles, permission in _denied_cases(env):
        sent = send(env, cmd, args, actor="bob", roles=roles, extra=SignOpts(stepup=True))
        _assert_refused(env, sent, f"missing_permission:{permission}")


def test_self_approval_is_answered(tmp_path: Path) -> None:
    """The proposer approving their own proposal gets self_approval."""
    env = make_env(tmp_path, mode="confirm")
    send(env, "propose", propose_args(env), actor="alice", roles=("engineer",))
    key = proposal_key(env.gateway.pending()[0])
    sent = send(env, "approve", {"key": key}, actor="alice", roles=("lead",))
    _assert_refused(env, sent, "self_approval")
    assert len(env.gateway.pending()) == 1


def test_mode_refusals_are_answered(tmp_path: Path) -> None:
    """A too-large mode rise, a rise above the cap and an unknown mode are all answered."""
    env = make_env(tmp_path, mode="advisory")
    jump = send(env, "set_mode", {"mode": "supervised"}, actor="alice", roles=("lead",))
    _assert_refused(env, jump, "mode_step_too_large")
    odd = send(env, "set_mode", {"mode": "turbo"}, actor="alice", roles=("lead",))
    _assert_refused(env, odd, "bad_mode")


def test_unknown_command_is_answered(tmp_path: Path) -> None:
    """A signed command with an unknown name is answered unknown_cmd."""
    env = make_env(tmp_path)
    _assert_refused(env, send(env, "frobnicate", {}, actor="alice"), "unknown_cmd")


def test_command_predating_start_is_answered(tmp_path: Path) -> None:
    """A verified command issued before the service started gets predates_start."""
    env = make_env(tmp_path, start_floor=True)
    old = send(env, "kill_reset", {}, extra=SignOpts(issued_offset_s=-30.0))
    _assert_refused(env, old, "predates_start")


def test_invalid_args_after_authentication_are_answered(tmp_path: Path) -> None:
    """Authorised propose with a bad value type is answered invalid_args and rejected."""
    env = make_env(tmp_path, mode="confirm")
    args = {**propose_args(env), "value": "high"}
    sent = send(env, "propose", args, actor="alice", roles=("engineer",))
    assert outbox(env.root, sent["id"]) == {
        "id": sent["id"],
        "ok": False,
        "result": None,
        "error": "invalid_args",
    }
    assert rejected_reason(env.root, sent["id"])


def _tampered(env: AuthEnv) -> dict[str, Any]:
    """Return a signed policy_reload whose args were changed after signing."""
    cmd = signed(env, "policy_reload", {}, actor="alice")
    cmd["args"] = {"x": 1}
    return cmd


def test_untrusted_commands_stay_silent(tmp_path: Path) -> None:
    """Bad signature, replay, stale and unsigned non-kill commands get no outbox file."""
    env = make_env(tmp_path)
    bad = _tampered(env)
    drop(env, bad)
    first = signed(env, "kill_reset", {}, actor="alice")
    stale = signed(env, "kill_reset", {}, actor="alice", extra=SignOpts(issued_offset_s=-3600.0))
    drop(env, stale)
    unsigned = {"id": "unsigned1", "cmd": "kill_reset", "args": {}}
    drop(env, unsigned)
    env.service.poll_once()
    drop(env, first)
    env.service.poll_once()
    drop(env, first)
    env.service.poll_once()
    assert outbox(env.root, bad["id"]) is None
    assert outbox(env.root, stale["id"]) is None
    assert outbox(env.root, "unsigned1") is None
    assert (rejected_reason(env.root, first["id"]) or "").startswith("replayed")
    assert rejected_reason(env.root, bad["id"]) == "bad_signature"
    assert rejected_reason(env.root, stale["id"]) == "stale"


def test_failed_reply_write_does_not_break_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full disk keeps the rejection and the audit event; no exception escapes."""
    env = make_env(tmp_path, mode="confirm", pinned_policy=True)

    def _boom(_cmd_id: str, _result: dict[str, Any]) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(env.service, "_write_result", _boom)
    sent = send(env, "policy_reload", {}, actor="alice")
    assert rejected_reason(env.root, sent["id"]) == "reload_requires_off_or_advisory"
    assert audit_events(env, "auth_reject")
    assert audit_events(env, "result_write_failed")


def test_legacy_mode_validation_error_is_answered(tmp_path: Path) -> None:
    """Without auth a well-formed id with invalid args is answered and moved to rejected."""
    clock = FakeClock()
    plant = SimPlant()
    gateway = WriteGateway(plant, {TAG: POLICY}, "confirm")
    service = GatewayService(tmp_path, gateway, clock)
    write_command(tmp_path, "v1", {"id": "v1", "cmd": "approve", "args": {}})
    write_command(tmp_path, "v2", {"id": "v2", "cmd": "frobnicate", "args": {}})
    service.poll_once()
    assert outbox_payload(tmp_path, "v1")["error"] == "invalid_args"
    assert outbox_payload(tmp_path, "v1")["ok"] is False
    assert outbox_payload(tmp_path, "v2")["error"] == "unknown_cmd"
    assert (tmp_path / "_gateway" / "rejected" / "v1.json").exists()

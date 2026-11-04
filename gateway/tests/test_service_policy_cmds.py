"""Gateway kill-reset, policy draft, pin and reload commands through the inbox service.

Each command is signed, dropped into the inbox and polled, then checked against the outbox,
the rejected folder, the policy and pin files, the gateway state and the audit log.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from auth_helpers import (
    KEY,
    AuthEnv,
    SignOpts,
    audit_events,
    make_env,
    outbox,
    policy_doc,
    rejected_reason,
    send,
)
from crosscut_gateway import policy_pin
from test_gateway_scenarios import TAG


def _reason(env: AuthEnv, envelope: dict) -> str:
    """Return the rejection reason for an envelope, or an empty string when not rejected."""
    return (rejected_reason(env.root, envelope["id"]) or "").strip()


def _kill_then_reset(env: AuthEnv) -> None:
    """Kill the gateway as an engineer, then reset it as a lead."""
    send(env, "kill", {}, roles=("engineer",))
    send(env, "kill_reset", {}, roles=("lead",))


def _draft_path(env: AuthEnv) -> Path:
    """Return the path of the saved policy draft."""
    return env.root / "_gateway" / "policy-draft.json"


def _save_draft(env: AuthEnv, document: object = None) -> dict:
    """Save a draft as the lead alice and return the envelope."""
    if document is None:
        document = policy_doc("advisory")
    return send(env, "policy_draft", {"document": document}, actor="alice", roles=("lead",))


def _json_advisory_doc(extra_tags: tuple[str, ...] = ()) -> dict:
    """Return the advisory policy document as it reads back from JSON (lists, not tuples)."""
    return json.loads(json.dumps(policy_doc("advisory", extra_tags)))


def _pin(
    env: AuthEnv,
    actor: str,
    *,
    stepup: bool = True,
    roles: tuple[str, ...] = ("lead",),
) -> dict:
    """Send a policy_pin command as ``actor``, with or without a step-up."""
    extra = SignOpts(stepup=True) if stepup else None
    return send(env, "policy_pin", {}, actor=actor, roles=roles, extra=extra)


def _pinned_with_draft(tmp_path: Path) -> AuthEnv:
    """Build a pinned confirm-mode gateway with an advisory draft saved by alice."""
    env = make_env(tmp_path, pinned_policy=True)
    _save_draft(env)
    return env


def test_lead_kill_reset_clears_kill_and_stops_target(tmp_path: Path) -> None:
    """A lead's kill_reset succeeds, clears the kill flag and leaves the target stopped."""
    env = make_env(tmp_path, mode="supervised")
    send(env, "kill", {}, roles=("engineer",))
    envelope = send(env, "kill_reset", {}, roles=("lead",))
    assert outbox(env.root, envelope["id"])["ok"] is True
    assert env.gateway.killed is False
    assert env.gateway.target_state(TAG) == "stopped:kill"
    assert audit_events(env, "kill_reset")


def test_kill_reset_from_supervised_drops_to_advisory(tmp_path: Path) -> None:
    """A kill reset from supervised mode leaves the gateway in advisory mode."""
    env = make_env(tmp_path, mode="supervised")
    _kill_then_reset(env)
    assert env.gateway.mode == "advisory"


def test_engineer_kill_reset_is_refused(tmp_path: Path) -> None:
    """An engineer without gw.kill.reset is refused and the gateway stays killed."""
    env = make_env(tmp_path, mode="supervised")
    send(env, "kill", {}, roles=("engineer",))
    envelope = send(env, "kill_reset", {}, roles=("engineer",))
    assert _reason(env, envelope) == "missing_permission:gw.kill.reset"
    assert env.gateway.killed is True


def test_operator_re_enable_of_stopped_target_is_refused(tmp_path: Path) -> None:
    """An operator cannot re-enable a target stopped by a kill reset."""
    env = make_env(tmp_path, mode="supervised")
    _kill_then_reset(env)
    envelope = send(env, "re_enable", {"tag": TAG}, roles=("operator",))
    assert _reason(env, envelope) == "missing_permission:gw.re_enable.stopped"
    assert env.gateway.target_state(TAG) == "stopped:kill"


def test_engineer_re_enable_of_stopped_target_enables_it(tmp_path: Path) -> None:
    """An engineer re-enables a target stopped by a kill reset and the outbox reports ok."""
    env = make_env(tmp_path, mode="supervised")
    _kill_then_reset(env)
    envelope = send(env, "re_enable", {"tag": TAG}, roles=("engineer",))
    assert outbox(env.root, envelope["id"])["ok"] is True
    assert env.gateway.target_state(TAG) == "enabled"


def test_policy_draft_leaves_live_policy_and_pin_untouched(tmp_path: Path) -> None:
    """Saving a draft does not change the live policy file or its pin."""
    env = make_env(tmp_path, pinned_policy=True)
    pin_path = policy_pin.pin_path_for(env.policy_path)
    policy_bytes = env.policy_path.read_bytes()
    pin_bytes = pin_path.read_bytes()
    _save_draft(env)
    assert env.policy_path.read_bytes() == policy_bytes
    assert pin_path.read_bytes() == pin_bytes


def test_policy_draft_records_document_author_and_time(tmp_path: Path) -> None:
    """The saved draft holds the document, the author alice and a saved_at timestamp."""
    env = make_env(tmp_path, pinned_policy=True)
    _save_draft(env)
    draft = json.loads(_draft_path(env).read_text(encoding="utf-8"))
    assert draft["document"] == _json_advisory_doc()
    assert draft["author"] == "alice"
    assert "saved_at" in draft
    assert datetime.fromisoformat(draft["saved_at"]).tzinfo is not None


def test_operator_policy_draft_is_refused(tmp_path: Path) -> None:
    """An operator without policy.edit cannot save a draft."""
    env = make_env(tmp_path, pinned_policy=True)
    envelope = send(
        env, "policy_draft", {"document": policy_doc("advisory")}, roles=("operator",)
    )
    assert _reason(env, envelope) == "missing_permission:policy.edit"
    assert not _draft_path(env).exists()


def test_invalid_policy_document_writes_no_draft(tmp_path: Path) -> None:
    """A document that fails schema validation is refused and no draft file is written."""
    env = make_env(tmp_path, pinned_policy=True)
    envelope = _save_draft(env, {"version": 1})
    assert outbox(env.root, envelope["id"])["ok"] is False
    assert not _draft_path(env).exists()


def test_non_object_policy_document_is_rejected_with_reason(tmp_path: Path) -> None:
    """A document that is not a JSON object is refused with a reason naming the document."""
    env = make_env(tmp_path, pinned_policy=True)
    envelope = _save_draft(env, "not an object")
    reason = _reason(env, envelope)
    assert reason
    assert "document" in reason


def test_pin_without_stepup_is_refused(tmp_path: Path) -> None:
    """A second signer without a step-up cannot pin the draft."""
    env = _pinned_with_draft(tmp_path)
    envelope = _pin(env, "bob", stepup=False)
    assert _reason(env, envelope) == "stepup_required"


def test_pin_by_draft_author_is_refused_and_audited(tmp_path: Path) -> None:
    """The draft author cannot approve their own pin, and the refusal is audited."""
    env = _pinned_with_draft(tmp_path)
    envelope = _pin(env, "alice")
    assert _reason(env, envelope) == "author_equals_approver"
    assert audit_events(env, "auth_reject")


def test_second_signer_pin_writes_policy_and_verifiable_pin(tmp_path: Path) -> None:
    """Pinning by a second signer writes the draft as the policy and a verifiable pin."""
    env = _pinned_with_draft(tmp_path)
    envelope = _pin(env, "bob")
    result = outbox(env.root, envelope["id"])
    assert result["ok"] is True
    assert json.loads(env.policy_path.read_text(encoding="utf-8")) == _json_advisory_doc()
    assert policy_pin.verify_pin(env.policy_path, KEY) == result["result"]["digest"]
    pin_path = policy_pin.pin_path_for(env.policy_path)
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    assert (pin["author"], pin["approver"]) == ("alice", "bob")


def test_engineer_pin_is_refused(tmp_path: Path) -> None:
    """An engineer without policy.pin cannot pin, even with a step-up."""
    env = _pinned_with_draft(tmp_path)
    envelope = _pin(env, "bob", roles=("engineer",))
    assert _reason(env, envelope) == "missing_permission:policy.pin"


def test_pin_without_draft_is_refused(tmp_path: Path) -> None:
    """Pinning when no draft has been saved is refused as no_draft."""
    env = make_env(tmp_path, pinned_policy=True)
    envelope = _pin(env, "bob")
    assert _reason(env, envelope) == "no_draft"


def _advisory_pinned_env(tmp_path: Path) -> AuthEnv:
    """Build a pinned gateway and move it to advisory mode so a reload is allowed."""
    env = make_env(tmp_path, pinned_policy=True)
    send(env, "set_mode", {"mode": "advisory"}, roles=("lead",))
    return env


def test_reload_in_confirm_mode_is_refused(tmp_path: Path) -> None:
    """A reload while the gateway is in confirm mode is refused."""
    env = make_env(tmp_path, pinned_policy=True)
    envelope = send(env, "policy_reload", {}, roles=("lead",))
    assert _reason(env, envelope) == "reload_requires_off_or_advisory"


def test_reload_in_advisory_swaps_policy_and_audits(tmp_path: Path) -> None:
    """A reload in advisory mode loads the newly pinned policy and audits its digest."""
    env = _advisory_pinned_env(tmp_path)
    _save_draft(env, _json_advisory_doc(extra_tags=("FIC102.SP",)))
    _pin(env, "bob")
    envelope = send(env, "policy_reload", {}, roles=("lead",))
    result = outbox(env.root, envelope["id"])
    assert result["ok"] is True
    assert env.gateway.target_state("FIC102.SP") == "enabled"
    events = audit_events(env, "policy_reload")
    assert events[-1]["value"] == result["result"]["digest"]


def test_engineer_reload_is_refused(tmp_path: Path) -> None:
    """An engineer without policy.reload cannot reload the policy."""
    env = _advisory_pinned_env(tmp_path)
    envelope = send(env, "policy_reload", {}, roles=("engineer",))
    assert _reason(env, envelope) == "missing_permission:policy.reload"


def test_reload_of_tampered_policy_fails_digest_check(tmp_path: Path) -> None:
    """A reload after the policy bytes change fails with digest_mismatch and keeps status."""
    env = _advisory_pinned_env(tmp_path)
    before = env.gateway.status()
    env.policy_path.write_bytes(env.policy_path.read_bytes() + b"\n")
    envelope = send(env, "policy_reload", {}, roles=("lead",))
    result = outbox(env.root, envelope["id"])
    assert result["ok"] is False
    assert result["error"] == "digest_mismatch"
    assert env.gateway.status() == before


def test_reload_with_deleted_pin_fails(tmp_path: Path) -> None:
    """A reload after the pin file is deleted fails with pin_missing."""
    env = _advisory_pinned_env(tmp_path)
    policy_pin.pin_path_for(env.policy_path).unlink()
    envelope = send(env, "policy_reload", {}, roles=("lead",))
    result = outbox(env.root, envelope["id"])
    assert result["ok"] is False
    assert result["error"] == "pin_missing"


def test_reload_with_pin_signed_by_wrong_key_fails(tmp_path: Path) -> None:
    """A pin re-signed with a different key fails verification with bad_signature."""
    env = _advisory_pinned_env(tmp_path)
    wrong_key = b"\x07" * 32
    policy_pin.create_pin(
        env.policy_path,
        wrong_key,
        policy_pin.PinSigners("alice", "bob"),
        now=datetime.now(UTC),
    )
    envelope = send(env, "policy_reload", {}, roles=("lead",))
    result = outbox(env.root, envelope["id"])
    assert result["ok"] is False
    assert result["error"] == "bad_signature"

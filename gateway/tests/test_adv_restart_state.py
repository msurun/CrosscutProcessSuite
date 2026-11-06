"""Adversarial restart state and crash recovery test suite for Write Gateway.

Evaluates persistence across restarts: kill latch retention, replay protection, corrupt state
and audit file recovery, and two-person policy pinning against file swapping attacks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from auth_helpers import (
    KEY,
    AuthEnv,
    drop,
    make_env,
    outbox,
    policy_doc,
    propose_args,
    rejected_reason,
    send,
    signed,
)
from crosscut_gateway import audit, engine, latch_store, policy_file, policy_pin
from crosscut_gateway import service as gateway_service
from crosscut_gateway.policy_cmds import PolicyPaths


def _recreate_service(
    env: AuthEnv, gw: engine.WriteGateway | None = None
) -> tuple[engine.WriteGateway, gateway_service.GatewayService]:
    """In plain words: Construct a fresh gateway and service instance over an existing root."""
    target_gw = gw or engine.WriteGateway(env.plant, env.gateway._policies, "confirm")
    opts = gateway_service.ServiceOptions(
        auth_required=True,
        key_path=env.key_path,
        policy_path=env.policy_path,
        enforce_start_floor=False,
    )
    svc = gateway_service.GatewayService(
        env.root,
        target_gw,
        clock=env.clock,
        options=opts,
    )
    return target_gw, svc


def test_kill_latch_survives_restart_and_blocks_proposals(tmp_path: Path) -> None:
    """In plain words: Persisted KILLED latch must survive crash/restart and keep writes locked."""
    env = make_env(tmp_path, mode="confirm")

    # Trigger kill latch
    send(env, "kill", {}, actor="alice", roles=("lead",))
    assert env.gateway.killed is True
    assert latch_store.kill_latch_present(env.root / "_gateway") is True

    # Crash & restart: new gateway and service over same root
    new_gw, new_svc = _recreate_service(env)
    assert new_gw.killed is True, "Restarted gateway failed to restore killed latch state!"

    # Send proposal to restarted gateway; must be refused due to killed state
    prop_env = signed(env, "propose", propose_args(env, 55.0), actor="alice", roles=("engineer",))
    drop(env, prop_env)
    new_svc.poll_once()

    result = outbox(env.root, prop_env["id"])
    assert result is not None
    assert result["result"]["accepted"] is False
    assert result["result"]["reason_code"] == "killed"

    # Reset kill latch with signed command by lead
    reset_env = signed(env, "kill_reset", {}, actor="alice", roles=("lead",))
    drop(env, reset_env)
    new_svc.poll_once()

    assert new_gw.killed is False
    assert latch_store.kill_latch_present(env.root / "_gateway") is False
    assert new_gw.mode == "advisory"


def test_nonce_replay_across_restart_is_refused(tmp_path: Path) -> None:
    """In plain words: Nonce cache persisted to disk prevents replay of envelopes after restart."""
    env = make_env(tmp_path, mode="confirm")

    # Send and accept a valid envelope
    first_env = send(env, "propose", propose_args(env, 55.0), actor="alice", roles=("engineer",))
    assert outbox(env.root, first_env["id"])["ok"] is True

    # Crash & restart over same root
    _, new_svc = _recreate_service(env)

    # Attempt replaying the exact same envelope
    drop(env, first_env)
    new_svc.poll_once()

    reason = rejected_reason(env.root, first_env["id"])
    assert reason in ("replayed_nonce", "replayed_id"), f"Expected replay refusal, got: {reason}"


def test_corrupt_nonce_cache_on_restart_starts_safely(tmp_path: Path) -> None:
    """In plain words: Corrupt nonce cache file does not crash startup and service recovers."""
    env = make_env(tmp_path, mode="confirm")
    (env.root / "_gateway" / latch_store.NONCE_NAME).write_text("{corrupt", encoding="utf-8")

    new_gw, new_svc = _recreate_service(env)
    new_svc.poll_once()
    assert new_gw.mode == "confirm"


def test_corrupt_killed_latch_on_restart_starts_safely(tmp_path: Path) -> None:
    """In plain words: Corrupt KILLED file fails closed into the safe killed state on startup."""
    env = make_env(tmp_path, mode="confirm")
    (env.root / "_gateway" / latch_store.KILLED_NAME).write_text("not_valid_json", encoding="utf-8")

    new_gw, new_svc = _recreate_service(env)
    assert new_gw.killed is True


def test_corrupt_policy_draft_on_restart_refuses_pin(tmp_path: Path) -> None:
    """In plain words: Corrupt policy draft file fails closed when a lead attempts to pin it."""
    env = make_env(tmp_path, mode="confirm", pinned_policy=True)
    (env.root / "_gateway" / "policy-draft.json").write_text("{broken", encoding="utf-8")

    _, new_svc = _recreate_service(env)
    pin_env = signed(
        env,
        "policy_pin",
        {"digest": "d" * 64},
        actor="bob",
        roles=("lead",),
    )
    # Add stepup flag to auth block
    pin_env["auth"]["stepup"] = True
    from crosscut_gateway.envelope import sign_envelope

    pin_env.pop("sig", None)
    pin_env = sign_envelope(pin_env, KEY)

    drop(env, pin_env)
    new_svc.poll_once()
    assert rejected_reason(env.root, pin_env["id"]) == "no_draft"


def test_corrupt_state_json_overwritten_cleanly(tmp_path: Path) -> None:
    """In plain words: Corrupt state.json file on disk is cleanly overwritten on poll."""
    env = make_env(tmp_path, mode="confirm")
    (env.root / "_gateway" / "state.json").write_text("invalid json state", encoding="utf-8")

    _, new_svc = _recreate_service(env)
    new_svc.poll_once()

    parsed = json.loads((env.root / "_gateway" / "state.json").read_text(encoding="utf-8"))
    assert parsed["auth"] == "ok"
    assert parsed["mode"] == "confirm"


def test_cut_audit_log_mid_json_refuses_to_start(tmp_path: Path) -> None:
    """In plain words: An audit log truncated mid-line must refuse startup with a clear error."""
    audit_file = tmp_path / "audit.jsonl"
    truncated_content = '{"seq": "0", "t_ns": "0", "event": "init"}\n{"seq": "1", "t_ns": "1", "eve'
    audit_file.write_text(truncated_content, encoding="utf-8")

    with pytest.raises(audit.AuditError, match="Malformed JSON in audit log"):
        audit.AuditLog(audit_file)


def test_pinned_policy_file_swapped_refuses_reload(tmp_path: Path) -> None:
    """In plain words: Swapping the policy file contents behind a signed pin refuses reload."""
    env = make_env(tmp_path, mode="advisory", pinned_policy=True)
    assert env.policy_path is not None

    # Tamper with the policy file content on disk
    tampered_doc = policy_doc(mode="advisory")
    tampered_doc["mode"] = "off"
    env.policy_path.write_text(json.dumps(tampered_doc, indent=2), encoding="utf-8")

    # Attempt to reload policy; pin verification must detect digest mismatch
    with pytest.raises(policy_pin.PinError, match="digest_mismatch"):
        policy_pin.load_pinned_policy(env.policy_path, KEY)


def test_draft_swapped_after_review_refuses_policy_pin(tmp_path: Path) -> None:
    """In plain words: Swapping draft after review triggers draft_changed refusal on pin."""
    policy_path = tmp_path / "policy" / "write-policy.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(json.dumps(policy_doc("confirm")), encoding="utf-8")
    env = make_env(tmp_path, mode="confirm")

    # Author drafts doc A
    doc_a = policy_doc(mode="confirm")
    env.service._policy = policy_file.__name__ if False else env.service._policy  # type check hint
    from crosscut_gateway.policy_cmds import PolicyCommands

    paths = PolicyPaths(policy_path, env.root / "_gateway" / "policy-draft.json")
    cmds = PolicyCommands(paths, key_source=lambda: KEY, clock=env.clock)
    env.service._policy = cmds

    # Draft doc A
    draft_res = send(env, "policy_draft", {"document": doc_a}, actor="alice", roles=("engineer",))
    assert outbox(env.root, draft_res["id"])["ok"] is True
    digest_a = outbox(env.root, draft_res["id"])["result"]["digest"]

    # Now doc B is drafted by charlie, overwriting the draft on disk
    doc_b = policy_doc(mode="advisory")
    send(env, "policy_draft", {"document": doc_b}, actor="charlie", roles=("engineer",))

    # Lead attempts to pin doc A digest; must be refused as draft_changed
    pin_env = signed(
        env,
        "policy_pin",
        {"digest": digest_a},
        actor="bob",
        roles=("lead",),
    )
    pin_env["auth"]["stepup"] = True
    from crosscut_gateway.envelope import sign_envelope

    pin_env.pop("sig", None)
    pin_env = sign_envelope(pin_env, KEY)

    drop(env, pin_env)
    env.service.poll_once()

    assert rejected_reason(env.root, pin_env["id"]) == "draft_changed"

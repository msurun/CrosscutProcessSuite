"""Adversarial authorization matrix and engine isolation test suite for Write Gateway.

Validates the full Cartesian product of commands, roles, modes, and target states against
an independent ADR 013 oracle, and ensures denied commands never reach engine methods.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from auth_helpers import (
    AuthEnv,
    make_env,
    outbox,
    propose_args,
    rejected_reason,
    send,
)
from crosscut_gateway import authz
from crosscut_gateway.authz import AuthRequest
from crosscut_gateway.policy import proposal_key

ALL_MODES = ("off", "advisory", "dry_run", "confirm", "supervised")

# Independent oracle table directly transcribed from ADR 013 Section 1
ORACLE_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "viewer": {
        "data.view",
        "gw.view",
        "audit.view",
        "gw.kill",
        "gw.mode.down",
        "gw.reject",
    },
    "operator": {
        "data.view",
        "gw.view",
        "audit.view",
        "gw.kill",
        "gw.mode.down",
        "gw.reject",
        "analysis.run",
        "job.stop",
        "gw.approve",
        "gw.re_enable.hold_off",
    },
    "engineer": {
        "data.view",
        "gw.view",
        "audit.view",
        "gw.kill",
        "gw.mode.down",
        "gw.reject",
        "analysis.run",
        "job.stop",
        "gw.approve",
        "gw.re_enable.hold_off",
        "data.import",
        "config.edit",
        "connector.use",
        "job.manage",
        "gw.propose",
        "gw.mode.up.advisory",
        "gw.mode.up.dry_run",
        "gw.mode.up.confirm",
        "gw.re_enable.stopped",
        "policy.edit",
    },
    "lead": {
        "data.view",
        "gw.view",
        "audit.view",
        "gw.kill",
        "gw.mode.down",
        "gw.reject",
        "analysis.run",
        "job.stop",
        "gw.approve",
        "gw.re_enable.hold_off",
        "data.import",
        "config.edit",
        "connector.use",
        "job.manage",
        "gw.propose",
        "gw.mode.up.advisory",
        "gw.mode.up.dry_run",
        "gw.mode.up.confirm",
        "gw.re_enable.stopped",
        "policy.edit",
        "gw.mode.up.supervised",
        "gw.kill.reset",
        "policy.pin",
        "policy.reload",
    },
    "admin": {
        "data.view",
        "gw.view",
        "audit.view",
        "gw.kill",
        "gw.mode.down",
        "gw.reject",
        "users.manage",
    },
    "service": {
        "gw.propose",
    },
}

SIMPLE_COMMAND_MAP: dict[str, str] = {
    "propose": "gw.propose",
    "approve": "gw.approve",
    "reject": "gw.reject",
    "kill": "gw.kill",
    "kill_reset": "gw.kill.reset",
    "policy_draft": "policy.edit",
    "policy_pin": "policy.pin",
    "policy_reload": "policy.reload",
}


def oracle_authorize(
    roles: tuple[str, ...],
    cmd: str,
    args: dict[str, Any],
    mode: str,
    target_state: str | None,
) -> tuple[bool, str]:
    """In plain words: Independent reference oracle implementing ADR 013 authority rules."""
    granted: set[str] = set()
    for role in roles:
        if role in ORACLE_ROLE_PERMISSIONS:
            granted.update(ORACLE_ROLE_PERMISSIONS[role])

    if cmd in SIMPLE_COMMAND_MAP:
        perm = SIMPLE_COMMAND_MAP[cmd]
        return (True, "ok") if perm in granted else (False, f"missing_permission:{perm}")

    if cmd == "re_enable":
        perm = "gw.re_enable.hold_off" if target_state == "hold_off" else "gw.re_enable.stopped"
        return (True, "ok") if perm in granted else (False, f"missing_permission:{perm}")

    if cmd == "set_mode":
        return _oracle_set_mode(granted, args, mode)

    return False, "unknown_cmd"


def _oracle_set_mode(
    granted: set[str], args: dict[str, Any], current_mode: str
) -> tuple[bool, str]:
    """In plain words: Independent oracle logic for mode change validation."""
    if current_mode not in ALL_MODES:
        return False, "bad_mode"
    new_mode = args.get("mode")
    if not isinstance(new_mode, str) or new_mode not in ALL_MODES:
        return False, "bad_mode"
    if new_mode == current_mode:
        return True, "ok"

    curr_idx = ALL_MODES.index(current_mode)
    new_idx = ALL_MODES.index(new_mode)
    if new_idx < curr_idx:
        if "gw.mode.down" in granted:
            return True, "ok"
        return False, "missing_permission:gw.mode.down"

    if new_idx - curr_idx != 1:
        return False, "mode_step_too_large"

    if "cap" in args:
        cap = args["cap"]
        if not isinstance(cap, str) or cap not in ALL_MODES:
            return False, "bad_mode"
        if new_idx > ALL_MODES.index(cap):
            return False, "above_cap"

    perm = f"gw.mode.up.{new_mode}"
    return (True, "ok") if perm in granted else (False, f"missing_permission:{perm}")


class EngineSpy:
    """In plain words: Intercepts and counts calls to WriteGateway engine methods."""

    def __init__(self, target_gateway: Any) -> None:
        self.gateway = target_gateway
        self.counts: dict[str, int] = {
            "propose": 0,
            "approve": 0,
            "reject": 0,
            "kill": 0,
            "reset_kill": 0,
            "re_enable": 0,
            "set_mode": 0,
        }
        self._wrap_methods()

    def _wrap_methods(self) -> None:
        """Wrap each monitored engine method with call tracking."""
        for method_name in list(self.counts.keys()):
            original = getattr(self.gateway, method_name)
            setattr(self.gateway, method_name, self._make_tracker(method_name, original))

    def _make_tracker(self, name: str, orig: Callable[..., Any]) -> Callable[..., Any]:
        def tracker(*args: Any, **kwargs: Any) -> Any:
            self.counts[name] += 1
            return orig(*args, **kwargs)

        return tracker


def test_authz_full_cartesian_matrix_matches_oracle() -> None:
    """In plain words: Exhaustively verify authorize against ADR 013 oracle on all combinations."""
    roles_table = authz.load_roles()

    test_commands = [
        "propose",
        "approve",
        "reject",
        "kill",
        "kill_reset",
        "re_enable",
        "set_mode",
        "policy_draft",
        "policy_pin",
        "policy_reload",
        "unknown_cmd",
    ]
    test_role_sets = [
        ("viewer",),
        ("operator",),
        ("engineer",),
        ("lead",),
        ("admin",),
        ("service",),
        ("guest_unknown",),
        (),
        ("operator", "operator"),
        ("Operator",),
        ("ENGINEER",),
    ]
    test_target_states = [
        None,
        "hold_off",
        "stopped:comm",
        "stopped:kill",
        "stopped:rejected",
        "enabled",
        "killed",
    ]

    checked = 0
    for cmd in test_commands:
        for roles in test_role_sets:
            for current_mode in ALL_MODES:
                for target_state in test_target_states:
                    for target_mode in ALL_MODES:
                        for cap in _caps_for(cmd):
                            args = {"mode": target_mode, "tag": "FIC101.SP", "key": "k1"}
                            if cap is not None:
                                args["cap"] = cap
                            req = AuthRequest(
                                roles=roles,
                                cmd=cmd,
                                args=args,
                                mode=current_mode,
                                target_state=target_state,
                            )
                            actual = authz.authorize(req, roles_table)
                            expected = oracle_authorize(
                                roles, cmd, args, current_mode, target_state
                            )
                            assert actual == expected, (cmd, roles, current_mode, args)
                            checked += 1
    assert checked > 20000


def test_matrix_covers_the_above_cap_denial() -> None:
    """In plain words: The oracle and authorize both produce above_cap for a lead at the cap."""
    roles_table = authz.load_roles()
    args = {"mode": "supervised", "cap": "confirm"}
    req = AuthRequest(
        roles=("lead",), cmd="set_mode", args=args, mode="confirm", target_state=None
    )
    assert authz.authorize(req, roles_table) == (False, "above_cap")
    assert oracle_authorize(("lead",), "set_mode", args, "confirm", None) == (False, "above_cap")


def _caps_for(cmd: str) -> list[str | None]:
    """In plain words: set_mode is exercised with no cap, every valid cap and an invalid one."""
    if cmd == "set_mode":
        return [None, *ALL_MODES, "bogus"]
    return [None]


def test_denied_commands_never_reach_engine_methods(tmp_path: Path) -> None:
    """In plain words: Unauthorized commands fail closed at the gate with the exact reason."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)
    mode_before = env.gateway.mode
    cases = [
        ("propose", propose_args(env), "bob", ("viewer",), "propose", "gw.propose"),
        ("approve", {"key": "dummy_key"}, "bob", ("viewer",), "approve", "gw.approve"),
        ("kill", {}, "svc:runtime", ("service",), "kill", "gw.kill"),
        ("kill_reset", {}, "bob", ("operator",), "reset_kill", "gw.kill.reset"),
        ("re_enable", {"tag": "FIC101.SP"}, "bob", ("operator",), "re_enable",
         "gw.re_enable.stopped"),
    ]
    for cmd, args, actor, roles, counter, permission in cases:
        sent = send(env, cmd, args, actor=actor, roles=roles)
        assert spy.counts[counter] == 0, cmd
        assert rejected_reason(env.root, sent["id"]) == f"missing_permission:{permission}", cmd
        reply = outbox(env.root, sent["id"])
        assert reply is not None and reply["ok"] is False, f"{cmd} got no refusal reply"
        assert reply["error"] == f"missing_permission:{permission}", cmd
    assert all(count == 0 for count in spy.counts.values())
    assert env.gateway.mode == mode_before
    assert env.gateway.pending() == []
    assert len(env.plant.writes) == 0
    denied = [r for r in env.gateway.audit_records() if r["event"] == "auth_reject"]
    assert len(denied) == len(cases)


def test_mode_transitions_step_cap_and_down_jumps(tmp_path: Path) -> None:
    """In plain words: Test mode step-size limits and downward jumps with exact reasons."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)

    # Downward multi-step jump by viewer is allowed
    send(env, "set_mode", {"mode": "off"}, actor="bob", roles=("viewer",))
    assert spy.counts["set_mode"] == 1
    assert env.gateway.mode == "off"

    # Upward jump > 1 step (off -> dry_run) by lead is denied
    jump = send(env, "set_mode", {"mode": "dry_run"}, actor="alice", roles=("lead",))
    assert rejected_reason(env.root, jump["id"]) == "mode_step_too_large"
    assert spy.counts["set_mode"] == 1  # Unchanged
    assert env.gateway.mode == "off"

    # Upward by a role without the permission is denied with the permission named
    weak = send(env, "set_mode", {"mode": "advisory"}, actor="bob", roles=("viewer",))
    assert rejected_reason(env.root, weak["id"]) == "missing_permission:gw.mode.up.advisory"
    assert spy.counts["set_mode"] == 1

    # Upward within cap (off -> advisory) by lead is allowed
    send(env, "set_mode", {"mode": "advisory"}, actor="alice", roles=("lead",))
    assert spy.counts["set_mode"] == 2
    assert env.gateway.mode == "advisory"


def test_set_mode_above_policy_cap_is_denied_and_envelope_cap_is_ignored(
    tmp_path: Path,
) -> None:
    """In plain words: The gateway's own cap decides; a cap argument cannot move it."""
    env = make_env(tmp_path, mode="confirm")
    env.gateway._mode_cap = "confirm"  # what start_from_policy_file does for a capped policy
    spy = EngineSpy(env.gateway)

    # A forged cap=supervised does not lift the real cap
    forged = send(
        env,
        "set_mode",
        {"mode": "supervised", "cap": "supervised"},
        actor="alice",
        roles=("lead",),
    )
    assert rejected_reason(env.root, forged["id"]) == "above_cap"
    assert spy.counts["set_mode"] == 0
    assert env.gateway.mode == "confirm"

    # A forged cap=off does not block a legitimate step either
    down = send(
        env, "set_mode", {"mode": "dry_run", "cap": "off"}, actor="alice", roles=("lead",)
    )
    assert rejected_reason(env.root, down["id"]) is None
    assert spy.counts["set_mode"] == 1
    assert env.gateway.mode == "dry_run"

    # Climbing back to the cap is fine, one more step is not
    up = send(env, "set_mode", {"mode": "confirm"}, actor="alice", roles=("lead",))
    assert rejected_reason(env.root, up["id"]) is None
    assert env.gateway.mode == "confirm"
    over = send(env, "set_mode", {"mode": "supervised"}, actor="alice", roles=("lead",))
    assert rejected_reason(env.root, over["id"]) == "above_cap"
    assert spy.counts["set_mode"] == 2
    assert env.gateway.mode == "confirm"


def _assert_self_approval_refused(
    env: AuthEnv, spy: EngineSpy, pkey: str, approver: str, proposer: str
) -> None:
    """In plain words: A same-person approval is refused at the gate and the proposal survives."""
    app_env = send(env, "approve", {"key": pkey}, actor=approver, roles=("lead",))
    assert spy.counts["approve"] == 0
    assert rejected_reason(env.root, app_env["id"]) == "self_approval"
    reply = outbox(env.root, app_env["id"])
    assert reply is not None and reply["ok"] is False and reply["error"] == "self_approval"
    pending = env.gateway.pending()
    assert [proposal_key(p) for p in pending] == [pkey], "pending proposal was disturbed"
    assert env.gateway.pending_proposer(pkey) == proposer
    assert len(env.plant.writes) == 0


def _propose_as(env: AuthEnv, actor: str) -> str:
    """In plain words: Queue one proposal in confirm mode as actor and return its key."""
    send(env, "propose", propose_args(env), actor=actor, roles=("engineer",))
    pending = env.gateway.pending()
    assert len(pending) == 1
    return proposal_key(pending[0])


def test_self_approval_exact_match_denied_at_gate(tmp_path: Path) -> None:
    """In plain words: Proposer approving their own proposal with exact name match is refused."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)
    pkey = _propose_as(env, "alice")
    _assert_self_approval_refused(env, spy, pkey, "alice", "alice")


def test_self_approval_case_variant_denied_at_gate(tmp_path: Path) -> None:
    """In plain words: Case-differing approver (Alice vs alice) is denied at the gate."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)
    pkey = _propose_as(env, "alice")
    _assert_self_approval_refused(env, spy, pkey, "Alice", "alice")


def test_self_approval_trailing_spaces_denied_at_gate(tmp_path: Path) -> None:
    """In plain words: Proposer approving with a trailing space is denied at the gate."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)
    pkey = _propose_as(env, "alice")
    _assert_self_approval_refused(env, spy, pkey, "alice ", "alice")


def test_self_approval_unicode_normalization_denied(tmp_path: Path) -> None:
    """In plain words: Canonical Unicode NFC/NFD equivalence is enforced for self-approval."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)
    actor_nfc = unicodedata.normalize("NFC", "rené")
    actor_nfd = unicodedata.normalize("NFD", "rené")
    assert actor_nfc != actor_nfd
    pkey = _propose_as(env, actor_nfc)
    _assert_self_approval_refused(env, spy, pkey, actor_nfd, actor_nfc)


def test_different_approver_still_approves_the_same_proposal(tmp_path: Path) -> None:
    """In plain words: Positive control, a second person's approval is not blocked."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)
    pkey = _propose_as(env, "alice")
    app_env = send(env, "approve", {"key": pkey}, actor="bob", roles=("lead",))
    assert rejected_reason(env.root, app_env["id"]) is None
    assert spy.counts["approve"] == 1

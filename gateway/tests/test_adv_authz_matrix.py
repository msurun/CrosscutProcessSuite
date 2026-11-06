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

    for cmd in test_commands:
        for roles in test_role_sets:
            for current_mode in ALL_MODES:
                for target_state in test_target_states:
                    for target_mode in ALL_MODES:
                        args = {"mode": target_mode, "tag": "FIC101.SP", "key": "k1"}
                        req = AuthRequest(
                            roles=roles,
                            cmd=cmd,
                            args=args,
                            mode=current_mode,
                            target_state=target_state,
                        )
                        actual_ok, actual_reason = authz.authorize(req, roles_table)
                        expected_ok, expected_reason = oracle_authorize(
                            roles, cmd, args, current_mode, target_state
                        )
                        assert (actual_ok, actual_reason) == (expected_ok, expected_reason)


def test_denied_commands_never_reach_engine_methods(tmp_path: Path) -> None:
    """In plain words: Ensure unauthorized commands fail closed before reaching the engine."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)

    # 1. Propose by viewer (lacks gw.propose)
    send(env, "propose", propose_args(env), actor="bob", roles=("viewer",))
    assert spy.counts["propose"] == 0

    # 2. Approve by viewer (lacks gw.approve)
    send(env, "approve", {"key": "dummy_key"}, actor="bob", roles=("viewer",))
    assert spy.counts["approve"] == 0

    # 3. Signed kill by service role (lacks gw.kill)
    send(env, "kill", {}, actor="svc:runtime", roles=("service",))
    assert spy.counts["kill"] == 0

    # 4. Kill reset by operator (lacks gw.kill.reset)
    send(env, "kill_reset", {}, actor="bob", roles=("operator",))
    assert spy.counts["reset_kill"] == 0

    # 5. Re-enable stopped by operator (lacks gw.re_enable.stopped)
    send(env, "re_enable", {"tag": "FIC101.SP"}, actor="bob", roles=("operator",))
    assert spy.counts["re_enable"] == 0


def test_mode_transitions_step_cap_and_down_jumps(tmp_path: Path) -> None:
    """In plain words: Test mode step-size limits, policy cap violations, and downward jumps."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)

    # Downward multi-step jump by viewer is allowed
    send(env, "set_mode", {"mode": "off"}, actor="bob", roles=("viewer",))
    assert spy.counts["set_mode"] == 1
    assert env.gateway.mode == "off"

    # Upward jump > 1 step (off -> dry_run) by lead is denied
    send(env, "set_mode", {"mode": "dry_run"}, actor="alice", roles=("lead",))
    assert spy.counts["set_mode"] == 1  # Unchanged
    assert env.gateway.mode == "off"

    # Upward within cap (off -> advisory) by lead is allowed
    send(env, "set_mode", {"mode": "advisory"}, actor="alice", roles=("lead",))
    assert spy.counts["set_mode"] == 2
    assert env.gateway.mode == "advisory"


def test_self_approval_exact_match_denied_at_gate(tmp_path: Path) -> None:
    """In plain words: Proposer approving their own proposal with exact name match is refused."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)

    prop_env = send(env, "propose", propose_args(env), actor="alice", roles=("engineer",))
    pkey = proposal_key(env.gateway.pending()[0])

    app_env = send(env, "approve", {"key": pkey}, actor="alice", roles=("lead",))
    assert spy.counts["approve"] == 0
    assert rejected_reason(env.root, app_env["id"]) == "self_approval"
    assert outbox(env.root, app_env["id"]) is None
    assert prop_env is not None


def test_self_approval_case_variant_denied_at_gate(tmp_path: Path) -> None:
    """In plain words: Case-differing approver (Alice vs alice) must be denied at gate."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)

    send(env, "propose", propose_args(env), actor="alice", roles=("engineer",))
    pkey = proposal_key(env.gateway.pending()[0])

    app_env = send(env, "approve", {"key": pkey}, actor="Alice", roles=("lead",))
    # Defect: auth_gate uses == and misses the case difference, passing to engine
    assert spy.counts["approve"] == 0
    assert rejected_reason(env.root, app_env["id"]) == "self_approval"


def test_self_approval_trailing_spaces_denied_at_gate(tmp_path: Path) -> None:
    """In plain words: Proposer approving with trailing space must be denied at gate."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)

    send(env, "propose", propose_args(env), actor="alice", roles=("engineer",))
    pkey = proposal_key(env.gateway.pending()[0])

    app_env = send(env, "approve", {"key": pkey}, actor="alice ", roles=("lead",))
    assert spy.counts["approve"] == 0
    assert rejected_reason(env.root, app_env["id"]) == "self_approval"


def test_self_approval_unicode_normalization_denied(tmp_path: Path) -> None:
    """In plain words: Canonical Unicode NFC/NFD equivalence must be enforced."""
    env = make_env(tmp_path, mode="confirm")
    spy = EngineSpy(env.gateway)

    actor_nfc = unicodedata.normalize("NFC", "rené")
    actor_nfd = unicodedata.normalize("NFD", "rené")

    send(env, "propose", propose_args(env), actor=actor_nfc, roles=("engineer",))
    pkey = proposal_key(env.gateway.pending()[0])

    app_env = send(env, "approve", {"key": pkey}, actor=actor_nfd, roles=("lead",))
    assert spy.counts["approve"] == 0
    assert len(env.plant.writes) == 0
    assert rejected_reason(env.root, app_env["id"]) == "self_approval"
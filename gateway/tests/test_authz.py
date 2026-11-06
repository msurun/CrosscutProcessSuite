"""Behavioural tests for crosscut_gateway.authz: role loading, invariants and authorization.

Every expected permission set below is written as a literal in this file, independent of the
packaged JSON, so a change to the shipped roles that bypasses review also breaks the tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from crosscut_gateway.authz import (
    PERMISSIONS,
    AuthRequest,
    AuthzError,
    authorize,
    default_roles_path,
    load_roles,
    roles_or_default,
)

VIEWER_PERMISSIONS = {
    "data.view",
    "gw.view",
    "audit.view",
    "gw.kill",
    "gw.mode.down",
    "gw.reject",
}
OPERATOR_PERMISSIONS = VIEWER_PERMISSIONS | {
    "analysis.run",
    "job.stop",
    "gw.approve",
    "gw.reject",
    "gw.re_enable.hold_off",
}
ENGINEER_PERMISSIONS = OPERATOR_PERMISSIONS | {
    "gw.approve.tuning",
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
}
LEAD_PERMISSIONS = ENGINEER_PERMISSIONS | {
    "gw.mode.up.supervised",
    "gw.kill.reset",
    "policy.pin",
    "policy.reload",
}
ADMIN_PERMISSIONS = VIEWER_PERMISSIONS | {"users.manage"}
SERVICE_PERMISSIONS = {"gw.propose"}

EXPECTED_ROLE_TABLE: dict[str, set[str]] = {
    "viewer": VIEWER_PERMISSIONS,
    "operator": OPERATOR_PERMISSIONS,
    "engineer": ENGINEER_PERMISSIONS,
    "lead": LEAD_PERMISSIONS,
    "admin": ADMIN_PERMISSIONS,
    "service": SERVICE_PERMISSIONS,
}

HUMAN_ROLES = ("viewer", "operator", "engineer", "lead", "admin")
MODES = ("off", "advisory", "dry_run", "confirm", "supervised")

# (cmd, args, permission that decides it, role-agnostic: role must hold `permission`).
SIMPLE_COMMANDS = (
    ("propose", {}, "gw.propose"),
    ("approve", {}, "gw.approve"),
    ("reject", {}, "gw.reject"),
    ("kill", {}, "gw.kill"),
    ("kill_reset", {}, "gw.kill.reset"),
)


@dataclass(frozen=True)
class Transition:
    """A mode transition to authorize: where we are, where we go, and the expected outcome."""

    current_mode: str
    new_mode: str
    expected_allowed: bool
    expected_reason: str


@pytest.fixture(scope="module")
def role_table() -> dict[str, frozenset[str]]:
    """Load the packaged default roles table once for all tests in this module."""
    return load_roles()


def _role_granted(role_permissions: set[str], permission: str) -> bool:
    """Return True when permission is in role_permissions."""
    return permission in role_permissions


def _mode_transition_pairs() -> list[tuple[str, str]]:
    """Build every (current_mode, new_mode) pair, for parametrization."""
    return [(current_mode, new_mode) for current_mode in MODES for new_mode in MODES]


def _good_roles_document() -> dict:
    """Build a valid roles JSON document from the literal table, for tmp_path tests."""
    roles_doc = {
        role_name: {"description": f"{role_name} role", "permissions": sorted(perms)}
        for role_name, perms in EXPECTED_ROLE_TABLE.items()
    }
    return {"version": 1, "roles": roles_doc}


def _write_roles_file(target: Path, document: dict) -> Path:
    """Write document as JSON to target and return target."""
    target.write_text(json.dumps(document), encoding="utf-8")
    return target


def _request_for(role_name: str, cmd: str) -> AuthRequest:
    """Build a supervised-mode AuthRequest with no args for cmd."""
    return AuthRequest(roles=[role_name], cmd=cmd, args={}, mode="supervised")


def _permission_outcome(role_name: str, permission: str) -> tuple[bool, str]:
    """Return (True, "ok") when role_name holds permission, else (False, missing_permission)."""
    if _role_granted(EXPECTED_ROLE_TABLE[role_name], permission):
        return True, "ok"
    return False, f"missing_permission:{permission}"


def _mode_expected_outcome(role_name: str, current_mode: str, new_mode: str) -> tuple[bool, str]:
    """Return (allowed, reason) for a role attempting a transition, from the literal table."""
    if new_mode == current_mode:
        return True, "ok"
    current_index = MODES.index(current_mode)
    new_index = MODES.index(new_mode)
    if new_index < current_index:
        return _permission_outcome(role_name, "gw.mode.down")
    if new_index - current_index != 1:
        return False, "mode_step_too_large"
    return _permission_outcome(role_name, "gw.mode.up." + new_mode)


def test_role_table_keys_are_the_six_roles(role_table: dict[str, frozenset[str]]) -> None:
    """The loaded default table has exactly the six expected role names."""
    assert set(role_table) == set(EXPECTED_ROLE_TABLE)


def test_expected_permissions_are_all_known() -> None:
    """Every permission used in the literal table is part of the PERMISSIONS constant."""
    used_permissions: set[str] = set()
    for permissions in EXPECTED_ROLE_TABLE.values():
        used_permissions.update(permissions)
    assert used_permissions <= PERMISSIONS


@pytest.mark.parametrize("role_name", sorted(EXPECTED_ROLE_TABLE))
@pytest.mark.parametrize("permission", sorted(PERMISSIONS))
def test_role_permission_matrix(
    role_table: dict[str, frozenset[str]], role_name: str, permission: str
) -> None:
    """Each role grants exactly the permissions the literal table lists for it."""
    expected_granted = _role_granted(EXPECTED_ROLE_TABLE[role_name], permission)
    assert (permission in role_table[role_name]) is expected_granted


@pytest.mark.parametrize("action", SIMPLE_COMMANDS)
@pytest.mark.parametrize("role_name", ("viewer", "operator", "engineer", "lead", "service"))
def test_simple_command_follows_its_permission(
    role_table: dict[str, frozenset[str]], role_name: str, action: tuple[str, dict, str]
) -> None:
    """A simple command is allowed exactly when the role holds the deciding permission."""
    cmd, args, permission = action
    request = AuthRequest(roles=[role_name], cmd=cmd, args=args, mode="supervised")
    expected_granted = _role_granted(EXPECTED_ROLE_TABLE[role_name], permission)
    expected = (True, "ok") if expected_granted else (False, f"missing_permission:{permission}")
    assert authorize(request, role_table) == expected


@pytest.mark.parametrize(
    "target_state,permission",
    (
        ("hold_off", "gw.re_enable.hold_off"),
        ("stopped", "gw.re_enable.stopped"),
        ("stopped:kill", "gw.re_enable.stopped"),
        (None, "gw.re_enable.stopped"),
    ),
)
@pytest.mark.parametrize("role_name", ("operator", "engineer", "lead", "service"))
def test_re_enable_permission_depends_on_target_state(
    role_table: dict[str, frozenset[str]],
    role_name: str,
    target_state: str | None,
    permission: str,
) -> None:
    """re_enable requires the hold_off permission for hold_off and the stopped one otherwise."""
    request = AuthRequest(
        roles=[role_name],
        cmd="re_enable",
        args={},
        mode="supervised",
        target_state=target_state,
    )
    expected_granted = _role_granted(EXPECTED_ROLE_TABLE[role_name], permission)
    expected = (True, "ok") if expected_granted else (False, f"missing_permission:{permission}")
    assert authorize(request, role_table) == expected


@pytest.mark.parametrize("current_mode,new_mode", _mode_transition_pairs())
@pytest.mark.parametrize("role_name", sorted(EXPECTED_ROLE_TABLE))
def test_mode_transition(
    role_table: dict[str, frozenset[str]],
    role_name: str,
    current_mode: str,
    new_mode: str,
) -> None:
    """Each mode transition follows the upward/downward step rules for every role."""
    request = AuthRequest(
        roles=[role_name], cmd="set_mode", args={"mode": new_mode}, mode=current_mode
    )
    expected = _mode_expected_outcome(role_name, current_mode, new_mode)
    assert authorize(request, role_table) == expected


def test_upward_within_cap_is_allowed(role_table: dict[str, frozenset[str]]) -> None:
    """Lead may step up to confirm while the cap is confirm."""
    request = AuthRequest(
        roles=["lead"],
        cmd="set_mode",
        args={"mode": "confirm", "cap": "confirm"},
        mode="dry_run",
    )
    assert authorize(request, role_table) == (True, "ok")


def test_new_mode_above_cap_is_rejected(role_table: dict[str, frozenset[str]]) -> None:
    """Even lead is denied when the requested mode is above the cap."""
    request = AuthRequest(
        roles=["lead"],
        cmd="set_mode",
        args={"mode": "supervised", "cap": "confirm"},
        mode="confirm",
    )
    assert authorize(request, role_table) == (False, "above_cap")


@pytest.mark.parametrize(
    "current_mode,requested_mode",
    (("off", "turbo"), ("turbo", "advisory")),
)
def test_unknown_mode_is_bad_mode(
    role_table: dict[str, frozenset[str]], current_mode: str, requested_mode: str
) -> None:
    """An unknown requested or current mode yields bad_mode."""
    request = AuthRequest(
        roles=["lead"], cmd="set_mode", args={"mode": requested_mode}, mode=current_mode
    )
    assert authorize(request, role_table) == (False, "bad_mode")


def test_unknown_command_is_denied(role_table: dict[str, frozenset[str]]) -> None:
    """A command that is not recognized yields unknown_cmd."""
    request = AuthRequest(roles=["lead"], cmd="explode", args={}, mode="supervised")
    assert authorize(request, role_table) == (False, "unknown_cmd")


def test_union_of_operator_and_admin_can_approve(role_table: dict[str, frozenset[str]]) -> None:
    """Roles are unioned: operator grants gw.approve even if admin does not."""
    request = AuthRequest(roles=["operator", "admin"], cmd="approve", args={}, mode="supervised")
    assert authorize(request, role_table) == (True, "ok")


def test_union_of_viewer_and_operator_can_approve(role_table: dict[str, frozenset[str]]) -> None:
    """The union takes the best of both roles, so gw.approve from operator wins."""
    request = AuthRequest(roles=["viewer", "operator"], cmd="approve", args={}, mode="supervised")
    assert authorize(request, role_table) == (True, "ok")


@pytest.mark.parametrize("cmd,args", (("propose", {}), ("kill", {})))
@pytest.mark.parametrize("roles", ([], ["ghost"]))
def test_unknown_or_empty_roles_grant_nothing(
    role_table: dict[str, frozenset[str]], roles: list[str], cmd: str, args: dict
) -> None:
    """No roles or unknown roles grant no permissions, so guarded commands are denied."""
    request = AuthRequest(roles=roles, cmd=cmd, args=args, mode="supervised")
    allowed, reason = authorize(request, role_table)
    assert allowed is False
    assert reason.startswith("missing_permission:")


@pytest.mark.parametrize("role_name", HUMAN_ROLES)
def test_forced_human_permissions_granted_to_human_roles(
    role_table: dict[str, frozenset[str]], role_name: str
) -> None:
    """Every human role can kill, reject and switch mode down."""
    assert authorize(_request_for(role_name, "kill"), role_table) == (True, "ok")
    assert authorize(_request_for(role_name, "reject"), role_table) == (True, "ok")
    down_mode = AuthRequest(
        roles=[role_name], cmd="set_mode", args={"mode": "off"}, mode="advisory"
    )
    assert authorize(down_mode, role_table) == (True, "ok")


@pytest.mark.parametrize("cmd", ("kill", "reject"))
def test_service_role_cannot_use_forced_human_permissions(
    role_table: dict[str, frozenset[str]], cmd: str
) -> None:
    """The service role is denied kill and reject."""
    allowed, reason = authorize(_request_for("service", cmd), role_table)
    assert allowed is False
    assert reason.startswith("missing_permission:")


def test_default_roles_path_is_an_existing_file() -> None:
    """The packaged default roles file exists on disk."""
    assert default_roles_path().is_file()


def test_good_roles_file_loads(tmp_path: Path) -> None:
    """A valid document written from the literal table loads into the expected table."""
    path = _write_roles_file(tmp_path / "roles.json", _good_roles_document())
    loaded = load_roles(path)
    assert {name: set(perms) for name, perms in loaded.items()} == EXPECTED_ROLE_TABLE


def test_good_roles_file_without_service_role_loads(tmp_path: Path) -> None:
    """A document with no service role is still accepted."""
    document = _good_roles_document()
    del document["roles"]["service"]
    path = _write_roles_file(tmp_path / "roles.json", document)
    assert "service" not in load_roles(path)


def _document_missing_permission(role_name: str, permission: str) -> dict:
    """Build a roles document whose role_name lacks permission."""
    document = _good_roles_document()
    permissions = document["roles"][role_name]["permissions"]
    document["roles"][role_name]["permissions"] = [
        granted for granted in permissions if granted != permission
    ]
    return document


def _document_with_extra_service_permission() -> dict:
    """Build a roles document where the service role also holds gw.approve."""
    document = _good_roles_document()
    document["roles"]["service"]["permissions"].append("gw.approve")
    return document


def _document_with_bogus_permission() -> dict:
    """Build a roles document holding an unknown permission id."""
    document = _good_roles_document()
    document["roles"]["lead"]["permissions"].append("bogus.perm")
    return document


def _document_with_unknown_top_level_key() -> dict:
    """Build a roles document with an unexpected top-level key."""
    document = _good_roles_document()
    document["unexpected"] = True
    return document


INVALID_DOCUMENTS = (
    _document_missing_permission("operator", "gw.kill"),
    _document_missing_permission("viewer", "gw.mode.down"),
    _document_missing_permission("admin", "gw.reject"),
    _document_with_extra_service_permission(),
    _document_with_bogus_permission(),
    _document_with_unknown_top_level_key(),
)


@pytest.mark.parametrize("document", INVALID_DOCUMENTS)
def test_invalid_roles_document_raises(tmp_path: Path, document: dict) -> None:
    """A schema or invariant violation raises AuthzError."""
    path = _write_roles_file(tmp_path / "roles.json", document)
    with pytest.raises(AuthzError):
        load_roles(path)


def test_duplicate_key_raises(tmp_path: Path) -> None:
    """A JSON object with a duplicated key raises AuthzError."""
    path = tmp_path / "roles.json"
    path.write_text('{"version": 1, "version": 2, "roles": {}}', encoding="utf-8")
    with pytest.raises(AuthzError):
        load_roles(path)


def test_malformed_json_raises(tmp_path: Path) -> None:
    """Text that is not JSON raises AuthzError."""
    path = tmp_path / "roles.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(AuthzError):
        load_roles(path)


@pytest.mark.parametrize("document", INVALID_DOCUMENTS)
def test_roles_or_default_falls_back_on_invalid_document(
    role_table: dict[str, frozenset[str]], tmp_path: Path, document: dict
) -> None:
    """An invalid file falls back to the default table with a non-empty reason."""
    path = _write_roles_file(tmp_path / "roles.json", document)
    table, reason = roles_or_default(path)
    assert table == role_table
    assert reason


@pytest.mark.parametrize("scenario", ("duplicate", "malformed", "missing"))
def test_roles_or_default_falls_back_on_bad_file(
    role_table: dict[str, frozenset[str]], tmp_path: Path, scenario: str
) -> None:
    """Duplicate keys, malformed JSON and a missing file all fall back with a reason."""
    path = tmp_path / "roles.json"
    if scenario == "duplicate":
        path.write_text('{"version": 1, "version": 2}', encoding="utf-8")
    elif scenario == "malformed":
        path.write_text("{not json", encoding="utf-8")
    table, reason = roles_or_default(path)
    assert table == role_table
    assert reason


def test_roles_or_default_returns_default_for_none(
    role_table: dict[str, frozenset[str]],
) -> None:
    """A path of None loads the default table with no reason."""
    assert roles_or_default(None) == (role_table, None)


def test_roles_or_default_returns_default_for_good_file(
    role_table: dict[str, frozenset[str]], tmp_path: Path
) -> None:
    """A valid file loads its own table with no reason."""
    path = _write_roles_file(tmp_path / "roles.json", _good_roles_document())
    assert roles_or_default(path) == (role_table, None)

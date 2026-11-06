"""Authorization of PID parameter sets (ADR 013/014): gw.approve.tuning, service principal.

The expectations are literals, independent of the packaged JSON, so a change to the shipped
roles that bypasses review also breaks these tests.
"""

from __future__ import annotations

import json

import pytest
from crosscut_gateway.authz import (
    PERMISSIONS,
    AuthRequest,
    authorize,
    load_roles,
    roles_schema_path,
)

ROLES = ("viewer", "operator", "engineer", "lead", "admin", "service")
CAN_APPROVE_TUNING = {"engineer", "lead"}
CAN_APPROVE_SETPOINT = {"operator", "engineer", "lead"}
CAN_PROPOSE = {"engineer", "lead", "service"}
TUNING = "gw.approve.tuning"


@pytest.fixture(scope="module")
def table() -> dict[str, frozenset[str]]:
    """The packaged default role table."""
    return load_roles()


def _approve(role: str, kind: str | None, table: dict[str, frozenset[str]]) -> tuple[bool, str]:
    request = AuthRequest(
        roles=[role], cmd="approve", args={"key": "k"}, mode="confirm", pending_kind=kind
    )
    return authorize(request, table)


def test_permission_is_known_and_in_schema_enum() -> None:
    assert TUNING in PERMISSIONS
    schema = json.loads(roles_schema_path().read_text(encoding="utf-8"))
    assert set(schema["$defs"]["permission"]["enum"]) == set(PERMISSIONS)


def test_default_json_grants_tuning_to_engineer_and_lead_only(
    table: dict[str, frozenset[str]],
) -> None:
    holders = {role for role, perms in table.items() if TUNING in perms}
    assert holders == CAN_APPROVE_TUNING
    assert table["operator"] >= {"gw.approve", "gw.reject"} and TUNING not in table["operator"]


def test_api_role_table_matches() -> None:
    roles = pytest.importorskip("crosscut_api.auth.roles")
    api_table = roles.load_roles(None)
    assert api_table.permissions_for(["engineer"]) >= {TUNING}
    assert api_table.permissions_for(["lead"]) >= {TUNING}
    assert TUNING not in api_table.permissions_for(["operator", "viewer", "admin", "service"])


@pytest.mark.parametrize("role", ROLES)
def test_approving_a_parameter_set_needs_the_tuning_permission(
    role: str, table: dict[str, frozenset[str]]
) -> None:
    allowed, reason = _approve(role, "pid_param", table)
    assert allowed is (role in CAN_APPROVE_TUNING)
    assert reason == ("ok" if allowed else f"missing_permission:{TUNING}")


@pytest.mark.parametrize("role", ROLES)
def test_approving_a_setpoint_is_unchanged(role: str, table: dict[str, frozenset[str]]) -> None:
    for kind in ("setpoint", None):
        allowed, reason = _approve(role, kind, table)
        assert allowed is (role in CAN_APPROVE_SETPOINT)
        assert reason == ("ok" if allowed else "missing_permission:gw.approve")


def test_gw_approve_alone_is_not_enough_for_tuning() -> None:
    only_approve = {"custom": frozenset({"gw.approve", "gw.reject"})}
    assert _approve("custom", "pid_param", only_approve) == (False, f"missing_permission:{TUNING}")
    assert _approve("custom", "setpoint", only_approve) == (True, "ok")


@pytest.mark.parametrize("role", ROLES)
def test_propose_params_needs_gw_propose(role: str, table: dict[str, frozenset[str]]) -> None:
    request = AuthRequest(roles=[role], cmd="propose_params", args={}, mode="confirm",
                          actor="erin")
    allowed, reason = authorize(request, table)
    if role == "service":
        assert (allowed, reason) == (False, "service_cannot_propose_tuning")
    elif role in CAN_PROPOSE:
        assert (allowed, reason) == (True, "ok")
    else:
        assert (allowed, reason) == (False, "missing_permission:gw.propose")


@pytest.mark.parametrize("actor", ["svc:runtime", "SVC:Runtime", " svc:other "])
def test_service_actor_may_never_propose_tuning_whatever_its_roles(
    actor: str, table: dict[str, frozenset[str]]
) -> None:
    for roles in (["service"], ["engineer"], ["lead", "service"]):
        request = AuthRequest(roles=roles, cmd="propose_params", args={}, mode="confirm",
                              actor=actor)
        assert authorize(request, table) == (False, "service_cannot_propose_tuning")


def test_service_may_still_propose_setpoints(table: dict[str, frozenset[str]]) -> None:
    request = AuthRequest(roles=["service"], cmd="propose", args={}, mode="confirm",
                          actor="svc:runtime")
    assert authorize(request, table) == (True, "ok")


def test_reject_is_unchanged_for_operators(table: dict[str, frozenset[str]]) -> None:
    request = AuthRequest(roles=["operator"], cmd="reject", args={"key": "k"}, mode="confirm",
                          pending_kind="pid_param")
    assert authorize(request, table) == (True, "ok")

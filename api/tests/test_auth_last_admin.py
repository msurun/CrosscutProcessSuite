"""Tests for the last-administrator guard on ``/auth/users`` writes and self-service limits.

Each test writes a roles override (all packaged roles plus a ``manager`` role holding the
admin permissions), seeds its own users, and uses a fake clock with one TestClient per user.
Shared helpers live in ``auth_support``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from auth_support import FakeClock, csrf, login, make_app, seed_users, stepup
from crosscut_api.auth.roles import OVERRIDE_RELATIVE, load_roles
from crosscut_api.auth.store import JsonUserStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

USERS_PATH = "/auth/users"
MANAGER_ROLE = "manager"
ONE_ADMIN: dict[str, list[str]] = {
    "admin1": ["admin"],
    "mgr1": [MANAGER_ROLE],
    "op1": ["operator"],
}
TWO_ADMINS: dict[str, list[str]] = {**ONE_ADMIN, "admin2": ["admin"]}


def _write_roles(root: Path) -> None:
    """Write the roles override: every packaged role plus a manager role with admin rights."""
    roles: dict[str, Any] = {
        name: {"description": f"{name} role", "permissions": sorted(permissions)}
        for name, permissions in load_roles(None).roles.items()
    }
    roles[MANAGER_ROLE] = {
        "description": "Manages users with the same permissions as admin (test role).",
        "permissions": sorted(roles["admin"]["permissions"]),
    }
    override = root / OVERRIDE_RELATIVE
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text(json.dumps({"version": 1, "roles": roles}), encoding="utf-8")


def _seed(root: Path, specs: dict[str, list[str]]) -> None:
    """Write the roles override under ``root`` and then the users described by ``specs``."""
    _write_roles(root)
    seed_users(root, specs)


@pytest.fixture
def clock() -> FakeClock:
    """Return a fake clock that starts at the shared test time."""
    return FakeClock()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Return a data root with exactly one administrator, a manager and an operator."""
    _seed(tmp_path, ONE_ADMIN)
    return tmp_path


@pytest.fixture
def two_admin_root(tmp_path: Path) -> Path:
    """Return a data root with two active administrators, a manager and an operator."""
    _seed(tmp_path, TWO_ADMINS)
    return tmp_path


@pytest.fixture
def disabled_admin_root(tmp_path: Path) -> Path:
    """Return a data root whose second administrator is disabled in the store."""
    _seed(tmp_path, TWO_ADMINS)
    JsonUserStore(tmp_path).update("admin2", {"disabled": True})
    return tmp_path


@pytest.fixture
def app(root: Path, clock: FakeClock) -> FastAPI:
    """Return the auth-only app served over the one-admin data root."""
    return make_app(root, clock)


def _signed_in(
    app: FastAPI, username: str
) -> tuple[TestClient, dict[str, Any]]:
    """Return a client holding its own session for ``username`` and the login payload."""
    client = TestClient(app)
    return client, login(client, username)


def _stepped_up(app: FastAPI, username: str) -> tuple[TestClient, dict[str, Any]]:
    """Return a signed-in client that has just completed a step-up."""
    client, payload = _signed_in(app, username)
    stepup(client, payload)
    return client, payload


def _patch(
    client: TestClient, payload: dict[str, Any], username: str, body: dict[str, Any]
) -> Response:
    """PATCH one user with the session's CSRF header."""
    return client.patch(f"{USERS_PATH}/{username}", json=body, headers=csrf(payload))


def _delete(client: TestClient, payload: dict[str, Any], username: str) -> Response:
    """DELETE one user with the session's CSRF header."""
    return client.delete(f"{USERS_PATH}/{username}", headers=csrf(payload))


def _assert_last_admin_refused(response: Response) -> None:
    """Assert a 409 whose detail names the last-administrator guard."""
    assert response.status_code == 409, response.text
    detail = str(response.json().get("detail", "")).lower()
    assert "last admin" in detail, response.text


def test_deleting_the_only_admin_is_refused(app: FastAPI) -> None:
    """With one administrator, a manager cannot delete that administrator (409, last admin)."""
    manager, payload = _stepped_up(app, "mgr1")
    _assert_last_admin_refused(_delete(manager, payload, "admin1"))
    assert manager.get(f"{USERS_PATH}/admin1").status_code == 200


def test_disabling_the_only_admin_is_refused(app: FastAPI) -> None:
    """With one administrator, a manager cannot disable that administrator (409, last admin)."""
    manager, payload = _stepped_up(app, "mgr1")
    _assert_last_admin_refused(_patch(manager, payload, "admin1", {"disabled": True}))


def test_demoting_the_only_admin_is_refused(app: FastAPI) -> None:
    """With one administrator, a manager cannot remove the admin role from it (409)."""
    manager, payload = _stepped_up(app, "mgr1")
    response = _patch(manager, payload, "admin1", {"roles": ["viewer"]})
    assert response.status_code == 409, response.text


def test_deleting_one_of_two_admins_is_allowed(two_admin_root: Path, clock: FakeClock) -> None:
    """With a second active administrator, deleting the first one succeeds."""
    manager, payload = _stepped_up(make_app(two_admin_root, clock), "mgr1")
    assert _delete(manager, payload, "admin1").status_code == 200


def test_disabling_one_of_two_admins_is_allowed(two_admin_root: Path, clock: FakeClock) -> None:
    """With two active administrators, disabling one succeeds and the other still logs in."""
    app = make_app(two_admin_root, clock)
    manager, payload = _stepped_up(app, "mgr1")
    assert _patch(manager, payload, "admin2", {"disabled": True}).status_code == 200
    login(TestClient(app), "admin1")


def test_demoting_one_of_two_admins_is_allowed(two_admin_root: Path, clock: FakeClock) -> None:
    """With a second active administrator, removing the admin role from one succeeds."""
    manager, payload = _stepped_up(make_app(two_admin_root, clock), "mgr1")
    assert _patch(manager, payload, "admin1", {"roles": ["viewer"]}).status_code == 200


def test_disabled_admin_does_not_count_as_active(
    disabled_admin_root: Path, clock: FakeClock
) -> None:
    """A disabled second administrator does not protect the only active one (409, last admin)."""
    manager, payload = _stepped_up(make_app(disabled_admin_root, clock), "mgr1")
    _assert_last_admin_refused(_delete(manager, payload, "admin1"))


def test_admin_still_cannot_change_or_delete_self_with_two_admins(
    two_admin_root: Path, clock: FakeClock
) -> None:
    """The own-account rule still applies when another administrator exists (403)."""
    admin, payload = _stepped_up(make_app(two_admin_root, clock), "admin1")
    assert _patch(admin, payload, "admin1", {"roles": ["viewer"]}).status_code == 403
    assert _delete(admin, payload, "admin1").status_code == 403


def test_deleting_a_non_admin_is_still_allowed(app: FastAPI) -> None:
    """The last-admin guard does not block deleting an ordinary user (no false positive)."""
    manager, payload = _stepped_up(app, "mgr1")
    response = _delete(manager, payload, "op1")
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}

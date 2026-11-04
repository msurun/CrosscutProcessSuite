"""Tests for the admin user routes under ``/auth/users``: access, writes, sessions and audit.

Each test uses a fake clock, a temporary data root seeded with DEFAULT_USERS and one
TestClient (its own cookie jar) per signed-in user. Shared helpers live in ``auth_support``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from auth_support import (
    DEFAULT_USERS,
    PASSWORD,
    FakeClock,
    csrf,
    login,
    make_app,
    seed_users,
    stepup,
)
from crosscut_api.auth.audit import read_records, verify_chain
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import USERS_FILE, auth_dir
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

USERS_PATH = "/auth/users"
NEW_PASSWORD = "battery staple 42"
NEW_USER: dict[str, Any] = {
    "username": "new1",
    "display_name": "New One",
    "roles": ["viewer"],
    "password": "another long pass 9",
}


@pytest.fixture
def clock() -> FakeClock:
    """Return a fake clock that starts at the shared test time."""
    return FakeClock()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Return a data root seeded with the default users."""
    seed_users(tmp_path, DEFAULT_USERS)
    return tmp_path


@pytest.fixture
def app(root: Path, clock: FakeClock) -> FastAPI:
    """Return the auth-only app served over the seeded data root."""
    return make_app(root, clock)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Return a plain-HTTP test client without a session."""
    return TestClient(app)


def _creds(username: str, password: str = PASSWORD) -> dict[str, str]:
    """Return a login body for ``username``."""
    return {"username": username, "password": password}


def _signed_in(
    app: FastAPI, username: str, password: str = PASSWORD
) -> tuple[TestClient, dict[str, Any]]:
    """Return a client holding its own session for ``username`` and the login payload."""
    client = TestClient(app)
    return client, login(client, username, password)


def _stepped_up(app: FastAPI, username: str = "admin1") -> tuple[TestClient, dict[str, Any]]:
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


def _record(texts: list[str], response: Response) -> Response:
    """Keep the body text of ``response`` for the leak scan and return the response."""
    texts.append(response.text)
    return response


def _users_file(root: Path) -> list[dict[str, Any]]:
    """Return the user records stored in the users file under ``root``."""
    document = json.loads((auth_dir(root) / USERS_FILE).read_text(encoding="utf-8"))
    users: list[dict[str, Any]] = document["users"]
    return users


def test_permission_matrix_limits_listing_to_admins(app: FastAPI) -> None:
    """Only users with ``users.manage`` can list users, and the listing never shows passwords."""
    for username in ("view1", "op1", "eng1"):
        other, _ = _signed_in(app, username)
        assert other.get(USERS_PATH).status_code == 403, username
    admin, _ = _signed_in(app, "admin1")
    response = admin.get(USERS_PATH)
    assert response.status_code == 200
    users = response.json()["users"]
    assert sorted(user["username"] for user in users) == sorted(DEFAULT_USERS)
    assert all("password" not in user for user in users)


def test_create_user_requires_step_up(app: FastAPI) -> None:
    """Creating a user is refused without a recent step-up and works after one."""
    admin, payload = _signed_in(app, "admin1")
    blocked = admin.post(USERS_PATH, json=NEW_USER, headers=csrf(payload))
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "step-up required"
    stepup(admin, payload)
    created = admin.post(USERS_PATH, json=NEW_USER, headers=csrf(payload))
    assert created.status_code == 201
    assert "password" not in created.json()
    newcomer, body = _signed_in(app, "new1", NEW_USER["password"])
    assert body["must_change_password"] is True
    assert newcomer.get("/auth/me").json()["must_change_password"] is True


def test_create_user_rejects_duplicates_and_bad_input(app: FastAPI) -> None:
    """Duplicate usernames give 409; weak passwords, unknown roles and bad names give 422."""
    admin, payload = _stepped_up(app)
    headers = csrf(payload)
    assert admin.post(USERS_PATH, json=NEW_USER, headers=headers).status_code == 201
    duplicate = admin.post(USERS_PATH, json=NEW_USER, headers=headers)
    assert duplicate.status_code == 409
    cases = [
        {**NEW_USER, "username": "new2", "password": "short"},
        {**NEW_USER, "username": "new3", "roles": ["wizard"]},
        {**NEW_USER, "username": "Bad User"},
    ]
    for body in cases:
        assert admin.post(USERS_PATH, json=body, headers=headers).status_code == 422, body


def test_role_change_revokes_open_session_and_new_login_gets_roles(app: FastAPI) -> None:
    """Changing roles ends the user's open session; the next login carries the new roles."""
    viewer, viewer_payload = _signed_in(app, "view1")
    assert viewer_payload["roles"] == ["viewer"]
    admin, payload = _stepped_up(app)
    response = _patch(admin, payload, "view1", {"roles": ["operator"]})
    assert response.status_code == 200
    assert response.json()["roles"] == ["operator"]
    assert viewer.get("/auth/me").status_code == 401
    _, relogin = _signed_in(app, "view1")
    assert relogin["roles"] == ["operator"]


def test_admin_cannot_change_own_roles_disabled_flag_or_delete_self(app: FastAPI) -> None:
    """An administrator cannot demote, disable or delete their own account."""
    admin, payload = _stepped_up(app)
    assert _patch(admin, payload, "admin1", {"roles": ["viewer"]}).status_code == 403
    assert _patch(admin, payload, "admin1", {"disabled": True}).status_code == 403
    assert _delete(admin, payload, "admin1").status_code == 403


def test_patch_rejects_unknown_fields_and_unknown_users(app: FastAPI) -> None:
    """PATCH refuses fields outside the editable set (422) and users that do not exist (404)."""
    admin, payload = _stepped_up(app)
    unknown_field = _patch(admin, payload, "view1", {"is_admin": True})
    assert unknown_field.status_code == 422
    missing = _patch(admin, payload, "ghost", {"display_name": "Ghost Name"})
    assert missing.status_code == 404


def test_disable_revokes_session_and_blocks_login(app: FastAPI) -> None:
    """Disabling an account ends its open session and makes further logins fail with 401."""
    viewer, _ = _signed_in(app, "view1")
    admin2, payload = _stepped_up(app, "admin2")
    response = _patch(admin2, payload, "view1", {"disabled": True})
    assert response.status_code == 200
    assert response.json()["disabled"] is True
    assert viewer.get("/auth/me").status_code == 401
    retry = TestClient(app).post("/auth/login", json=_creds("view1"))
    assert retry.status_code == 401


def test_admin_password_reset_forces_change_and_revokes_sessions(app: FastAPI) -> None:
    """An administrative password reset forces a password change and ends the user's sessions."""
    operator, _ = _signed_in(app, "op1")
    admin, payload = _stepped_up(app)
    response = _patch(admin, payload, "op1", {"password": NEW_PASSWORD})
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    assert operator.get("/auth/me").status_code == 401
    reset_login = login(TestClient(app), "op1", NEW_PASSWORD)
    assert reset_login["must_change_password"] is True


def test_delete_removes_user_and_later_lookup_returns_404(app: FastAPI) -> None:
    """Deleting another user succeeds once; a later lookup of that user gives 404."""
    admin, payload = _stepped_up(app)
    deleted = _delete(admin, payload, "view1")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert admin.get(f"{USERS_PATH}/view1").status_code == 404


def test_audit_chain_verifies_and_records_every_event_kind(app: FastAPI, root: Path) -> None:
    """After logins, logout, password change and user writes, the audit chain verifies."""
    admin, payload = _stepped_up(app)
    failed = TestClient(app).post("/auth/login", json=_creds("view1", "wrong one 99"))
    assert failed.status_code == 401
    headers = csrf(payload)
    assert admin.post(USERS_PATH, json=NEW_USER, headers=headers).status_code == 201
    assert _patch(admin, payload, "new1", {"display_name": "Renamed"}).status_code == 200
    assert _delete(admin, payload, "new1").status_code == 200
    operator, operator_payload = _signed_in(app, "op1")
    changed = operator.post(
        "/auth/password",
        json={"old_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=csrf(operator_payload),
    )
    assert changed.status_code == 200
    assert admin.post("/auth/logout", headers=headers).status_code == 200
    records = read_records(auth_dir(root) / AUDIT_FILE)
    events = {record["event"] for record in records}
    assert verify_chain(records) is True
    expected = {
        "login_ok",
        "login_fail",
        "logout",
        "password_change",
        "user_create",
        "user_update",
        "user_delete",
    }
    assert expected <= events


def test_responses_and_audit_never_leak_secrets(app: FastAPI, root: Path) -> None:
    """Across a scenario, no response body or audit line holds a password or a stored hash."""
    seeded_hashes = [user["password"]["hash_b64"] for user in _users_file(root)]
    texts: list[str] = []
    admin = TestClient(app)
    payload = _record(texts, admin.post("/auth/login", json=_creds("admin1"))).json()
    stepup(admin, payload)
    headers = csrf(payload)
    _record(texts, admin.post(USERS_PATH, json=NEW_USER, headers=headers))
    _record(texts, admin.get(USERS_PATH))
    _record(texts, admin.get(f"{USERS_PATH}/new1"))
    _record(texts, _patch(admin, payload, "op1", {"password": NEW_PASSWORD}))
    _record(texts, TestClient(app).post("/auth/login", json=_creds("view1", "wrong one 99")))
    _record(texts, TestClient(app).post("/auth/login", json=_creds("op1", NEW_PASSWORD)))
    _record(texts, admin.post("/auth/logout", headers=headers))
    audit_text = (auth_dir(root) / AUDIT_FILE).read_text(encoding="utf-8")
    haystack = "\n".join([*texts, audit_text])
    for secret in (PASSWORD, NEW_PASSWORD, NEW_USER["password"], "wrong one 99"):
        assert secret not in haystack
    assert "hash_b64" not in haystack
    assert "salt_b64" not in haystack
    assert not [digest for digest in seeded_hashes if digest in haystack]


def test_login_rejects_malformed_bodies_without_echo(client: TestClient) -> None:
    """A non-object JSON body or a missing field gets 422 and the response never echoes input."""
    not_object = client.post("/auth/login", json=[PASSWORD])
    assert not_object.status_code == 422
    assert PASSWORD not in not_object.text
    missing = client.post("/auth/login", json={"username": "admin1"})
    assert missing.status_code == 422
    assert "password is required" in missing.text
    assert PASSWORD not in missing.text

"""Tests for the auth HTTP routes: login, lockout, rate limit, session, password and step-up.

Uses a fake clock and a cheap scrypt cost; no real time passes and no network is used.
Shared helpers live in ``auth_support``.
"""

from __future__ import annotations

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
)
from crosscut_api.auth.audit import read_records
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import JsonUserStore, auth_dir
from fastapi.testclient import TestClient

NEW_PASSWORD = "battery staple 42"
USERS_BODY: dict[str, Any] = {
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
def client(root: Path, clock: FakeClock) -> TestClient:
    """Return a plain-HTTP test client for the auth router."""
    return TestClient(make_app(root, clock))


def _audit_events(root: Path) -> list[str]:
    """Return the event names recorded in the auth audit log, in order."""
    return [record["event"] for record in read_records(auth_dir(root) / AUDIT_FILE)]


def test_login_success_sets_cookie_and_returns_session(client: TestClient, root: Path) -> None:
    """A correct password returns the session payload and an HttpOnly strict cookie."""
    response = client.post("/auth/login", json={"username": "admin1", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "admin1"
    assert "admin" in body["roles"]
    assert body["csrf"]
    cookie = response.headers["set-cookie"].lower()
    assert "cc_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie
    assert "secure" not in cookie
    assert "login_ok" in _audit_events(root)


def test_login_over_https_sets_secure_cookie(root: Path, clock: FakeClock) -> None:
    """Behind an https request the session cookie carries the Secure flag."""
    secure_client = TestClient(make_app(root, clock), base_url="https://testserver")
    response = secure_client.post(
        "/auth/login",
        json={"username": "admin1", "password": PASSWORD},
    )
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_login_unknown_user_and_bad_password_share_one_response(
    client: TestClient,
) -> None:
    """Unknown user and wrong password return 401 with identical bodies."""
    unknown = client.post("/auth/login", json={"username": "nobody", "password": PASSWORD})
    wrong = client.post("/auth/login", json={"username": "admin1", "password": "wrong pass 1"})
    assert unknown.status_code == 401
    assert wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert "set-cookie" not in unknown.headers


def test_login_disabled_user_is_refused(client: TestClient, root: Path) -> None:
    """A disabled account gets 401 even with the correct password."""
    JsonUserStore(root).update("op1", {"disabled": True})
    response = client.post("/auth/login", json={"username": "op1", "password": PASSWORD})
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid credentials"}


def test_lockout_after_five_failures_then_recovers(
    client: TestClient,
    clock: FakeClock,
    root: Path,
) -> None:
    """Five bad passwords lock the account; the right password is refused until the lock lapses."""
    for _ in range(5):
        response = client.post(
            "/auth/login",
            json={"username": "admin2", "password": "wrong pass 1"},
        )
        assert response.status_code == 401
    locked = client.post("/auth/login", json={"username": "admin2", "password": PASSWORD})
    assert locked.status_code == 423
    assert int(locked.headers["retry-after"]) > 0
    clock.advance(301)
    assert login(client, "admin2")["user"]["username"] == "admin2"
    events = _audit_events(root)
    assert "login_fail" in events
    assert "lockout" in events


def test_ip_rate_limit_returns_429_then_resets_after_window(
    client: TestClient,
    clock: FakeClock,
) -> None:
    """The 21st attempt from one IP within the window gets 429; a new window allows login."""
    for i in range(20):
        response = client.post(
            "/auth/login",
            json={"username": f"ghost{i}", "password": "wrong pass 1"},
        )
        assert response.status_code == 401
    limited = client.post("/auth/login", json={"username": "ghost20", "password": "x"})
    assert limited.status_code == 429
    clock.advance(61)
    assert login(client, "admin1")["user"]["username"] == "admin1"


def test_me_requires_a_session_and_expires_when_idle(
    client: TestClient,
    root: Path,
    clock: FakeClock,
) -> None:
    """GET /auth/me returns the caller, then 401 without a cookie or after the idle timeout."""
    payload = login(client, "op1")
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "op1"
    assert me.json()["csrf"] == payload["csrf"]

    anonymous = TestClient(make_app(root, clock))
    assert anonymous.get("/auth/me").status_code == 401

    clock.advance(3601)
    assert client.get("/auth/me").status_code == 401


def test_logout_ends_session_and_checks_csrf(client: TestClient) -> None:
    """Logout needs the CSRF token, then ends the session so /auth/me returns 401."""
    payload = login(client, "op1")
    assert client.post("/auth/logout").status_code == 403
    assert client.post("/auth/logout", headers={"X-Crosscut-CSRF": "bogus"}).status_code == 403

    response = client.post("/auth/logout", headers=csrf(payload))
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert client.get("/auth/me").status_code == 401


def test_password_change_rejects_wrong_old_and_short_new(client: TestClient) -> None:
    """A wrong current password gives 403 and a short new password gives 422."""
    payload = login(client, "eng1")
    wrong_old = client.post(
        "/auth/password",
        json={"old_password": "wrong pass 1", "new_password": NEW_PASSWORD},
        headers=csrf(payload),
    )
    assert wrong_old.status_code == 403
    assert wrong_old.json()["detail"] == "wrong_password"
    too_short = client.post(
        "/auth/password",
        json={"old_password": PASSWORD, "new_password": "short"},
        headers=csrf(payload),
    )
    assert too_short.status_code == 422


def test_password_change_replaces_password_and_revokes_other_sessions(
    root: Path,
    clock: FakeClock,
) -> None:
    """After a change the old password fails, the new one works, and other sessions end."""
    app = make_app(root, clock)
    first = TestClient(app)
    second = TestClient(app)
    payload = login(first, "view1")
    login(second, "view1")

    response = first.post(
        "/auth/password",
        json={"old_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=csrf(payload),
    )
    assert response.status_code == 200
    assert second.get("/auth/me").status_code == 401
    assert first.get("/auth/me").status_code == 200

    old = first.post("/auth/login", json={"username": "view1", "password": PASSWORD})
    assert old.status_code == 401
    assert login(first, "view1", NEW_PASSWORD)["user"]["username"] == "view1"


def test_stepup_wrong_password_then_ok_then_expires(client: TestClient, clock: FakeClock) -> None:
    """Step-up needs the right password, allows user creation, and lapses after its window."""
    payload = login(client, "admin1")
    wrong = client.post(
        "/auth/stepup",
        json={"password": "wrong pass 1"},
        headers=csrf(payload),
    )
    assert wrong.status_code == 403
    assert wrong.json()["detail"] == "wrong_password"

    good = client.post("/auth/stepup", json={"password": PASSWORD}, headers=csrf(payload))
    assert good.status_code == 200
    assert good.json()["ok"] is True
    assert good.json()["valid_for_s"] > 0
    created = client.post("/auth/users", json=USERS_BODY, headers=csrf(payload))
    assert created.status_code == 201

    clock.advance(301)
    expired = client.post("/auth/users", json=USERS_BODY, headers=csrf(payload))
    assert expired.status_code == 428
    assert expired.json()["detail"] == "step_up_required"


def test_uninitialised_store_returns_503(tmp_path: Path, clock: FakeClock) -> None:
    """With no users file, login and /auth/me both report 503 not initialised."""
    empty = TestClient(make_app(tmp_path, clock))
    login_response = empty.post("/auth/login", json={"username": "admin1", "password": PASSWORD})
    assert login_response.status_code == 503
    assert empty.get("/auth/me").status_code == 503

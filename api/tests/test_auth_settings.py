"""Tests for the site auth settings, the settings route and the two-person pending flow.

Covers defaults equal to the former constants, bounds and unknown keys refused with the field
named, effects on sessions and lockout under a fake clock, the pending-change flow with two
administrators and the admin-only ``GET /auth/settings`` route. Helpers live in ``auth_support``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from auth_support import (
    DEFAULT_USERS,
    LEGACY_CONFIG,
    PASSWORD,
    TEST_CONFIG,
    FakeClock,
    csrf,
    login,
    make_app,
    seed_users,
    stepup,
)
from crosscut_api.app import create_app
from crosscut_api.auth.lockout import failure_changes
from crosscut_api.auth.sessions import AuthConfig, SessionStore
from crosscut_api.auth.settings import (
    AuthSettings,
    AuthSettingsError,
    load_auth_config,
    load_auth_settings,
    parse_settings,
    settings_view,
    to_config,
)
from fastapi.testclient import TestClient

NEW_PASSWORD = "battery staple 42"


def _write(root: Path, data: dict[str, Any]) -> None:
    """Write ``<root>/_auth/config.json``."""
    path = root / "_auth" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_defaults_equal_previous_constants(tmp_path: Path) -> None:
    """A missing file gives exactly the built-in AuthConfig."""
    assert load_auth_config(tmp_path) == AuthConfig()
    assert to_config(AuthSettings()) == AuthConfig()
    assert AuthConfig().idle_timeout_s == 3600.0 and AuthConfig().stepup_valid_s == 300.0


def test_file_values_are_applied(tmp_path: Path) -> None:
    """File values override defaults and are converted to seconds."""
    _write(tmp_path, {"session_idle_minutes": 30, "session_absolute_hours": 8})
    config = load_auth_config(tmp_path)
    assert config.idle_timeout_s == 1800.0
    assert config.absolute_timeout_s == 8 * 3600.0


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("session_idle_minutes", 4),
        ("session_idle_minutes", 1441),
        ("session_absolute_hours", 0),
        ("session_absolute_hours", 73),
        ("stepup_valid_minutes", 31),
        ("lockout_failures", 2),
        ("password_min_length", 11),
        ("login_rate_per_ip_per_min", 0),
        ("secure_cookie", "maybe"),
        ("allowed_origins", ["not-an-origin"]),
        ("require_second_admin_for_password_reset", "yes"),
    ],
)
def test_out_of_bounds_values_are_refused_naming_the_field(
    tmp_path: Path, key: str, value: object
) -> None:
    """Values outside the schema bounds stop startup with the field name."""
    _write(tmp_path, {key: value})
    with pytest.raises(AuthSettingsError, match=key):
        load_auth_settings(tmp_path)


def test_lockout_max_below_base_is_refused() -> None:
    """lockout_max_minutes must not be smaller than lockout_base_minutes."""
    with pytest.raises(AuthSettingsError, match="lockout_max_minutes"):
        parse_settings({"lockout_base_minutes": 30, "lockout_max_minutes": 10})


def test_unknown_key_and_bad_file_are_refused(tmp_path: Path) -> None:
    """Unknown keys, invalid JSON and non-objects are startup errors."""
    _write(tmp_path, {"session_idle_minuts": 30})
    with pytest.raises(AuthSettingsError, match="session_idle_minuts"):
        load_auth_settings(tmp_path)
    (tmp_path / "_auth" / "config.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(AuthSettingsError, match="JSON object"):
        load_auth_settings(tmp_path)
    (tmp_path / "_auth" / "config.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(AuthSettingsError, match="cannot read"):
        load_auth_settings(tmp_path)


def test_create_app_refuses_invalid_settings(tmp_path: Path) -> None:
    """An invalid settings file stops create_app (startup refusal)."""
    _write(tmp_path, {"password_min_length": 5})
    with pytest.raises(AuthSettingsError, match="password_min_length"):
        create_app(tmp_path)


def test_settings_change_session_lifetime() -> None:
    """A shorter idle timeout from settings expires sessions earlier on the fake clock."""
    clock = FakeClock()
    config = to_config(AuthSettings(session_idle_minutes=10))
    store = SessionStore(config, clock)
    token, _ = store.create("op1", "127.0.0.1")
    clock.advance(9 * 60)
    assert store.get(token) is not None
    clock.advance(10 * 60 + 1)
    assert store.get(token) is None


def test_settings_change_stepup_and_lockout() -> None:
    """Step-up window and lockout threshold and duration follow the settings."""
    clock = FakeClock()
    config = to_config(
        AuthSettings(stepup_valid_minutes=1, lockout_failures=3, lockout_base_minutes=2)
    )
    store = SessionStore(config, clock)
    _, session = store.create("a", "ip")
    store.mark_stepup(session)
    clock.advance(61)
    assert not store.stepup_valid(session)
    user: dict[str, Any] = {}
    for _ in range(2):
        changes, locked = failure_changes(user, clock(), config)
        user.update(changes)
        assert not locked
    changes, locked = failure_changes(user, clock(), config)
    assert locked and "locked_until" in changes


class _Site:
    """Two administrators and a target user served by one app."""

    def __init__(self, root: Path, clock: FakeClock, config: AuthConfig) -> None:
        """Seed users and open stepped-up sessions for admin1 and admin2 on one app."""
        seed_users(root, {**DEFAULT_USERS, "lead1": ["lead"]})
        self.app = make_app(root, clock, config)
        self.clients: dict[str, tuple[TestClient, dict]] = {}
        for name in ("admin1", "admin2"):
            client = TestClient(self.app)
            payload = login(client, name)
            stepup(client, payload)
            self.clients[name] = (client, payload)

    def post(self, who: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """POST as ``who`` with its CSRF header."""
        client, payload = self.clients[who]
        return client.post(path, json=body or {}, headers=csrf(payload))

    def patch(self, who: str, path: str, body: dict[str, Any]) -> Any:
        """PATCH as ``who`` with its CSRF header."""
        client, payload = self.clients[who]
        return client.patch(path, json=body, headers=csrf(payload))


@pytest.fixture
def site(tmp_path: Path) -> _Site:
    """Return a site with the default two-person rule on."""
    return _Site(tmp_path, FakeClock(), TEST_CONFIG)


def test_password_reset_needs_second_admin(site: _Site) -> None:
    """admin1 requests, admin2 approves; the target can then sign in with the new password."""
    created = site.post("admin1", "/auth/users/op1/password-reset", {"password": NEW_PASSWORD})
    assert created.status_code == 202
    assert NEW_PASSWORD not in json.dumps(created.json())
    pending_id = created.json()["id"]
    old_login = TestClient(site.app).post(
        "/auth/login", json={"username": "op1", "password": PASSWORD}
    )
    assert old_login.status_code == 200
    approved = site.post("admin2", f"/auth/pending/{pending_id}/approve")
    assert approved.status_code == 200
    fresh = TestClient(site.app).post(
        "/auth/login", json={"username": "op1", "password": NEW_PASSWORD}
    )
    assert fresh.status_code == 200 and fresh.json()["must_change_password"] is True


def test_same_admin_cannot_approve_own_change(site: _Site) -> None:
    """The requester gets 403 on approve and the change stays pending."""
    pending_id = site.post(
        "admin1", "/auth/users/op1/password-reset", {"password": NEW_PASSWORD}
    ).json()["id"]
    assert site.post("admin1", f"/auth/pending/{pending_id}/approve").status_code == 403
    listing = site.clients["admin2"][0].get("/auth/pending").json()["pending"]
    assert [item["id"] for item in listing] == [pending_id]
    assert "changes" not in listing[0]


def test_approving_unknown_change_is_404(site: _Site) -> None:
    """An unknown or already used id gives 404."""
    assert site.post("admin2", "/auth/pending/nope/approve").status_code == 404
    pending_id = site.post(
        "admin1", "/auth/users/op1/password-reset", {"password": NEW_PASSWORD}
    ).json()["id"]
    assert site.post("admin2", f"/auth/pending/{pending_id}/approve").status_code == 200
    assert site.post("admin2", f"/auth/pending/{pending_id}/approve").status_code == 404


def test_direct_patch_password_is_refused_when_rule_on(site: _Site) -> None:
    """PATCH with a password for another user is refused while the rule is on."""
    response = site.patch("admin1", "/auth/users/op1", {"password": NEW_PASSWORD})
    assert response.status_code == 409
    assert "second_admin_required" in response.json()["detail"]


def test_sensitive_role_grant_is_pending_and_plain_grant_is_direct(site: _Site) -> None:
    """Granting lead (policy.pin and more) is held; granting operator-level roles is direct."""
    held = site.patch("admin1", "/auth/users/eng1", {"roles": ["lead"]})
    assert held.status_code == 202
    users = site.clients["admin2"][0].get("/auth/users/eng1").json()
    assert users["roles"] == ["engineer"]
    assert site.post("admin2", f"/auth/pending/{held.json()['id']}/approve").status_code == 200
    assert site.clients["admin2"][0].get("/auth/users/eng1").json()["roles"] == ["lead"]
    direct = site.patch("admin1", "/auth/users/view1", {"roles": ["operator"]})
    assert direct.status_code == 200


def test_rule_off_keeps_direct_behaviour(tmp_path: Path) -> None:
    """With require_second_admin off, resets and grants apply directly."""
    site = _Site(tmp_path, FakeClock(), LEGACY_CONFIG)
    assert site.patch("admin1", "/auth/users/op1", {"password": NEW_PASSWORD}).status_code == 200
    reset = site.post("admin1", "/auth/users/view1/password-reset", {"password": NEW_PASSWORD})
    assert reset.status_code == 200
    assert site.patch("admin1", "/auth/users/eng1", {"roles": ["lead"]}).status_code == 200


def test_settings_route_is_admin_only_and_shows_effective_values(site: _Site) -> None:
    """Admins read the effective settings; an operator gets 403; there is no write route."""
    client, payload = site.clients["admin1"]
    assert client.get("/auth/settings").json() == settings_view(TEST_CONFIG)
    operator = TestClient(site.app)
    login(operator, "op1")
    assert operator.get("/auth/settings").status_code == 403
    assert client.put("/auth/settings", json={}, headers=csrf(payload)).status_code == 405
    assert client.patch("/auth/settings", json={}, headers=csrf(payload)).status_code == 405


def test_public_config_exposes_only_flags(site: _Site) -> None:
    """GET /auth/config stays public and carries only the two non-sensitive flags."""
    body = TestClient(site.app).get("/auth/config").json()
    assert set(body) == {"auth_enabled", "initialised"}


def test_secure_cookie_modes(tmp_path: Path) -> None:
    """secure_cookie=true marks the cookie secure even over http; false never does."""
    seed_users(tmp_path, DEFAULT_USERS)
    for mode, expected in (("true", True), ("false", False)):
        config = to_config(AuthSettings(secure_cookie=mode), TEST_CONFIG)
        client = TestClient(make_app(tmp_path, FakeClock(), config))
        response = client.post("/auth/login", json={"username": "op1", "password": PASSWORD})
        assert ("secure" in response.headers["set-cookie"].lower()) is expected

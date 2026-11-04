"""Tests for Crosscut API authentication session handling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.auth.audit import AuthAudit, AuthAuditError, verify_chain
from crosscut_api.auth.lockout import (
    IpRateLimiter,
    failure_changes,
    is_locked,
    lock_remaining_s,
    success_changes,
)
from crosscut_api.auth.roles import load_roles
from crosscut_api.auth.sessions import AuthConfig, SessionStore, token_key


class FakeClock:
    """Fake clock for testing time-dependent behaviour."""

    def __init__(self, initial: float = 0.0):
        self._now = initial

    def now(self) -> float:
        """Return the current time."""
        return self._now

    def __call__(self) -> float:
        """Return the current time."""
        return self.now()

    def advance(self, seconds: float) -> None:
        """Advance the clock by seconds."""
        self._now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    """Fixture providing a fake clock."""
    return FakeClock()


@pytest.fixture
def auth_config() -> AuthConfig:
    """Fixture providing a default AuthConfig."""
    return AuthConfig()


@pytest.fixture
def session_store(fake_clock: FakeClock, auth_config: AuthConfig) -> SessionStore:
    """Fixture providing a SessionStore with a fake clock."""
    return SessionStore(auth_config, fake_clock)


def test_session_create(session_store: SessionStore, fake_clock: FakeClock) -> None:
    """Test that create generates distinct tokens, keys, CSRFs and SIDs."""
    token1, session1 = session_store.create("user1", "127.0.0.1")
    token2, session2 = session_store.create("user2", "127.0.0.2")

    assert token1 != token2
    assert session1.key == token_key(token1)
    assert session2.key == token_key(token2)
    assert session1.csrf != session2.csrf
    assert len(session1.sid) == 16
    assert session1.sid == session1.key[:16]


def test_session_get_updates_last_seen(session_store: SessionStore, fake_clock: FakeClock) -> None:
    """Test that get returns the session and updates last_seen."""
    token, session = session_store.create("user", "127.0.0.1")
    fake_clock.advance(100)
    retrieved = session_store.get(token)

    assert retrieved == session
    assert retrieved.last_seen == fake_clock.now()


def test_session_idle_expiry(session_store: SessionStore, fake_clock: FakeClock) -> None:
    """Test that sessions expire after idle timeout."""
    token, _ = session_store.create("user", "127.0.0.1")
    fake_clock.advance(3601)
    assert session_store.get(token) is None


def test_session_absolute_expiry(session_store: SessionStore, fake_clock: FakeClock) -> None:
    """Test that sessions expire after absolute timeout."""
    token, _ = session_store.create("user", "127.0.0.1")
    fake_clock.advance(43201)
    assert session_store.get(token) is None


def test_session_destroy(session_store: SessionStore, fake_clock: FakeClock) -> None:
    """Test that destroy removes the session."""
    token, _ = session_store.create("user", "127.0.0.1")
    session_store.destroy(token)
    assert session_store.get(token) is None


def test_session_destroy_user(session_store: SessionStore, fake_clock: FakeClock) -> None:
    """Test that destroy_user removes all sessions for a user except one."""
    token1, _ = session_store.create("user", "127.0.0.1")
    token2, _ = session_store.create("user", "127.0.0.2")
    removed = session_store.destroy_user("user", token_key(token1))
    assert removed == 1
    assert session_store.get(token1) is not None
    assert session_store.get(token2) is None


def test_stepup_validity(session_store: SessionStore, fake_clock: FakeClock) -> None:
    """Test that step-up authentication is valid for 300 seconds."""
    token, session = session_store.create("user", "127.0.0.1")
    session_store.mark_stepup(session)
    assert session_store.stepup_valid(session)
    fake_clock.advance(301)
    assert not session_store.stepup_valid(session)


def test_unknown_token_returns_none(session_store: SessionStore, fake_clock: FakeClock) -> None:
    """Test that unknown or None tokens return None."""
    assert session_store.get("unknown") is None
    assert session_store.get(None) is None


def test_lockout_behaviour(auth_config: AuthConfig, fake_clock: FakeClock) -> None:
    """Test that lockout occurs after 5 failures and resets on success."""
    user: dict[str, Any] = {"failed_logins": 0}
    for _ in range(4):
        changes, newly_locked = failure_changes(user, fake_clock.now(), auth_config)
        user.update(changes)
        assert not newly_locked
    changes, newly_locked = failure_changes(user, fake_clock.now(), auth_config)
    user.update(changes)
    assert newly_locked
    assert is_locked(user, fake_clock.now())
    assert lock_remaining_s(user, fake_clock.now()) == 300
    fake_clock.advance(301)
    assert not is_locked(user, fake_clock.now())
    assert user["failed_logins"] == 5
    for attempt in range(5):
        changes, newly_locked = failure_changes(user, fake_clock.now(), auth_config)
        user.update(changes)
        assert newly_locked == (attempt == 4)
    assert lock_remaining_s(user, fake_clock.now()) == 600
    user.update(success_changes())
    assert not is_locked(user, fake_clock.now())


def test_ip_rate_limiter(fake_clock: FakeClock) -> None:
    """Test that IpRateLimiter blocks after 20 requests per minute."""
    limiter = IpRateLimiter(20, 60, fake_clock)
    for _ in range(20):
        assert limiter.allow("127.0.0.1")
    assert not limiter.allow("127.0.0.1")
    fake_clock.advance(61)
    assert limiter.allow("127.0.0.1")


def test_roles_load_default(tmp_path: Path) -> None:
    """Test that load_roles(None) loads the default roles."""
    table = load_roles(None)
    assert len(table.roles) == 6
    assert "users.manage" in table.permissions_for(["admin"])
    assert "gw.propose" in table.permissions_for(["service"])
    both = table.permissions_for(["viewer", "service"])
    assert {"gw.view", "gw.propose"} <= both
    assert table.permissions_for(["unknown"]) == frozenset()


def test_roles_override_invalid(tmp_path: Path) -> None:
    """Test that an invalid override is ignored with a warning."""
    override_path = tmp_path / "_auth" / "roles.json"
    override_path.parent.mkdir(parents=True)
    override_path.write_text('{"roles": {"admin": {"permissions": ["gw.kill"]}}}')
    table = load_roles(tmp_path)
    assert table.source == "default"
    ignored = [w for w in table.warnings if w.startswith("roles override ignored")]
    assert len(ignored) == 1


def test_roles_override_valid(tmp_path: Path) -> None:
    """Test that a valid override is used."""
    default_path = Path(__file__).resolve().parents[2] / "schemas" / "auth-roles.default.json"
    data = json.loads(default_path.read_text(encoding="utf-8"))
    data["roles"]["admin"]["description"] = "Admin changed"
    for role_name in ("viewer", "admin"):
        perms = data["roles"][role_name]["permissions"]
        if "gw.reject" not in perms:
            perms.append("gw.reject")
    override_path = tmp_path / "_auth" / "roles.json"
    override_path.parent.mkdir(parents=True)
    override_path.write_text(json.dumps(data), encoding="utf-8")
    table = load_roles(tmp_path)
    assert table.source == "override"
    assert "gw.reject" in table.roles["admin"]


def test_audit_append_and_verify(tmp_path: Path, fake_clock: FakeClock) -> None:
    """Test that audit records are appended and verified."""
    audit_path = tmp_path / "audit.log"
    audit1 = AuthAudit(audit_path, fake_clock)
    audit2 = AuthAudit(audit_path, fake_clock)
    record1 = audit1.append("login", username="user1")
    record2 = audit2.append("logout", username="user1")
    assert verify_chain(audit1.records())
    assert audit1.records() == [record1, record2]


def test_audit_tamper_detection(tmp_path: Path, fake_clock: FakeClock) -> None:
    """Test that tampering with audit records is detected."""
    audit_path = tmp_path / "audit.log"
    audit = AuthAudit(audit_path, fake_clock)
    audit.append("login", username="user1")
    with audit_path.open("a", encoding="utf-8") as file:
        file.write(
            '{"seq": "1", "t_ns": "1000", "event": "logout", '
            '"prev_hash": "0000", "hash": "0000"}\n'
        )
    assert not verify_chain(audit.records())


def test_audit_reserved_key_rejected(tmp_path: Path, fake_clock: FakeClock) -> None:
    """Test that reserved keys are rejected."""
    audit_path = tmp_path / "audit.log"
    audit = AuthAudit(audit_path, fake_clock)
    with pytest.raises(AuthAuditError):
        audit.append("login", seq="1")


"""Server-side session store for Crosscut API authentication.

Provides an in-memory store for active sessions, handling token hashing,
expiration policies, and optional step-up authentication state. Designed
for single-process usage with thread safety.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from crosscut_api.auth.passwords import ScryptParams


def token_key(token: str) -> str:
    """Return the SHA-256 hex digest of a raw session token.

    Args:
        token: The raw token supplied to the client.

    Returns:
        Hexadecimal representation of the SHA-256 hash of `token`.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthConfig:
    """Configuration values for authentication and session handling.

    The defaults reflect common security recommendations.
    """
    scrypt: ScryptParams = field(default_factory=ScryptParams)
    min_password_length: int = 12
    idle_timeout_s: float = 3600.0
    absolute_timeout_s: float = 43200.0
    stepup_valid_s: float = 300.0
    max_failed_logins: int = 5
    lock_base_s: float = 300.0
    lock_max_s: float = 3600.0
    ip_rate_limit: int = 20
    ip_rate_window_s: float = 60.0
    allowed_origins: tuple[str, ...] = ()


@dataclass
class Session:
    """A user session representing an authenticated interaction.

    Attributes:
        key: SHA-256 hash (hex) of the raw session token.
        username: Username associated with the session.
        csrf: CSRF token for request validation.
        created: Epoch seconds when the session was created.
        last_seen: Epoch seconds of the last activity.
        ip: IP address from which the session originated.
        last_stepup: Epoch seconds of the most recent step-up authentication,
            or ``None`` if no step-up has occurred.
    """
    key: str
    username: str
    csrf: str
    created: float
    last_seen: float
    ip: str
    last_stepup: float | None = None

    @property
    def sid(self) -> str:
        """Return a short identifier derived from the session key.

        Uses the first 16 hexadecimal characters, which are sufficient for
        display or logging without exposing the full token hash.
        """
        return self.key[:16]


class SessionStore:
    """Thread-safe in-memory store for active user sessions.

    Sessions are indexed by the hash of their token. The store enforces
    idle and absolute expiration policies and provides utilities for step-up
    authentication tracking.
    """

    def __init__(self, config: AuthConfig, clock: Callable[[], float] = time.time):
        """Create a store with a given configuration and clock source.

        Args:
            config: Configuration values controlling expiration and limits.
            clock: Callable returning the current time in seconds since the epoch.
                Defaults to ``time.time``. Allows injection of deterministic clocks
                for testing.
        """
        self._config = config
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, username: str, ip: str) -> tuple[str, Session]:
        """Create a new session for a user.

        Generates a random token and CSRF token, stores the session, and returns
        the raw token together with the associated ``Session`` object.

        Args:
            username: Identifier of the authenticated user.
            ip: IP address from which the session originates.

        Returns:
            A tuple of (raw token, session). The raw token must be sent to the
            client; the stored session can be used for subsequent lookups.
        """
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = self._clock()
        session = Session(
            key=token_key(token),
            username=username,
            csrf=csrf,
            created=now,
            last_seen=now,
            ip=ip,
        )
        with self._lock:
            self._sessions[session.key] = session
        return token, session

    def get(self, token: str | None) -> Session | None:
        """Retrieve a session by its token, updating its last-seen timestamp.

        If the token is missing, unknown, or the session has expired (idle or
        absolute), the method returns ``None``. An expired session is removed
        from the store.

        Args:
            token: Raw token string supplied by the client.

        Returns:
            The matching ``Session`` if it is valid, otherwise ``None``.
        """
        if token is None:
            return None
        key = token_key(token)
        now = self._clock()
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            if self._is_expired(session, now):
                self._sessions.pop(key, None)
                return None
            session.last_seen = now
            return session

    def destroy(self, token: str | None) -> None:
        """Remove a session identified by its token.

        This operation is safe to call with ``None``; in that case it does nothing.

        Args:
            token: Raw token string or ``None``.
        """
        if token is None:
            return
        key = token_key(token)
        with self._lock:
            self._sessions.pop(key, None)

    def destroy_user(self, username: str, keep: str | None = None) -> int:
        """Delete all sessions belonging to ``username`` except optionally one.

        Args:
            username: The user whose sessions should be removed.
            keep: Optional session key (token_key hash) of a session to retain.

        Returns:
            The number of sessions deleted.
        """
        keep_key = keep
        deleted = 0
        with self._lock:
            keys_to_delete = [
                key
                for key, sess in self._sessions.items()
                if sess.username == username and key != keep_key
            ]
            for key in keys_to_delete:
                self._sessions.pop(key, None)
                deleted += 1
        return deleted

    def mark_stepup(self, session: Session) -> None:
        """Record the current time as the moment of step-up authentication.

        Args:
            session: The session to update.
        """
        now = self._clock()
        with self._lock:
            session.last_stepup = now

    def stepup_valid(self, session: Session) -> bool:
        """Check whether the session's step-up authentication is still valid.

        Returns:
            ``True`` if a step-up occurred within the configured validity window,
            otherwise ``False``.
        """
        now = self._clock()
        last = session.last_stepup
        return last is not None and (now - last) <= self._config.stepup_valid_s

    def count(self) -> int:
        """Return the number of active sessions stored."""
        with self._lock:
            return len(self._sessions)

    def _is_expired(self, session: Session, now: float) -> bool:
        """Determine whether a session is expired by idle or absolute timeout.

        Args:
            session: The session to evaluate.
            now: Current time from the store's clock.

        Returns:
            ``True`` if the session should be considered expired, otherwise
            ``False``.
        """
        idle_elapsed = now - session.last_seen
        absolute_elapsed = now - session.created
        return (
            idle_elapsed > self._config.idle_timeout_s
            or absolute_elapsed > self._config.absolute_timeout_s
        )

"""Lockout and IP rate-limit utilities for authentication.

Provides helpers for managing user lockout state after repeated failures
and a per-IP sliding-window rate limiter. Designed for in-memory use in
the Crosscut API server.
"""

from __future__ import annotations

import threading
import time
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from crosscut_api.auth.sessions import AuthConfig


def to_iso(ts: float) -> str:
    """Convert a POSIX timestamp to an ISO-8601 UTC string with a ``Z`` suffix.

    Args:
        ts: Seconds since the Unix epoch.

    Returns:
        A UTC timestamp formatted as ``YYYY-MM-DDTHH:MM:SSZ``.
    """
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(text: str) -> float:
    """Parse an ISO-8601 timestamp (``Z`` or offset) into a POSIX timestamp.

    Args:
        text: ISO-8601 datetime string, e.g. ``2026-11-03T10:00:00Z``.

    Returns:
        Seconds since the Unix epoch.
    """
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).timestamp()


def is_locked(user: dict[str, Any], now: float) -> bool:
    """Return ``True`` if the user's lock is still in effect.

    The ``locked_until`` field must be a UTC ISO-8601 string; ``None`` means
    the user is not locked.

    Args:
        user: Mapping containing a ``locked_until`` key.
        now: Current time as POSIX timestamp.

    Returns:
        ``True`` when the lock expiration is in the future, otherwise ``False``.
    """
    locked_until = user.get("locked_until")
    if not locked_until:
        return False
    return from_iso(locked_until) > now


def lock_remaining_s(user: dict[str, Any], now: float) -> float:
    """Return the remaining lock duration in seconds, or ``0.0`` if unlocked.

    Args:
        user: Mapping containing a ``locked_until`` key.
        now: Current time as POSIX timestamp.

    Returns:
        Non-negative seconds remaining on the lock.
    """
    locked_until = user.get("locked_until")
    if not locked_until:
        return 0.0
    remaining = from_iso(locked_until) - now
    return max(0.0, remaining)


def _lock_seconds(level: int, config: AuthConfig) -> float:
    """Calculate lock duration for a given failure level.

    The duration grows exponentially with the level, capped by ``config.lock_max_s``.

    Args:
        level: Failure level (1-based). ``1`` corresponds to the first lock.
        config: Authentication configuration.

    Returns:
        Lock duration in seconds.
    """
    # Exponential back-off: base * 2^(level-1), limited by max.
    factor = float(2 ** (level - 1))
    return min(config.lock_base_s * factor, config.lock_max_s)


def failure_changes(
    user: dict[str, Any],
    now: float,
    config: AuthConfig,
) -> tuple[dict[str, Any], bool]:
    """Update a user record after a failed login attempt.

    Returns a tuple ``(changes, newly_locked)`` where ``changes`` contains the
    fields that should be persisted to the user store. ``newly_locked`` signals
    whether this failure triggered a new lock.

    Args:
        user: Mapping containing ``failed_logins`` and ``locked_until`` fields.
        now: Current time as POSIX timestamp.
        config: Authentication configuration controlling lockout behaviour.

    Returns:
        A tuple of ``(changes, newly_locked)``.
    """
    failed = int(user.get("failed_logins", 0)) + 1
    changes: dict[str, Any] = {"failed_logins": failed}
    newly_locked = False

    if failed % config.max_failed_logins == 0:
        level = failed // config.max_failed_logins
        duration = _lock_seconds(level, config)
        changes["locked_until"] = to_iso(now + duration)
        newly_locked = True

    return changes, newly_locked


def success_changes() -> dict[str, Any]:
    """Return a changes mapping that resets failures and clears any lock.

    Use this result to update a user record after a successful authentication.

    Returns:
        Changes setting ``failed_logins`` to 0 and ``locked_until`` to ``None``.
    """
    return {"failed_logins": 0, "locked_until": None}


class IpRateLimiter:
    """Per-IP sliding-window rate limiter.

    Tracks request timestamps for each IP address and decides whether a new
    request is allowed based on ``limit`` requests per ``window_s`` seconds.
    """

    def __init__(
        self,
        limit: int,
        window_s: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Create a new rate limiter.

        Args:
            limit: Maximum number of requests allowed in the sliding window.
            window_s: Length of the sliding window in seconds.
            clock: Callable returning the current POSIX time. Defaults to ``time.time``.
        """
        self._limit = limit
        self._window = window_s
        self._clock = clock
        self._records: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, ip: str, now: float) -> None:
        """Remove timestamps older than the current sliding window for ``ip``."""
        timestamps = self._records.get(ip)
        if not timestamps:
            return
        cutoff = now - self._window
        timestamps[:] = [t for t in timestamps if t > cutoff]
        if not timestamps:
            self._records.pop(ip, None)

    def allow(self, ip: str) -> bool:
        """Determine whether a request from ``ip`` is permitted.

        The method updates the internal state: if the request is allowed, the
        current timestamp is recorded; otherwise the state is unchanged.

        Args:
            ip: The IP address of the incoming request.

        Returns:
            ``True`` if the request is within the limit, ``False`` otherwise.
        """
        now = self._clock()
        with self._lock:
            self._prune(ip, now)
            timestamps = self._records.setdefault(ip, [])
            if len(timestamps) >= self._limit:
                return False
            timestamps.append(now)
            return True


def normalise_username(name: str) -> str:
    """Return the canonical form of a username used as a lockout key.

    Args:
        name: Username as submitted by the client.

    Returns:
        The NFKC-normalised, whitespace-stripped, case-folded username.
    """
    return unicodedata.normalize("NFKC", name).strip().casefold()


MAX_TRACKED = 10_000


class AttemptTracker:
    """In-memory lockout state for usernames that have no account.

    Keeps at most ``MAX_TRACKED`` keys; the oldest inserted key is evicted first.
    """

    def __init__(self) -> None:
        """Create an empty tracker."""
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any]:
        """Return a shallow copy of the stored record for ``key``, or ``{}``."""
        with self._lock:
            return dict(self._records.get(key, {}))

    def record_failure(
        self,
        key: str,
        now: float,
        config: AuthConfig,
    ) -> tuple[dict[str, Any], bool]:
        """Apply a failed attempt to ``key`` and return ``(changes, newly_locked)``."""
        with self._lock:
            current = self._records.get(key, {})
            changes, newly_locked = failure_changes(current, now, config)
            if key not in self._records and len(self._records) >= MAX_TRACKED:
                self._records.pop(next(iter(self._records)))
            self._records.setdefault(key, {}).update(changes)
            return changes, newly_locked

    def clear(self, key: str) -> None:
        """Forget any lockout state held for ``key``."""
        with self._lock:
            self._records.pop(key, None)


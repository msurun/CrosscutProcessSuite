"""Pending two-person changes: password resets and sensitive role grants (ADR 013).

When ``require_second_admin_for_password_reset`` is on, these admin actions are stored
here and take effect only after a different administrator approves them. The store is
in memory: a restart drops every pending change, which is the safe direction.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

SENSITIVE_PERMISSIONS = frozenset({"policy.pin", "gw.kill.reset", "gw.mode.up.supervised"})
PENDING_TTL_S = 86400.0
KIND_PASSWORD_RESET = "password_reset"
KIND_ROLE_GRANT = "role_grant"


@dataclass(frozen=True)
class PendingChange:
    """One change waiting for a second administrator; ``changes`` may hold a password hash."""

    id: str
    kind: str
    target: str
    requested_by: str
    created: float
    changes: dict[str, Any] = field(repr=False)

    def public(self) -> dict[str, Any]:
        """Return the client view, without the stored changes."""
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "requested_by": self.requested_by,
            "created": self.created,
        }


class PendingStore:
    """Thread-safe in-memory store of pending changes with a time-to-live."""

    def __init__(self, clock: Callable[[], float], ttl_s: float = PENDING_TTL_S) -> None:
        """Create an empty store reading time from ``clock``."""
        self._clock = clock
        self._ttl = ttl_s
        self._items: dict[str, PendingChange] = {}
        self._lock = threading.Lock()

    def add(
        self, kind: str, target: str, requested_by: str, changes: dict[str, Any]
    ) -> PendingChange:
        """Store a new pending change and return it."""
        item = PendingChange(
            secrets.token_hex(8), kind, target, requested_by, self._clock(), dict(changes)
        )
        with self._lock:
            self._purge()
            self._items[item.id] = item
        return item

    def get(self, pending_id: str) -> PendingChange | None:
        """Return a live pending change, or ``None`` when unknown or expired."""
        with self._lock:
            self._purge()
            return self._items.get(pending_id)

    def remove(self, pending_id: str) -> None:
        """Forget a pending change."""
        with self._lock:
            self._items.pop(pending_id, None)

    def items(self) -> list[PendingChange]:
        """Return the live pending changes, oldest first."""
        with self._lock:
            self._purge()
            return sorted(self._items.values(), key=lambda item: item.created)

    def _purge(self) -> None:
        """Drop expired entries; the caller holds the lock."""
        cutoff = self._clock() - self._ttl
        for key in [k for k, v in self._items.items() if v.created < cutoff]:
            del self._items[key]

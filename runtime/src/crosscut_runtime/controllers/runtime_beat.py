"""Liveness beat of the runtime process itself (ADR 015).

Sent through the signed gateway mailbox at most every ``BEAT_PERIOD_S`` while the runtime hosts
controllers. The gateway treats a silent runtime as lost after ``LIVENESS_CYCLES`` periods and
releases what the controllers hold. No DCS access: the one DCS heartbeat stays the gateway's.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

BEAT_PERIOD_S = 10.0
LIVENESS_CYCLES = 3
RUNTIME_ID = "runtime"


class RuntimeBeat:
    """Rate-limited beat of the runtime process; inert without a sender factory."""

    def __init__(self, root: Path, clock: Callable[[], float], factory: Any | None) -> None:
        """Bind the root, the clock and the sender factory ``(root, id, kind) -> send``."""
        self._root, self._clock, self._factory = root, clock, factory
        self._send: Any = None
        self._last_s: float | None = None
        self._count = 0

    def maybe_send(self, hosting_controllers: bool) -> bool:
        """Send a beat when due and controllers are hosted; True when one was sent."""
        if self._factory is None or not hosting_controllers:
            return False
        now = self._clock()
        if self._last_s is not None and now - self._last_s < BEAT_PERIOD_S:
            return False
        if self._send is None:
            self._send = self._factory(self._root, RUNTIME_ID, "runtime")
        self._last_s, self._count = now, self._count + 1
        self._send(
            "runtime", RUNTIME_ID, "running", self._count, BEAT_PERIOD_S, LIVENESS_CYCLES, []
        )
        return True

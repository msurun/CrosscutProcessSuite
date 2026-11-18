"""Liveness of the runtime and of its controllers, judged by the gateway (ADR 015).

The runtime process and each controller send a beat through the signed file mailbox. A beat
names the sender, its state, a cycle count, its ``cycle_s`` and ``liveness_cycles``. The
monitor keeps the newest beat per sender; a sender is *expired* when no beat arrived within
``liveness_cycles x cycle_s``. A controller that is not ``on`` and holds nothing is never
*lost*: silence of an idle controller is not an alarm. Pure bookkeeping: no I/O, no plant.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from crosscut_gateway.interfaces import WritePolicy

KIND_RUNTIME = "runtime"
KIND_CONTROLLER = "controller"
KINDS = (KIND_RUNTIME, KIND_CONTROLLER)
MIN_LIVENESS_CYCLES = 2
MIN_WATCHDOG_FACTOR = 2.0
ON_STATE = "on"
NS_PER_S = 1_000_000_000
Holds = Callable[[str], bool]


class LivenessError(ValueError):
    """A beat the gateway refuses (bad shape, or a watchdog shorter than two controller cycles)."""


@dataclass(frozen=True)
class Beat:
    """One liveness beat: ``kind`` runtime or controller, sender id, state, cycle count."""

    kind: str
    sender: str
    state: str
    cycles: int
    cycle_s: float
    liveness_cycles: int
    targets: tuple[str, ...] = ()

    @property
    def timeout_ns(self) -> int:
        """Silence after which the sender is expired."""
        return int(self.liveness_cycles * self.cycle_s * NS_PER_S)


def parse_beat(args: Mapping[str, Any]) -> Beat:
    """Build a Beat from mailbox arguments; LivenessError when a field is out of range."""
    kind, cycle_s = args["kind"], float(args["cycle_s"])
    cycles = int(args["liveness_cycles"])
    if kind not in KINDS:
        raise LivenessError(f"liveness: unknown kind {kind!r}")
    if cycle_s <= 0 or cycles < MIN_LIVENESS_CYCLES:
        raise LivenessError("liveness: cycle_s must be > 0 and liveness_cycles >= 2")
    targets = tuple(args["targets"])
    return Beat(kind, args["id"], str(args["state"]), int(args["count"]), cycle_s, cycles, targets)


def watchdog_problems(beat: Beat, policies: Mapping[str, WritePolicy]) -> list[str]:
    """Targets of the beat whose ``watchdog_s`` is below two controller cycles."""
    limit = MIN_WATCHDOG_FACTOR * beat.cycle_s
    return [
        f"{tag}: watchdog_s {policies[tag].watchdog_s} < 2 x cycle_s {beat.cycle_s}"
        for tag in beat.targets
        if tag in policies and policies[tag].watchdog_s < limit
    ]


@dataclass
class _Entry:
    """The newest beat of one sender and whether its loss was already handled."""

    beat: Beat
    last_ns: int
    handled: bool = False


class LivenessMonitor:
    """Newest beat per sender and the loss decision."""

    def __init__(self) -> None:
        """Start empty: a gateway restart forgets every beat (and holds nothing either)."""
        self._entries: dict[tuple[str, str], _Entry] = {}

    def record(self, beat: Beat, now_ns: int) -> None:
        """Remember a beat; a new beat clears an earlier loss."""
        self._entries[(beat.kind, beat.sender)] = _Entry(beat, now_ns)

    def newly_lost(self, now_ns: int, holds: Holds) -> list[tuple[str, str]]:
        """Senders to treat as lost now; each loss is reported once until the next beat.

        ``holds(sender_id)`` tells whether a controller holds a target at the gateway.
        """
        lost: list[tuple[str, str]] = []
        runtime_gone = self._runtime_expired(now_ns)
        for key, entry in self._entries.items():
            if entry.handled or not self._is_lost(key, entry, now_ns, runtime_gone, holds):
                continue
            entry.handled = True
            lost.append(key)
        return lost

    def view(self, now_ns: int, holds: Holds) -> dict[str, Any]:
        """Read-only view for the gateway state: age, state and lost flag per sender."""
        runtime_gone = self._runtime_expired(now_ns)
        rows = {
            key: self._row(entry, now_ns, self._is_lost(key, entry, now_ns, runtime_gone, holds))
            for key, entry in self._entries.items()
        }
        runtime = [row for (kind, _), row in rows.items() if kind == KIND_RUNTIME]
        controllers = {s: row for (kind, s), row in rows.items() if kind == KIND_CONTROLLER}
        return {"runtime": runtime[0] if runtime else None, "controllers": controllers}

    def controller_ids(self) -> list[str]:
        """Controllers that have beaten at least once."""
        return [sender for kind, sender in self._entries if kind == KIND_CONTROLLER]

    def _runtime_expired(self, now_ns: int) -> bool:
        """True when a known runtime process has gone silent for too long."""
        return any(
            self._expired(e, now_ns)
            for (kind, _), e in self._entries.items()
            if kind == KIND_RUNTIME
        )

    @staticmethod
    def _expired(entry: _Entry, now_ns: int) -> bool:
        """True when the silence exceeds ``liveness_cycles x cycle_s``."""
        return now_ns - entry.last_ns > entry.beat.timeout_ns

    def _is_lost(
        self, key: tuple[str, str], entry: _Entry, now_ns: int, runtime_gone: bool, holds: Holds
    ) -> bool:
        """Expired (or its runtime is) and either ``on``/holding, or the runtime process itself."""
        kind, sender = key
        if kind == KIND_RUNTIME:
            return self._expired(entry, now_ns) and self._anything_active(holds)
        silent = self._expired(entry, now_ns) or runtime_gone
        return silent and (entry.beat.state == ON_STATE or holds(sender))

    def _anything_active(self, holds: Holds) -> bool:
        """True when some known controller is ``on`` or holds a target."""
        return any(
            e.beat.state == ON_STATE or holds(s)
            for (kind, s), e in self._entries.items()
            if kind == KIND_CONTROLLER
        )

    @staticmethod
    def _row(entry: _Entry, now_ns: int, lost: bool) -> dict[str, Any]:
        """One row of the view."""
        return {
            "state": entry.beat.state,
            "count": entry.beat.cycles,
            "cycle_s": entry.beat.cycle_s,
            "liveness_cycles": entry.beat.liveness_cycles,
            "age_s": round(max(0, now_ns - entry.last_ns) / NS_PER_S, 3),
            "lost": lost,
        }


def holders_of(holding: Mapping[str, bool], holder: Mapping[str, str], sender: str) -> list[str]:
    """Targets currently held by ``controller:<sender>``."""
    name = f"controller:{sender}"
    return [tag for tag, held in holding.items() if held and holder.get(tag) == name]

"""Interfaces of the write gateway (ADR 011): proposals, policy, decisions and three Protocols.

Types only. No behaviour, no connectivity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WriteProposal:
    """A request from an analysis package to change one setpoint (data, never a call)."""

    target_tag: str
    value: float
    proposer: str
    t_ns: int
    reason: str


@dataclass(frozen=True)
class WritePolicy:
    """Per-target write policy (schema ``write-policy``); anything outside it is refused."""

    limits: tuple[float, float]
    max_step: float
    max_rate_per_s: float
    min_interval_s: float
    allowed_loop_modes: tuple[str, ...]
    hold_off_s: float
    watchdog_s: float
    readback_tolerance: float


@dataclass(frozen=True)
class ParamPolicy:
    """Per-target policy of one PID parameter (schema ``write-policy``, kind ``pid_param``).

    Out-of-range values are refused, never clamped. Units: ``limits`` and
    ``readback_tolerance`` in the unit ``unit``; ``max_ratio`` dimensionless (> 1);
    ``min_interval_s`` in seconds.
    """

    loop: str
    param: str
    unit: str
    vendor_form: str
    limits: tuple[float, float]
    max_ratio: float
    readback_tolerance: float
    min_interval_s: float
    allowed_loop_modes: tuple[str, ...]


@dataclass(frozen=True)
class ParamItem:
    """One parameter change: ``from_value`` read live from the DCS, ``to_value`` proposed.

    Both values are in ``unit``. ``target`` is the policy target tag it is written to.
    """

    param: str
    target: str
    unit: str
    vendor_form: str
    from_value: float
    to_value: float


@dataclass(frozen=True)
class ParamSetProposal:
    """An atomic set of parameter changes of one loop (data, never a call).

    ``t_ns`` and ``expires_ns`` are UTC nanoseconds; ``rollback_of`` is the id of the
    reverted proposal or None.
    """

    proposal_id: str
    loop_id: str
    items: tuple[ParamItem, ...]
    proposer: str
    t_ns: int
    expires_ns: int
    reason: str
    rollback_of: str | None = None


@dataclass(frozen=True)
class WriteDecision:
    """Outcome of a proposal: accepted or not, a stable reason code, the value actually used."""

    accepted: bool
    reason_code: str
    clamped_value: float | None = None


class ControlSystem(Protocol):
    """The control system as the gateway sees it: what any adapter, simulated or real,
    implements."""

    def read(self, tag: str) -> float:
        """Current value of a tag."""
        ...

    def write(self, tag: str, value: float) -> bool:
        """Write a setpoint; False if the control system refuses (bad status);
        ConnectionError/TimeoutError on transport failure."""
        ...

    def heartbeat_seen(self) -> bool:
        """True while the control system sees the gateway heartbeat."""
        ...

    def send_heartbeat(self) -> None:
        """Gateway heartbeat towards the control system."""
        ...

    def loop_mode(self, tag: str) -> str:
        """Current mode of the loop owning ``tag``."""
        ...

    def setpoint_source(self, tag: str) -> str:
        """``"local"`` or ``"remote"``: who currently owns the setpoint."""
        ...

    def release(self, tag: str) -> None:
        """Hand the setpoint of ``tag`` back to local control."""
        ...


class SimControlSystem(ControlSystem, Protocol):
    """Simulator-only extension with operator actions."""

    def set_mode_by_operator(self, tag: str, mode: str) -> None:
        """An operator changes the loop mode."""
        ...

    def set_setpoint_by_operator(self, tag: str, value: float) -> None:
        """An operator changes the setpoint."""
        ...


class Gateway(Protocol):
    """The write gateway: the only component allowed to write to a control system."""

    def propose(self, proposal: WriteProposal) -> WriteDecision:
        """Validate a proposal against the policy; write, or log only in dry run."""
        ...

    def tick(self, now_ns: int) -> None:
        """One gateway cycle: heartbeat, read-back, watchdog, hold-off, kill switch."""
        ...

    def kill(self) -> None:
        """Kill switch: stop all writing and hand setpoints back; honoured within one tick."""
        ...

    def status(self) -> dict[str, str]:
        """Per-target state (mode, enabled, reason of the last stop)."""
        ...

    def audit_records(self) -> list[dict[str, str]]:
        """Append-only audit records (proposals, decisions, writes) in order."""
        ...

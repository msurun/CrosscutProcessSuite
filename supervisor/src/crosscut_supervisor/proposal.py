"""Pure translation from supervisor advice to setpoint write proposals (ADR 014, section 7).

This module bridges the advisory supervisor with the Write Gateway setpoint propose
contract. It converts an Advice record into a SetpointProposal payload without performing
any network I/O or direct control system writes (pure function design).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crosscut_supervisor.advise import Advice


@dataclass(frozen=True)
class SetpointProposal:
    """A setpoint write proposal created from supervisor advice (ADR 014 section 7).

    Attributes:
        target_tag: Setpoint tag name in the DCS or plant (e.g. 'FIC101.SP').
        value: Absolute target setpoint value in physical engineering units (e.g. t/h, %).
        proposer: Identity of the proposing agent or supervisor (e.g. 'supervisor:mill_feed').
        t_ns: UTC nanosecond timestamp of the advice evaluation.
        reason: Human-readable explanation sentence describing why the setpoint is moved.
        advice_id: Hex-encoded SHA-256 identifier of the source advice.
    """

    target_tag: str
    value: float
    proposer: str
    t_ns: int
    reason: str
    advice_id: str

    def to_gateway_args(self) -> dict[str, Any]:
        """Convert to the argument structure accepted by the Write Gateway 'propose' command."""
        return {
            "target_tag": self.target_tag,
            "value": self.value,
            "proposer": self.proposer,
            "t_ns": self.t_ns,
            "reason": self.reason,
        }


def signed_change(advice: Advice) -> float | None:
    """Compute the signed engineering setpoint adjustment from an advice record.

    # In plain words:
    An advisory supervisor evaluates fuzzy rules to suggest whether a setpoint should
    increase, decrease, or hold. If the advice is 'hold' or carries no magnitude (e.g.
    due to a blocked gate or silent band), no adjustment is warranted. When an increase
    is advised, the delta is positive; when a decrease is advised, the delta is negative.

    Args:
        advice: Evaluated supervisor advice record.

    Returns:
        Signed setpoint delta in engineering units, or None if no move is advised.
    """
    if advice.direction == "hold" or advice.magnitude is None or advice.magnitude <= 0.0:
        return None
    return advice.magnitude if advice.direction == "increase" else -advice.magnitude


def _format_reason(advice: Advice) -> str:
    """Extract or format an intuitive reason string from the advice explanation."""
    if advice.explanation:
        return advice.explanation[0].sentence
    return f"Supervisor {advice.target_loop} advice: {advice.direction} {advice.magnitude}"


def build_setpoint_proposal(
    advice: Advice,
    current_sp: float,
    target_tag: str,
    proposer: str | None = None,
) -> SetpointProposal | None:
    """Build a SetpointProposal from an advice record and the current setpoint value.

    # In plain words:
    The fuzzy supervisor calculates an incremental change (delta), but the Write Gateway
    and DCS setpoint controllers expect an absolute target setpoint value. This function
    adds the signed delta to the current setpoint, constructs an auditable reason from
    the dominant fuzzy rule, and binds the supervisor's identifier.

    Args:
        advice: Evaluated supervisor advice.
        current_sp: Current setpoint read from the plant or dataset in engineering units.
        target_tag: Tag address of the setpoint target.
        proposer: Optional proposer string (defaults to 'supervisor:<target_loop>').

    Returns:
        SetpointProposal ready for submission to Write Gateway, or None if advice is hold.
    """
    delta_sp = signed_change(advice)
    if delta_sp is None:
        return None

    new_sp_value = current_sp + delta_sp
    effective_proposer = proposer or f"supervisor:{advice.target_loop}"
    reason_text = _format_reason(advice)

    return SetpointProposal(
        target_tag=target_tag,
        value=new_sp_value,
        proposer=effective_proposer,
        t_ns=advice.t_ns,
        reason=reason_text,
        advice_id=advice.advice_id,
    )

"""Pure translation from supervisor advice to setpoint write proposals (ADR 014, section 7).

This module bridges the advisory supervisor with the Write Gateway setpoint propose
contract. It converts an Advice record into a SetpointProposal payload without performing
any network I/O or direct control system writes (pure function design).
"""

from __future__ import annotations

import math
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
        t_ns: UTC nanosecond timestamp of the real send time.
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


class ProposalRefusal(ValueError):
    """A proposal that must not be sent; ``code`` is the stable machine-readable reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


REASON_MAX_CHARS = 300


@dataclass(frozen=True)
class ProposalContext:
    """Live facts a proposal is built from: the live setpoint read from the plant, never a guess.

    Attributes:
        live_sp: Setpoint read live from the plant or gateway just now.
        target_tag: Setpoint tag from the supervisor config or site catalogue.
        proposer: Identity written to the gateway audit.
        max_step: Largest allowed absolute setpoint move (config max_step).
        t_ns: Real send time in nanoseconds (the gateway min_interval needs it).
    """

    live_sp: float
    target_tag: str
    proposer: str
    max_step: float
    t_ns: int


def advice_reason(advice_id: str, sentence: str) -> str:
    """Audit reason that links the gateway record to the advice: ``advice:<id> <sentence>``."""
    return f"advice:{advice_id} {sentence}"[:REASON_MAX_CHARS]


def checked_value(live_sp: float, delta: float, max_step: float) -> float:
    """The new setpoint ``live_sp + delta`` after the safety checks.

    Raises:
        ProposalRefusal: ``delta_too_large`` above max_step, ``sign_mismatch`` when the move
            does not go the way of the advice (or inputs are not finite).
    """
    if not (math.isfinite(live_sp) and math.isfinite(delta)):
        raise ProposalRefusal("sign_mismatch")
    if abs(delta) > max_step:
        raise ProposalRefusal("delta_too_large")
    value = live_sp + delta
    if math.copysign(1.0, value - live_sp) != math.copysign(1.0, delta) or value == live_sp:
        raise ProposalRefusal("sign_mismatch")
    return value


def build_from_delta(
    advice_id: str, delta: float, sentence: str, ctx: ProposalContext
) -> SetpointProposal:
    """Proposal moving the live setpoint by ``delta`` (raises ProposalRefusal when unsafe)."""
    return SetpointProposal(
        target_tag=ctx.target_tag,
        value=checked_value(ctx.live_sp, delta, ctx.max_step),
        proposer=ctx.proposer,
        t_ns=ctx.t_ns,
        reason=advice_reason(advice_id, sentence),
        advice_id=advice_id,
    )


def _format_reason(advice: Advice) -> str:
    """Extract or format an intuitive reason string from the advice explanation."""
    if advice.explanation:
        return advice.explanation[0].sentence
    return f"Supervisor {advice.target_loop} advice: {advice.direction} {advice.magnitude}"


def build_setpoint_proposal(advice: Advice, ctx: ProposalContext) -> SetpointProposal | None:
    """Build a SetpointProposal from an advice and the live context; None when advice is hold.

    # In plain words:
    The supervisor advises an incremental change, the gateway wants an absolute setpoint.
    The delta is added to the LIVE setpoint only (ctx.live_sp), never to a historical value.

    Raises:
        ProposalRefusal: when the move is above max_step or goes the wrong way.
    """
    delta_sp = signed_change(advice)
    if delta_sp is None:
        return None
    return build_from_delta(advice.advice_id, delta_sp, _format_reason(advice), ctx)

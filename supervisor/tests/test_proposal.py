"""Unit tests for supervisor setpoint proposal generation (ADR 014, section 7).

Pure translation from Advice records into SetpointProposal payloads; the live setpoint, the
step limit and the sign check are part of the contract.
"""

from __future__ import annotations

import pytest
from crosscut_supervisor.advise import Advice, Reason
from crosscut_supervisor.gates import GateResult
from crosscut_supervisor.proposal import (
    ProposalContext,
    ProposalRefusal,
    SetpointProposal,
    build_from_delta,
    build_setpoint_proposal,
    checked_value,
    signed_change,
)

NOW_NS = 1_700_000_000_000_000_000


def _make_advice(
    direction: str = "increase",
    magnitude: float | None = 5.0,
    explanation: tuple[Reason, ...] = (),
) -> Advice:
    """Helper to construct a valid Advice record for testing."""
    return Advice(
        advice_id="test-advice-id-1234", t_ns=NOW_NS, target_loop="mill_feed",
        direction=direction, magnitude=magnitude, activation=0.85, explanation=explanation,
        inputs={"load": 120.0}, gate=GateResult(state="open", reasons=()),
        rulebase_sha256="abc123sha",
    )


def _ctx(live_sp: float = 150.0, max_step: float = 20.0, proposer: str = "supervisor:x") -> (
    ProposalContext
):
    return ProposalContext(live_sp, "FIC101.SP", proposer, max_step, NOW_NS + 5)


def test_signed_change_signs() -> None:
    assert signed_change(_make_advice("increase", 4.5)) == 4.5
    assert signed_change(_make_advice("decrease", 3.2)) == -3.2
    assert signed_change(_make_advice("hold", None)) is None
    assert signed_change(_make_advice("increase", 0.0)) is None


def test_build_adds_delta_to_live_sp_and_links_advice_in_reason() -> None:
    reason = Reason("r1", "IF load IS low THEN feed IS up", 0.9)
    proposal = build_setpoint_proposal(_make_advice(magnitude=10.0, explanation=(reason,)), _ctx())
    assert proposal is not None
    assert proposal.value == 160.0
    assert proposal.t_ns == NOW_NS + 5
    assert proposal.reason == "advice:test-advice-id-1234 IF load IS low THEN feed IS up"
    assert proposal.advice_id == "test-advice-id-1234"


def test_decrease_moves_down_and_uses_context_proposer() -> None:
    proposal = build_setpoint_proposal(_make_advice("decrease", 8.0), _ctx(proposer="op:a"))
    assert proposal is not None and proposal.value == 142.0 and proposal.proposer == "op:a"


def test_hold_returns_none() -> None:
    assert build_setpoint_proposal(_make_advice("hold", None), _ctx()) is None


def test_delta_above_max_step_is_refused() -> None:
    with pytest.raises(ProposalRefusal) as error:
        build_setpoint_proposal(_make_advice(magnitude=21.0), _ctx(max_step=20.0))
    assert error.value.code == "delta_too_large"


@pytest.mark.parametrize("live", [float("nan"), float("inf")])
def test_non_finite_live_sp_is_refused(live: float) -> None:
    with pytest.raises(ProposalRefusal):
        checked_value(live, 1.0, 5.0)


def test_move_lost_to_float_rounding_is_a_sign_mismatch() -> None:
    with pytest.raises(ProposalRefusal) as error:
        checked_value(1e18, 1.0, 5.0)
    assert error.value.code == "sign_mismatch"


def test_reason_is_truncated() -> None:
    proposal = build_from_delta("a1", 1.0, "x" * 1000, _ctx())
    assert len(proposal.reason) == 300 and proposal.reason.startswith("advice:a1 ")


def test_to_gateway_args_formatting() -> None:
    proposal = SetpointProposal("FIC101.SP", 155.0, "supervisor:m", 1, "Test", "adv123")
    assert proposal.to_gateway_args() == {
        "target_tag": "FIC101.SP", "value": 155.0, "proposer": "supervisor:m",
        "t_ns": 1, "reason": "Test",
    }

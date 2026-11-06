"""Unit tests for supervisor setpoint proposal generation (ADR 014, section 7).

Tests pure translation from Advice records into SetpointProposal payloads and gateway arguments.
"""

from __future__ import annotations

from crosscut_supervisor.advise import Advice, Reason
from crosscut_supervisor.gates import GateResult
from crosscut_supervisor.proposal import (
    SetpointProposal,
    build_setpoint_proposal,
    signed_change,
)


def _make_advice(
    direction: str = "increase",
    magnitude: float | None = 5.0,
    explanation: tuple[Reason, ...] = (),
) -> Advice:
    """Helper to construct a valid Advice record for testing."""
    return Advice(
        advice_id="test-advice-id-1234",
        t_ns=1_700_000_000_000_000_000,
        target_loop="mill_feed",
        direction=direction,
        magnitude=magnitude,
        activation=0.85,
        explanation=explanation,
        inputs={"load": 120.0},
        gate=GateResult(state="open", reasons=()),
        rulebase_sha256="abc123sha",
    )


def test_signed_change_returns_positive_for_increase() -> None:
    advice = _make_advice(direction="increase", magnitude=4.5)
    assert signed_change(advice) == 4.5


def test_signed_change_returns_negative_for_decrease() -> None:
    advice = _make_advice(direction="decrease", magnitude=3.2)
    assert signed_change(advice) == -3.2


def test_signed_change_returns_none_for_hold() -> None:
    advice = _make_advice(direction="hold", magnitude=None)
    assert signed_change(advice) is None


def test_signed_change_returns_none_for_zero_or_negative_magnitude() -> None:
    advice = _make_advice(direction="increase", magnitude=0.0)
    assert signed_change(advice) is None


def test_build_setpoint_proposal_for_increase() -> None:
    reason = Reason("r1", "IF load IS low THEN feed change IS increase_large", 0.9)
    advice = _make_advice(direction="increase", magnitude=10.0, explanation=(reason,))

    proposal = build_setpoint_proposal(
        advice=advice,
        current_sp=150.0,
        target_tag="FIC101.SP",
    )
    assert proposal is not None
    assert proposal.target_tag == "FIC101.SP"
    assert proposal.value == 160.0
    assert proposal.proposer == "supervisor:mill_feed"
    assert proposal.t_ns == advice.t_ns
    assert proposal.reason == "IF load IS low THEN feed change IS increase_large"
    assert proposal.advice_id == "test-advice-id-1234"


def test_build_setpoint_proposal_for_decrease_with_custom_proposer() -> None:
    advice = _make_advice(direction="decrease", magnitude=8.0)
    proposal = build_setpoint_proposal(
        advice=advice,
        current_sp=150.0,
        target_tag="FIC101.SP",
        proposer="operator:alice",
    )
    assert proposal is not None
    assert proposal.value == 142.0
    assert proposal.proposer == "operator:alice"
    assert proposal.reason == "Supervisor mill_feed advice: decrease 8.0"


def test_build_setpoint_proposal_returns_none_when_hold() -> None:
    advice = _make_advice(direction="hold", magnitude=None)
    proposal = build_setpoint_proposal(advice, 150.0, "FIC101.SP")
    assert proposal is None


def test_to_gateway_args_formatting() -> None:
    proposal = SetpointProposal(
        target_tag="FIC101.SP",
        value=155.0,
        proposer="supervisor:mill_feed",
        t_ns=1_000_000_000,
        reason="Test reason",
        advice_id="adv123",
    )
    args = proposal.to_gateway_args()
    assert args == {
        "target_tag": "FIC101.SP",
        "value": 155.0,
        "proposer": "supervisor:mill_feed",
        "t_ns": 1_000_000_000,
        "reason": "Test reason",
    }

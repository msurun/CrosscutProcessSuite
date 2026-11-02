"""Unit tests for stateless write policy validation and clamping (Phase 2, #46).

Verifies reason codes, priority ordering of policy checks, table-driven clamp
mechanics across limits/steps/rates, proposal idempotency keys, and randomized invariants.
"""

from __future__ import annotations

import math
import random

import pytest
from crosscut_gateway.interfaces import WritePolicy, WriteProposal
from crosscut_gateway.policy import (
    PolicyError,
    policy_from_dict,
    proposal_key,
    validate_proposal,
)

TAG = "LIC101.SP"
ONE_SECOND_NS = 1_000_000_000

TEST_POLICY = WritePolicy(
    limits=(0.0, 100.0),
    max_step=10.0,
    max_rate_per_s=5.0,
    min_interval_s=1.0,
    allowed_loop_modes=("AUTO", "CAS"),
    hold_off_s=30.0,
    watchdog_s=5.0,
    readback_tolerance=0.5,
)


def _make_proposal(value: float, t_ns: int = 1_000_000_000, reason: str = "test") -> WriteProposal:
    """Helper creating a test WriteProposal with default arguments."""
    return WriteProposal(
        target_tag=TAG,
        value=value,
        proposer="supervisor_agent",
        t_ns=t_ns,
        reason=reason,
    )


# --- Reason Code Tests ---


def test_refuse_when_policy_is_none() -> None:
    """Refuse proposal with reason code no_policy when target has no configured policy."""
    prop = _make_proposal(50.0)
    decision = validate_proposal(None, prop, last_value=50.0, last_write_t_ns=None, loop_mode="CAS")
    assert not decision.accepted
    assert decision.reason_code == "no_policy"
    assert decision.clamped_value is None


def test_refuse_when_value_is_nan() -> None:
    """Refuse proposal with reason code bad_value when proposed value is NaN."""
    prop = _make_proposal(math.nan)
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=50.0, last_write_t_ns=None, loop_mode="CAS"
    )
    assert not decision.accepted
    assert decision.reason_code == "bad_value"


def test_refuse_when_value_is_infinite() -> None:
    """Refuse with reason code bad_value when proposed value is positive or negative inf."""
    for inf_val in (math.inf, -math.inf):
        prop = _make_proposal(inf_val)
        decision = validate_proposal(
            TEST_POLICY, prop, last_value=50.0, last_write_t_ns=None, loop_mode="CAS"
        )
        assert not decision.accepted
        assert decision.reason_code == "bad_value"


def test_refuse_when_loop_mode_is_not_allowed() -> None:
    """Refuse proposal with reason code mode_not_allowed when loop is in MAN or unsupported mode."""
    prop = _make_proposal(55.0)
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=50.0, last_write_t_ns=None, loop_mode="MAN"
    )
    assert not decision.accepted
    assert decision.reason_code == "mode_not_allowed"


def test_refuse_when_clock_moves_backwards() -> None:
    """Refuse proposal with reason code clock_backwards when proposal timestamp is in the past."""
    prop = _make_proposal(55.0, t_ns=ONE_SECOND_NS)
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=50.0, last_write_t_ns=ONE_SECOND_NS + 100, loop_mode="CAS"
    )
    assert not decision.accepted
    assert decision.reason_code == "clock_backwards"


def test_refuse_when_within_minimum_write_interval() -> None:
    """Refuse proposal with reason code min_interval when elapsed time is below min_interval_s."""
    last_write = ONE_SECOND_NS
    too_early = last_write + int(0.5 * ONE_SECOND_NS)  # 0.5s elapsed, policy requires 1.0s
    prop = _make_proposal(55.0, t_ns=too_early)
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=50.0, last_write_t_ns=last_write, loop_mode="CAS"
    )
    assert not decision.accepted
    assert decision.reason_code == "min_interval"


def test_refuse_when_proposal_causes_no_setpoint_change() -> None:
    """Refuse proposal with reason code no_change when target setpoint is already at proposal."""
    prop = _make_proposal(50.0, t_ns=2 * ONE_SECOND_NS)
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=50.0, last_write_t_ns=ONE_SECOND_NS, loop_mode="CAS"
    )
    assert not decision.accepted
    assert decision.reason_code == "no_change"


def test_accept_proposal_unmodified_with_reason_ok() -> None:
    """Accept proposal with reason code ok and clamped_value=None when inside all constraints."""
    prop = _make_proposal(54.0, t_ns=2 * ONE_SECOND_NS)
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=50.0, last_write_t_ns=ONE_SECOND_NS, loop_mode="CAS"
    )
    assert decision.accepted
    assert decision.reason_code == "ok"
    assert decision.clamped_value is None


def test_accept_proposal_clamped_with_reason_clamped() -> None:
    """Accept proposal with reason code clamped when restricted by engineering limits or step."""
    prop = _make_proposal(80.0, t_ns=3 * ONE_SECOND_NS)
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=50.0, last_write_t_ns=ONE_SECOND_NS, loop_mode="CAS"
    )
    assert decision.accepted
    assert decision.reason_code == "clamped"
    assert decision.clamped_value == 60.0  # max_step=10 restricts 50 -> 60


# --- Priority Rule Tests ---


def test_priority_no_policy_beats_bad_value() -> None:
    """Verify Priority 1: Missing policy check precedes proposal value check."""
    prop = _make_proposal(math.nan)
    decision = validate_proposal(None, prop, last_value=50.0, last_write_t_ns=None, loop_mode="CAS")
    assert decision.reason_code == "no_policy"


def test_priority_bad_value_beats_mode_not_allowed() -> None:
    """Verify Priority 2: Invalid numeric value check precedes allowed loop mode check."""
    prop = _make_proposal(math.nan)
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=50.0, last_write_t_ns=None, loop_mode="MAN"
    )
    assert decision.reason_code == "bad_value"


def test_priority_mode_not_allowed_beats_clock_backwards() -> None:
    """Verify Priority 3: Loop mode check precedes clock timestamp check."""
    prop = _make_proposal(55.0, t_ns=ONE_SECOND_NS)
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=50.0, last_write_t_ns=ONE_SECOND_NS + 100, loop_mode="MAN"
    )
    assert decision.reason_code == "mode_not_allowed"


def test_priority_clock_backwards_beats_min_interval() -> None:
    """Verify Priority 4: Backwards clock check precedes minimum interval check."""
    prop = _make_proposal(55.0, t_ns=ONE_SECOND_NS - 50)
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=50.0, last_write_t_ns=ONE_SECOND_NS, loop_mode="CAS"
    )
    assert decision.reason_code == "clock_backwards"


def test_priority_min_interval_beats_clamping() -> None:
    """Verify Priority 5: Minimum interval check precedes value clamping and calculation."""
    last_write = ONE_SECOND_NS
    too_early = last_write + int(0.2 * ONE_SECOND_NS)
    prop = _make_proposal(500.0, t_ns=too_early)  # Out of limits, but timing fails first
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=50.0, last_write_t_ns=last_write, loop_mode="CAS"
    )
    assert decision.reason_code == "min_interval"
    assert not decision.accepted


# --- Table-Driven Clamp Tests (>= 15 cases) ---


@pytest.mark.parametrize(
    (
        "last_val",
        "last_t_ns",
        "prop_val",
        "prop_t_ns",
        "expected_accepted",
        "expected_reason",
        "expected_clamped",
    ),
    [
        # 1. Limit hi clamp without prior setpoint
        (None, None, 150.0, ONE_SECOND_NS, True, "clamped", 100.0),
        # 2. Limit lo clamp without prior setpoint
        (None, None, -25.0, ONE_SECOND_NS, True, "clamped", 0.0),
        # 3. Normal value without prior setpoint
        (None, None, 42.0, ONE_SECOND_NS, True, "ok", None),
        # 4. Step up clamp (dt large, step is bottleneck)
        (50.0, ONE_SECOND_NS, 80.0, 10 * ONE_SECOND_NS, True, "clamped", 60.0),
        # 5. Step down clamp (dt large, step is bottleneck)
        (50.0, ONE_SECOND_NS, 20.0, 10 * ONE_SECOND_NS, True, "clamped", 40.0),
        # 6. Rate up clamp (dt=1s allows 5.0, step allows 10.0)
        (50.0, ONE_SECOND_NS, 60.0, 2 * ONE_SECOND_NS, True, "clamped", 55.0),
        # 7. Rate down clamp (dt=1s allows -5.0, step allows -10.0)
        (50.0, ONE_SECOND_NS, 40.0, 2 * ONE_SECOND_NS, True, "clamped", 45.0),
        # 8. Limit beats step and rate (last near hi limit)
        (95.0, ONE_SECOND_NS, 120.0, 5 * ONE_SECOND_NS, True, "clamped", 100.0),
        # 9. Limit beats step and rate (last near lo limit)
        (5.0, ONE_SECOND_NS, -30.0, 5 * ONE_SECOND_NS, True, "clamped", 0.0),
        # 10. Rate beats step and limit (dt=1.2s -> rate change 6.0)
        (50.0, ONE_SECOND_NS, 70.0, int(2.2 * ONE_SECOND_NS), True, "clamped", 56.0),
        # 11. Step beats rate and limit (dt=5s -> rate allows 25, step allows 10)
        (50.0, ONE_SECOND_NS, 70.0, 6 * ONE_SECOND_NS, True, "clamped", 60.0),
        # 12. Exact boundary on hi limit
        (90.0, ONE_SECOND_NS, 100.0, 3 * ONE_SECOND_NS, True, "ok", None),
        # 13. Exact boundary on lo limit
        (10.0, ONE_SECOND_NS, 0.0, 3 * ONE_SECOND_NS, True, "ok", None),
        # 14. No previous write (last_write_t_ns None): step clamp applies, rate skipped
        (50.0, None, 70.0, ONE_SECOND_NS, True, "clamped", 60.0),
        # 15. Negative step clamp below lower limit boundary
        (5.0, None, -10.0, ONE_SECOND_NS, True, "clamped", 0.0),
        # 16. Proposal equals last_value (no setpoint change)
        (50.0, ONE_SECOND_NS, 50.0, 2 * ONE_SECOND_NS, False, "no_change", None),
        # 17. Clamped step equals last_value when last_value at hi boundary
        (100.0, ONE_SECOND_NS, 120.0, 2 * ONE_SECOND_NS, False, "no_change", None),
    ],
)
def test_table_driven_clamping_scenarios(
    last_val: float | None,
    last_t_ns: int | None,
    prop_val: float,
    prop_t_ns: int,
    expected_accepted: bool,
    expected_reason: str,
    expected_clamped: float | None,
) -> None:
    """Validate comprehensive matrix of clamping constraints against expected decisions."""
    prop = _make_proposal(prop_val, t_ns=prop_t_ns)
    decision = validate_proposal(
        TEST_POLICY, prop, last_value=last_val, last_write_t_ns=last_t_ns, loop_mode="CAS"
    )
    assert decision.accepted == expected_accepted
    assert decision.reason_code == expected_reason
    if expected_clamped is None:
        assert decision.clamped_value is None
    else:
        assert decision.clamped_value == pytest.approx(expected_clamped)


# --- Property-Style Randomized Invariants Test ---


def test_property_randomized_proposals_satisfy_invariants() -> None:
    """Property test over 500 pseudo-random proposals verifying physical invariants."""
    # In plain words: We generate 500 varied proposals and confirm that whenever the gateway
    # accepts, the target setpoint strictly respects hard limits, step, and rate bounds.
    rng = random.Random(1234)
    last_val = 50.0
    last_t_ns = ONE_SECOND_NS

    for _ in range(500):
        val = rng.uniform(-50.0, 150.0)
        dt_s = rng.uniform(1.0, 10.0)  # Always >= min_interval_s to test clamping mechanics
        t_ns = last_t_ns + int(dt_s * ONE_SECOND_NS)
        prop = _make_proposal(val, t_ns=t_ns)

        decision = validate_proposal(
            TEST_POLICY, prop, last_value=last_val, last_write_t_ns=last_t_ns, loop_mode="CAS"
        )
        if decision.accepted:
            effective = decision.clamped_value if decision.clamped_value is not None else prop.value
            # Invariant 1: Inside hard engineering limits
            assert TEST_POLICY.limits[0] <= effective <= TEST_POLICY.limits[1]
            # Invariant 2: Jump never exceeds max_step
            step = abs(effective - last_val)
            assert step <= TEST_POLICY.max_step + 1e-9
            # Invariant 3: Velocity never exceeds max_rate_per_s
            rate_allowed = TEST_POLICY.max_rate_per_s * dt_s
            assert step <= rate_allowed + 1e-9
            last_val = effective
            last_t_ns = t_ns


# --- Proposal Key Tests ---


def test_proposal_key_is_stable_and_deterministic() -> None:
    """Proposal key produces identical SHA-256 hex across repeated calls with identical data."""
    prop1 = _make_proposal(42.5, t_ns=1000, reason="Optimization cycle 1")
    prop2 = _make_proposal(42.5, t_ns=1000, reason="Optimization cycle 1")
    assert proposal_key(prop1) == proposal_key(prop2)
    assert len(proposal_key(prop1)) == 64


def test_proposal_key_is_insensitive_to_reason() -> None:
    """Proposal key ignores reason string so idempotent re-submissions match."""
    prop1 = _make_proposal(42.5, t_ns=1000, reason="Reason A")
    prop2 = _make_proposal(42.5, t_ns=1000, reason="Reason B")
    assert proposal_key(prop1) == proposal_key(prop2)


def test_proposal_key_is_sensitive_to_semantic_fields() -> None:
    """Proposal key changes when tag, value, proposer, or timestamp differ."""
    base = _make_proposal(42.5, t_ns=1000)
    key_base = proposal_key(base)

    diff_tag = WriteProposal("OTHER.SP", 42.5, "supervisor_agent", 1000, "test")
    diff_val = _make_proposal(42.6, t_ns=1000)
    diff_user = WriteProposal(TAG, 42.5, "operator_manual", 1000, "test")
    diff_time = _make_proposal(42.5, t_ns=1001)

    assert proposal_key(diff_tag) != key_base
    assert proposal_key(diff_val) != key_base
    assert proposal_key(diff_user) != key_base
    assert proposal_key(diff_time) != key_base


# --- Policy From Dict Tests ---


def test_policy_from_dict_rejects_inverted_limits() -> None:
    """Raise PolicyError naming the target when limits[0] > limits[1]."""
    raw = {
        "FIC101.SP": {
            "limits": [100.0, 50.0],  # Inverted!
            "max_step": 5.0,
            "max_rate_per_s": 2.0,
            "min_interval_s": 1.0,
            "allowed_loop_modes": ["CAS"],
            "hold_off_s": 10.0,
            "watchdog_s": 5.0,
            "readback_tolerance": 0.5,
        }
    }
    with pytest.raises(PolicyError, match=r"Target 'FIC101\.SP'.*limits\[0\].*>.*limits\[1\]"):
        policy_from_dict(raw)


def test_policy_from_dict_rejects_booleans_in_numerical_fields() -> None:
    """Raise PolicyError when boolean is supplied for numeric fields (e.g. max_step=True)."""
    raw = {
        "FIC101.SP": {
            "limits": [0.0, 100.0],
            "max_step": True,  # Booleans are not numbers
            "max_rate_per_s": 2.0,
            "min_interval_s": 1.0,
            "allowed_loop_modes": ["CAS"],
            "hold_off_s": 10.0,
            "watchdog_s": 5.0,
            "readback_tolerance": 0.5,
        }
    }
    with pytest.raises(PolicyError, match=r"Target 'FIC101\.SP': max_step must be a number"):
        policy_from_dict(raw)


def test_policy_from_dict_rejects_missing_field() -> None:
    """Raise PolicyError naming the target when a required target field is missing."""
    raw = {
        "FIC101.SP": {
            "limits": [0.0, 100.0],
            "max_rate_per_s": 2.0,
            "min_interval_s": 1.0,
            "allowed_loop_modes": ["CAS"],
            "hold_off_s": 10.0,
            "watchdog_s": 5.0,
            "readback_tolerance": 0.5,
            # max_step is missing
        }
    }
    expected_err = r"Target 'FIC101\.SP': missing required field 'max_step'"
    with pytest.raises(PolicyError, match=expected_err):
        policy_from_dict(raw)

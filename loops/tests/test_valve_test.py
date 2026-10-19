"""
Tests for the guided valve stroke test: plan construction, operator procedure,
and analysis of the PV response of a simulated valve with backlash.

The records are built directly in the tests, with no simulator: a staircase OP
drives a small backlash model, and PV is an instantaneous process on top of it.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.valve_test import (
    StrokePlan,
    analyze_stroke_test,
    plan_stroke_test,
    procedure_text,
)

DWELL_S = 30
OP_START = 50.0
GAIN = 2.0


def _backlash(op: np.ndarray, deadband: float) -> np.ndarray:
    """Return the valve position for an OP command, following a backlash model.

    The position p stays put inside a band of total width `deadband` around the
    command c: p only moves when the command leaves the band, and then lands on
    its edge. This yields a reversal deadband equal to `deadband`.
    """
    position = np.empty_like(op)
    p = float(op[0])
    half = deadband / 2.0
    for i, c in enumerate(op):
        if c > p + half:
            p = c - half
        elif c < p - half:
            p = c + half
        position[i] = p
    return position


def _record(
    plan: StrokePlan,
    valve_positions_fn,
    gain: float = GAIN,
    noise: float = 0.0,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build (t_s, op, pv) for a plan: staircase OP, valve model, instant process.

    Each segment is held for `dwell_s` samples at 1 s per sample; the initial hold
    at `op_start` comes first, then one hold per plan step. PV = 50 + gain *
    (valve - op_start) + noise.
    """
    op_values: list[float] = [plan.op_start] * plan.dwell_s
    for step in plan.steps:
        op_values.extend([step.op_target] * step.dwell_s)
    op = np.array(op_values, dtype=float)
    t_s = np.arange(len(op), dtype=float)
    valve = valve_positions_fn(op)
    rng = np.random.default_rng(seed)
    pv = 50.0 + gain * (valve - plan.op_start) + rng.normal(0.0, noise, size=len(op))
    return t_s, op, pv


def _default_plan() -> StrokePlan:
    """Return the default plan starting at 50 % with a 30 s dwell."""
    return plan_stroke_test(op_start=OP_START, dwell_s=DWELL_S)


def test_default_plan_has_forty_eight_steps():
    """The default plan builds 3*4 + 3*12 = 48 operator steps."""
    plan = _default_plan()
    assert len(plan.steps) == 48


def test_first_step_targets_fifty_one_percent():
    """The first step of the default plan moves up by 1 % from 50 %."""
    plan = _default_plan()
    assert plan.steps[0].op_target == pytest.approx(51.0)


def test_step_after_the_first_leg_follows_a_reversal():
    """The first step of the second leg comes right after a direction change."""
    plan = _default_plan()
    assert plan.steps[4].after_reversal is True


def test_all_targets_stay_within_output_range():
    """Every plan target lies within [0, 100] % of span for the default plan."""
    plan = _default_plan()
    targets = [step.op_target for step in plan.steps]
    assert min(targets) >= 0.0
    assert max(targets) <= 100.0


def test_plan_raises_when_targets_leave_the_range():
    """A start of 99 % pushes targets above the high limit, so planning fails."""
    with pytest.raises(ValueError):
        plan_stroke_test(op_start=99.0, dwell_s=DWELL_S)


def test_plan_raises_on_zero_dwell():
    """A zero dwell time is rejected."""
    with pytest.raises(ValueError):
        plan_stroke_test(op_start=OP_START, dwell_s=0)


def test_plan_raises_on_length_mismatch():
    """step_sizes and steps_per_leg must have equal lengths."""
    with pytest.raises(ValueError):
        plan_stroke_test(
            op_start=OP_START,
            dwell_s=DWELL_S,
            step_sizes=(1.0, 0.25),
            steps_per_leg=(4,),
        )


def test_procedure_starts_in_manual_and_ends_in_auto():
    """The operator procedure opens with MANUAL and closes with AUTO."""
    lines = procedure_text(_default_plan())
    assert "MANUAL" in lines[0]
    assert "AUTO" in lines[-1]


def test_procedure_has_one_line_per_step_plus_framing():
    """There are len(steps) + 4 lines: MANUAL, abort rule, start hold, return and AUTO."""
    plan = _default_plan()
    lines = procedure_text(plan)
    assert len(lines) == len(plan.steps) + 4


def test_procedure_mentions_abort_when_a_band_is_set():
    """A plan with an abort band adds one line telling the operator to abort."""
    plan = plan_stroke_test(op_start=OP_START, dwell_s=DWELL_S, pv_band=5.0)
    lines = procedure_text(plan)
    assert any("abort" in line for line in lines)


def test_healthy_valve_has_small_deadband_and_unit_gain():
    """A valve with no backlash reports a tiny deadband and gain near 2.0."""
    plan = _default_plan()
    t_s, op, pv = _record(plan, lambda cmd: _backlash(cmd, 0.0))
    result = analyze_stroke_test(t_s, op, pv, plan)
    assert result.deadband is not None
    assert result.deadband <= 0.25
    assert result.gain == pytest.approx(GAIN, rel=0.01)


def test_healthy_valve_resolves_the_smallest_step():
    """With no backlash the 0.25 % steps all move, certifying resolution."""
    plan = _default_plan()
    t_s, op, pv = _record(plan, lambda cmd: _backlash(cmd, 0.0))
    result = analyze_stroke_test(t_s, op, pv, plan)
    assert result.resolution_le == 0.25


def test_backlash_bracket_contains_the_true_deadband():
    """A 0.8 % backlash is bracketed and estimated within 0.25 %."""
    plan = _default_plan()
    t_s, op, pv = _record(plan, lambda cmd: _backlash(cmd, 0.8))
    result = analyze_stroke_test(t_s, op, pv, plan)
    assert result.deadband_bracket is not None
    lower, upper = result.deadband_bracket
    assert lower < 0.8 <= upper + 1e-9
    assert abs(result.deadband - 0.8) <= 0.25


def test_backlash_estimate_survives_noise_and_negative_gain():
    """A 2.0 % backlash with gain -1.5 and noise 0.02 is estimated within 0.25 %."""
    plan = _default_plan()
    t_s, op, pv = _record(
        plan, lambda cmd: _backlash(cmd, 2.0), gain=-1.5, noise=0.02, seed=1
    )
    result = analyze_stroke_test(t_s, op, pv, plan)
    assert abs(result.deadband - 2.0) <= 0.25


def test_a_valve_that_never_moves_reports_no_gain():
    """A flat PV hides the valve motion, so gain is None with a reason."""
    plan = _default_plan()
    t_s, op, _ = _record(plan, lambda cmd: _backlash(cmd, 0.0))
    rng = np.random.default_rng(0)
    pv = 50.0 + rng.normal(0.0, 1e-6, size=len(op))
    result = analyze_stroke_test(t_s, op, pv, plan)
    assert result.gain is None
    assert result.reason.startswith("no gain")


def test_pv_left_band_is_true_when_pv_exceeds_the_band():
    """A PV that swings by 2 units trips a 0.5 unit abort band."""
    plan = plan_stroke_test(op_start=OP_START, dwell_s=DWELL_S, pv_band=0.5)
    t_s, op, pv = _record(plan, lambda cmd: _backlash(cmd, 0.0), gain=1.0)
    result = analyze_stroke_test(t_s, op, pv, plan)
    assert result.pv_left_band is True


def test_pv_left_band_is_false_without_a_band():
    """With pv_band None the abort check is skipped and never trips."""
    plan = _default_plan()
    t_s, op, pv = _record(plan, lambda cmd: _backlash(cmd, 0.0), gain=1.0)
    result = analyze_stroke_test(t_s, op, pv, plan)
    assert result.pv_left_band is False


def test_analyze_raises_when_op_and_pv_lengths_differ():
    """Mismatched record lengths are rejected with a ValueError."""
    plan = _default_plan()
    t_s, op, pv = _record(plan, lambda cmd: _backlash(cmd, 0.0))
    with pytest.raises(ValueError):
        analyze_stroke_test(t_s, op, pv[:-1], plan)


def _ramped(op: np.ndarray, samples: int) -> np.ndarray:
    """Replace every OP step by a linear ramp over `samples` samples (a rate-limited DCS)."""
    out = op.copy()
    for k in np.flatnonzero(np.diff(op) != 0.0) + 1:
        start, stop = float(op[k - 1]), float(op[k])
        span = min(samples, len(op) - k)
        out[k : k + span] = start + (stop - start) * np.arange(1, span + 1) / samples
    return out


def test_ramped_steps_still_bracket_the_deadband():
    """Steps executed as 6-sample ramps (review finding 1) still give the 0.8 % bracket."""
    plan = _default_plan()
    t_s, op, _ = _record(plan, lambda o: _backlash(o, 0.8))
    op = _ramped(op, 6)
    pv = 50.0 + GAIN * (_backlash(op, 0.8) - plan.op_start)
    result = analyze_stroke_test(t_s, op, pv, plan)
    assert result.deadband is not None and abs(result.deadband - 0.8) <= 0.25


def test_op_noise_does_not_invent_reversals():
    """OP noise of std 0.05 % (review finding 2) leaves the healthy-valve estimate small."""
    plan = _default_plan()
    t_s, op, _ = _record(plan, lambda o: o)
    op = op + np.random.default_rng(3).normal(0.0, 0.05, size=len(op))
    pv = 50.0 + GAIN * (op - plan.op_start)
    result = analyze_stroke_test(t_s, op, pv, plan)
    assert result.deadband is not None and result.deadband <= 0.25


def test_nan_in_record_is_rejected():
    """A NaN sample raises ValueError instead of giving a silent wrong answer (finding 4)."""
    plan = _default_plan()
    t_s, op, pv = _record(plan, lambda o: o)
    pv[100] = np.nan
    with pytest.raises(ValueError):
        analyze_stroke_test(t_s, op, pv, plan)

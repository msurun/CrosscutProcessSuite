"""Check the economic steady-state target on small linear programs with known optima.

Priority over economics, determinism and the zero-value identity are tested through the
public API, not solver internals.
"""

from dataclasses import replace

import numpy as np
import pytest
from crosscut_mpc import (
    Controller,
    CycleInputs,
    Economics,
    neutral,
    steady_economic_target,
    steady_target,
)
from mpc_helpers import make_controller

GAINS = [[1.0, 1.0], [1.0, -1.0]]


def economic(controller: Controller, **fields: object) -> Controller:
    """Attach economics with the given vector fields on top of a neutral block."""
    base = neutral(len(controller.limits.cv_lower), len(controller.limits.mv_lower))
    return replace(controller, economics=replace(base, **fields))


def inputs(targets: list[float]) -> CycleInputs:
    """Zero measurements and actual MVs with the given CV targets."""
    return CycleInputs(np.zeros(2), np.zeros(2), np.array(targets))


def test_economic_target_picks_the_higher_value_vertex() -> None:
    controller = economic(make_controller(GAINS, cv_upper=[20.0, 20.0], cv_lower=[-20.0, -20.0]),
                          cv_value=np.array([1.0, 0.0]))
    target = steady_economic_target(controller, inputs([0.0, 0.0]), np.zeros(2))
    assert target.solution.values == pytest.approx([5.0, 5.0], abs=1e-4)
    assert target.report is not None and target.report.benefit_rate == pytest.approx(10.0, abs=1e-4)
    assert {(b.kind, b.index, b.side) for b in target.report.binding} == {
        ("mv", 0, "upper"), ("mv", 1, "upper")}


def test_cv_limit_binds_with_shadow_price_and_ties_go_toward_targets() -> None:
    controller = economic(make_controller(GAINS, cv_upper=[6.0, 20.0], cv_lower=[-20.0, -20.0]),
                          cv_value=np.array([2.0, 0.0]))
    target = steady_economic_target(controller, inputs([0.0, 0.0]), np.zeros(2))
    # y1=u1+u2 <= 6 is optimal along a face; y2=u1-u2 is free and its target 0 breaks the tie.
    assert target.solution.values == pytest.approx([3.0, 3.0], abs=1e-3)
    cv_rows = [b for b in target.report.binding if b.kind == "cv"]  # type: ignore[union-attr]
    assert [(b.index, b.side, b.limit) for b in cv_rows] == [(0, "upper", "hard")]
    assert cv_rows[0].shadow_price == pytest.approx(2.0, abs=1e-4)


def test_tie_break_is_deterministic() -> None:
    controller = economic(make_controller(GAINS, cv_upper=[6.0, 20.0], cv_lower=[-20.0, -20.0]),
                          cv_value=np.array([2.0, 0.0]))
    first = steady_economic_target(controller, inputs([0.0, 2.0]), np.zeros(2))
    second = steady_economic_target(controller, inputs([0.0, 2.0]), np.zeros(2))
    assert first.solution.values is not None
    assert np.array_equal(first.solution.values, second.solution.values)
    assert first.solution.values == pytest.approx([4.0, 2.0], abs=1e-3)


def test_zero_values_equal_setpoint_tracking() -> None:
    controller = economic(make_controller(GAINS))
    target = steady_economic_target(controller, inputs([1.0, 0.5]), np.zeros(2))
    plain = steady_target(controller, inputs([1.0, 0.5]), np.zeros(2))
    assert target.report is None
    assert target.solution.values == pytest.approx(plain.values, abs=1e-9)


def test_mv_cost_pulls_the_mv_down() -> None:
    controller = economic(make_controller([[1.0]], cv_upper=[4.0], cv_lower=[-4.0]),
                          cv_value=np.array([1.0]), mv_cost=np.array([3.0]))
    target = steady_economic_target(controller, CycleInputs(np.zeros(1), np.zeros(1), np.zeros(1)),
                                    np.zeros(1))
    # Each MV unit earns 1 and costs 3 (net -2): the optimum is the lowest u the CV band allows.
    assert target.solution.values == pytest.approx([-4.0], abs=1e-4)


def test_hard_limits_are_never_violated() -> None:
    controller = economic(make_controller(GAINS, cv_upper=[2.0, 1.0], cv_lower=[-2.0, -1.0]),
                          cv_value=np.array([5.0, 4.0]), mv_cost=np.array([-1.0, 0.5]))
    target = steady_economic_target(controller, inputs([0.0, 0.0]), np.zeros(2))
    values = target.solution.values
    assert values is not None
    cvs = np.asarray(GAINS) @ values
    assert np.all(cvs <= controller.limits.cv_upper + 2e-5)
    assert np.all(cvs >= controller.limits.cv_lower - 2e-5)
    assert np.all(np.abs(values) <= 5.0 + 2e-5)


def test_priority_is_not_traded_for_value() -> None:
    # One MV drives both CVs with gain 1. CV0 (priority 1) must stay in [-1, 1]; CV1 (priority 2)
    # wants [2, 4] and carries all the value. Value must not push CV0 out of its band.
    controller = economic(
        make_controller([[1.0], [1.0]], cv_lower=[-1.0, 2.0], cv_upper=[1.0, 4.0]),
        cv_value=np.array([0.0, 10.0]))
    single = CycleInputs(np.zeros(2), np.zeros(1), np.zeros(2))
    target = steady_economic_target(controller, single, np.zeros(2))
    assert target.solution.values == pytest.approx([1.0], abs=1e-4)
    assert target.solution.relaxed == (1,)
    assert target.report is not None and target.report.status == "optimal"


def test_soft_limits_back_off_the_optimum_and_fall_back_when_infeasible() -> None:
    wide = make_controller([[1.0]], cv_upper=[8.0], cv_lower=[-8.0])
    soft = economic(wide, cv_value=np.array([1.0]), cv_soft_upper=np.array([2.0]))
    single = CycleInputs(np.zeros(1), np.zeros(1), np.zeros(1))
    backed = steady_economic_target(soft, single, np.zeros(1))
    assert backed.solution.values == pytest.approx([2.0], abs=1e-4)
    assert backed.report is not None and backed.report.soft_limits_applied
    assert [(b.kind, b.limit) for b in backed.report.binding] == [("cv", "soft")]
    # A bias of -9 puts the whole reachable CV range below the soft limit: it is unusable.
    tight = steady_economic_target(soft, single, np.array([-9.0]))
    assert tight.solution.values is not None


def test_economics_dimensions_are_validated() -> None:
    controller = make_controller(GAINS)
    with pytest.raises(ValueError, match="match"):
        Controller(controller.model, controller.limits, controller.settings, neutral(3, 2))
    with pytest.raises(ValueError, match="Soft lower"):
        Economics(np.zeros(1), np.zeros(1), np.array([2.0]), np.array([1.0]),
                  np.full(1, -np.inf), np.full(1, np.inf))

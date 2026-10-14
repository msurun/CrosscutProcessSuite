"""Behaviour of the series cascade planner in crosscut_loops.cascade.

Each test pins one decision the planner makes: the separation formula, the SIMC
settings of both loops, and the warnings that guard against bad time-scale ratios.
"""

from __future__ import annotations

import dataclasses

import pytest
from crosscut_loops.cascade import (
    MIN_SEPARATION,
    RECOMMENDED_SEPARATION,
    CascadePlan,
    plan_cascade,
    time_scale_separation,
)
from crosscut_loops.tuning_rules import FopdtModel, simc_pi


def test_separation_divides_the_outer_time_constant_by_the_inner_one():
    assert time_scale_separation(2.0, 20.0) == pytest.approx(10.0)


@pytest.mark.parametrize("inner_tau", [0.0, -1.0])
def test_a_non_positive_inner_time_constant_is_rejected(inner_tau):
    with pytest.raises(ValueError):
        time_scale_separation(inner_tau, 20.0)


@pytest.mark.parametrize("outer_tau", [0.0, -1.0])
def test_a_non_positive_outer_time_constant_is_rejected(outer_tau):
    with pytest.raises(ValueError):
        time_scale_separation(2.0, outer_tau)


def _example_plan(separation: float = RECOMMENDED_SEPARATION) -> CascadePlan:
    inner = FopdtModel(1.0, 5.0, 2.0)
    outer = FopdtModel(2.0, 60.0, 8.0)
    return plan_cascade(inner, outer, separation)


def test_the_inner_loop_is_commissioned_before_the_outer_loop():
    assert _example_plan().order == ("inner", "outer")


def test_the_inner_closed_loop_time_constant_is_the_inner_delay():
    assert _example_plan().tau_c_inner_s == pytest.approx(2.0)


def test_the_inner_settings_match_simc_tuned_on_the_inner_delay():
    plan = _example_plan()
    assert plan.inner == simc_pi(FopdtModel(1.0, 5.0, 2.0), 2.0)


def test_the_outer_closed_loop_time_constant_respects_the_default_separation():
    assert _example_plan().tau_c_outer_s == pytest.approx(20.0)


def test_the_outer_settings_match_simc_tuned_on_the_outer_time_constant():
    plan = _example_plan()
    assert plan.outer == simc_pi(FopdtModel(2.0, 60.0, 8.0), 20.0)


def test_the_default_plan_achieves_the_recommended_separation_without_warnings():
    plan = _example_plan()
    assert plan.separation == pytest.approx(10.0)
    assert plan.warnings == ()


def test_a_slow_outer_delay_raises_the_achieved_separation_above_the_request():
    plan = _example_plan(separation=2.0)
    assert plan.tau_c_outer_s == pytest.approx(8.0)
    assert plan.separation == pytest.approx(MIN_SEPARATION)
    assert any("below 4" in warning for warning in plan.warnings)


def test_a_fast_outer_process_still_warns_about_the_requested_separation():
    inner = FopdtModel(1.0, 5.0, 2.0)
    plan = plan_cascade(inner, FopdtModel(1.0, 5.0, 1.0), separation=1.0)
    assert plan.separation == pytest.approx(1.0)
    assert len(plan.warnings) == 2


def test_a_very_slow_outer_loop_warns_to_tune_the_inner_loop_tighter():
    plan = _example_plan(separation=30.0)
    assert any("tune the inner loop" in warning for warning in plan.warnings)


@pytest.mark.parametrize("separation", [0.0, -1.0])
def test_a_non_positive_separation_is_rejected(separation):
    with pytest.raises(ValueError):
        _example_plan(separation)


def test_a_cascade_plan_cannot_be_modified_after_it_is_built():
    plan = _example_plan()
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.separation = 1.0

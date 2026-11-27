"""Verify pre-commissioning comparisons on synthetic linear plants.

Wood-Berry parameters are public benchmark values; no plant data is used.
"""

from dataclasses import replace

import numpy as np
import pytest
from crosscut_mpc.config import Controller
from crosscut_mpc.model import FopdtModel
from crosscut_mpc.planning import CycleInputs
from crosscut_mpc.simulator import (
    PidState,
    PidTuning,
    Scenario,
    compute_kpis,
    pid_moves,
    settling_times,
    simulate,
)
from mpc_helpers import make_controller


@pytest.fixture(scope="module")
def wood_berry() -> Controller:
    """Return Wood-Berry distillation paths, with published minutes converted to seconds."""
    template = make_controller([[12.8, -18.9], [6.6, -19.4]])
    # Wood-Berry 1973: gains (composition/input), lag and delay matrices (minutes).
    model = FopdtModel(np.array([[12.8, -18.9], [6.6, -19.4]]),
                       np.array([[16.7, 21.0], [10.9, 14.4]]) * 60,
                       np.array([[1.0, 3.0], [7.0, 3.0]]) * 60, 60.0)
    return replace(template, model=model)


@pytest.fixture(scope="module")
def wood_berry_result(wood_berry: Controller) -> dict:
    """Run diagonal signed PI loops and the reference MPC on one setpoint event."""
    return simulate(wood_berry, (PidTuning(0.02, 600), PidTuning(-0.02, 600, cv_index=1)),
                    Scenario(steps=100))


def test_wood_berry_mpc_tracks_the_selected_setpoint(wood_berry_result: dict) -> None:
    assert wood_berry_result["mpc"]["cvs"][-1] == pytest.approx([1, 0], abs=0.03)


def test_wood_berry_pid_baseline_runs_on_the_same_time_grid(wood_berry_result: dict) -> None:
    assert np.asarray(wood_berry_result["pid"]["cvs"]).shape == (101, 2)
    assert np.asarray(wood_berry_result["pid"]["mvs"]).shape == (101, 2)
    assert wood_berry_result["pid"]["kpis"]["iae"][0] > 0


def test_kpis_report_error_travel_settling_and_constraint_counts(wood_berry_result: dict) -> None:
    metrics = wood_berry_result["mpc"]["kpis"]
    assert metrics["iae"][0] > 0
    assert metrics["mv_travel"][0] > 0
    assert metrics["settling_time_s"][0] is not None
    assert metrics["overshoot"][0] >= 0
    assert metrics["constraint_violations"] == {
        "cv": [0, 0], "mv": [0, 0], "move": [0, 0], "rate": [0, 0]}


def test_mpc_respects_hard_position_and_move_limits() -> None:
    controller = make_controller([[1.0]], mv_lower=[-0.2], mv_upper=[0.2], move_max=[0.05])
    result = simulate(controller, (PidTuning(1, 4),), Scenario(steps=20))
    moves = np.asarray(result["mpc"]["mvs"])
    assert np.max(np.abs(moves)) <= 0.2
    assert np.max(np.abs(np.diff(moves, axis=0))) <= 0.05 + 1e-12
    assert result["mpc"]["kpis"]["settling_time_s"] == [None]


def test_repeated_scenarios_are_exactly_deterministic() -> None:
    controller = make_controller([[1.0]])
    first = simulate(controller, (PidTuning(1, 4),), Scenario(steps=15))
    second = simulate(controller, (PidTuning(1, 4),), Scenario(steps=15))
    assert first == second


def test_disturbance_steps_are_applied_to_both_plants() -> None:
    template = make_controller([[1.0, 0.5]])
    limits = replace(template.limits, mv_lower=np.array([-5.0]), mv_upper=np.array([5.0]),
                     move_max=np.array([0.5]), rate_max=np.array([0.5]))
    result = simulate(replace(template, limits=limits), (PidTuning(1, 4),),
                      Scenario(kind="dv_step", steps=30))
    assert result["disturbances"][5] == [1.0]
    assert result["mpc"]["kpis"]["mv_travel"][0] > 0
    assert result["pid"]["kpis"]["mv_travel"][0] > 0


def test_constraint_scenario_requests_beyond_the_cv_band() -> None:
    controller = make_controller([[1.0]], cv_upper=[0.2])
    result = simulate(controller, (PidTuning(1, 4),),
                      Scenario(kind="constraint_active", steps=40))
    assert result["targets"][-1] == [1.2]
    assert result["mpc"]["cvs"][-1][0] <= 0.2 + 2e-5


def test_disturbance_scenario_without_a_dv_column_is_rejected() -> None:
    with pytest.raises(ValueError, match="disturbance column"):
        simulate(make_controller([[1.0]]), (PidTuning(1, 4),), Scenario(kind="dv_step"))


def test_missing_current_pid_tunings_are_rejected() -> None:
    with pytest.raises(ValueError, match="one current PID"):
        simulate(make_controller([[1.0]]), (), Scenario())


def test_nonfinite_pid_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        PidTuning(float("nan"), 4)


def test_invalid_scenario_is_rejected() -> None:
    with pytest.raises(ValueError, match="step_at"):
        Scenario(steps=10, step_at=10)



def test_a_disturbance_at_zero_starts_from_the_undisturbed_plant() -> None:
    template = make_controller([[1.0, 0.5]])
    limits = replace(template.limits, mv_lower=np.array([-5.0]), mv_upper=np.array([5.0]),
                     move_max=np.array([0.5]), rate_max=np.array([0.5]))
    result = simulate(replace(template, limits=limits), (PidTuning(1, 4),),
                      Scenario(kind="dv_step", steps=15, step_at=0))
    assert result["mpc"]["cvs"][0] == [0.0]
    assert result["pid"]["cvs"][0] == [0.0]
    assert result["pid"]["cvs"][2][0] > 0.0


def test_a_small_step_uses_two_percent_of_its_own_amplitude() -> None:
    outputs = np.array([[0.0], [0.005], [0.0099]])
    targets = np.array([[0.0], [0.01], [0.01]])
    assert settling_times(outputs, targets, (1, 1.0)) == [1.0]



def test_known_trajectory_has_exact_error_overshoot_travel_and_violation_metrics() -> None:
    controller = make_controller([[1.0]], cv_upper=[1.1], mv_upper=[0.25],
                                 move_max=[0.15], rate_max=[0.15])
    outputs = np.array([[0.0], [0.5], [1.2], [1.01], [1.0]])
    moves = np.array([[0.0], [0.4], [0.2], [0.3], [0.3]])
    metrics = compute_kpis(controller, (outputs, moves), np.ones((5, 1)),
                           Scenario(steps=4, step_at=0))
    assert metrics["iae"] == pytest.approx([1.71])
    assert metrics["overshoot"] == pytest.approx([0.2])
    assert metrics["mv_travel"] == pytest.approx([0.7])
    assert metrics["settling_time_s"] == [3.0]
    assert metrics["constraint_violations"] == {
        "cv": [1], "mv": [3], "move": [2], "rate": [2]}


def test_ideal_pid_integrates_error_and_differentiates_only_the_measurement() -> None:
    controller = make_controller([[1.0]], move_max=[10.0], rate_max=[10.0])
    tuning = (PidTuning(kp=2.0, ti_s=4.0, td_s=3.0),)
    state = PidState(np.zeros(1), np.zeros(1))
    step = CycleInputs(np.array([0.0]), np.array([0.0]), np.array([1.0]))
    first = pid_moves(controller, tuning, state, step)
    measured = CycleInputs(np.array([0.1]), first, np.array([1.0]))
    second = pid_moves(controller, tuning, state, measured)
    # Ts=1 s: first=2*1+2/4*1=2.5; next=2*(.9-3*.1)+(.5+2/4*.9)=2.15.
    assert first == pytest.approx([2.5])
    assert second == pytest.approx([2.15])
    assert state.integral == pytest.approx([0.95])

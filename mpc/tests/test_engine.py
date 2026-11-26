"""Exercise two-layer reference MPC on synthetic constrained linear plants.

These L1 tests make no claim about performance on an operating plant.
"""

from dataclasses import asdict, replace

import numpy as np
import pytest
from crosscut_mpc import CycleInputs, cycle, initialise, steady_target
from crosscut_mpc.planning import rate_limited_target
from crosscut_mpc.qp import QuadraticProgram, solve
from helpers import make_controller, simulate


def test_siso_tracks_a_target_without_offset_under_unmeasured_load() -> None:
    controller = make_controller([[2.0]])
    measured, results = simulate(controller, np.array([2.0]), 100, load=0.7)
    assert measured == pytest.approx([2.0], abs=0.002)
    assert results[-1].bias == pytest.approx([0.7], abs=0.002)


def test_infeasible_target_relaxes_the_lower_priority_cv_first() -> None:
    controller = make_controller([[1.0], [1.0]], cv_lower=[1.0, -2.0],
                                 cv_upper=[2.0, 0.0], priorities=[0, 1])
    inputs = CycleInputs(np.zeros(2), np.zeros(1), np.array([1.0, 0.0]))
    result = steady_target(controller, inputs, np.zeros(2))
    assert result.relaxed == (1,)
    assert result.values[0] >= 1.0 - 2e-5


def test_a_saturated_mv_stays_at_its_limit_while_the_other_compensates() -> None:
    controller = make_controller([[1.0, 1.0]], mv_lower=[0.0, -5.0], mv_upper=[0.0, 5.0])
    measured, results = simulate(controller, np.array([2.0]), 80)
    assert np.array([result.moves[0] for result in results]) == pytest.approx(0.0, abs=2e-5)
    assert results[-1].moves[1] == pytest.approx(2.0, abs=0.002)
    assert measured == pytest.approx([2.0], abs=0.002)


def failure_sequence() -> tuple[list[str], list]:
    """Make hard MV bounds unreachable within the permitted first move."""
    controller = make_controller([[1.0]], mv_lower=[1.0], mv_upper=[2.0], move_max=[0.1])
    inputs = CycleInputs(np.zeros(1), np.zeros(1), np.ones(1))
    state = initialise(controller, inputs)
    _, state = cycle(controller, state, inputs)
    results = []
    for _ in range(4):
        result, state = cycle(controller, state, inputs)
        results.append(result)
    return [result.status for result in results], results


def test_controller_sheds_after_three_consecutive_infeasible_cycles() -> None:
    statuses, results = failure_sequence()
    assert statuses == ["hold", "hold", "shed", "shed"]
    assert results[2].moves == (0.0,)


def test_identical_inputs_produce_identical_moves_predictions_and_diagnostics() -> None:
    controller = make_controller([[1.0]])
    _, first = simulate(controller, np.ones(1), 12)
    _, second = simulate(controller, np.ones(1), 12)
    assert [asdict(replace(result, solve_time_s=0)) for result in first] == [
        asdict(replace(result, solve_time_s=0)) for result in second
    ]


def test_initialisation_holds_the_current_mv() -> None:
    controller = make_controller([[1.0]])
    inputs = CycleInputs(np.ones(1), np.ones(1), np.array([3.0]))
    result, _ = cycle(controller, initialise(controller, inputs), inputs)
    assert result.moves == (1.0,)
    assert result.move_plan == ((0.0,),) * 5


def test_cv_targets_are_rate_limited_between_cycles() -> None:
    controller = make_controller([[1.0]], target_rate=[0.1])
    target = rate_limited_target(controller, np.array([0.0]), np.array([5.0]))
    assert target == pytest.approx([0.1])


def test_a_genuinely_infeasible_qp_has_no_solution() -> None:
    program = QuadraticProgram(np.eye(1), np.zeros(1), np.ones((2, 1)),
                               np.array([1.0, -np.inf]), np.array([np.inf, 0.0]))
    solution = solve(program)
    assert solution.values is None
    assert solution.status == "primal infeasible"


def test_input_dimensions_fail_visibly() -> None:
    controller = make_controller([[1.0]])
    inputs = CycleInputs(np.zeros(2), np.zeros(1), np.zeros(1))
    with pytest.raises(ValueError, match="measured_cvs"):
        initialise(controller, inputs)


def test_infeasible_cv_funnels_relax_before_holding_mvs() -> None:
    controller = make_controller([[1.0]], funnel_start=[0.0], funnel_end=[0.0])
    _, results = simulate(controller, np.array([3.0]), 5)
    assert results[1].status == "relaxed"
    assert results[1].relaxed_cvs == (0,)


def test_a_successful_cycle_resets_the_failure_counter() -> None:
    controller = make_controller([[1.0]])
    inputs = CycleInputs(np.zeros(1), np.zeros(1), np.ones(1))
    state = replace(initialise(controller, inputs), is_initial=False, infeasible_cycles=2)
    result, state = cycle(controller, state, inputs)
    assert result.status == "solved"
    assert state.infeasible_cycles == 0


def test_refused_moves_are_reconciled_using_actual_mv_readback() -> None:
    controller = make_controller([[1.0]])
    inputs = CycleInputs(np.zeros(1), np.zeros(1), np.ones(1))
    _, state = cycle(controller, initialise(controller, inputs), inputs)
    first, state = cycle(controller, state, inputs)
    repeated, state = cycle(controller, state, inputs)
    assert first.moves[0] > 0.0
    assert repeated.bias == pytest.approx([0.0], abs=1e-10)
    assert repeated.moves == pytest.approx(first.moves, abs=1e-7)


def test_active_constraints_report_a_saturated_actuator() -> None:
    controller = make_controller([[1.0, 1.0]], mv_lower=[0.0, -5.0], mv_upper=[0.0, 5.0])
    _, results = simulate(controller, np.ones(1), 3)
    assert "mv[0].upper@1" in results[-1].active_constraints


def test_moving_too_fast_is_prevented_by_the_rate_limit() -> None:
    controller = make_controller([[1.0]], move_max=[0.5], rate_max=[0.05])
    _, results = simulate(controller, np.array([3.0]), 10)
    positions = np.array([result.moves for result in results])
    assert np.max(np.abs(np.diff(positions, axis=0))) <= 0.05 + 2e-5


def test_larger_move_suppression_reduces_the_first_move() -> None:
    controller = make_controller([[1.0]], move_max=[5.0], rate_max=[5.0])
    cautious = replace(controller, settings=replace(controller.settings, move_suppression=100.0))
    _, normal = simulate(controller, np.ones(1), 2)
    _, suppressed = simulate(cautious, np.ones(1), 2)
    assert 0.0 < suppressed[1].moves[0] < normal[1].moves[0]

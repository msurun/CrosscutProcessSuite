"""Check funnel geometry, measured disturbances and independent CV slack groups.

These tests expose numerical inputs and outputs rather than solver internals.
"""

from dataclasses import replace

import numpy as np
import pytest
from crosscut_mpc import Controller, CycleInputs, FopdtModel, cycle, initialise, steady_target
from crosscut_mpc.planning import Prediction, cv_bands
from mpc_helpers import make_controller


def test_cv_funnels_narrow_linearly_and_intersect_operator_limits() -> None:
    controller = make_controller([[1.0]], cv_lower=[-2.0], cv_upper=[2.0],
                                 funnel_start=[3.0], funnel_end=[0.5])
    prediction = Prediction(np.zeros((25, 1)), np.zeros((25, 5)), np.ones(1))
    lower, upper = cv_bands(controller, prediction)
    assert lower[[0, -1]] == pytest.approx([-2.0, 0.5])
    assert upper[[0, -1]] == pytest.approx([2.0, 1.5])


def test_measured_disturbance_contributes_to_the_steady_target() -> None:
    controller = make_controller([[2.0]])
    model = FopdtModel([[2.0, 3.0]], [[4.0, 5.0]], [[1.0, 2.0]], 1.0)
    controller = Controller(model, controller.limits, controller.settings)
    inputs = CycleInputs(np.array([3.0]), np.zeros(1), np.array([5.0]), (1.0,))
    solution = steady_target(controller, inputs, np.zeros(1))
    assert solution.values == pytest.approx([1.0], abs=2e-5)


def test_initial_bias_includes_measured_disturbance_prediction() -> None:
    base = make_controller([[2.0]])
    model = FopdtModel([[2.0, 3.0]], [[4.0, 5.0]], [[1.0, 2.0]], 1.0)
    controller = Controller(model, base.limits, base.settings)
    inputs = CycleInputs(np.array([3.5]), np.zeros(1), np.array([5.0]), (1.0,))
    result, _ = cycle(controller, initialise(controller, inputs), inputs)
    assert result.bias == pytest.approx([0.5])
    assert np.array(result.predicted_cvs) == pytest.approx(np.full((25, 1), 3.5))


def test_equal_cv_priorities_relax_together() -> None:
    controller = make_controller([[1.0], [1.0]], cv_lower=[1.0, -2.0],
                                 cv_upper=[2.0, 0.0], priorities=[0, 0])
    inputs = CycleInputs(np.zeros(2), np.zeros(1), np.array([1.0, 0.0]))
    solution = steady_target(controller, inputs, np.zeros(2))
    assert solution.values is not None
    assert solution.relaxed == (0, 1)


def test_limits_reject_a_funnel_that_widens_over_the_horizon() -> None:
    controller = make_controller([[1.0]])
    with pytest.raises(ValueError, match="Funnel start"):
        replace(controller.limits, funnel_start=np.array([0.0]), funnel_end=np.array([1.0]))

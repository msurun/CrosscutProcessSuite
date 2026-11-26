"""Check exact ZOH delay and step-response conventions independently of the solver.

The simulator's SISO element provides an independent recurrence implementation.
"""

import numpy as np
import pytest
from crosscut_mpc import FopdtModel, advance, initial_model_state
from crosscut_mpc.model import move_matrix
from crosscut_sim.core import Fopdt


def trajectory(model: FopdtModel) -> np.ndarray:
    """Apply a unit step and collect path outputs in CV engineering units."""
    state = initial_model_state(model, np.zeros(1))
    values = []
    for _ in range(10):
        state = advance(model, state, np.ones(1))
        values.append(state.paths[0, 0])
    return np.array(values)


def test_dead_time_step_response_matches_the_simulator() -> None:
    model = FopdtModel([[2.0]], [[4.0]], [[2.0]], 1.0)
    plant = Fopdt(2.0, 4.0, 2.0, 1.0)
    expected = np.array([plant.update(1.0) for _ in range(10)])
    assert trajectory(model) == pytest.approx(expected)
    assert model.step_response(10)[:, 0, 0] == pytest.approx(expected)


def test_move_matrix_shifts_each_future_increment() -> None:
    model = FopdtModel([[2.0]], [[4.0]], [[0.0]], 1.0)
    matrix = move_matrix(model, (5, 2), 1)
    assert matrix[0, 1] == 0.0
    assert matrix[1:, 1] == pytest.approx(matrix[:-1, 0])


@pytest.mark.parametrize("tau,delay,cycle", [(0, 0, 1), (1, -1, 1), (1, 0, 0)])
def test_nonphysical_model_coefficients_are_rejected(
    tau: float, delay: float, cycle: float,
) -> None:
    with pytest.raises(ValueError):
        FopdtModel([[1.0]], [[tau]], [[delay]], cycle)

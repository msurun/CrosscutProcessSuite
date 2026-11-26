"""Construct synthetic controllers and closed-loop trajectories for L1 tests.

Helpers keep each test focused on one externally observable controller behaviour.
"""

import numpy as np
from crosscut_mpc import (
    Controller,
    CycleInputs,
    FopdtModel,
    Limits,
    Settings,
    advance,
    cycle,
    initial_model_state,
    initialise,
)


def make_controller(gains: list[list[float]], **changes: object) -> Controller:
    """Create a seconds-based model with wide bands unless a test overrides them."""
    matrix = np.asarray(gains)
    outputs, inputs = matrix.shape
    limit_values = dict(mv_lower=np.full(inputs, -5.0), mv_upper=np.full(inputs, 5.0),
                        cv_lower=np.full(outputs, -10.0), cv_upper=np.full(outputs, 10.0),
                        priorities=np.arange(outputs), move_max=np.full(inputs, 0.5),
                        rate_max=np.full(inputs, 0.5), target_rate=np.full(outputs, 10.0),
                        funnel_start=np.full(outputs, 20.0), funnel_end=np.full(outputs, 10.0))
    limit_values.update(changes)
    model = FopdtModel(matrix, np.full(matrix.shape, 4.0), np.ones(matrix.shape), 1.0)
    return Controller(model, Limits(**limit_values), Settings(25, 5, 0.2))


def simulate(controller: Controller, targets: np.ndarray, cycles: int,
             load: float = 0.0) -> tuple[np.ndarray, list]:
    """Run a noiseless model with an unmeasured constant CV load in CV units."""
    actual = np.zeros(len(controller.limits.mv_lower))
    plant = initial_model_state(controller.model, actual)
    inputs = CycleInputs(np.full(len(targets), load), actual, targets)
    state = initialise(controller, inputs)
    results = []
    for _ in range(cycles):
        result, state = cycle(controller, state, inputs)
        actual = np.array(result.moves)
        plant = advance(controller.model, plant, actual)
        inputs = CycleInputs(plant.paths.sum(axis=1) + load, actual, targets)
        results.append(result)
    return inputs.measured_cvs, results

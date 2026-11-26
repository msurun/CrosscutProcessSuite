"""Build the steady-state target and finite-horizon move quadratic programs.

Both layers use engineering units and share hard actuator limits and CV priorities.
"""

from dataclasses import dataclass

import numpy as np

from .config import Controller, priority_weights
from .model import Array, ModelState, free_response, move_matrix
from .qp import QuadraticProgram, Solution, solve_priorities


@dataclass(frozen=True)
class CycleInputs:
    """Supply measured CVs, actual MVs, operator targets and optional measured DVs.

    All values are deviations from the same model operating point, in engineering units.
    """

    measured_cvs: Array
    actual_mvs: Array
    targets: Array
    disturbances: tuple[float, ...] = ()


@dataclass(frozen=True)
class Prediction:
    """Store free CV response, move convolution and a rate-limited CV target."""

    free: Array
    matrix: Array
    target: Array


def tracking_cost(matrix: Array, error: Array, tuning: tuple[Array, float]) -> tuple[Array, Array]:
    """Expand ||matrix*x+error||_Q^2 + suppression*||x||^2 into OSQP form."""
    weights, suppression = tuning
    # P=2*(G'QG+R), q=2*G'Q*error; error is CV-unit and x is MV-unit.
    quadratic = 2 * (matrix.T @ (weights[:, None] * matrix) +
                     suppression * np.eye(matrix.shape[1]))
    return quadratic, 2 * matrix.T @ (weights * error)


def steady_target(controller: Controller, inputs: CycleInputs, bias: Array) -> Solution:
    """Solve y_ss=K_mv*u_ss+K_dv*d+bias within hard MV and soft CV limits."""
    limits = controller.limits
    count = len(limits.mv_lower)
    gains = controller.model.gains[:, :count]
    # Constant measured DVs contribute their steady gain; bias is in CV units.
    offset = bias + controller.model.gains[:, count:] @ np.asarray(inputs.disturbances)
    weights = priority_weights(limits.priorities)
    quadratic, linear = tracking_cost(gains, offset - inputs.targets, (weights, 0.0))
    program = QuadraticProgram(quadratic, linear, np.vstack((gains, np.eye(count))),
                               np.r_[limits.cv_lower - offset, limits.mv_lower],
                               np.r_[limits.cv_upper - offset, limits.mv_upper])
    return solve_priorities(program, limits.priorities, weights)


def rate_limited_target(controller: Controller, previous: Array, desired: Array) -> Array:
    """Bound the CV target change using the configured CV-units/second rates."""
    # dy_target <= target_rate [CV/s] * Ts [s]; this also limits restart transients.
    maximum_change = controller.limits.target_rate * controller.model.cycle_s
    return previous + np.clip(desired - previous, -maximum_change, maximum_change)


def build_prediction(controller: Controller, state: ModelState,
                     inputs: CycleInputs, target_bias: tuple[Array, Array]) -> Prediction:
    """Predict held-input CVs plus bias and the future response to MV increments."""
    settings = controller.settings
    target, bias = target_bias
    held_inputs = np.r_[inputs.actual_mvs, inputs.disturbances]
    free = free_response(controller.model, state, (held_inputs, settings.prediction_horizon))
    matrix = move_matrix(controller.model, (settings.prediction_horizon, settings.move_horizon),
                         len(inputs.actual_mvs))
    return Prediction(free + bias, matrix, target)


def cv_bands(controller: Controller, prediction: Prediction) -> tuple[Array, Array]:
    """Intersect CV operator limits with a linearly narrowing target funnel."""
    limits = controller.limits
    # Width[j,c] linearly interpolates start to end [CV units], shape (Np,CV).
    widths = np.linspace(limits.funnel_start, limits.funnel_end,
                         controller.settings.prediction_horizon)
    lower = np.maximum(limits.cv_lower, prediction.target - widths)
    upper = np.minimum(limits.cv_upper, prediction.target + widths)
    return (lower - prediction.free).ravel(), (upper - prediction.free).ravel()


def actuator_constraints(controller: Controller, actual: Array) -> tuple[Array, Array, Array]:
    """Bound cumulative MV positions and individual increments in MV units."""
    limits, settings = controller.limits, controller.settings
    size = settings.move_horizon * len(actual)
    # u[j]=u_now+sum(i<=j)du[i]; kron(L,I) accumulates time-major increments.
    accumulate = np.kron(np.tril(np.ones((settings.move_horizon, settings.move_horizon))),
                         np.eye(len(actual)))
    move_bound = np.minimum(limits.move_max, limits.rate_max * controller.model.cycle_s)
    matrix = np.vstack((accumulate, np.eye(size)))
    lower = np.r_[np.tile(limits.mv_lower - actual, settings.move_horizon),
                  -np.tile(move_bound, settings.move_horizon)]
    upper = np.r_[np.tile(limits.mv_upper - actual, settings.move_horizon),
                  np.tile(move_bound, settings.move_horizon)]
    return matrix, lower, upper


def dynamic_plan(controller: Controller, inputs: CycleInputs, prediction: Prediction) -> Solution:
    """Minimise weighted horizon error plus move suppression with soft CV bands."""
    settings, limits = controller.settings, controller.limits
    weights = np.tile(priority_weights(limits.priorities), settings.prediction_horizon)
    quadratic, linear = tracking_cost(prediction.matrix,
                                      (prediction.free - prediction.target).ravel(),
                                      (weights, settings.move_suppression))
    cv_lower, cv_upper = cv_bands(controller, prediction)
    hard_matrix, hard_lower, hard_upper = actuator_constraints(controller, inputs.actual_mvs)
    program = QuadraticProgram(quadratic, linear, np.vstack((prediction.matrix, hard_matrix)),
                               np.r_[cv_lower, hard_lower], np.r_[cv_upper, hard_upper])
    priorities = np.tile(limits.priorities, settings.prediction_horizon)
    return solve_priorities(program, priorities, weights)

"""Run a pure two-layer MPC cycle and return plain data for a future runtime host.

No gateway, file, network or clock calls occur here; callers explicitly carry state.
"""

from dataclasses import dataclass, replace

import numpy as np

from .config import Controller
from .economics import EconomicReport, steady_economic_target
from .model import Array, ModelState, advance, initial_model_state
from .planning import (
    CycleInputs,
    Prediction,
    build_prediction,
    dynamic_plan,
    rate_limited_target,
)
from .qp import ACCEPTANCE_TOLERANCE, Solution

SHED_CYCLES = 3  # Consecutive cycles with no feasible plan before shedding to base control.


@dataclass(frozen=True)
class ControllerState:
    """Store model state at the measurement instant and the last CV target."""

    model_state: ModelState
    target: Array
    infeasible_cycles: int = 0
    is_initial: bool = True
    is_shed: bool = False
    prior_model_state: ModelState | None = None


@dataclass(frozen=True)
class Result:
    """Return absolute proposed MVs, increment plan, CV predictions and diagnostics.

    Tuples contain only Python scalars; state is returned separately by cycle().
    """

    moves: tuple[float, ...]
    move_plan: tuple[tuple[float, ...], ...]
    predicted_cvs: tuple[tuple[float, ...], ...]
    steady_mvs: tuple[float, ...]
    target_cvs: tuple[float, ...]
    bias: tuple[float, ...]
    active_constraints: tuple[str, ...]
    relaxed_cvs: tuple[int, ...]
    status: str
    reason: str
    iterations: int
    solve_time_s: float
    economics: EconomicReport | None = None


def validate_inputs(controller: Controller, inputs: CycleInputs) -> None:
    """Reject nonfinite measurements or dimensions inconsistent with the model."""
    outputs, total_inputs = controller.model.gains.shape
    count = len(controller.limits.mv_lower)
    for name, expected in (("measured_cvs", outputs), ("actual_mvs", count),
                           ("targets", outputs), ("disturbances", total_inputs - count)):
        values = np.asarray(getattr(inputs, name), dtype=float)
        if values.shape != (expected,) or not np.all(np.isfinite(values)):
            raise ValueError(f"{name} must contain {expected} finite engineering-unit values")


def initialise(controller: Controller, inputs: CycleInputs) -> ControllerState:
    """Initialise at current inputs; the first cycle holds MVs for bumpless entry."""
    validate_inputs(controller, inputs)
    state = initial_model_state(controller.model, np.r_[inputs.actual_mvs, inputs.disturbances])
    return ControllerState(state, np.array(inputs.measured_cvs, copy=True))


def active_constraints(controller: Controller, moves: Array, predictions: Array) -> tuple[str, ...]:
    """Identify binding MV and CV operator bounds by variable and horizon sample."""
    labels = []
    for kind, values, lower, upper in (
        ("mv", moves, controller.limits.mv_lower, controller.limits.mv_upper),
        ("cv", predictions, controller.limits.cv_lower, controller.limits.cv_upper),
    ):
        for side, bound in (("lower", lower), ("upper", upper)):
            for sample, variable in np.argwhere(np.abs(values - bound) <= ACCEPTANCE_TOLERANCE):
                labels.append(f"{kind}[{variable}].{side}@{sample + 1}")
    return tuple(labels)


def rows(values: Array) -> tuple[tuple[float, ...], ...]:
    """Convert a numerical matrix to plain Python rows for host serialisation."""
    return tuple(tuple(float(value) for value in row) for row in values)


def scalars(values: Array) -> tuple[float, ...]:
    """Convert a signal vector to plain Python floats."""
    return tuple(float(value) for value in values)


def finish_cycle(
    controller: Controller, state: ControllerState, inputs: CycleInputs,
    outcome: tuple[Result, Array],
) -> tuple[Result, ControllerState]:
    """Advance prediction with the proposal; actual read-back is reconciled next cycle."""
    result, target = outcome
    model_state = advance(controller.model, state.model_state,
                          np.r_[result.moves, inputs.disturbances])
    failures = state.infeasible_cycles + 1 if result.status in ("hold", "shed") else 0
    updated = ControllerState(model_state, target.copy(), failures, False,
                              result.status == "shed", state.model_state)
    return result, updated


def held_result(controller: Controller, state: ControllerState,
                inputs: CycleInputs, reason: str) -> Result:
    """Return a zero-move plan and latch shed on the third consecutive failure."""
    bias = np.asarray(inputs.measured_cvs) - state.model_state.paths.sum(axis=1)
    prediction = build_prediction(controller, state.model_state, inputs, (state.target, bias))
    is_shed = state.is_shed or state.infeasible_cycles + 1 >= SHED_CYCLES
    status = "shed" if is_shed else "hold"
    if reason == "bumpless initialisation":
        status = "initialised"
    zeros = np.zeros((controller.settings.move_horizon, len(inputs.actual_mvs)))
    return Result(scalars(inputs.actual_mvs), rows(zeros), rows(prediction.free), (),
                  scalars(state.target), scalars(bias), (), (), status, reason, 0, 0.0)


def planned_result(controller: Controller, inputs: CycleInputs,
                   state: ControllerState, bias: Array) -> tuple[Result, Array]:
    """Solve both layers and return a hold when either layer cannot certify feasibility."""
    economic = steady_economic_target(controller, inputs, bias)
    target_solution = economic.solution
    if target_solution.values is None:
        held = held_result(controller, state, inputs, target_solution.status)
        return replace(held, iterations=target_solution.iterations,
                       solve_time_s=target_solution.solve_time_s), state.target
    desired = controller.model.gains @ np.r_[target_solution.values, inputs.disturbances] + bias
    target = rate_limited_target(controller, state.target, desired)
    prediction = build_prediction(controller, state.model_state, inputs, (target, bias))
    plan = dynamic_plan(controller, inputs, prediction)
    if plan.values is None:
        held = held_result(controller, state, inputs, plan.status)
        return replace(held, iterations=target_solution.iterations + plan.iterations,
                       solve_time_s=target_solution.solve_time_s + plan.solve_time_s), state.target
    result = successful_result(controller, inputs, (prediction, bias), (target_solution, plan))
    return replace(result, economics=economic.report), target


def successful_result(controller: Controller, inputs: CycleInputs,
                      prediction_bias: tuple[Prediction, Array],
                      solutions: tuple[Solution, Solution]) -> Result:
    """Format the certified move plan, target and active constraints as plain data."""
    prediction, bias = prediction_bias
    target_solution, plan = solutions
    if plan.values is None or target_solution.values is None:
        raise ValueError("Result formatting requires certified target and plan solutions")
    increments = plan.values.reshape(controller.settings.move_horizon, -1)
    positions = inputs.actual_mvs + np.cumsum(increments, axis=0)
    predicted = prediction.free + (prediction.matrix @ plan.values).reshape(prediction.free.shape)
    count = len(inputs.measured_cvs)
    relaxed = tuple(sorted(set(target_solution.relaxed) | {row % count for row in plan.relaxed}))
    return Result(scalars(positions[0]), rows(increments), rows(predicted),
                  scalars(target_solution.values), scalars(prediction.target),
                  scalars(bias), active_constraints(controller, positions, predicted), relaxed,
                  "relaxed" if relaxed else "solved", "",
                  target_solution.iterations + plan.iterations,
                  target_solution.solve_time_s + plan.solve_time_s)


def cycle(controller: Controller, state: ControllerState,
          inputs: CycleInputs) -> tuple[Result, ControllerState]:
    """Compute a receding-horizon proposal and next state without changing arguments."""
    validate_inputs(controller, inputs)
    if state.prior_model_state is not None:
        reconciled = advance(controller.model, state.prior_model_state,
                             np.r_[inputs.actual_mvs, inputs.disturbances])
        state = replace(state, model_state=reconciled)
    if state.is_initial or state.is_shed:
        reason = ("shed latched; initialise to restart" if state.is_shed
                  else "bumpless initialisation")
        result = held_result(controller, state, inputs, reason)
        return finish_cycle(controller, state, inputs, (result, state.target))
    # d[k]=y_measured[k]-y_model[k], held constant over every future CV sample.
    # Reconcile the previous applied MV using read-back, so refused proposals add no phantom move.
    bias = np.asarray(inputs.measured_cvs) - state.model_state.paths.sum(axis=1)
    outcome = planned_result(controller, inputs, state, bias)
    return finish_cycle(controller, state, inputs, outcome)

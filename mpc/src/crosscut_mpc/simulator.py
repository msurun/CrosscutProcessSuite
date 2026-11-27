"""Compare MPC and current PID loops on one identified linear plant before commissioning.

All signals are operating-point deviations in engineering units; this module has no I/O.
PID is ideal positional control with derivative on measurement and tracking anti-windup.
"""

from dataclasses import dataclass

import numpy as np

from .config import Controller
from .engine import ControllerState, cycle, initialise
from .model import Array, ModelState, advance, initial_model_state
from .planning import CycleInputs
from .qp import ACCEPTANCE_TOLERANCE

SETTLING_FRACTION = 0.02  # Settled means within 2 percent of the requested CV step.
SETTLING_ABSOLUTE_FLOOR = 1e-9  # CV units: numerical tolerance for an unchanged CV.
MAX_SAMPLES = 2000  # Bound offline work; samples, not elapsed seconds.


@dataclass(frozen=True)
class PidTuning:
    """Canonical ideal PID: signed gain [MV/CV], integral/derivative times [s]."""

    kp: float
    ti_s: float
    td_s: float = 0.0
    cv_index: int = 0

    def __post_init__(self) -> None:
        """Reject nonfinite or nonphysical canonical tunings."""
        if not np.all(np.isfinite([self.kp, self.ti_s, self.td_s])):
            raise ValueError("PID tuning must contain finite gain and times")
        if self.ti_s <= 0 or self.td_s < 0:
            raise ValueError("PID integral time must be positive and derivative time nonnegative")
        if not isinstance(self.cv_index, int) or self.cv_index < 0:
            raise ValueError("PID cv_index must be a nonnegative integer")


@dataclass(frozen=True)
class Scenario:
    """Specify one deviation step, with event and duration in sample counts."""

    kind: str = "sp_step"
    steps: int = 120
    step_at: int = 5
    amplitude: float = 1.0
    cv_index: int = 0
    dv_index: int = 0

    def __post_init__(self) -> None:
        """Reject invalid scenarios before starting numerical work."""
        if self.kind not in ("sp_step", "dv_step", "constraint_active"):
            raise ValueError("Choose sp_step, dv_step or constraint_active")
        if not isinstance(self.steps, int) or not 2 <= self.steps <= MAX_SAMPLES:
            raise ValueError(f"Scenario steps must be an integer from 2 to {MAX_SAMPLES}")
        if not isinstance(self.step_at, int) or not 0 <= self.step_at < self.steps:
            raise ValueError("Scenario step_at must be an integer within the simulation")
        if not np.isfinite(self.amplitude) or self.amplitude == 0:
            raise ValueError("Scenario amplitude must be finite and nonzero")
        if any(not isinstance(value, int) or value < 0
               for value in (self.cv_index, self.dv_index)):
            raise ValueError("Scenario variable indices must be nonnegative integers")


def validate_scenario(controller: Controller, tunings: tuple[PidTuning, ...],
                      scenario: Scenario) -> None:
    """Require a PID for each MV and a valid selected model channel."""
    outputs, inputs = controller.model.gains.shape
    manipulated = len(controller.limits.mv_lower)
    if len(tunings) != manipulated:
        raise ValueError("Provide one current PID tuning for each manipulated variable")
    if scenario.cv_index >= outputs or any(tuning.cv_index >= outputs for tuning in tunings):
        raise ValueError("Selected CV or PID pairing is outside the model rows")
    if scenario.kind == "dv_step" and scenario.dv_index >= inputs - manipulated:
        raise ValueError("DV scenario requires a measured-disturbance column in the model")
    if np.any(controller.limits.mv_lower > 0) or np.any(controller.limits.mv_upper < 0):
        raise ValueError("MV deviation limits must include the zero operating point")


def scenario_signals(controller: Controller, scenario: Scenario) -> tuple[Array, Array]:
    """Build time-major targets (samples,CV) and measured loads (samples,DV)."""
    outputs, inputs = controller.model.gains.shape
    targets = np.zeros((scenario.steps + 1, outputs))
    disturbances = np.zeros((scenario.steps + 1, inputs - len(controller.limits.mv_lower)))
    if scenario.kind == "dv_step":
        disturbances[scenario.step_at:, scenario.dv_index] = scenario.amplitude
    else:
        requested = scenario.amplitude
        if scenario.kind == "constraint_active":
            # Request beyond a CV band so the engineer sees the active constraint response.
            bound = (controller.limits.cv_upper if requested > 0 else
                     controller.limits.cv_lower)[scenario.cv_index]
            requested += bound
        targets[scenario.step_at:, scenario.cv_index] = requested
    return targets, disturbances


@dataclass
class PidState:
    """Keep local integral [MV] and previous measurement [CV] vectors per MV loop."""

    integral: Array
    previous: Array


def pid_moves(controller: Controller, tunings: tuple[PidTuning, ...],
              state: PidState, inputs: CycleInputs) -> Array:
    """Compute ideal positional PID with derivative on PV and tracking anti-windup."""
    indices = [tuning.cv_index for tuning in tunings]
    gain = np.array([tuning.kp for tuning in tunings])
    integral_time = np.array([tuning.ti_s for tuning in tunings])
    derivative_time = np.array([tuning.td_s for tuning in tunings])
    measured = inputs.measured_cvs[indices]
    error = inputs.targets[indices] - measured
    period = controller.model.cycle_s
    # u=Kp*(e + integral(e)/Ti - Td*dPV/dt); each vector is (MV,).
    proportional_derivative = gain * (error - derivative_time * (measured-state.previous)/period)
    integral = state.integral + gain * period / integral_time * error
    proposed = proportional_derivative + integral
    moves = clamp_moves(controller, inputs.actual_mvs, proposed)
    # Tracking the applied output prevents integral windup at position and rate limits.
    state.integral = moves - proportional_derivative
    state.previous = measured.copy()
    return moves


def clamp_moves(controller: Controller, previous: Array, proposed: Array) -> Array:
    """Apply the same hard MV position and sample/rate limits to either controller."""
    limits = controller.limits
    maximum = np.minimum(limits.move_max, limits.rate_max * controller.model.cycle_s)
    return np.clip(proposed, np.maximum(limits.mv_lower, previous - maximum),
                   np.minimum(limits.mv_upper, previous + maximum))


def initial_comparison(
    controller: Controller, tunings: tuple[PidTuning, ...], targets: Array,
) -> tuple[Array, ModelState, Array, ControllerState, PidState]:
    """Start both controllers and the plant at the zero deviation operating point."""
    actual = np.zeros(len(tunings))
    disturbance_count = controller.model.gains.shape[1] - len(tunings)
    plant = initial_model_state(controller.model, np.r_[actual, np.zeros(disturbance_count)])
    measured = plant.paths.sum(axis=1)
    inputs = CycleInputs(measured, actual, targets[0], tuple(np.zeros(disturbance_count)))
    state = initialise(controller, inputs)
    pid_state = PidState(actual.copy(), measured[[tuning.cv_index for tuning in tunings]])
    return actual, plant, measured, state, pid_state


def simulate_branch(controller: Controller, tunings: tuple[PidTuning, ...],
                    signals: tuple[Array, Array], use_mpc: bool) -> tuple[Array, Array]:
    """Integrate the identical exact-ZOH FOPDT plant with MPC or canonical PID."""
    targets, disturbances = signals
    actual, plant, measured, state, pid_state = initial_comparison(controller, tunings, targets)
    outputs, moves = [measured.copy()], [actual.copy()]
    for sample in range(len(targets) - 1):
        inputs = CycleInputs(measured, actual, targets[sample], tuple(disturbances[sample]))
        if use_mpc:
            result, state = cycle(controller, state, inputs)
            actual = clamp_moves(controller, actual, np.array(result.moves))
        else:
            actual = pid_moves(controller, tunings, pid_state, inputs)
        plant = advance(controller.model, plant, np.r_[actual, disturbances[sample]])
        measured = plant.paths.sum(axis=1)
        outputs.append(measured.copy())
        moves.append(actual.copy())
    return np.asarray(outputs), np.asarray(moves)


def settling_times(outputs: Array, targets: Array,
                   timing: tuple[int, float]) -> list[float | None]:
    """Return seconds after the event to permanent 2-percent settling, or null."""
    step_at, period = timing
    reference = np.where(np.abs(targets[-1]) > 0, np.abs(targets[-1]),
                         np.max(np.abs(outputs[step_at:]), axis=0))
    tolerance = np.maximum(SETTLING_FRACTION * reference, SETTLING_ABSOLUTE_FLOOR)
    outside = np.abs(outputs[step_at:] - targets[-1]) > tolerance
    settled = []
    for variable in range(outputs.shape[1]):
        failures = np.flatnonzero(outside[:, variable])
        first = int(failures[-1]) + 1 if failures.size else 0
        settled.append(float(first * period) if first < len(outside) else None)
    return settled


def count_violations(values: Array, bounds: tuple[Array, Array]) -> list[int]:
    """Count samples outside each band, allowing the MPC solver residual tolerance."""
    lower, upper = bounds
    violated = ((values < lower - ACCEPTANCE_TOLERANCE) |
                (values > upper + ACCEPTANCE_TOLERANCE))
    return [int(value) for value in np.sum(violated, axis=0)]


def compute_kpis(controller: Controller, trajectory: tuple[Array, Array],
                 targets: Array, scenario: Scenario) -> dict[str, object]:
    """Compute IAE [CV*s], overshoot [CV], settling [s], travel [MV], violation counts."""
    outputs, moves = trajectory
    period = controller.model.cycle_s
    # Rectangular integration uses the error at the beginning of each plant interval.
    iae = np.sum(np.abs(outputs[:-1] - targets[:-1]), axis=0) * period
    direction = np.sign(targets[-1])
    overshoot = np.maximum(np.max((outputs[scenario.step_at:] - targets[-1]) * direction,
                                 axis=0), 0)
    return {"iae": iae.tolist(), "overshoot": overshoot.tolist(),
            "settling_time_s": settling_times(outputs, targets, (scenario.step_at, period)),
            "mv_travel": np.sum(np.abs(np.diff(moves, axis=0)), axis=0).tolist(),
            "constraint_violations": trajectory_violations(controller, trajectory)}


def trajectory_violations(controller: Controller,
                          trajectory: tuple[Array, Array]) -> dict[str, list[int]]:
    """Count CV, position, per-sample move and per-second rate breaches independently."""
    outputs, moves = trajectory
    limits, period = controller.limits, controller.model.cycle_s
    changes = np.diff(moves, axis=0)
    return {"cv": count_violations(outputs, (limits.cv_lower, limits.cv_upper)),
            "mv": count_violations(moves, (limits.mv_lower, limits.mv_upper)),
            "move": count_violations(changes, (-limits.move_max, limits.move_max)),
            "rate": count_violations(changes / period, (-limits.rate_max, limits.rate_max))}



DEFAULT_SCENARIO = Scenario()


def simulate(controller: Controller, pid_tunings: tuple[PidTuning, ...],
             scenario: Scenario = DEFAULT_SCENARIO) -> dict[str, object]:
    """Return deterministic JSON-ready MPC/PID series and metrics without external writes.

    Build Controller from an accepted ident_model.to_mpc_model() or a FopdtModel matrix.
    CV bands are soft in the reference MPC; violations are reported, never hidden.
    """
    validate_scenario(controller, pid_tunings, scenario)
    signals = scenario_signals(controller, scenario)
    result: dict[str, object] = {
        "time_s": (np.arange(scenario.steps + 1) * controller.model.cycle_s).tolist(),
        "targets": signals[0].tolist(), "disturbances": signals[1].tolist(),
        "limits": {name: getattr(controller.limits, name).tolist()
                   for name in ("mv_lower", "mv_upper", "cv_lower", "cv_upper")}}
    for name, use_mpc in (("mpc", True), ("pid", False)):
        trajectory = simulate_branch(controller, pid_tunings, signals, use_mpc)
        result[name] = {"cvs": trajectory[0].tolist(), "mvs": trajectory[1].tolist(),
                        "kpis": compute_kpis(controller, trajectory, signals[0], scenario)}
    return result

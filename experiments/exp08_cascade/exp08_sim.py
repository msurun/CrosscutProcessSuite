"""Simulation helpers for experiment exp08: cascade tuning order and time-scale separation.

Builds the two-loop plant from the README (inner G2 = 1/(5 s + 1) with 2 s delay, outer
G1 = 2 e^(-5 s)/(60 s + 1) driven by the inner output), runs the identification and control
experiments, and returns the metrics (overshoot, settled flag, IAE) the acceptance targets use.

Assumed interfaces: Fopdt(gain, tau_s, delay_s, dt_s) with .update(u) consuming this step's
input and returning the next output; identify_fopdt(u, y, dt_s, max_delay_s) -> FopdtModel;
PiSettings carries .kc and .ti_s; simc_pi(model) -> PiSettings.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from crosscut_loops.identification import identify_fopdt
from crosscut_loops.tuning_rules import FopdtModel, PiSettings, simc_pi
from crosscut_sim.core import Fopdt

DT_S = 0.5  # sampling period, seconds
INNER_PROCESS_GAIN = 1.0  # dimensionless
INNER_TIME_CONSTANT_S = 5.0  # seconds
INNER_DELAY_S = 2.0  # seconds
OUTER_PROCESS_GAIN = 2.0  # dimensionless
OUTER_TIME_CONSTANT_S = 60.0  # seconds
OUTER_DELAY_S = 5.0  # seconds
NOISE_SD = 0.01  # standard deviation of the measurement noise, engineering units
STEP_TIME_S = 50.0  # time the identification/control step is applied, seconds
SETPOINT_RECORD_S = 1500.0  # length of the setpoint-response record, seconds
INNER_ID_RECORD_S = 600.0  # length of the open-loop inner identification record, seconds
SMOOTH_WINDOW_S = 60.0  # moving-average window used to measure overshoot, seconds
SETTLED_TAIL_S = 150.0  # tail length used to test settling, seconds
SETTLED_FRACTION = 0.05  # settled if tail error < this fraction of the step
INNER_ID_MAX_DELAY_S = 20.0  # upper bound for the inner delay estimate, seconds
OUTER_ID_MAX_DELAY_S = 60.0  # upper bound for the outer delay estimate, seconds
OUTER_SETPOINT_STEP = 1.0  # unit step on the outer setpoint, engineering units
ID_PULSE_S = 600.0  # length of the identification pulse, seconds (up at STEP_TIME_S, then down)
DISTURBANCE_STEP = 1.0  # unit step d2 at the inner process input, engineering units


def _n_samples(record_s: float) -> int:
    """Number of samples in a record of `record_s` seconds at sampling period DT_S."""
    return int(round(record_s / DT_S))


def _step_index() -> int:
    """Sample index at which the step is applied."""
    return int(round(STEP_TIME_S / DT_S))


def _id_pulse(k: int) -> float:
    """Identification test signal: +1 from STEP_TIME_S for ID_PULSE_S seconds, 0 elsewhere.

    A pulse (up, then down) instead of a single step keeps the input and the constant of the
    ARX regression from being collinear over most of the record, which a lone step does
    (the one-step ARX fit then returned gain 0.55 instead of 2 for the closed inner loop).
    """
    start = _step_index()
    return OUTER_SETPOINT_STEP if start <= k < start + int(round(ID_PULSE_S / DT_S)) else 0.0


def _noisy_signal(values: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Return `values` plus additive white noise with standard deviation NOISE_SD."""
    return values + rng.normal(0.0, NOISE_SD, size=values.shape)


def _run_open_loop_step(process: Fopdt, n_samples: int, rng: np.random.Generator) -> tuple:
    """Apply a +1 step on the process input at STEP_TIME_S; return (input, noisy output)."""
    inputs = np.zeros(n_samples)
    outputs = np.zeros(n_samples)
    _step_index()
    for k in range(n_samples):
        inputs[k] = _id_pulse(k)
        outputs[k] = process.update(inputs[k])
    return inputs, _noisy_signal(outputs, rng)


def _run_closed_loop_step(inner_pi: PiSettings, n_samples: int, rng: np.random.Generator) -> tuple:
    """Run the inner loop closed on a +1 inner-setpoint step; return (setpoint, noisy y1).

    The inner loop is the only controller present: its output drives the inner process, whose
    output y2 drives the outer process. The outer model is identified from the inner SETPOINT
    to y1, so it contains the closed inner loop.
    """
    inner_process = Fopdt(INNER_PROCESS_GAIN, INNER_TIME_CONSTANT_S, INNER_DELAY_S, DT_S)
    outer_process = Fopdt(OUTER_PROCESS_GAIN, OUTER_TIME_CONSTANT_S, OUTER_DELAY_S, DT_S)
    controller = PiController(inner_pi.kc, inner_pi.ti_s, DT_S)
    setpoints = np.zeros(n_samples)
    outputs = np.zeros(n_samples)
    _step_index()
    y2_measured = 0.0
    for k in range(n_samples):
        setpoints[k] = _id_pulse(k)
        u2 = controller.update(setpoints[k] - y2_measured)
        y2 = inner_process.update(u2)
        y2_measured = y2 + rng.normal(0.0, NOISE_SD)
        outputs[k] = outer_process.update(y2) + rng.normal(0.0, NOISE_SD)
    return setpoints, outputs


class PiController:
    """Discrete PI controller without limits (u = kc*e + I, I += kc/ti*e*dt)."""

    def __init__(self, kc: float, ti_s: float, dt_s: float) -> None:
        self.kc = kc
        self.ti_s = ti_s
        self.dt_s = dt_s
        self.integral = 0.0

    def update(self, error: float) -> float:
        """Consume this step's error and return the control output for this step."""
        output = self.kc * error + self.integral
        self.integral += self.kc / self.ti_s * error * self.dt_s
        return output


def identify_inner(seed: int) -> FopdtModel:
    """Identify the inner process from an open-loop +1 step on its input."""
    rng = np.random.default_rng(seed)
    inner_process = Fopdt(INNER_PROCESS_GAIN, INNER_TIME_CONSTANT_S, INNER_DELAY_S, DT_S)
    inputs, y2_measured = _run_open_loop_step(inner_process, _n_samples(INNER_ID_RECORD_S), rng)
    return identify_fopdt(inputs, y2_measured, DT_S, INNER_ID_MAX_DELAY_S)


def identify_outer_with_inner_closed(inner_pi: PiSettings, seed: int) -> FopdtModel:
    """Identify the outer process from a +1 inner-setpoint step with the inner loop closed."""
    rng = np.random.default_rng(seed)
    setpoints, y1_measured = _run_closed_loop_step(inner_pi, _n_samples(SETPOINT_RECORD_S), rng)
    return identify_fopdt(setpoints, y1_measured, DT_S, OUTER_ID_MAX_DELAY_S)


def identify_outer_open(seed: int) -> FopdtModel:
    """Identify the outer process from an open-loop +1 step (no inner controller)."""
    rng = np.random.default_rng(seed)
    inner_process = Fopdt(INNER_PROCESS_GAIN, INNER_TIME_CONSTANT_S, INNER_DELAY_S, DT_S)
    outer_process = Fopdt(OUTER_PROCESS_GAIN, OUTER_TIME_CONSTANT_S, OUTER_DELAY_S, DT_S)
    inputs, _ = _run_open_loop_step(inner_process, _n_samples(SETPOINT_RECORD_S), rng)
    y1_measured = _run_outer_open_loop(
        inner_process_gain=1.0, outer=outer_process, inputs=inputs, rng=rng
    )
    return identify_fopdt(inputs, y1_measured, DT_S, OUTER_ID_MAX_DELAY_S)


def _run_outer_open_loop(
    inner_process_gain: float, outer: Fopdt, inputs: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    """Drive `outer` from the (noisy) inner process output on the given inputs; return noisy y1.

    The inner loop is absent, so the inner input is `inputs` directly and y2 is that input
    filtered by a fresh inner process of the given gain.
    """
    inner_process = Fopdt(inner_process_gain, INNER_TIME_CONSTANT_S, INNER_DELAY_S, DT_S)
    outputs = np.zeros(inputs.shape)
    for k, inner_input in enumerate(inputs):
        y2 = inner_process.update(inner_input)
        outputs[k] = outer.update(y2 + rng.normal(0.0, NOISE_SD))
    return _noisy_signal(outputs, rng)


@dataclass(frozen=True)
class Response:
    """Outer setpoint-response metrics: overshoot in percent, settled flag, IAE in units*s."""

    overshoot_pct: float
    settled: bool
    iae: float


def _smooth(values: np.ndarray, window_samples: int) -> np.ndarray:
    """Moving average of `values` over the trailing `window_samples` samples."""
    kernel = np.ones(window_samples) / window_samples
    return np.convolve(values, kernel, mode="valid")


def _overshoot_pct(smoothed_after_step: np.ndarray) -> float:
    """Overshoot above the unit step, percent, from the smoothed response after the step."""
    return max(0.0, float(smoothed_after_step.max()) - OUTER_SETPOINT_STEP) * 100.0


def _is_settled(y1_after_step: np.ndarray) -> bool:
    """True when the mean tail error over SETTLED_TAIL_S is below SETTLED_FRACTION."""
    tail_samples = _n_samples(SETTLED_TAIL_S)
    tail_error = np.mean(np.abs(y1_after_step[-tail_samples:] - OUTER_SETPOINT_STEP))
    return bool(tail_error < SETTLED_FRACTION * OUTER_SETPOINT_STEP)


def cascade_setpoint_response(inner_pi: PiSettings, outer_pi: PiSettings, seed: int) -> Response:
    """Run the cascade on a +1 outer-setpoint step and return overshoot, settled and IAE.

    Outer PI output is the inner setpoint; outer error uses the noisy y1, inner error the
    noisy y2. Metrics are computed on y1 after STEP_TIME_S.
    """
    rng = np.random.default_rng(seed)
    n_samples = _n_samples(SETPOINT_RECORD_S)
    inner_process = Fopdt(INNER_PROCESS_GAIN, INNER_TIME_CONSTANT_S, INNER_DELAY_S, DT_S)
    outer_process = Fopdt(OUTER_PROCESS_GAIN, OUTER_TIME_CONSTANT_S, OUTER_DELAY_S, DT_S)
    outer_controller = PiController(outer_pi.kc, outer_pi.ti_s, DT_S)
    inner_controller = PiController(inner_pi.kc, inner_pi.ti_s, DT_S)
    step_index = _step_index()
    y1 = np.zeros(n_samples)
    y2_measured = 0.0
    y1_measured = 0.0
    for k in range(n_samples):
        setpoint = 0.0 if k < step_index else OUTER_SETPOINT_STEP
        inner_setpoint = outer_controller.update(setpoint - y1_measured)
        u2 = inner_controller.update(inner_setpoint - y2_measured)
        y2 = inner_process.update(u2)
        y2_measured = y2 + rng.normal(0.0, NOISE_SD)
        y1[k] = outer_process.update(y2_measured)
        y1_measured = y1[k] + rng.normal(0.0, NOISE_SD)
    after_step = y1[step_index:]
    smoothed = _smooth(after_step, _n_samples(SMOOTH_WINDOW_S))
    iae = float(np.sum(np.abs(OUTER_SETPOINT_STEP - after_step)) * DT_S)
    return Response(_overshoot_pct(smoothed), _is_settled(after_step), iae)


def cascade_disturbance_iae(inner_pi: PiSettings, outer_pi: PiSettings, seed: int) -> float:
    """Run the cascade with outer setpoint 0 and d2 = +1 at the inner input; return IAE of y1."""
    rng = np.random.default_rng(seed)
    n_samples = _n_samples(SETPOINT_RECORD_S)
    inner_process = Fopdt(INNER_PROCESS_GAIN, INNER_TIME_CONSTANT_S, INNER_DELAY_S, DT_S)
    outer_process = Fopdt(OUTER_PROCESS_GAIN, OUTER_TIME_CONSTANT_S, OUTER_DELAY_S, DT_S)
    outer_controller = PiController(outer_pi.kc, outer_pi.ti_s, DT_S)
    inner_controller = PiController(inner_pi.kc, inner_pi.ti_s, DT_S)
    step_index = _step_index()
    y1 = np.zeros(n_samples)
    y2_measured = 0.0
    y1_measured = 0.0
    for k in range(n_samples):
        disturbance = 0.0 if k < step_index else DISTURBANCE_STEP
        inner_setpoint = outer_controller.update(0.0 - y1_measured)
        u2 = inner_controller.update(inner_setpoint - y2_measured)
        y2 = inner_process.update(u2 + disturbance)
        y2_measured = y2 + rng.normal(0.0, NOISE_SD)
        y1[k] = outer_process.update(y2_measured)
        y1_measured = y1[k] + rng.normal(0.0, NOISE_SD)
    return float(np.sum(np.abs(y1)) * DT_S)


def single_loop_disturbance_iae(outer_pi: PiSettings, seed: int) -> float:
    """Run one outer PI loop (its output feeds the inner input) with d2 = +1; return IAE of y1."""
    rng = np.random.default_rng(seed)
    n_samples = _n_samples(SETPOINT_RECORD_S)
    inner_process = Fopdt(INNER_PROCESS_GAIN, INNER_TIME_CONSTANT_S, INNER_DELAY_S, DT_S)
    outer_process = Fopdt(OUTER_PROCESS_GAIN, OUTER_TIME_CONSTANT_S, OUTER_DELAY_S, DT_S)
    controller = PiController(outer_pi.kc, outer_pi.ti_s, DT_S)
    step_index = _step_index()
    y1 = np.zeros(n_samples)
    y1_measured = 0.0
    for k in range(n_samples):
        disturbance = 0.0 if k < step_index else DISTURBANCE_STEP
        u2 = controller.update(0.0 - y1_measured)
        y2 = inner_process.update(u2 + disturbance)
        y1[k] = outer_process.update(y2)
        y1_measured = y1[k] + rng.normal(0.0, NOISE_SD)
    return float(np.sum(np.abs(y1)) * DT_S)


def outer_pi_for(outer_model: FopdtModel) -> PiSettings:
    """SIMC PI settings for the identified outer model (convenience for the runners)."""
    return simc_pi(outer_model)

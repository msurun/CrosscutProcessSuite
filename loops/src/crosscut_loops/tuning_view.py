"""Numerics behind the tuning screen: model check, closed-loop step preview, test-window hints.

Everything here works on plain arrays and returns plain values, so the web layer only has to
choose a window and serialise the result.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from crosscut_loops.tuning_rules import FopdtModel, PiSettings

GOOD_R_SQUARED = 0.8  # share of PV variance the model explains: "good" at or above this
FAIR_R_SQUARED = 0.5  # "fair" at or above this, "poor" below
STEP_SAMPLES_PER_TIME_CONSTANT = 10  # preview resolution: the smaller of tau and delay / 10
PREVIEW_HORIZON_FACTOR = 6.0  # preview length in (time constant + delay)
PREVIEW_POINTS = 200
MIN_OUT_MOVE_PCT = 1.0  # a stretch needs at least this OUT movement to count as a test
MANUAL_MODE = 0.0
MOVE_STEP_PCT = 0.5  # a sample-to-sample OUT change above this counts as a deliberate move
LEAD_S = 300.0  # quiet time kept before the first move, so the model sees the start at rest
TAIL_S = 900.0  # time kept after the last move, so the settling is inside the window


@dataclass(frozen=True)
class FitCheck:
    """How well a model reproduces the measured PV on the chosen window."""

    verdict: str  # "good", "fair" or "poor"
    r_squared: float


@dataclass(frozen=True)
class StepPreview:
    """Predicted closed-loop response of the model to a unit setpoint step."""

    t_s: np.ndarray
    pv: np.ndarray
    out: np.ndarray


def simulate_fopdt(model: FopdtModel, u: np.ndarray, dt_s: float, y0: float) -> np.ndarray:
    """PV that the model predicts for the input ``u``, starting at rest at ``y0``.

    Deviation form: the input before the window is taken as ``u[0]``, so the model only has to
    explain the movement inside the window (the identification fits a constant offset as well).
    """
    decay = float(np.exp(-dt_s / model.time_constant_s))
    delay = int(round(model.delay_s / dt_s))
    deviation = np.zeros(len(u))
    for k in range(len(u) - 1):
        delayed = u[k - delay] if k >= delay else u[0]
        drive = model.gain * (1.0 - decay) * (delayed - u[0])
        deviation[k + 1] = decay * deviation[k] + drive
    return y0 + deviation


def fit_check(
    model: FopdtModel, u: np.ndarray, y: np.ndarray, dt_s: float
) -> tuple[FitCheck, np.ndarray]:
    """Compare the model with the measurement: R-squared, a verdict and the simulated PV."""
    simulated = simulate_fopdt(model, u, dt_s, float(y[0]))
    spread = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - float(np.sum((y - simulated) ** 2)) / spread if spread > 0.0 else 0.0
    return FitCheck(_verdict(r_squared), r_squared), simulated


def _verdict(r_squared: float) -> str:
    """Plain-language verdict for an R-squared value."""
    if r_squared >= GOOD_R_SQUARED:
        return "good"
    return "fair" if r_squared >= FAIR_R_SQUARED else "poor"


def closed_loop_step(model: FopdtModel, settings: PiSettings) -> StepPreview:
    """Simulate the loop (PI controller plus the model) for a unit setpoint step at time 0.

    Positional PI with a rectangular integral; the preview shows what the chosen robustness
    would do on the identified model, not on the real plant.
    """
    dt_s = min(model.time_constant_s, model.delay_s) / STEP_SAMPLES_PER_TIME_CONSTANT
    horizon_s = PREVIEW_HORIZON_FACTOR * (model.time_constant_s + model.delay_s)
    n_steps = int(np.ceil(horizon_s / dt_s))
    pv, out = _run_pi_loop(model, settings, dt_s, n_steps)
    keep = np.linspace(0, n_steps - 1, min(PREVIEW_POINTS, n_steps)).astype(int)
    return StepPreview(t_s=keep * dt_s, pv=pv[keep], out=out[keep])


def _run_pi_loop(
    model: FopdtModel, settings: PiSettings, dt_s: float, n_steps: int
) -> tuple[np.ndarray, np.ndarray]:
    """Time loop of :func:`closed_loop_step`: returns the PV and OUT deviation arrays."""
    decay = float(np.exp(-dt_s / model.time_constant_s))
    delay = max(1, int(round(model.delay_s / dt_s)))
    pv = np.zeros(n_steps)
    out = np.zeros(n_steps)
    integral = 0.0
    for k in range(n_steps - 1):
        error = 1.0 - pv[k]
        integral += error * dt_s
        out[k] = settings.kc * (error + integral / settings.ti_s)
        delayed = out[k - delay] if k >= delay else 0.0
        pv[k + 1] = decay * pv[k] + model.gain * (1.0 - decay) * delayed
    out[-1] = out[-2]
    return pv, out


def suggest_windows(
    t_s: np.ndarray, mode: np.ndarray, out: np.ndarray, min_length_s: float
) -> list[tuple[float, float]]:
    """Manual-mode stretches in which the output really moved: good places to identify a model.

    A loop in MAN is open, so the response to OUT is not distorted by the controller. Each stretch
    is trimmed to a lead before the first OUT move and a tail after the last one. Returns
    (start_s, end_s) pairs, the biggest OUT movement first.
    """
    manual = mode == MANUAL_MODE
    edges = np.flatnonzero(np.diff(np.concatenate(([0], manual.astype(int), [0]))))
    found: list[tuple[float, float, float]] = []
    for first, stop in zip(edges[::2], edges[1::2], strict=True):
        window = _trim_to_moves(t_s[first:stop], out[first:stop])
        if window is not None and window[1] - window[0] >= min_length_s:
            found.append((*window, float(np.ptp(out[first:stop]))))
    found.sort(key=lambda item: -item[2])
    return [(start, end) for start, end, _ in found]


def _trim_to_moves(t_s: np.ndarray, out: np.ndarray) -> tuple[float, float] | None:
    """Span of one MAN stretch from LEAD_S before its first OUT move to TAIL_S after its last."""
    if float(np.ptp(out)) < MIN_OUT_MOVE_PCT:
        return None
    moved = np.flatnonzero(np.abs(np.diff(out)) > MOVE_STEP_PCT)
    if len(moved) == 0:
        return None
    start = max(float(t_s[0]), float(t_s[moved[0]]) - LEAD_S)
    end = min(float(t_s[-1]), float(t_s[moved[-1] + 1]) + TAIL_S)
    return start, end

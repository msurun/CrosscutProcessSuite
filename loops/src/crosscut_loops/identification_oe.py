"""Output-error refit of a FOPDT model: the free-run response is matched to y.

The ARX fit in identification.py regresses y[k+1] on the measured y[k], so noise in y
pulls the pole towards zero and the time constant and gain come out too small. Here
the model is simulated without feedback from y and the three parameters are searched
so that the simulated output matches the measured one (an "output-error" fit).
Numpy only: tau and the delay are scanned on grids, the gain and offset are exact
linear least squares for each pair, then the grid is refined around the best pair.
"""

from __future__ import annotations

import numpy as np

from crosscut_loops.tuning_rules import FopdtModel

TAU_GRID_POINTS = 60
REFINE_ROUNDS = 3
MIN_DELAY_SAMPLES = 0.5
REFINE_POINTS = 9
MAX_DELAY_CANDIDATES = 40  # coarse delay grid size; the refinement rounds sharpen it


def refine_output_error(
    model: FopdtModel, u: np.ndarray, y: np.ndarray, dt_s: float, max_delay_s: float
) -> FopdtModel:
    """Return the output-error fit, started from the ARX ``model``'s time scale.

    The tau grid spans 1/20 .. 20 times the ARX tau, so a badly biased start is covered.
    Falls back to ``model`` when no candidate has a positive gain and tau.
    """
    u_values = np.asarray(u, dtype=float)
    y_values = np.asarray(y, dtype=float)
    taus = model.time_constant_s * np.geomspace(0.05, 20.0, TAU_GRID_POINTS)
    delays = np.linspace(0.0, max_delay_s / dt_s, MAX_DELAY_CANDIDATES)
    best = _scan(u_values, y_values, dt_s, taus, delays)
    span = max_delay_s / dt_s / (MAX_DELAY_CANDIDATES - 1)  # one coarse delay step
    for _ in range(REFINE_ROUNDS):
        taus = best[1] * np.geomspace(0.8, 1.25, REFINE_POINTS)
        delays = np.maximum(best[2] + np.linspace(-span, span, REFINE_POINTS), 0.0)
        span /= 3.0
        best = min(best, _scan(u_values, y_values, dt_s, taus, delays), key=lambda c: c[3])
    gain, tau_s, delay_samples, _ = best
    if gain <= 0.0 or tau_s <= 0.0:
        return model
    # FopdtModel requires a positive dead time; half a sample is below what data can resolve.
    delay_s = max(delay_samples, MIN_DELAY_SAMPLES) * dt_s
    return FopdtModel(gain=gain, time_constant_s=tau_s, delay_s=delay_s)


def _scan(
    u: np.ndarray, y: np.ndarray, dt_s: float, taus_s: np.ndarray, delays: np.ndarray
) -> tuple[float, float, float, float]:
    """Best (gain, tau_s, delay_samples, sum_of_squares) over the tau and delay grids."""
    best = (0.0, float(taus_s[0]), float(delays[0]), float("inf"))
    decay = np.exp(-dt_s / taus_s)
    for delay in delays:
        shifted = _delayed(u, float(delay)) - u[0]
        unit = _unit_responses(shifted, decay)
        for index in range(len(taus_s)):
            gain, sse = _gain_and_error(unit[:, index], y)
            if sse < best[3]:
                best = (gain, float(taus_s[index]), float(delay), sse)
    return best


def _delayed(u: np.ndarray, delay_samples: float) -> np.ndarray:
    """``u`` shifted by a fractional number of samples (linear interpolation, edge held)."""
    positions = np.arange(len(u)) - delay_samples
    return np.asarray(np.interp(positions, np.arange(len(u)), u), dtype=float)


def _unit_responses(shifted_u: np.ndarray, decay: np.ndarray) -> np.ndarray:
    """First-order responses (gain 1) of ``shifted_u``, one column per decay factor.

    Same recursion as the discrete model: s[k+1] = a*s[k] + (1-a)*u[k].
    """
    out = np.zeros((len(shifted_u), len(decay)))
    for k in range(len(shifted_u) - 1):
        out[k + 1] = decay * out[k] + (1.0 - decay) * shifted_u[k]
    return out


def _gain_and_error(unit_response: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Least-squares gain (with a free offset) and the resulting sum of squared errors."""
    design = np.column_stack([unit_response, np.ones(len(y))])
    coefficients, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    residual = y - design @ coefficients
    return float(coefficients[0]), float(residual @ residual)

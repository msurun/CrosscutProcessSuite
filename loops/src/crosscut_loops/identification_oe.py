"""Output-error refit of a FOPDT model: the free-run response is matched to y.

The ARX fit in identification.py regresses y[k+1] on the measured y[k], so noise in y
pulls the pole towards zero and the time constant and gain come out too small. Here
the model is simulated without feedback from y and gain, time constant and delay are
searched so that the simulated output matches the measured one (an "output-error" fit).
Numpy only: tau and the delay are scanned on grids, the gain and an output offset are
exact linear least squares for each pair, then the grid is refined around the best pair.
"""

from __future__ import annotations

import numpy as np

from crosscut_loops.tuning_rules import FopdtModel

TAU_GRID_POINTS = 60  # log-spaced time-constant candidates in the coarse scan
REFINE_ROUNDS = 3  # finer re-scans around the best (tau, delay) pair
MIN_DELAY_SAMPLES = 0.5  # smallest dead time reported, in samples
REFINE_POINTS = 9  # grid points per axis in each refinement round
MAX_DELAY_CANDIDATES = 40  # coarse delay grid size; the refinement rounds sharpen it


# codecheck: allow too-many-parameters (public signature used by tuning_report and tests)
def refine_output_error(
    model: FopdtModel,
    controller_output: np.ndarray,
    process_value: np.ndarray,
    dt_s: float,
    max_delay_s: float,
) -> FopdtModel:
    """Return the output-error fit, started from the ARX ``model``'s time scale.

    The tau grid spans 1/20 .. 20 times the ARX tau, so a badly biased start is covered; the
    delay grid spans 0 .. ``max_delay_s`` (converted to samples with ``dt_s``).
    Falls back to ``model`` when no candidate has a positive gain and tau.
    """
    signals = (
        np.asarray(controller_output, dtype=float),
        np.asarray(process_value, dtype=float),
    )
    taus = model.time_constant_s * np.geomspace(0.05, 20.0, TAU_GRID_POINTS)
    delays = np.linspace(0.0, max_delay_s / dt_s, MAX_DELAY_CANDIDATES)
    coarse = _scan(signals, dt_s, taus, delays)
    coarse_step = float(delays[1] - delays[0])  # samples between coarse delay points
    best = _refine_grids(signals, dt_s, coarse, coarse_step)
    return _model_from_fit(model, best, dt_s)


def _model_from_fit(
    fallback: FopdtModel, best: tuple[float, float, float, float], dt_s: float
) -> FopdtModel:
    """FOPDT model of the best (gain, tau_s, delay_samples, sse); ``fallback`` if non-positive."""
    gain, tau_s, delay_samples, _ = best
    if gain <= 0.0 or tau_s <= 0.0:
        return fallback
    # FopdtModel requires a positive dead time; half a sample is below what data can resolve.
    delay_s = max(delay_samples, MIN_DELAY_SAMPLES) * dt_s
    return FopdtModel(gain=gain, time_constant_s=tau_s, delay_s=delay_s)


def _refine_grids(
    signals: tuple[np.ndarray, np.ndarray],
    dt_s: float,
    best: tuple[float, float, float, float],
    span: float,
) -> tuple[float, float, float, float]:
    """Re-scan finer tau and delay grids around ``best``; the delay span shrinks 3x per round."""
    for _ in range(REFINE_ROUNDS):
        taus = best[1] * np.geomspace(0.8, 1.25, REFINE_POINTS)
        delays = np.maximum(best[2] + np.linspace(-span, span, REFINE_POINTS), 0.0)
        span /= 3.0
        refined = _scan(signals, dt_s, taus, delays)
        best = min(best, refined, key=lambda candidate: candidate[3])
    return best


def _scan(
    signals: tuple[np.ndarray, np.ndarray],
    dt_s: float,
    taus_s: np.ndarray,
    delays: np.ndarray,
) -> tuple[float, float, float, float]:
    """Best (gain, tau_s, delay_samples, sum_of_squares) over the tau and delay grids.

    ``signals`` is (controller_output, process_value), equal length.
    """
    controller_output, process_value = signals
    best = (0.0, float(taus_s[0]), float(delays[0]), float("inf"))
    decay = np.exp(-dt_s / taus_s)
    for delay in delays:
        shifted = _delayed(controller_output, float(delay)) - controller_output[0]
        unit = _unit_responses(shifted, decay)
        for index in range(len(taus_s)):
            gain, sse = _gain_and_error(unit[:, index], process_value)
            if sse < best[3]:
                best = (gain, float(taus_s[index]), float(delay), sse)
    return best


def _delayed(controller_output: np.ndarray, delay_samples: float) -> np.ndarray:
    """Controller output delayed by a fractional number of samples (linear interpolation)."""
    sample_index = np.arange(len(controller_output))
    shifted = np.interp(sample_index - delay_samples, sample_index, controller_output)
    return np.asarray(shifted, dtype=float)


def _unit_responses(shifted_u: np.ndarray, decay: np.ndarray) -> np.ndarray:
    """First-order responses (gain 1) of ``shifted_u``, one column per decay factor.

    Same recursion as the discrete model: s[k+1] = a*s[k] + (1-a)*u[k].
    """
    out = np.zeros((len(shifted_u), len(decay)))
    for k in range(len(shifted_u) - 1):
        out[k + 1] = decay * out[k] + (1.0 - decay) * shifted_u[k]
    return out


def _gain_and_error(unit_response: np.ndarray, process_value: np.ndarray) -> tuple[float, float]:
    """Least-squares gain (with a free offset) and the resulting sum of squared errors."""
    design = np.column_stack([unit_response, np.ones(len(process_value))])
    coefficients, _, _, _ = np.linalg.lstsq(design, process_value, rcond=None)
    residual = process_value - design @ coefficients
    return float(coefficients[0]), float(residual @ residual)

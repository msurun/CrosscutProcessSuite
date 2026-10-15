"""Stiction index from the shape of the controller output (curve-fitting method).

A PI controller facing a sticking valve ends up in a limit cycle. The valve position is then
a square-like wave, and the controller output (OUT, the integral of the error) is its
integral: a triangle. Oscillations from aggressive tuning or a sinusoidal disturbance leave a
sine in OUT instead. The method cuts OUT into half-cycles, fits each with a half-sine and a
triangle, and asks which fits better (He, Wang, Pottmann, Qin 2007; see docs/PROVENANCE.md).
OUT is already low-pass filtered by the integral action, which is why this works where
zero-crossing counts and distortion of the noisy PV do not.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

MIN_CYCLES = 6  # fewer cycles give too few half-cycles for a stable median
MIN_SAMPLES_PER_HALF_CYCLE = 30  # fewer samples cannot tell a triangle from a sine
MAX_LENGTH_VARIATION = 0.35  # std/mean of the half-cycle lengths; larger is not a limit cycle
HYSTERESIS_FRACTION = 0.3  # of the signal std: noise inside this band cannot flip the sign
PEAK_POSITIONS = np.linspace(0.2, 0.8, 13)  # triangle apex, as a fraction of the half-cycle


@dataclass(frozen=True)
class CurveFitResult:
    """Median stiction index (0 sine-like, 1 triangle-like) or the reason there is none."""

    index: float | None
    n_cycles: int
    reason: str
    period_s: float | None = None


def curve_fit_index(out: NDArray[np.float64], dt_s: float) -> CurveFitResult:
    """Return the stiction index SI = MSE_sine / (MSE_sine + MSE_triangle), median over half-cycles.

    ``out`` is the controller output sampled every ``dt_s`` seconds. SI is near 1 when a triangle
    describes the half-cycles better than a sine (stiction) and near 0 in the opposite case.
    The index is None, with a reason, when OUT does not show a regular limit cycle.

    Raises:
        ValueError: for a non-positive ``dt_s``, an empty or non-1-D array, or non-finite values.
    """
    _validate(out, dt_s)
    signal = _detrend(out)
    crossings = _zero_crossings(signal)
    n_cycles = max(0, (len(crossings) - 1) // 2)
    reason = _irregularity(crossings, n_cycles)
    if reason:
        return CurveFitResult(None, n_cycles, reason)
    halves = [signal[start:end] for start, end in zip(crossings[:-1], crossings[1:], strict=True)]
    index = float(np.median([_shape_index(half) for half in halves]))
    period_s = 2.0 * float(np.mean(np.diff(np.array(crossings)))) * dt_s
    return CurveFitResult(index, n_cycles, "", period_s)


def _validate(out: NDArray[np.float64], dt_s: float) -> None:
    """Reject input the analysis cannot interpret."""
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")
    if out.ndim != 1 or out.size == 0:
        raise ValueError("out must be a non-empty 1-D array")
    if not np.all(np.isfinite(out)):
        raise ValueError("out must contain only finite values")


def _detrend(out: NDArray[np.float64]) -> NDArray[np.float64]:
    """Remove the mean and a straight-line drift, which would shift the zero crossings."""
    sample_index = np.arange(out.size, dtype=np.float64)
    slope, offset = (float(c) for c in np.polyfit(sample_index, out, 1))
    return np.asarray(out - (slope * sample_index + offset), dtype=np.float64)


def _zero_crossings(signal: NDArray[np.float64]) -> list[int]:
    """Sample indices where the signal changes sign, ignoring wiggles inside the hysteresis band.

    A sign change counts only after the signal has moved beyond ``HYSTERESIS_FRACTION * std`` on
    the other side; the crossing itself is placed at the last sample of the old sign.
    """
    band = HYSTERESIS_FRACTION * float(np.std(signal))
    side = 0
    crossings: list[int] = []
    for i, value in enumerate(signal):
        if abs(value) <= band:
            continue
        new_side = 1 if value > 0 else -1
        if side != 0 and new_side != side:
            crossings.append(_last_sample_of_old_sign(signal, i, new_side))
        side = new_side
    return crossings


def _last_sample_of_old_sign(signal: NDArray[np.float64], confirmed_at: int, new_side: int) -> int:
    """Walk back from the confirming sample to where the signal first took the new sign."""
    j = confirmed_at
    while j > 0 and np.sign(signal[j - 1]) == new_side:
        j -= 1
    return j


def _irregularity(crossings: list[int], n_cycles: int) -> str:
    """Explain why the crossings do not describe a usable limit cycle; empty when they do."""
    if n_cycles < MIN_CYCLES:
        return f"only {n_cycles} cycles found, {MIN_CYCLES} are needed"
    lengths = np.diff(np.array(crossings))
    if int(np.min(lengths)) < MIN_SAMPLES_PER_HALF_CYCLE:
        return f"a half-cycle has fewer than {MIN_SAMPLES_PER_HALF_CYCLE} samples"
    if np.std(lengths) / np.mean(lengths) > MAX_LENGTH_VARIATION:
        return "half-cycle lengths vary too much for a limit cycle"
    return ""


def _shape_index(half_cycle: NDArray[np.float64]) -> float:
    """SI of one half-cycle: 1 when a triangle fits much better than a half-sine."""
    x = np.linspace(0.0, 1.0, half_cycle.size)
    mse_sine = _fit_error(half_cycle, np.sin(np.pi * x))
    mse_triangle = min(_fit_error(half_cycle, _triangle(x, peak)) for peak in PEAK_POSITIONS)
    total = mse_sine + mse_triangle
    return 0.5 if total == 0.0 else float(mse_sine / total)


def _triangle(x: NDArray[np.float64], peak: float) -> NDArray[np.float64]:
    """Unit triangle on [0, 1]: rises from 0 to 1 at ``peak``, then falls back to 0."""
    return np.where(x < peak, x / peak, (1.0 - x) / (1.0 - peak))


def _fit_error(y: NDArray[np.float64], shape: NDArray[np.float64]) -> float:
    """Mean squared residual of y ~ amplitude * shape + offset (both free, least squares)."""
    design = np.column_stack([shape, np.ones_like(shape)])
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    return float(np.mean((y - design @ coefficients) ** 2))

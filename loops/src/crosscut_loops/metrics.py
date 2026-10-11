"""Performance metrics for single control loops, each tested on signals with a known answer.

* Harris index: minimum-variance benchmark (Harris 1989; Desborough and Harris 1992).
* Hagglund oscillation detector: IAE between zero crossings (Hagglund 1995).
* Saturation and flatline fractions: simple data-quality and actuator checks.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

AR_SAMPLES_PER_COEFFICIENT = 10  # shortest series accepted, in samples per AR coefficient
DEFAULT_AR_ORDER = 20
SATURATION_MARGIN_FRACTION = 0.005  # of the output range
DEFAULT_MIN_EXCEEDANCES = 10
DEFAULT_WINDOW_HALF_CYCLES = 20
DEFAULT_MIN_FLAT_RUN = 10

FULL_CIRCLE_RAD = 2.0 * np.pi  # radians in one full oscillation cycle


def _fit_ar(x: np.ndarray, order: int) -> tuple[np.ndarray, float]:
    """Least-squares AR fit of a mean-free series: (coefficients a_1..a_p, residual variance)."""
    lagged = np.column_stack([x[order - j : len(x) - j] for j in range(1, order + 1)])
    target = x[order:]
    coefficients, *_ = np.linalg.lstsq(lagged, target, rcond=None)
    residual = target - lagged @ coefficients
    return coefficients, float(np.var(residual))


def _impulse_response(ar: np.ndarray, length: int) -> np.ndarray:
    """First ``length`` MA coefficients psi_i of the AR model (psi_0 = 1)."""
    psi = np.zeros(length)
    psi[0] = 1.0
    for i in range(1, length):
        terms = min(i, len(ar))
        psi[i] = float(np.dot(ar[:terms], psi[i - 1 :: -1][:terms]))
    return psi


def harris_index(error: np.ndarray, delay_samples: int, ar_order: int = DEFAULT_AR_ORDER) -> float:
    """Harris index in [0, 1]: minimum achievable variance divided by the actual variance.

    A value near 1 means the loop is as good as a minimum-variance controller could be; a small
    value means the variance could be cut a lot by better tuning (given the process delay).
    The minimum variance is sigma_a^2 * sum(psi_i^2, i < delay): the part of the error that
    cannot be influenced within the dead time. A constant error series gives NaN.
    """
    centered_error = _center_and_validate(error, delay_samples, ar_order)
    variance = _variance_of(centered_error)
    ar_coefficients, noise_variance = _fit_ar(centered_error, ar_order)
    impulse_response = _impulse_response(ar_coefficients, delay_samples)
    return _clamp_index(noise_variance, impulse_response, variance)


def _center_and_validate(error: np.ndarray, delay_samples: int, ar_order: int) -> np.ndarray:
    """Validate the inputs, center the error series, and return it as a float array.

    Raises:
        ValueError: if delay_samples is below 1 or the series is too short for the AR fit.
    """
    if delay_samples < 1:
        raise ValueError("delay_samples must be at least 1")
    error_series = np.asarray(error, dtype=float)
    if len(error_series) < AR_SAMPLES_PER_COEFFICIENT * ar_order:
        raise ValueError("error series is too short for the AR fit")
    return error_series - float(error_series.mean())


def _variance_of(centered_error: np.ndarray) -> float:
    """Return the variance of the centered error, or NaN when the error is constant."""
    variance = float(np.var(centered_error))
    if variance == 0.0:
        # A constant error has no variance to benchmark against: the index is undefined (NaN),
        # the same convention analyze_loop uses for segments with zero variance.
        return float("nan")
    return variance


def _clamp_index(noise_variance: float, impulse_response: np.ndarray, variance: float) -> float:
    """Compute the Harris index from the noise variance, impulse response, and error variance."""
    minimum_variance = noise_variance * float(np.sum(impulse_response**2))
    index = minimum_variance / variance
    return float(np.clip(index, 0.0, 1.0))


@dataclass(frozen=True)
class OscillationResult:
    """Outcome of the oscillation detector."""

    detected: bool
    period_s: float | None


def _half_cycles(error: np.ndarray, dt_s: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (IAE, duration in samples) of every half cycle between zero crossings."""
    negative = np.signbit(error - error.mean())
    crossings = np.flatnonzero(negative[1:] != negative[:-1]) + 1
    edges = crossings
    if len(edges) < 2:
        return np.zeros(0), np.zeros(0)
    absolute = np.abs(error - error.mean())
    iae = np.add.reduceat(absolute, edges)[:-1] * dt_s
    return iae, np.diff(edges).astype(float)


def _has_dense_exceedances(exceeds: np.ndarray, minimum: int, window: int) -> bool:
    """True when some window of ``window`` consecutive half cycles holds >= ``minimum`` hits."""
    if len(exceeds) < minimum:
        return False
    width = min(window, len(exceeds))
    counts = np.convolve(exceeds.astype(int), np.ones(width, dtype=int), mode="valid")
    return bool(counts.max() >= minimum)


def _acceptable_iae(amplitude_limit: float, ultimate_period_s: float) -> float:
    """IAE a half cycle may reach before it counts as too large.

    A cycle of the loop's natural frequency with the acceptable amplitude has IAE
    2 * amplitude_limit / omega_u, where omega_u is the ultimate angular frequency.
    """
    omega_u = FULL_CIRCLE_RAD / ultimate_period_s
    return 2.0 * amplitude_limit / omega_u


def _oscillation_period_s(lengths: np.ndarray, large: np.ndarray, dt_s: float) -> float:
    """Dominant oscillation period in seconds: twice the median large half cycle duration."""
    median_half_cycles = float(np.median(lengths[large]))
    return 2.0 * median_half_cycles * dt_s


# codecheck: allow too-many-parameters (public signature used by callers and tests)
def hagglund_oscillation(
    error: np.ndarray,
    dt_s: float,
    amplitude_limit: float,
    ultimate_period_s: float,
    min_exceedances: int = DEFAULT_MIN_EXCEEDANCES,
    window_half_cycles: int = DEFAULT_WINDOW_HALF_CYCLES,
) -> OscillationResult:
    """Detect a sustained oscillation by the IAE of the half cycles between zero crossings.

    A half cycle is "large" when its IAE exceeds 2 * amplitude_limit / omega_u, i.e. when a
    cycle of the loop's natural frequency has more than the acceptable amplitude. Many large
    half cycles in a short stretch mean a sustained oscillation (Hagglund 1995).
    """
    x = np.asarray(error, dtype=float)
    iae, lengths = _half_cycles(x, dt_s)
    large = iae > _acceptable_iae(amplitude_limit, ultimate_period_s)
    if not _has_dense_exceedances(large, min_exceedances, window_half_cycles):
        return OscillationResult(detected=False, period_s=None)
    return OscillationResult(True, _oscillation_period_s(lengths, large, dt_s))


def saturation_fraction(
    out: np.ndarray, low: float, high: float, margin_fraction: float = SATURATION_MARGIN_FRACTION
) -> float:
    """Fraction of (non-NaN) samples at either end of the actuator range."""
    values = np.asarray(out, dtype=float)
    values = values[~np.isnan(values)]
    if len(values) == 0:
        return 0.0
    margin = margin_fraction * (high - low)
    return float(np.mean((values <= low + margin) | (values >= high - margin)))


def flatline_fraction(x: np.ndarray, min_run: int = DEFAULT_MIN_FLAT_RUN) -> float:
    """Fraction of samples inside runs of at least ``min_run`` identical values (stuck signal)."""
    values = np.asarray(x, dtype=float)
    if len(values) == 0:
        return 0.0
    starts = np.flatnonzero(np.append(True, values[1:] != values[:-1]))
    lengths = np.diff(np.append(starts, len(values)))
    return float(lengths[lengths >= min_run].sum() / len(values))

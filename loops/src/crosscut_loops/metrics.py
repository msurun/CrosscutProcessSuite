"""Performance metrics for single control loops, each tested on signals with a known answer.

* Harris index: minimum-variance benchmark (Harris 1989; Desborough and Harris 1992).
* Hagglund oscillation detector: IAE between zero crossings (Hagglund 1995).
* Saturation and flatline fractions: simple data-quality and actuator checks.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

AR_SAMPLES_PER_COEFFICIENT = 10  # shortest series accepted, in samples per AR coefficient
DEFAULT_AR_ORDER = 20  # number of AR coefficients fitted to the error
SATURATION_MARGIN_FRACTION = 0.005  # of the output range
DEFAULT_MIN_EXCEEDANCES = 10  # large half cycles needed inside one window
DEFAULT_WINDOW_HALF_CYCLES = 20  # window length, in half cycles
DEFAULT_MIN_FLAT_RUN = 10  # identical consecutive samples that make a run "flat"

FULL_CIRCLE_RAD = 2.0 * np.pi  # radians in one full oscillation cycle


def _fit_ar(series: np.ndarray, order: int) -> tuple[np.ndarray, float]:
    """Least-squares AR fit of a mean-free series: (coefficients a_1..a_p, residual variance).

    An autoregressive model of order p predicts each sample from the previous p samples:
    series[t] = a_1 * series[t-1] + a_2 * series[t-2] + ... + a_p * series[t-p] + e[t],
    where e[t] is the residual (the part the model cannot explain). The coefficients a_i are
    found by ordinary least squares, which minimises the sum of squared residuals.

    Args:
        series: the observed series (1-D array), assumed to already be mean-free (mean 0).
        order: the model order p, i.e. how many past samples are used as predictors.

    Returns:
        coefficients: array of shape (p,), holding a_1..a_p (dimensionless: units of series/series).
        residual variance: the variance of the residuals e[t] (units: series squared).
    """
    # Build the lag matrix: one column per lag. Column j (0-based) holds series shifted
    # by j+1 samples forward, so row t contains the p values that predict series[order + t].
    # Each column has len(series) - order rows, matching target; the slices stop at len(series) - j
    # only to make that column align with the predictor values, not to set a shared length.
    lagged = np.column_stack([series[order - j : len(series) - j] for j in range(1, order + 1)])
    # The values being predicted: everything from index `order` onwards.
    target = series[order:]
    # Solve min ||lagged @ coefficients - target||^2; lstsq also returns diagnostics (residual
    # sum, rank, singular values) that are dropped through the *_ unpacking.
    coefficients, *_ = np.linalg.lstsq(lagged, target, rcond=None)
    # Residuals e[t] = observed - predicted, where `@` is the matrix product lagged @ coefficients.
    residual = target - lagged @ coefficients
    # Population variance of the residuals (np.var divides by N, not N - 1).
    return coefficients, float(np.var(residual))


def _impulse_response(ar: np.ndarray, length: int) -> np.ndarray:
    """First ``length`` MA coefficients psi_i of the AR model (psi_0 = 1).

    An AR model is a feedback filter: y_t = sum_k ar[k] * y_{t-k} + e_t. The
    impulse response is what the system outputs over time when it is hit once
    by a unit shock e_0 = 1 and nothing afterwards. It is the same as the
    infinite MA representation y_t = sum_i psi_i * e_{t-i}, so psi_0 = 1 and the
    recursion psi_i = sum_{k=1..min(i, order)} ar[k-1] * psi_{i-k} gives each
    coefficient from the previous ones.

    Returns psi, shape (length,), where psi[i] is the response at lag i.
    """
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
    # Center the series (subtract its mean) and check it is long enough to fit an AR model of
    # the requested order; raises if there are too few samples.
    centered_error = _center_and_validate(error, delay_samples, ar_order)
    # Actual variance of the error, in squared error units — the denominator of the index.
    variance = _variance_of(centered_error)
    # Fit an autoregressive (AR) model to the error: the error is assumed to be white noise
    # driving an all-pole filter. ar_coefficients are the a_i of that filter; noise_variance is
    # sigma_a^2, the variance of the driving white noise (in squared error units).
    ar_coefficients, noise_variance = _fit_ar(centered_error, ar_order)
    # Impulse-response coefficients psi_i of the AR filter, truncated at delay_samples.
    # The first `delay_samples` of them (i < delay) cover the dead time, where no controller can
    # act; sigma_a^2 times their squared sum is the irreducible (minimum) variance.
    impulse_response = _impulse_response(ar_coefficients, delay_samples)
    # Harris index = minimum achievable variance / actual variance, clipped into [0, 1];
    # returns NaN when the error is constant (variance zero).
    return _clamp_index(noise_variance, impulse_response, variance)


def _center_and_validate(error: np.ndarray, delay_samples: int, ar_order: int) -> np.ndarray:
    """Validate the inputs, center the error series, and return it as a float array.

    "Centering" means subtracting the mean, so the returned series has mean 0. The
    downstream AR (autoregressive) fit assumes a zero-mean signal, so this is the
    preprocessing step that makes that assumption true.

    Args:
        error: the raw error signal, one sample per time step.
        delay_samples: process dead time in SAMPLES (integer >= 1); the Harris benchmark
            keeps this many impulse-response coefficients.
        ar_order: number of AR coefficients to fit.

    Returns:
        The error samples as float64, shifted so their mean is exactly 0.

    Raises:
        ValueError: if delay_samples is below 1 or the series is too short for the AR fit.
    """
    if delay_samples < 1:
        raise ValueError("delay_samples must be at least 1")

    # Convert to float64 (no copy if it already is) so the mean subtraction below never
    # truncates to integer; the subtraction returns a new array, the caller's stays unchanged.
    error_series = np.asarray(error, dtype=float)

    # An AR fit of `ar_order` coefficients needs roughly AR_SAMPLES_PER_COEFFICIENT
    # samples per coefficient to be well conditioned; fewer samples make the fit
    # unstable, so we reject the input instead of returning garbage coefficients.
    if len(error_series) < AR_SAMPLES_PER_COEFFICIENT * ar_order:
        raise ValueError("error series is too short for the AR fit")

    return error_series - float(error_series.mean())


def _variance_of(centered_error: np.ndarray) -> float:
    """Return the variance of the centered error, or NaN when the error is constant.

    The "centered error" is the error signal with its mean subtracted, so its variance is the
    average of the squared deviations. It is the denominator of the Harris index: a constant
    error has no spread to compare the minimum variance with, so the index is undefined (NaN).

    Args:
        centered_error: 1-D array of error values, already centered (mean removed).

    Returns:
        The variance, in squared units of the error. NaN if the error is constant (variance 0).
    """
    # np.var divides the sum of squared deviations by the number of samples; the cast to float
    # turns numpy's scalar type into a plain Python float the callers can compare and format.
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
    """Return (IAE, duration in samples) of every half cycle between zero crossings.

    A "half cycle" is the stretch of signal between two consecutive crossings of the
    mean of `error`: the curve goes from zero up to a peak and back to zero, or from
    zero down to a trough and back to zero. Hagglund's detector (1995) integrates the
    absolute error over each such stretch, so the sign flip at a crossing separates them.

    A half cycle is cut short — and therefore dropped from both returned arrays —
    when the signal starts or ends away from the mean, since that fraction is
    unobservable.

    Args:
        error: signal samples, e.g. setpoint minus measurement, in engineering units.
        dt_s: sampling period in SECONDS per sample; converts sample counts to time.

    Returns:
        `iae`: integral of the absolute deviation from the mean over each complete half cycle,
        in engineering-units * seconds. `duration`: length of each half cycle in samples.
    """
    # `np.signbit` returns True for values below zero. A sample exactly at the
    # mean is not below zero, so it is classified as non-negative.
    negative = np.signbit(error - error.mean())

    # An index i > 0 belongs to `crossings` when samples i-1 and i lie on opposite sides
    # of the mean, i.e. the signal crossed the mean somewhere in between. The + 1 shifts
    # the crossing index to the first sample after the crossing.
    crossings = np.flatnonzero(negative[1:] != negative[:-1]) + 1

    edges = crossings
    if len(edges) < 2:
        return np.zeros(0), np.zeros(0)

    absolute = np.abs(error - error.mean())

    # `reduceat` sums `absolute` between consecutive edges: segment k covers samples
    # edges[k] .. edges[k+1] - 1. The trailing [:-1] drops the last segment, which runs
    # from the final edge to the end and is truncated. Multiplying by dt_s converts the
    # sample-wise sum into an integral in seconds.
    iae = np.add.reduceat(absolute, edges)[:-1] * dt_s

    # Distance between consecutive edges in samples, i.e. the half cycle length in samples;
    # returned as float because it is later multiplied by dt_s in seconds per sample.
    return iae, np.diff(edges).astype(float)


def _has_dense_exceedances(exceeds: np.ndarray, minimum: int, window: int) -> bool:
    """True when some window of ``window`` consecutive half cycles holds >= ``minimum`` hits.

    One large half cycle can be chance; a sustained oscillation shows many large half
    cycles close together. This helper answers "is there a dense enough stretch?" by sliding
    a window along the half cycles and counting hits in it.

    ``exceeds`` is a boolean array, one entry per half cycle, True when that half cycle
    exceeded the limit. ``minimum`` is the hit count required inside a window (unit:
    half cycles, i.e. a count, not a duration). ``window`` is the window length in half
    cycles (must be >= ``minimum`` to be satisfiable).

    Returns False when the array is too short to ever hold ``minimum`` hits, otherwise
    whether the largest hit count over all windows of length ``min(window, len(exceeds))``
    reaches ``minimum``.
    """
    if len(exceeds) < minimum:
        return False
    width = min(window, len(exceeds))
    counts = np.convolve(exceeds.astype(int), np.ones(width, dtype=int), mode="valid")
    return bool(counts.max() >= minimum)


def _acceptable_iae(amplitude_limit: float, ultimate_period_s: float) -> float:
    """IAE a half cycle may reach before it counts as too large.

    IAE (Integral of the Absolute Error) is the area between the controlled variable
    and its setpoint, accumulated over time. This helper gives the threshold area for
    one half cycle of the loop's oscillation, so a caller can compare a measured or
    simulated half cycle against it.

    A half cycle of a sine with the acceptable amplitude a and the ultimate angular
    frequency omega_u has IAE = a * (T_u / pi) = 2 * a / omega_u, with omega_u = 2 pi / T_u.

    Parameters:
        amplitude_limit: peak deviation of the controlled variable from setpoint, in
            the controlled variable's own unit (for example degrees Celsius).
        ultimate_period_s: period of the loop's self-sustained oscillation at the
            ultimate gain, in seconds.

    Returns:
        The acceptable IAE of one half cycle, in (controlled variable unit * second).
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

    Method of Hagglund 1995. An oscillating loop swings around its setpoint; each swing
    is a "half cycle" between two crossings of the error's mean. Instead of looking at
    peak amplitude, we integrate the absolute error over each half cycle (the IAE) and call
    it "large" when the IAE exceeds 2 * amplitude_limit / omega_u, i.e. when a sine half
    cycle at the loop's ultimate frequency would exceed the acceptable amplitude.
    Many large half cycles in a short stretch mean a sustained oscillation.

    Args:
        error: Error signal samples, error[k] = setpoint - measurement at time k * dt_s.
        dt_s: Sample period of `error`, in seconds.
        amplitude_limit: Largest tolerable oscillation amplitude, in measurement units.
        ultimate_period_s: Period of the loop's natural/ultimate cycle, in seconds.
        min_exceedances: How many "large" half cycles must fall in one window to count.
        window_half_cycles: Width of that sliding window, in half cycles.

    Returns:
        OscillationResult with detected=True and the measured period in seconds, or
        detected=False and period_s=None when no sustained oscillation was found.
    """
    error_array = np.asarray(error, dtype=float)
    # iae[k] is the integral of |error| over the k-th half cycle, in (units * seconds);
    # lengths[k] is that half cycle's duration, in samples.
    iae, lengths = _half_cycles(error_array, dt_s)
    large = iae > _acceptable_iae(amplitude_limit, ultimate_period_s)
    if not _has_dense_exceedances(large, min_exceedances, window_half_cycles):
        return OscillationResult(detected=False, period_s=None)
    return OscillationResult(True, _oscillation_period_s(lengths, large, dt_s))


def saturation_fraction(
    out: np.ndarray, low: float, high: float, margin_fraction: float = SATURATION_MARGIN_FRACTION
) -> float:
    """Fraction of (non-NaN) samples at either end of the actuator range.

    Measures how often the recorded actuator signal (``out``) sits at its
    physical limits, which is the standard sign that a controller is not
    being given enough authority to hold its setpoint.

    ``out``      samples of the actuator signal, in the actuator's own units.
    ``low``      lower end of the actuator range, in the same units.
    ``high``     upper end of the actuator range, in the same units.
    ``margin_fraction``  how close to an end counts as "saturated", as a
                 fraction of the full range (0.02 = within 2% of the end).

    Returns a fraction in [0.0, 1.0]: 0.0 if no sample is saturated, 1.0 if
    every sample is. NaN samples are dropped before counting.

    The margin scales with the range rather than being a fixed number of
    units, so the same threshold works for any actuator regardless of how
    wide its range is.
    """
    # Float values with NaN dropped; boolean indexing makes a new array, the caller's stays intact.
    values = np.asarray(out, dtype=float)
    values = values[~np.isnan(values)]
    if len(values) == 0:
        # No usable samples: there is nothing to take a fraction of.
        return 0.0
    # Distance from each end that still counts as saturated, in actuator units.
    margin = margin_fraction * (high - low)
    return float(np.mean((values <= low + margin) | (values >= high - margin)))


def flatline_fraction(signal: np.ndarray, min_run: int = DEFAULT_MIN_FLAT_RUN) -> float:
    """Fraction of samples inside runs of at least ``min_run`` identical values (stuck signal).

    A signal that is stuck (a sensor that stopped updating, a wire that came loose) repeats
    the same value sample after sample. A "flat run" is a maximal block of consecutive
    samples that all hold the same value. Only runs whose length reaches ``min_run`` count:
    a value that merely happens to repeat once is noise, not a stuck signal.

    ``min_run`` is a number of samples, not a duration, so it must be scaled by the callers
    for their sampling rate.

    Returns a number in [0.0, 1.0]: the share of all samples that sit in such long runs.
    Returns 0.0 for an empty input, since there is no sample to be stuck.
    """
    values = np.asarray(signal, dtype=float)
    if len(values) == 0:
        return 0.0
    # A run starts where the value changes from the previous sample. Prepending True marks the very
    # first sample as a start, because it has no predecessor to compare against. starts then holds
    # the index of every run start, in increasing order.
    starts = np.flatnonzero(np.append(True, values[1:] != values[:-1]))
    # The length of one run is the distance to the next run start. Appending len(values)
    # supplies the end position for the final, otherwise unterminated run, so
    # np.diff yields exactly one length per run.
    lengths = np.diff(np.append(starts, len(values)))
    # Keep only runs at least min_run samples long, add up how many samples they cover,
    # and divide by the total sample count to turn a count into a fraction.
    return float(lengths[lengths >= min_run].sum() / len(values))

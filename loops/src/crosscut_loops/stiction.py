"""Detect stiction in a control loop.

The algorithm detects stiction by looking at the harmonic content of the PV signal.
Stiction makes the PV oscillation non-sinusoidal, while a healthy loop oscillating because of a
disturbance gives a pure sinusoid. The total harmonic distortion (THD) of the PV signal is used
to distinguish between the two cases.

The algorithm is based on the ideas of Thornhill and Choudhury et al. on non-linearity detection.
It has been tested only on self-regulating processes. Integrating processes may behave
differently. Strong measurement noise or other non-linearities (e.g. saturation, non-linear
process gain) also raise THD. The OP signal is currently validated but not used in the verdict.

The algorithm works as follows:
1. Subtract the mean from the PV signal.
2. Count the number of cycles in the PV signal using zero crossings with hysteresis.
3. Calculate the period of the PV signal.
4. Calculate the autocorrelation of the PV signal to check for periodicity.
5. Calculate the total harmonic distortion (THD) of the PV signal.
6. If the THD is above a threshold, the loop is considered to have stiction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.fft import irfft, rfft
from numpy.typing import NDArray

# Minimum number of cycles to consider the signal periodic.
MIN_CYCLES = 5

# Minimum height of the first autocorrelation repeat peak to consider the signal periodic
# (measured: simulated stiction 0.25-0.35, noise-driven wander and random noise below 0.06).
AUTOCORR_MIN = 0.15

# Minimum THD to consider the loop to have stiction.
THD_STICTION_MIN = 0.2

# Largest accepted ratio of zero-crossing cycles to the repeats implied by the autocorrelation peak.
MAX_CYCLE_RATIO = 3.5

# Hysteresis for zero crossings.
HYSTERESIS = 0.1

# Shortest signal that can hold a zero crossing; shorter input has no pair of samples to compare.
MIN_SAMPLES = 2


@dataclass(frozen=True)
class StictionResult:
    """Result of the stiction detection algorithm.

    Attributes:
        verdict: "stiction", "no_stiction" or "inconclusive".
        score: The total harmonic distortion (THD) of the PV signal.
        n_cycles: The number of cycles in the PV signal.
        period_s: The period of the PV signal in seconds, or None if the signal is not periodic.
        reason: A human-readable reason for the verdict.
    """

    verdict: str
    score: float
    n_cycles: int
    period_s: float | None
    reason: str


def detect_stiction(
    pv: NDArray[np.float64], out: NDArray[np.float64], dt_s: float
) -> StictionResult:
    """Detect stiction in a control loop.

    Args:
        pv: The process variable (PV) signal.
        out: The output (OP) signal.
        dt_s: The sampling time in seconds.

    Raises:
        ValueError: If the inputs are invalid (see _validate_input).
    """
    _validate_input(pv, out, dt_s)
    centered_pv = pv - np.mean(pv)
    n_cycles, period_s = _count_cycles(centered_pv, dt_s)
    if not _is_periodic(centered_pv, n_cycles):
        return _inconclusive_result(n_cycles, period_s)
    thd = _calculate_thd(centered_pv)
    return _verdict_from_thd(thd, n_cycles, period_s)


def _inconclusive_result(n_cycles: int, period_s: float | None) -> StictionResult:
    """Build the verdict for a signal that is not periodic."""
    return StictionResult(
        verdict="inconclusive",
        score=0.0,
        n_cycles=n_cycles,
        period_s=period_s,
        reason=f"Signal is not periodic (n_cycles={n_cycles}, period_s={period_s}).",
    )


def _verdict_from_thd(thd: float, n_cycles: int, period_s: float | None) -> StictionResult:
    """Classify the loop as stiction or no stiction by its THD."""
    if thd > THD_STICTION_MIN:
        verdict = "stiction"
        reason = f"High THD ({thd:.2f}) and {n_cycles} cycles."
    else:
        verdict = "no_stiction"
        reason = f"Low THD ({thd:.2f}) and {n_cycles} cycles."
    return StictionResult(
        verdict=verdict,
        score=thd,
        n_cycles=n_cycles,
        period_s=period_s,
        reason=reason,
    )


def _validate_input(pv: NDArray[np.float64], out: NDArray[np.float64], dt_s: float) -> None:
    """Validate the input signals and sampling time.

    Args:
        pv: The process variable (PV) signal.
        out: The output (OP) signal.
        dt_s: The sampling time in seconds.

    Raises:
        ValueError: If the PV and OP signals are shorter than MIN_SAMPLES, have different
            lengths, contain NaN, or if dt_s is not positive.
    """
    if len(pv) < MIN_SAMPLES:
        raise ValueError(f"PV and OP signals need at least {MIN_SAMPLES} samples, got {len(pv)}.")
    if len(pv) != len(out):
        raise ValueError("PV and OP signals must have the same length.")
    if np.isnan(pv).any() or np.isnan(out).any():
        raise ValueError("PV and OP signals must not contain NaN.")
    if dt_s <= 0:
        raise ValueError("Sampling time must be positive.")


def _count_cycles(centered_pv: NDArray[np.float64], dt_s: float) -> tuple[int, float | None]:
    """Count the cycles in the signal and calculate the period.

    Args:
        centered_pv: The mean-free PV signal to analyze.
        dt_s: The sampling time in seconds.

    Returns:
        The number of cycles and the period in seconds, or None if no cycle was found.
    """
    std_pv = np.std(centered_pv)
    if std_pv == 0:
        return 0, None

    crossings = _find_zero_crossings(centered_pv, std_pv)
    n_cycles = len(crossings) // 2
    if n_cycles == 0:
        return 0, None

    return n_cycles, _period_seconds(len(centered_pv), len(crossings), dt_s)


def _period_seconds(n_samples: int, n_crossings: int, dt_s: float) -> float:
    """Return the period of the signal from its zero crossings."""
    # Each cycle crosses zero twice, so the record spans n_crossings / 2 periods.
    return 2 * n_samples * dt_s / n_crossings


def _find_zero_crossings(centered_pv: NDArray[np.float64], std_pv: float) -> list[int]:
    """Find the zero crossings in the signal using hysteresis.

    Args:
        centered_pv: The mean-free PV signal to analyze.
        std_pv: The standard deviation of the signal.

    Returns:
        A list of indices where the signal crosses zero.
    """
    crossings: list[int] = []
    threshold = HYSTERESIS * std_pv
    sign = np.sign(centered_pv[0])

    for i in range(1, len(centered_pv)):
        if sign != np.sign(centered_pv[i]) and abs(centered_pv[i]) > threshold:
            crossings.append(i)
            sign = np.sign(centered_pv[i])

    return crossings


def _is_periodic(centered_pv: NDArray[np.float64], n_cycles: int) -> bool:
    """Check if the signal repeats itself (a limit cycle) and is not just wandering noise.

    The autocorrelation needs a clear repeat peak AND the zero-crossing cycle count must match the
    repeats that peak implies: random wander crosses zero far more often than it repeats (ratio 4.7
    and above, a stiction cycle stays below 3.5), which removes the chance peaks of noise.

    Args:
        centered_pv: The mean-free PV signal to analyze.
        n_cycles: The number of cycles in the signal.

    Returns:
        True if the signal shows a consistent limit cycle, False otherwise.
    """
    if n_cycles < MIN_CYCLES:
        return False
    height, lag = _first_repeat_peak(centered_pv)
    if height < AUTOCORR_MIN or lag == 0:
        return False
    return n_cycles <= MAX_CYCLE_RATIO * len(centered_pv) / lag


def _first_repeat_peak(centered_pv: NDArray[np.float64]) -> tuple[float, int]:
    """Height and lag of the first positive autocorrelation peak after it first turns negative.

    Any smooth signal, noise included, has an autocorrelation near 1 at lag 1, so the maximum over
    small lags says nothing. A periodic signal comes back up to a peak after one period; a random
    wander seldom does. Returns (0.0, 0) when there is no such peak.
    """
    n_samples = len(centered_pv)
    spectrum = rfft(centered_pv, 2 * n_samples)
    autocorr = irfft(np.abs(spectrum) ** 2)[: n_samples // 2]
    autocorr = autocorr / autocorr[0]
    negative = np.flatnonzero(autocorr < 0.0)
    if len(negative) == 0:
        return 0.0, 0
    tail = autocorr[negative[0] :]
    middle = tail[1:-1]
    peaks = np.flatnonzero((middle > tail[:-2]) & (middle >= tail[2:]) & (middle > 0.0))
    if len(peaks) == 0:
        return 0.0, 0
    return float(middle[peaks[0]]), int(negative[0] + peaks[0] + 1)


def _calculate_thd(centered_pv: NDArray[np.float64]) -> float:
    """Calculate the total harmonic distortion (THD) of the signal.

    Args:
        centered_pv: The mean-free PV signal to analyze.

    Returns:
        The harmonic amplitudes relative to the fundamental.
    """
    window = np.hanning(len(centered_pv))
    spectrum = np.abs(rfft(centered_pv * window))
    fundamental = int(np.argmax(spectrum[1:])) + 1
    harmonic_amplitude = np.sqrt(_harmonic_power(spectrum, fundamental))
    return float(harmonic_amplitude / spectrum[fundamental])


def _harmonic_power(spectrum: NDArray[np.float64], fundamental: int) -> float:
    """Sum the squared peak magnitudes around the 2nd to 5th harmonic bins."""
    power = 0.0
    for harmonic in range(2, 6):
        if harmonic * fundamental + 2 >= len(spectrum):
            break
        bin_slice = spectrum[harmonic * fundamental - 1 : harmonic * fundamental + 2]
        power += float(np.max(bin_slice)) ** 2
    return power

"""Detect stiction in a control loop: curve fit on OUT (``detect_stiction``) or THD of PV.

``detect_stiction`` fits the half-cycles of OUT with a sine and a triangle (see
stiction_curvefit.py). ``detect_stiction_from_pv`` is the first method, kept for comparison:
stiction makes the PV oscillation non-sinusoidal, so the total harmonic distortion (THD) of PV
is used to tell it from a disturbance-driven sinusoid. It follows the ideas of Thornhill and
Choudhury et al. on non-linearity detection, was tested only on self-regulating processes, and
strong measurement noise or other non-linearities (saturation, non-linear process gain) also
raise THD. There the OP signal is validated but not used in the verdict.

The PV method works as follows:
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

from crosscut_loops.stiction_curvefit import CurveFitResult, curve_fit_index

# Stiction index thresholds on the shape of OUT (He et al. 2007; see docs/PROVENANCE.md). They were
# fixed before the validation runs and are not to be tuned on the data they are judged on.
SI_STICTION_MIN = 0.6
SI_NO_STICTION_MAX = 0.4

# Minimum number of zero-crossing cycles required to consider the PV signal periodic.
MIN_CYCLES = 5

# Minimum height of the first autocorrelation repeat peak to consider the signal periodic
# (measured: simulated stiction 0.25-0.35, noise-driven wander and random noise below 0.06).
AUTOCORR_MIN = 0.15

# THD of PV (harmonic amplitude / fundamental amplitude, dimensionless) above which the
# PV method says "stiction".
THD_STICTION_MIN = 0.2

# Largest accepted ratio of zero-crossing cycles to the cycles implied by the autocorrelation peak.
MAX_CYCLE_RATIO = 3.5

# Hysteresis multiplier applied to the signal standard deviation for zero crossing detection.
HYSTERESIS = 0.1

# Minimum number of samples a record needs to pass input validation.
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


def detect_stiction_from_pv(
    pv: NDArray[np.float64], out: NDArray[np.float64], dt_s: float
) -> StictionResult:
    """Detect stiction from the harmonic distortion of PV alone (the first method).

    Kept for comparison with :func:`detect_stiction`; it fails when PV carries measurement
    noise or random wander, because zero crossings and distortion then say nothing about the valve.

    Stiction (static friction) is what makes a valve stick and then jump: the
    controller output (OP) moves in small steps while the process variable (PV)
    stays flat, so the loop oscillates even though nothing else is wrong. This
    function looks for the tell-tale sign of that oscillation, a periodic PV
    signal carrying extra harmonics, and reports a verdict.

    The algorithm, in plain words: remove the offset from the PV, measure how
    many oscillation cycles it contains and over how long (the period), check
    that the oscillation repeats, then measure how much harmonic distortion the
    PV carries. A clean sine (no stiction) is almost pure fundamental; a
    sticking valve produces a stick-slip wave rich in harmonics.

    Args:
        pv: The process variable (PV) signal, in engineering units.
        out: The output (OP) signal, in percent of the controller output range.
            Passed to _validate_input only; the current decision uses pv alone.
        dt_s: The sampling time in seconds.

    Returns:
        A StictionResult holding the verdict, the cycle count and the period.

    Raises:
        ValueError: If the inputs are invalid (see _validate_input).
    """
    _validate_input(pv, out, dt_s)
    # Remove the mean to leave only the oscillation, so that zero crossings
    # represent crossings of the oscillation around its own average.
    centered_pv = pv - np.mean(pv)
    n_cycles, period_s = _count_cycles(centered_pv, dt_s)
    if not _is_periodic(centered_pv, n_cycles):
        return _inconclusive_result(n_cycles, period_s)
    # Total Harmonic Distortion: ratio of harmonic amplitude to fundamental amplitude.
    # A pure sine has THD near zero; a non-sinusoidal waveform has a larger value.
    thd = _calculate_thd(centered_pv)
    return _verdict_from_thd(thd, n_cycles, period_s)


def _inconclusive_result(n_cycles: int, period_s: float | None) -> StictionResult:
    """Build the verdict for a signal that is not periodic.

    Called when the stiction detector cannot find a repeating oscillation, so it
    has no basis for a friction verdict. Returning an "inconclusive" result
    instead of a numeric score makes the abstention explicit to the caller.

    Args:
        n_cycles: number of full oscillation cycles detected in the signal, in
            count -- zero when no periodicity was found at all.
        period_s: duration of one oscillation cycle in seconds, or None when the
            signal is aperiodic and no period could be measured.

    Returns:
        A StictionResult with verdict "inconclusive" and score 0.0, since no
        friction score can be computed without a period.
    """
    return StictionResult(
        verdict="inconclusive",
        score=0.0,
        n_cycles=n_cycles,
        period_s=period_s,
        reason=f"Signal is not periodic (n_cycles={n_cycles}, period_s={period_s}).",
    )


def _verdict_from_thd(thd: float, n_cycles: int, period_s: float | None) -> StictionResult:
    """Classify the loop as stiction or no stiction by its THD.

    THD is the total harmonic distortion of the PV signal: the root of the summed power in
    the 2nd to 5th harmonic peaks divided by the amplitude of the fundamental peak.
    A large THD means the loop oscillates on a non-sinusoidal limit cycle,
    which is the signature of valve stiction; a clean loop has a low THD.

    Args:
        thd: total harmonic distortion, dimensionless (0.0 = pure sine,
            1.0 = as much harmonic energy as fundamental).
        n_cycles: number of oscillation cycles observed in the window.
        period_s: period of the oscillation in seconds, or None if not known.

    Returns:
        StictionResult with the verdict, the THD stored as the score, and a
        human-readable reason.
    """
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

    A "cycle" is one full oscillation of the signal, detected by counting the up and down
    zero crossings of the mean-free signal. Two crossings (one up, one down) make one cycle.

    Args:
        centered_pv: The mean-free PV signal to analyze.
        dt_s: The sampling time in seconds.

    Returns:
        The number of cycles and the period in seconds, or None if no cycle was found.
    """
    # A perfectly flat signal has no oscillation to count, so std is zero.
    std_pv = np.std(centered_pv)
    if std_pv == 0:
        return 0, None

    # A zero crossing here is a point where the signal changes sign and is further
    # from zero than a dead band based on the signal's own standard deviation;
    # this filters out tiny jitter around zero.
    crossings = _find_zero_crossings(centered_pv, std_pv)

    # Each cycle needs two crossings: one going up and one coming back down.
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

    A zero crossing is a place where the signal switches from positive to negative or vice
    versa. Counting them over a record of known length gives the frequency of a periodic
    signal, the same idea as counting peaks.

    A plain "did the sign change?" test is fragile: noise near zero makes the signal flicker
    across the axis many times at a single real crossing, inflating the count. Hysteresis
    fixes this by requiring the new sample to be further from zero than a dead band before
    the crossing is accepted.

    Args:
        centered_pv: The mean-free PV signal to analyze, in the unit of the original PV.
            Only the sign and the distance from zero matter here.
        std_pv: The standard deviation of the signal, in the same unit as ``centered_pv``.
            It sets the size of the dead band so the threshold adapts to how noisy the signal
            is.

    Returns:
        A list of indices where the signal crosses zero. Indices are positions into
        ``centered_pv`` (0-based, samples, not seconds). An empty list means no crossing was
        found.
    """
    crossings: list[int] = []

    # Dead band around zero: samples with a smaller magnitude than this are treated as "too
    # close to zero to trust", so noise cannot fake a crossing. HYSTERESIS is a plain scalar
    # multiplier (dimensionless); threshold therefore carries the same unit as centered_pv.
    threshold = HYSTERESIS * std_pv

    # Start from the sign of the first sample and remember the sign of the last *accepted*
    # sample. Only accepted crossings move it, so the state always refers to a sample that
    # already proved it is outside the dead band.
    sign = np.sign(centered_pv[0])

    for i in range(1, len(centered_pv)):
        if sign != np.sign(centered_pv[i]) and abs(centered_pv[i]) > threshold:
            crossings.append(i)
            sign = np.sign(centered_pv[i])

    return crossings


def _is_periodic(centered_pv: NDArray[np.float64], n_cycles: int) -> bool:
    """Check if the signal repeats itself (a limit cycle) and is not just wandering noise.

    A limit cycle is the self-sustained oscillation a sticky valve settles into; because it
    repeats with a stable period, its autocorrelation (the signal correlated with a
    time-shifted copy of itself) shows a tall peak at that period. Random wander has no such
    period, so it must be told apart from a real cycle by comparing two independent counts.

    The autocorrelation needs a clear repeat peak AND the zero-crossing cycle count must match the
    repeats that peak implies: random wander crosses zero far more often than it repeats (ratio 4.7
    and above, a stiction cycle stays below 3.5), which removes the chance peaks of noise.

    Args:
        centered_pv: The mean-free PV signal to analyze.
        n_cycles: The number of cycles in the signal.

    Returns:
        True if the signal shows a consistent limit cycle, False otherwise.
    """
    # Too short a record cannot hold enough repeats to judge periodicity, so bail out early.
    if n_cycles < MIN_CYCLES:
        return False

    # height: normalized autocorrelation at the repeat peak, unitless in [-1, 1], where 1 is a
    #         perfect repeat. lag: how many samples apart the two copies are, i.e. the period in
    #         samples. lag == 0 would mean "the signal repeats with itself", which is meaningless.
    height, lag = _first_repeat_peak(centered_pv)
    if height < AUTOCORR_MIN or lag == 0:
        return False

    # A signal repeating every `lag` samples fits len(centered_pv) / lag cycles in the whole
    # record; that is how many cycles the autocorrelation peak implies. Random wander crosses
    # zero several times inside each swing, so its zero-crossing count (n_cycles) comes out
    # much higher than the peak implies. MAX_CYCLE_RATIO is the largest allowed ratio between
    # the two counts, in cycles per cycle, above which we call the signal mere noise.
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

    THD measures how much energy the signal carries in its harmonics (integer
    multiples of the fundamental frequency) compared with the fundamental
    itself. It is a unitless ratio, so 0.05 means the harmonics total 5 % of
    the fundamental amplitude.

    The estimate is computed with the FFT: the harmonics are the spectral
    peaks at 2f, 3f, 4f, ... where f is the strongest peak.

    Args:
        centered_pv: The mean-free PV signal to analyze. A non-zero mean would
            create a large DC peak that could be mistaken for the fundamental,
            hence the "centered" requirement.

    Returns:
        The total harmonic amplitude relative to the fundamental amplitude,
        as a unitless ratio.

    Raises:
        ValueError: If the signal is too short to contain a harmonic, or if no
            spectral peak other than DC is found.
    """
    # Multiplying by a Hann window tapers the signal to zero at both edges.
    # Without it, the FFT treats the first and last samples as a step, which
    # spreads energy of every tone into neighbouring bins (spectral leakage)
    # and inflates the measured harmonics.
    window = np.hanning(len(centered_pv))

    # rfft = FFT for a real-valued input; it returns only the non-negative
    # frequencies, roughly half as many bins as a full FFT would. abs() turns
    # the complex bins into an amplitude spectrum.
    spectrum = np.abs(rfft(centered_pv * window))

    # spectrum[0] is the DC bin (0 Hz). It is excluded from the search so the
    # fundamental is the strongest *non-DC* bin. argmax returns an index
    # relative to the sliced array, so +1 restores the true bin number.
    fundamental = int(np.argmax(spectrum[1:])) + 1

    # _harmonic_power returns the summed power (amplitude squared) of the
    # harmonics; sqrt() turns that power back into an amplitude, so it can be
    # divided by the fundamental amplitude further down.
    harmonic_amplitude = np.sqrt(_harmonic_power(spectrum, fundamental))

    # Ratio of harmonic amplitude to fundamental amplitude, both unitless.
    return float(harmonic_amplitude / spectrum[fundamental])


def _harmonic_power(spectrum: NDArray[np.float64], fundamental: int) -> float:
    """Sum the squared peak magnitudes around the 2nd to 5th harmonic bins.

    A harmonic is a frequency that is an integer multiple of the fundamental
    frequency: the 2nd harmonic sits at 2 * fundamental, the 3rd at 3 * fundamental,
    and so on. A non-sinusoidal periodic wave (triangle, stick-slip) puts energy at those
    multiples, a pure sine does not, so a high total means a distorted wave.

    :param spectrum: magnitude spectrum in bins, one value per frequency bin
        (unit: amplitude, arbitrary scale).
    :param fundamental: index of the fundamental-frequency bin in the spectrum
        (unit: bin index, not Hz).
    :return: sum over the 2nd..5th harmonics of the squared local peak magnitude
        (unit: amplitude squared).
    """
    power = 0.0
    for harmonic in range(2, 6):
        # A window of one bin on each side is needed around the harmonic bin:
        # spectral leakage and rounding of the bin index mean the real peak is not
        # always exactly on harmonic * fundamental.
        if harmonic * fundamental + 2 >= len(spectrum):
            break
        # Slice covering bin numbers harmonic*fundamental - 1, +0 and +1.
        bin_slice = spectrum[harmonic * fundamental - 1 : harmonic * fundamental + 2]
        # Take the largest value in the window (the peak) and square it, so louder
        # harmonics dominate the sum, then add it to the running total.
        power += float(np.max(bin_slice)) ** 2
    return power


def detect_stiction(
    pv: NDArray[np.float64], out: NDArray[np.float64], dt_s: float
) -> StictionResult:
    """Detect stiction from the shape of the controller output (curve-fitting method).

    A sticking valve turns the PI loop's limit cycle into a triangular OUT; tuning or
    disturbance oscillations leave a sinusoidal OUT. The stiction index (0 = sine, 1 = triangle)
    above ``SI_STICTION_MIN`` means "stiction", below ``SI_NO_STICTION_MAX`` "no_stiction", and
    anything else, or an OUT without a regular limit cycle, "inconclusive". PV is validated but
    not used, because its noise is what defeated :func:`detect_stiction_from_pv`.

    Not applicable to integrating processes, where OUT is not triangular under stiction.

    Raises:
        ValueError: If the inputs are invalid (see _validate_input).
    """
    _validate_input(pv, out, dt_s)
    fit = curve_fit_index(out, dt_s)
    if fit.index is None:
        return StictionResult("inconclusive", 0.0, fit.n_cycles, None, fit.reason)
    return _verdict_from_index(fit)


def _verdict_from_index(fit: CurveFitResult) -> StictionResult:
    """Turn a computed stiction index into a verdict with the index as the score."""
    assert fit.index is not None
    if fit.index > SI_STICTION_MIN:
        verdict, relation = "stiction", "triangular"
    elif fit.index < SI_NO_STICTION_MAX:
        verdict, relation = "no_stiction", "sinusoidal"
    else:
        verdict, relation = "inconclusive", "between sine and triangle"
    reason = f"OUT is {relation} (index {fit.index:.2f}, {fit.n_cycles} cycles)."
    return StictionResult(verdict, fit.index, fit.n_cycles, fit.period_s, reason)

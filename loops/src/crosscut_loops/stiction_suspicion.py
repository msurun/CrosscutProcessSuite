"""Ranked stiction suspicion of one control loop: which valve should be tested first?

Mean of two calibrated tests on an oscillation window: a noise-corrected curve-fit index
(He et al. 2007, band-limited variant) and Horch's cross-correlation oddness. The window is the
longest stretch of the record (whole, halves, quarters, eighths) in which OUT or PV has a
spectral peak that stands out of its neighbourhood (prominence). If no such window exists, the
curve-fit index is also tried on the whole record (no Horch test).

The score is a RANKED SUSPICION in [0, 1], used to decide which valve to take out for a
bump test. It is never a diagnosis: only the test itself shows stiction.

LIMITS: a periodic upstream on/off or square disturbance gives a triangular controller output
and mimics stiction; on synthetic healthy loops with sinusoidal or square disturbances the advice
test_valve appeared in roughly 28 % and 50 % of cases (exp15); at high noise only part of the
sticking valves are found; below 18 samples per half-cycle the curve-fit index is unavailable and
the ranking is near chance (AUC about 0.54). Validated on simulation and 17 public loops only: no
plant data with valve tests exists, model error beyond the synthetic generators is unmeasured, and
level loops rest on 3 real loops. Confirm with a valve test.

Sources:
    * He, Wang, Pottmann, Qin 2007 curve-fit index: the half-cycles of OUT (or PV of an
      integrating level loop) are fitted with a half-sine and a triangle; a triangle means
      stiction. The noise-corrected, band-limited, upsampled variant is our construction
      (experiment exp12): find the period, estimate the white-noise variance above the 8th
      harmonic, keep harmonics 1-7, upsample, fit both shapes and subtract the noise.
    * Horch 1999 cross-correlation: with a sticking valve the cross-correlation of OUT and
      PV is an odd function of the lag, with a disturbance it is even. The odd share of its
      energy is our oddness measure (experiment exp13). It is mapped to 0..1 with the
      medians of synthetic closed loops, NOT of real data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from crosscut_loops.stiction_curvefit import (
    MAX_LENGTH_VARIATION,
    PEAK_POSITIONS,
    _detrend,
    _fit_error,
    _triangle,
    _zero_crossings,
)
from crosscut_loops.stiction_curvefit import MIN_CYCLES as CF_MIN_CYCLES

HARMONICS_KEPT = 7  # harmonics of the fundamental that the band-limited signal keeps
NOISE_FROM_HARMONIC = 8  # noise variance is estimated from bins above this harmonic
MIN_SAMPLES_AFTER_UPSAMPLING = 64  # samples per half-cycle wanted after upsampling
MIN_NOISE_BINS = 16  # fewer high-frequency bins give no noise estimate (noise = 0)
MIN_HALF_CYCLE_SAMPLES = 18  # samples per half-cycle floor; synthetic data only (exp12)
MIN_CYCLES = 6  # cycles a window must hold
PROMINENCE_MIN = 36.5  # pooled 97th percentile of noise-only records, exp15, synthetic
NEIGHBOURHOOD = (0.5, 2.0)  # band around the peak (in frequency) that sets the noise floor
SEGMENT_SPLITS = (1, 2, 4, 8)  # window candidates: whole record, halves, quarters, eighths
MAX_SP_SWING = 0.3  # SP peak-to-peak allowed, relative to the PV oscillation peak-to-peak
HORCH_NONSTICKING_MEDIAN = 0.51  # median oddness, synthetic closed loops (exp13), not real data
HORCH_STICKING_MEDIAN = 0.69  # median oddness, synthetic closed loops (exp13), not real data
TEST_VALVE_MIN = 0.5  # score at or above this: advise a valve test
EPS = 1e-12  # guards against division by zero

ARRAY = NDArray[np.float64]


@dataclass(frozen=True)
class SuspicionResult:
    """Suspicion score of one loop; ``advice`` is test_valve, unlikely or not_ranked."""

    score: float | None
    advice: str
    he_index: float | None
    horch: float | None  # calibrated 0..1; None for kind "L" or when not computed
    period_s: float | None  # period of the window in seconds
    reason: str


@dataclass(frozen=True)
class Window:
    """A stretch [start, stop) of the record that holds a prominent spectral peak."""

    start: int
    stop: int
    period: float  # samples
    prominence: float  # peak power / median power around the peak


@dataclass(frozen=True)
class Record:
    """Setpoint, process value and controller output of one loop plus its loop kind."""

    sp: ARRAY
    pv: ARRAY
    out: ARRAY
    kind: str


def _not_ranked(reason: str) -> SuspicionResult:
    """A result without a score, carrying only the reason."""
    return SuspicionResult(None, "not_ranked", None, None, None, reason)


def _period_samples(x: ARRAY) -> float | None:
    """Period in samples: first autocorrelation maximum after the first zero crossing."""
    n = x.size
    spectrum = np.fft.rfft(x, 2 * n)
    acf = np.fft.irfft(spectrum * np.conj(spectrum))[: n // 2]
    below = np.flatnonzero(acf < 0)
    if below.size == 0:
        return None
    lag = int(below[0] + np.argmax(acf[below[0] :]))
    return float(lag) if lag > 1 and acf[lag] > 0 else None


def _noise_variance(spectrum: NDArray[np.complex128], n: int, k0: float) -> float:
    """White-noise variance from the median power above 8 fundamentals (0 if too few bins)."""
    high = np.abs(spectrum[int(NOISE_FROM_HARMONIC * k0) :]) ** 2 / n
    if high.size < MIN_NOISE_BINS:
        return 0.0
    return float(np.median(high) / np.log(2.0))


def _band_limit(x: ARRAY, k0: float, factor: int) -> ARRAY:
    """Keep bins up to (HARMONICS_KEPT + 0.5) * k0 and return the signal upsampled by factor."""
    n = x.size
    spectrum = np.fft.rfft(x)
    kept = np.zeros(n * factor // 2 + 1, dtype=complex)
    top = min(int((HARMONICS_KEPT + 0.5) * k0), spectrum.size - 1)
    kept[: top + 1] = spectrum[: top + 1]
    return np.asarray(np.fft.irfft(kept, n * factor) * factor)


def _irregularity(crossings: list[int], n_cycles: int) -> str:
    """Why the crossings are not a usable limit cycle (count, length spread); empty if usable."""
    if n_cycles < CF_MIN_CYCLES:
        return f"only {n_cycles} cycles found, {CF_MIN_CYCLES} are needed"
    lengths = np.diff(np.array(crossings))
    if np.std(lengths) / np.mean(lengths) > MAX_LENGTH_VARIATION:
        return "half-cycle lengths vary too much for a limit cycle"
    return ""


def _corrected_index(half: ARRAY, noise: float) -> float:
    """Shape index of one half-cycle with the leftover noise variance removed from both errors."""
    t = np.linspace(0.0, 1.0, half.size)
    sine_err = _fit_error(half, np.sin(np.pi * t))
    tri_err = min(_fit_error(half, _triangle(t, p)) for p in PEAK_POSITIONS)
    denom = sine_err + tri_err - 2.0 * noise
    if denom <= EPS:
        return 0.5
    return float(np.clip((sine_err - noise) / denom, 0.0, 1.0))


def _band_limited(x: ARRAY, period: float) -> tuple[ARRAY, float]:
    """Band-limited upsampled signal and the noise variance that remains in it."""
    k0 = x.size / period
    noise = _noise_variance(np.fft.rfft(x), x.size, k0)
    factor = max(1, int(np.ceil(MIN_SAMPLES_AFTER_UPSAMPLING / (period / 2.0))))
    remaining = noise * (HARMONICS_KEPT + 0.5) * k0 / (x.size / 2.0)
    return _band_limit(x, k0, factor), remaining


def _he_index(signal: ARRAY) -> tuple[float | None, str]:
    """Noise-corrected curve-fit index of ``signal``; None plus a reason if refused."""
    x = _detrend(np.asarray(signal, dtype=float))
    period = _period_samples(x)
    if period is None:
        return None, "no periodicity in the autocorrelation"
    if period / 2.0 < MIN_HALF_CYCLE_SAMPLES:
        return None, f"fewer than {MIN_HALF_CYCLE_SAMPLES} samples per half-cycle"
    y, remaining = _band_limited(x, period)
    crossings = _zero_crossings(y)
    reason = _irregularity(crossings, max(0, (len(crossings) - 1) // 2))
    if reason:
        return None, reason
    halves = [y[a:b] for a, b in zip(crossings[:-1], crossings[1:], strict=True)]
    return float(np.median([_corrected_index(h, remaining) for h in halves])), ""


def _peak_prominence(x: ARRAY) -> tuple[float, float] | None:
    """(period in samples, prominence) of the strongest spectral peak with >= MIN_CYCLES cycles.

    Prominence = peak power / median power in the band NEIGHBOURHOOD times the peak frequency,
    with the peak itself (+-3 bins) left out: a red-noise spectrum is lifted around the peak as
    well, so a random wander does not look prominent, while a limit cycle stands out.
    """
    n = x.size
    pad = 4 * n
    power = np.abs(np.fft.rfft((x - x.mean()) * np.hanning(n), pad)) ** 2
    k_min, k_max = int(MIN_CYCLES * 4), pad // 4
    if k_min >= k_max - 8:
        return None
    k = k_min + int(np.argmax(power[k_min:k_max]))
    lo, hi = int(NEIGHBOURHOOD[0] * k), min(int(NEIGHBOURHOOD[1] * k), power.size - 1)
    around = np.r_[power[lo : k - 3], power[k + 4 : hi]]
    if around.size < 8 or np.median(around) <= 0:
        return None
    a, b, c = np.log(power[k - 1 : k + 2] + EPS)
    shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
    return float(pad / (k + shift)), float(power[k] / np.median(around))


def _try_segment(sp: ARRAY, signals: tuple[ARRAY, ARRAY], a: int, b: int) -> Window | None:
    """The segment as a Window (OUT or PV, higher prominence) if a peak is significant."""
    best = None
    for sig in signals:
        found = _peak_prominence(_detrend(sig[a:b]))
        if found is None or (b - a) / found[0] < MIN_CYCLES or found[1] < PROMINENCE_MIN:
            continue
        quiet = np.ptp(sp[a:b]) <= MAX_SP_SWING * max(np.ptp(_detrend(signals[1][a:b])), EPS)
        if quiet and (best is None or found[1] > best.prominence):
            best = Window(a, b, found[0], found[1])
    return best


def _find_window(sp: ARRAY, pv: ARRAY, out: ARRAY) -> Window | None:
    """Longest segment with a significant peak; ties (same length) go to the higher prominence."""
    n = pv.size
    found = []
    for k in SEGMENT_SPLITS:
        for i in range(k):
            w = _try_segment(sp, (out, pv), i * n // k, (i + 1) * n // k)
            if w is not None:
                found.append(((w.stop - w.start, w.prominence), w))
    return max(found, key=lambda f: f[0])[1] if found else None


def _horch_oddness(op: ARRAY, pv: ARRAY, period: float) -> float:
    """Odd share of the OUT-PV cross-correlation energy over lags of +-1 period (0..1)."""
    x, y = _detrend(op), _detrend(pv)
    m = int(period)
    full = np.correlate(x, y, "full") / (x.std() * y.std() * x.size + EPS)
    mid = x.size - 1
    pos, neg = full[mid + 1 : mid + m + 1], full[mid - m : mid][::-1]
    odd, even = (pos - neg) / 2.0, (pos + neg) / 2.0
    return float(np.sum(odd**2) / (np.sum(odd**2) + np.sum(even**2) + EPS))


def _calibrated(raw: float) -> float:
    """Map a raw oddness to 0..1: 0 = synthetic non-sticking median, 1 = sticking median."""
    lo, hi = HORCH_NONSTICKING_MEDIAN, HORCH_STICKING_MEDIAN
    return float(np.clip((raw - lo) / (hi - lo), 0.0, 1.0))


def _advice(score: float) -> str:
    """test_valve at or above TEST_VALVE_MIN, otherwise unlikely."""
    return "test_valve" if score >= TEST_VALVE_MIN else "unlikely"


def _rank(rec: Record, w: Window, dt_s: float) -> SuspicionResult:
    """Run the tests on the window and average the calibrated ones."""
    sl = slice(w.start, w.stop)
    he, he_reason = _he_index((rec.pv if rec.kind == "L" else rec.out)[sl])
    horch = None
    if rec.kind != "L":
        horch = _calibrated(_horch_oddness(rec.out[sl], rec.pv[sl], w.period))
    parts = [p for p in (horch, he) if p is not None]
    period_s = w.period * dt_s
    if not parts:
        return SuspicionResult(None, "not_ranked", he, horch, period_s, he_reason)
    score = float(np.mean(parts))
    reason = f"mean of {len(parts)} test(s) on {w.stop - w.start} samples (prominent peak)" + (
        f"; curve-fit index unavailable: {he_reason}" if he is None else ""
    )
    return SuspicionResult(score, _advice(score), he, horch, period_s, reason)


def _whole_record(rec: Record) -> SuspicionResult:
    """No window: the curve-fit index on the whole record is the only test (no Horch)."""
    he, why = _he_index(rec.pv if rec.kind == "L" else rec.out)
    if he is None:
        return _not_ranked(f"no window; curve-fit index unavailable: {why}")
    return SuspicionResult(he, _advice(he), he, None, None, "whole record, no window")


def _validate(arrays: tuple[ARRAY, ARRAY, ARRAY], dt_s: float, kind: str) -> None:
    """Raise ValueError for an unknown kind, unequal lengths or a non-positive dt_s."""
    if kind not in ("F", "L"):
        raise ValueError(f"kind must be 'F' or 'L', got {kind!r}")
    if len({a.size for a in arrays}) != 1:
        raise ValueError("sp, pv and out must have the same length")
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")


def stiction_suspicion(
    sp: ARRAY, pv: ARRAY, out: ARRAY, dt_s: float, kind: str = "F"
) -> SuspicionResult:
    """Rank how strongly a loop's record points to a sticking valve (a suspicion, no diagnosis).

    ``sp``, ``pv`` and ``out`` are equally long, sampled every ``dt_s`` seconds. ``kind`` "F" is
    a self-regulating loop (curve-fit index on OUT plus Horch), "L" an integrating level loop
    (curve-fit index on PV, no Horch). A score from 0.5 up advises a valve test.

    Raises:
        ValueError: for an unknown kind, unequal array lengths or ``dt_s`` <= 0.
    """
    arrays = (
        np.asarray(sp, dtype=float),
        np.asarray(pv, dtype=float),
        np.asarray(out, dtype=float),
    )
    _validate(arrays, dt_s, kind)
    if not all(bool(np.all(np.isfinite(a))) for a in arrays):
        return _not_ranked("arrays contain NaN or infinite values")
    if arrays[0].size < 8 * MIN_CYCLES:
        return _not_ranked(f"fewer than {8 * MIN_CYCLES} samples")
    rec = Record(arrays[0], arrays[1], arrays[2], kind)
    w = _find_window(rec.sp, rec.pv, rec.out)
    return _whole_record(rec) if w is None else _rank(rec, w, dt_s)

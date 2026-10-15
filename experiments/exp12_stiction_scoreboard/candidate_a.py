"""Candidate A: band-limited, upsampled, noise-corrected stiction index (round 1 of exp12).

Idea: white noise adds the same variance to the sine fit error and the triangle fit error, which pulls the index to 0.5.
We (1) find the period, (2) estimate the noise variance above the 8th harmonic, (3) keep harmonics 1-7 and upsample
the band-limited signal so each half-cycle has many samples, (4) fit the shapes and subtract the remaining noise variance.
"""

from __future__ import annotations

import numpy as np
from crosscut_loops import stiction_curvefit as cf
from crosscut_loops.stiction import SI_NO_STICTION_MAX, SI_STICTION_MIN

HARMONICS_KEPT = 7
NOISE_FROM_HARMONIC = 8
MIN_SAMPLES_AFTER_UPSAMPLING = 64
MIN_NOISE_BINS = 16
EPS = 1e-12


def period_samples(x: np.ndarray) -> float | None:
    """Period in samples from the first autocorrelation maximum after the first zero crossing; None if absent."""
    n = x.size
    spectrum = np.fft.rfft(x, 2 * n)
    acf = np.fft.irfft(spectrum * np.conj(spectrum))[: n // 2]
    below = np.flatnonzero(acf < 0)
    if below.size == 0:
        return None
    lag = int(below[0] + np.argmax(acf[below[0] :]))
    return float(lag) if lag > 1 and acf[lag] > 0 else None


def noise_variance(spectrum: np.ndarray, n: int, k0: float) -> float:
    """White-noise variance from the median power above NOISE_FROM_HARMONIC fundamentals (0 if too few bins)."""
    high = np.abs(spectrum[int(NOISE_FROM_HARMONIC * k0) :]) ** 2 / n
    if high.size < MIN_NOISE_BINS:
        return 0.0
    return float(np.median(high) / np.log(2.0))


def band_limit(x: np.ndarray, k0: float, factor: int) -> np.ndarray:
    """Keep bins up to (HARMONICS_KEPT + 0.5) * k0 and return the signal upsampled by ``factor``."""
    n = x.size
    spectrum = np.fft.rfft(x)
    kept = np.zeros(n * factor // 2 + 1, dtype=complex)
    top = min(int((HARMONICS_KEPT + 0.5) * k0), spectrum.size - 1)
    kept[: top + 1] = spectrum[: top + 1]
    return np.asarray(np.fft.irfft(kept, n * factor) * factor)


def corrected_index(half: np.ndarray, noise: float) -> float:
    """Shape index of one half-cycle with the leftover noise variance removed from both fit errors."""
    t = np.linspace(0.0, 1.0, half.size)
    sine_err = cf._fit_error(half, np.sin(np.pi * t))
    tri_err = min(cf._fit_error(half, cf._triangle(t, p)) for p in cf.PEAK_POSITIONS)
    denom = sine_err + tri_err - 2.0 * noise
    if denom <= EPS:
        return 0.5
    return float(np.clip((sine_err - noise) / denom, 0.0, 1.0))


def curve_fit_index_a(out: np.ndarray, dt_s: float) -> cf.CurveFitResult:
    """Noise-corrected stiction index on the band-limited, upsampled OP; None with a reason if no regular cycle."""
    x = cf._detrend(np.asarray(out, dtype=float))
    period = period_samples(x)
    if period is None:
        return cf.CurveFitResult(None, 0, "no periodicity in the autocorrelation")
    k0 = x.size / period
    spectrum = np.fft.rfft(x)
    noise = noise_variance(spectrum, x.size, k0)
    factor = max(1, int(np.ceil(MIN_SAMPLES_AFTER_UPSAMPLING / (period / 2.0))))
    y = band_limit(x, k0, factor)
    remaining = noise * (HARMONICS_KEPT + 0.5) * k0 / (x.size / 2.0)
    crossings = cf._zero_crossings(y)
    n_cycles = max(0, (len(crossings) - 1) // 2)
    reason = cf._irregularity(crossings, n_cycles)
    if reason:
        return cf.CurveFitResult(None, n_cycles, reason)
    halves = [y[a:b] for a, b in zip(crossings[:-1], crossings[1:], strict=True)]
    index = float(np.median([corrected_index(h, remaining) for h in halves]))
    return cf.CurveFitResult(
        index, n_cycles, "", 2.0 * float(np.mean(np.diff(crossings))) * dt_s / factor
    )


def candidate_a(pv: np.ndarray, out: np.ndarray, dt_s: float) -> str:
    """Verdict string of candidate A with the shipped thresholds 0.6 / 0.4 (PV unused, as in the shipped path)."""
    del pv
    fit = curve_fit_index_a(out, dt_s)
    if fit.index is None:
        return "inconclusive"
    if fit.index > SI_STICTION_MIN:
        return "stiction"
    return "no_stiction" if fit.index < SI_NO_STICTION_MAX else "inconclusive"

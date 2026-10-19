"""Synthetic signal generator for experiment exp20 (ACF on short records).

Implements G20_SPEC.md: positive cases are jittered sine/square waves plus noise,
negative cases are AR(1), random walks and filtered Poisson steps. Each call uses
one seeded RNG so a (cell, seed) pair is reproducible. Numpy only.
"""

from __future__ import annotations

import numpy as np

POSITIVE_WAVEFORMS = ("sine", "square", "lagged_square")
NOISE_KINDS = ("white", "ar09")
NEGATIVE_KINDS = ("white", "ar050", "ar090", "ar097", "ar099", "random_walk", "sp_steps")

# Jitter of the phase increment: relative std of the per-sample period.
JITTER_RELATIVE_STD = 0.05
JITTER_AR_PHI = 0.99

# Lag filter tau (in samples) for the lagged square wave and the sp_steps level.
SQUARE_LAG_TAU = 1.0  # overwritten per call as P/8
SP_STEPS_LAG_TAU = 20.0

# White noise std added on top of the filtered sp_steps level.
SP_STEPS_NOISE_STD = 0.2
# Mean spacing (in samples) between Poisson step times.
SP_STEPS_MEAN_SPACING_FRACTION = 5.0

MIN_PERIOD_SAMPLES = 10.0
MIN_RECORD_LEN = 50

# AR(1) coefficients per negative kind (and "ar09" positive noise kind).
AR_COEFFICIENTS = {
    "ar050": 0.5,
    "ar090": 0.9,
    "ar097": 0.97,
    "ar099": 0.99,
    "ar09": 0.9,
}


def _stationary_std(phi: float) -> float:
    """Return the stationary std of an AR(1) with coefficient phi and unit innovation std."""
    return 1.0 / np.sqrt(1.0 - phi * phi)


def _scale_to_std(sequence: np.ndarray, target_std: float) -> np.ndarray:
    """Rescale `sequence` to have sample std exactly `target_std` (zeros if its std is 0)."""
    sample_std = float(np.std(sequence))
    if sample_std == 0.0:
        return np.zeros_like(sequence)
    return sequence * (target_std / sample_std)


def _generate_ar1(n: int, phi: float, rng: np.random.Generator) -> np.ndarray:
    """Simulate an AR(1) x[k] = phi*x[k-1] + eps[k], x[0] drawn from the stationary law."""
    innovations = rng.standard_normal(n)
    out = np.empty(n)
    out[0] = rng.normal(0.0, _stationary_std(phi))
    for k in range(1, n):
        out[k] = phi * out[k - 1] + innovations[k]
    return out


def _first_order_lag(signal: np.ndarray, tau: float) -> np.ndarray:
    """Apply a first-order lag y[k] = a*y[k-1] + (1-a)*x[k] with a = exp(-1/tau), y[0] = x[0]."""
    a = float(np.exp(-1.0 / tau))
    out = np.empty_like(signal)
    out[0] = signal[0]
    for k in range(1, len(signal)):
        out[k] = a * out[k - 1] + (1.0 - a) * signal[k]
    return out


def _jittered_phase(n: int, period: float, rng: np.random.Generator) -> np.ndarray:
    """Build phase phi[k] = phi[k-1] + (2 pi / P)*(1 + 0.05*w[k]) with AR(1) jitter w."""
    raw_jitter = _generate_ar1(n, JITTER_AR_PHI, rng)
    jitter = _scale_to_std(raw_jitter, 1.0)
    phase = np.empty(n)
    phase[0] = rng.uniform(0.0, 2.0 * np.pi)
    increments = (2.0 * np.pi / period) * (1.0 + JITTER_RELATIVE_STD * jitter)
    for k in range(1, n):
        phase[k] = phase[k - 1] + increments[k]
    return phase


def _square_wave(phase: np.ndarray) -> np.ndarray:
    """Return sign(sin(phase)) with sign(0) taken as +1."""
    values = np.sin(phase)
    return np.where(values < 0.0, -1.0, 1.0)


def _positive_waveform(waveform: str, phase: np.ndarray, period: float) -> np.ndarray:
    """Render one of POSITIVE_WAVEFORMS from the phase sequence."""
    if waveform == "sine":
        return np.sin(phase)
    square = _square_wave(phase)
    if waveform == "square":
        return square
    lagged = _first_order_lag(square, period / 8.0)
    peak = float(np.max(np.abs(lagged)))
    if peak == 0.0:
        return lagged
    return lagged / peak


def _positive_noise(noise: str, n: int, rng: np.random.Generator) -> np.ndarray:
    """Return noise with sample std exactly 1 (scaling to 1/snr happens later)."""
    if noise == "white":
        return rng.standard_normal(n)
    return _generate_ar1(n, AR_COEFFICIENTS["ar09"], rng)


def positive_case(
    waveform: str, n: int, cycles: int, snr: float, noise: str, seed: int
) -> np.ndarray:
    """Return a jittered waveform plus additive noise with sample std 1/snr.

    Raises ValueError when n < 50, cycles < 1, period < 10 samples, snr <= 0,
    or waveform / noise names are unknown.
    """
    if n < MIN_RECORD_LEN:
        raise ValueError(f"n must be at least {MIN_RECORD_LEN}, got {n}")
    if cycles < 1:
        raise ValueError(f"cycles must be at least 1, got {cycles}")
    if snr <= 0:
        raise ValueError(f"snr must be positive, got {snr}")
    if waveform not in POSITIVE_WAVEFORMS:
        raise ValueError(f"unknown waveform {waveform!r}; expected one of {POSITIVE_WAVEFORMS}")
    if noise not in NOISE_KINDS:
        raise ValueError(f"unknown noise {noise!r}; expected one of {NOISE_KINDS}")

    period = n / float(cycles)
    if period < MIN_PERIOD_SAMPLES:
        raise ValueError(f"period {period:.2f} samples is below {MIN_PERIOD_SAMPLES}")

    rng = np.random.default_rng(seed)
    phase = _jittered_phase(n, period, rng)
    signal = _positive_waveform(waveform, phase, period)
    raw_noise = _positive_noise(noise, n, rng)
    scaled_noise = _scale_to_std(raw_noise, 1.0 / snr)
    return signal + scaled_noise


def _random_walk(n: int, rng: np.random.Generator) -> np.ndarray:
    """Return the cumulative sum of standard normal steps."""
    return np.cumsum(rng.standard_normal(n))


def _poisson_step_times(n: int, rng: np.random.Generator) -> np.ndarray:
    """Return ascending step indices in [1, n) from a Poisson process; at least one step."""
    mean_spacing = n / SP_STEPS_MEAN_SPACING_FRACTION
    gaps = rng.exponential(mean_spacing, n)
    times = np.cumsum(gaps)
    steps = np.unique(times[(times >= 1.0) & (times < float(n))].astype(int))
    if steps.size == 0:
        steps = np.array([1], dtype=int)
    return steps


def _sp_steps(n: int, rng: np.random.Generator) -> np.ndarray:
    """Return a piecewise-constant level through a lag with white noise of std 0.2 added."""
    step_indices = _poisson_step_times(n, rng)
    levels_for_steps = rng.uniform(-1.0, 1.0, step_indices.size)
    level = np.empty(n)
    # Reviewer fix (spec ambiguity): the level before the first step is its own draw, so the
    # first step is a real change; the generated code reused the first step's level.
    level[: step_indices[0]] = rng.uniform(-1.0, 1.0)
    for i, start in enumerate(step_indices):
        end = step_indices[i + 1] if i + 1 < step_indices.size else n
        level[start:end] = levels_for_steps[i]
    lagged = _first_order_lag(level, SP_STEPS_LAG_TAU)
    return lagged + SP_STEPS_NOISE_STD * rng.standard_normal(n)


def negative_case(kind: str, n: int, seed: int) -> np.ndarray:
    """Return a negative-case series of length n (AR(1), random walk or filtered steps).

    Raises ValueError for n < 50 or an unknown kind.
    """
    if n < MIN_RECORD_LEN:
        raise ValueError(f"n must be at least {MIN_RECORD_LEN}, got {n}")
    if kind not in NEGATIVE_KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {NEGATIVE_KINDS}")

    rng = np.random.default_rng(seed)
    if kind == "white":
        return rng.standard_normal(n)
    if kind == "random_walk":
        return _random_walk(n, rng)
    if kind == "sp_steps":
        return _sp_steps(n, rng)
    return _generate_ar1(n, AR_COEFFICIENTS[kind], rng)

"""Tests for the curve-fit stiction index based on half-cycle shape comparison.

The signal under test is the controller output (OP) of a control loop: a triangular
wave means the valve sticks and slips (stiction), a sine means ordinary tuning or
load oscillation. Every test builds its own signal from numpy, so the tests need no
data files and run in well under a second.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.stiction_curvefit import (
    MAX_LENGTH_VARIATION,
    MIN_CYCLES,
    MIN_SAMPLES_PER_HALF_CYCLE,
    curve_fit_index,
)

DT = 1.0
PERIOD = 400
TWELVE_CYCLES = 12 * PERIOD
# A triangle wave written as the inverse sine of a sine: the arcsine turns each
# straight ramp of the sine into a straight line, giving a pure triangle.
TRIANGLE_PEAK = 2 / np.pi


def triangle_wave(sample_count: int = TWELVE_CYCLES, period: int = PERIOD) -> np.ndarray:
    """Triangle with unit amplitude and the given period, in samples."""
    time = np.arange(sample_count) * DT
    return TRIANGLE_PEAK * np.arcsin(np.sin(2 * np.pi * time / period))


def sine_wave(sample_count: int = TWELVE_CYCLES, period: int = PERIOD) -> np.ndarray:
    """Sine with unit amplitude and the given period, in samples."""
    time = np.arange(sample_count) * DT
    return np.sin(2 * np.pi * time / period)


def wave_with_noise(base_wave: np.ndarray, seed: int, sd: float) -> np.ndarray:
    """Return a copy of `base_wave` with gaussian noise of standard deviation `sd`."""
    noise = np.random.default_rng(seed).normal(0.0, sd, base_wave.size)
    return base_wave + noise


def sine_with_drift(seed: int, slope_per_sample: float = 0.0005) -> np.ndarray:
    """Sine plus a slow linear trend, as a drifting load would add."""
    time = np.arange(TWELVE_CYCLES)
    return sine_wave() + slope_per_sample * time


def chirp_sine(sample_count: int = TWELVE_CYCLES) -> np.ndarray:
    """Sine whose period grows from 200 to 800 samples: not a limit cycle."""
    instantaneous_period = np.linspace(200, 800, sample_count)
    phase = 2 * np.pi * np.cumsum(1 / instantaneous_period)
    return np.sin(phase)


def test_constant_cycles_and_length_limits_are_importable() -> None:
    assert MIN_CYCLES == 6
    assert MIN_SAMPLES_PER_HALF_CYCLE == 30
    assert MAX_LENGTH_VARIATION == pytest.approx(0.35)


def test_clean_triangle_gives_index_above_nine_tenths() -> None:
    result = curve_fit_index(triangle_wave(), DT)
    assert result.index is not None
    assert result.index > 0.9


def test_clean_sine_gives_index_below_one_tenth() -> None:
    result = curve_fit_index(sine_wave(), DT)
    assert result.index is not None
    assert result.index < 0.1


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_triangle_with_noise_gives_index_above_six_tenths(seed: int) -> None:
    noisy = wave_with_noise(triangle_wave(), seed, sd=0.03)
    result = curve_fit_index(noisy, DT)
    assert result.index is not None
    assert result.index > 0.6


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_sine_with_noise_gives_index_below_four_tenths(seed: int) -> None:
    noisy = wave_with_noise(sine_wave(), seed, sd=0.03)
    result = curve_fit_index(noisy, DT)
    assert result.index is not None
    assert result.index < 0.4


def test_sine_with_linear_trend_is_detrended() -> None:
    result = curve_fit_index(sine_with_drift(seed=1), DT)
    assert result.index is not None
    assert result.index < 0.1


def test_four_cycles_are_too_few_and_are_reported() -> None:
    result = curve_fit_index(sine_wave(sample_count=4 * PERIOD), DT)
    assert result.index is None
    assert result.n_cycles == 4
    assert "cycle" in result.reason


def test_white_noise_gives_no_index() -> None:
    noise = np.random.default_rng(1).normal(0.0, 1.0, TWELVE_CYCLES)
    result = curve_fit_index(noise, DT)
    assert result.index is None


def test_varying_period_gives_no_index() -> None:
    result = curve_fit_index(chirp_sine(), DT)
    assert result.index is None


def test_a_reason_is_given_whenever_the_index_is_missing() -> None:
    result = curve_fit_index(white_noise(seed=2), DT)
    assert result.index is None
    assert result.reason


def white_noise(seed: int, sample_count: int = TWELVE_CYCLES) -> np.ndarray:
    """Gaussian white noise of unit standard deviation."""
    return np.random.default_rng(seed).normal(0.0, 1.0, sample_count)


def test_non_positive_dt_raises_value_error() -> None:
    with pytest.raises(ValueError):
        curve_fit_index(sine_wave(), 0.0)


def test_empty_array_raises_value_error() -> None:
    with pytest.raises(ValueError):
        curve_fit_index(np.zeros(0), DT)


def test_two_dimensional_array_raises_value_error() -> None:
    with pytest.raises(ValueError):
        curve_fit_index(np.zeros((100, 2)), DT)


def test_non_finite_value_raises_value_error() -> None:
    signal = sine_wave()
    signal[500] = np.nan
    with pytest.raises(ValueError):
        curve_fit_index(signal, DT)


def test_clean_triangle_has_between_eleven_and_twelve_cycles() -> None:
    result = curve_fit_index(triangle_wave(), DT)
    assert 11 <= result.n_cycles <= 12

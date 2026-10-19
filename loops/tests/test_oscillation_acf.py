"""Behavioural tests for ACF-based oscillation detection (Thornhill 2003).

A regular oscillation shows evenly spaced ACF zero crossings, so the mean
period is close to three standard deviations: r = mean(Tp) / (3 * std(Tp))
stays above 1.0 for periodic limit cycles and drops below it for noise.
All signals use fixed seeds so results are reproducible.
"""

import dataclasses

import numpy as np
import pytest
from crosscut_loops.oscillation_acf import (
    REGULARITY_THRESHOLD,
    AcfOscillation,
    acf_regularity,
)


def make_sine(period_samples: int, sample_count: int, amplitude: float = 1.0) -> np.ndarray:
    """Return a sine wave with the given period measured in samples."""
    sample_index = np.arange(sample_count)
    return amplitude * np.sin(2.0 * np.pi * sample_index / period_samples)


def test_a_pure_sine_is_recognised_as_a_regular_oscillation() -> None:
    """A clean sine at 50 samples per period must be flagged regular."""
    error = make_sine(period_samples=50, sample_count=2000)

    result = acf_regularity(error, dt_s=2.0)

    assert result.regular is True
    assert result.period_s == pytest.approx(100.0, rel=0.03)
    assert result.regularity > 1.0
    assert result.reason == ""


def test_a_noisy_sine_is_still_regular_and_on_period() -> None:
    """White noise of std 0.5 must not hide a period-40 sine."""
    rng = np.random.default_rng(0)
    error = make_sine(period_samples=40, sample_count=3000)
    error = error + rng.normal(0.0, 0.5, size=error.size)

    result = acf_regularity(error, dt_s=1.0)

    assert result.regular is True
    assert result.period_s == pytest.approx(40.0, rel=0.05)


def test_a_linear_ramp_is_removed_before_the_acf_is_computed() -> None:
    """Detrending must recover a period-60 sine hidden under a ramp."""
    sample_index = np.arange(2000)
    error = make_sine(period_samples=60, sample_count=2000) + 0.01 * sample_index

    result = acf_regularity(error, dt_s=1.0)

    assert result.regular is True
    assert result.period_s == pytest.approx(60.0, rel=0.05)


def test_white_noise_is_rejected_for_almost_every_seed() -> None:
    """The Thornhill ratio should flag noise as irregular for 9 of 10 seeds."""
    regular_count = 0
    for seed in range(10):
        rng = np.random.default_rng(seed)
        error = rng.normal(0.0, 1.0, size=3000)
        if acf_regularity(error, dt_s=1.0).regular:
            regular_count += 1

    assert regular_count <= 1


def test_a_random_walk_is_not_a_regular_oscillation() -> None:
    """A cumsum of white noise drifts and must be rejected."""
    rng = np.random.default_rng(1)
    error = np.cumsum(rng.normal(0.0, 1.0, size=3000))

    result = acf_regularity(error, dt_s=1.0)

    assert result.regular is False


def test_a_square_wave_is_a_regular_limit_cycle() -> None:
    """A stiction-like square wave at period 80 must be detected."""
    sine = make_sine(period_samples=80, sample_count=2000)
    error = np.sign(sine)

    result = acf_regularity(error, dt_s=1.0)

    assert result.regular is True
    assert result.period_s == pytest.approx(80.0, rel=0.05)


def test_a_signal_shorter_than_the_minimum_is_reported() -> None:
    """Fifty samples are not enough to estimate an ACF."""
    error = make_sine(period_samples=10, sample_count=50)

    result = acf_regularity(error, dt_s=1.0)

    assert result.regular is False
    assert result.reason == "too short"


def test_a_flat_signal_is_reported() -> None:
    """A constant signal has zero variance and no oscillations."""
    error = np.full(500, 3.0)

    result = acf_regularity(error, dt_s=1.0)

    assert result.regular is False
    assert result.reason == "flat signal"


def test_a_nan_value_raises_a_value_error() -> None:
    """A NaN in the signal is a caller error, not a silent rejection."""
    error = make_sine(period_samples=50, sample_count=2000)
    error[100] = np.nan

    with pytest.raises(ValueError):
        acf_regularity(error, dt_s=1.0)


def test_a_non_positive_time_step_raises_a_value_error() -> None:
    """The sampling interval must be strictly positive."""
    error = make_sine(period_samples=50, sample_count=2000)

    with pytest.raises(ValueError):
        acf_regularity(error, dt_s=0.0)


def test_the_regularity_threshold_is_one() -> None:
    """Thornhill's 2003 paper sets the regularity threshold at r = 1.0."""
    assert REGULARITY_THRESHOLD == 1.0


def test_the_result_is_a_frozen_dataclass() -> None:
    """The result type is AcfOscillation and cannot be mutated."""
    error = make_sine(period_samples=50, sample_count=2000)

    result = acf_regularity(error, dt_s=1.0)

    assert isinstance(result, AcfOscillation)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.regular = False


def _ar1(phi: float, n: int, rng: np.random.Generator) -> np.ndarray:
    """Return an AR(1) process x[k] = phi * x[k-1] + e[k] with unit noise."""
    noise = rng.normal(0.0, 1.0, size=n)
    x = np.zeros(n)
    for k in range(1, n):
        x[k] = phi * x[k - 1] + noise[k]
    return x


def test_correlated_noise_is_not_an_oscillation() -> None:
    """AR(1) noise with phi 0.9 or 0.99 must be rejected for at least 19 of 20 seeds."""
    for phi in (0.9, 0.99):
        rejected = 0
        for seed in range(20):
            rng = np.random.default_rng(seed)
            if not acf_regularity(_ar1(phi, 3000, rng), dt_s=1.0).regular:
                rejected += 1

        assert rejected >= 19


def test_a_weak_sine_in_white_noise_is_detected() -> None:
    """A 0.3-amplitude period-60 sine under unit noise must be detected for 18 of 20 seeds."""
    sine = make_sine(period_samples=60, sample_count=3000, amplitude=0.3)
    detected = 0
    for seed in range(20):
        rng = np.random.default_rng(seed)
        result = acf_regularity(sine + rng.normal(0.0, 1.0, size=3000), dt_s=1.0)
        if result.regular:
            detected += 1
            assert result.period_s == pytest.approx(60.0, rel=0.05)

    assert detected >= 18


def test_white_noise_reason_names_the_cause() -> None:
    """Rejected white noise must give a reason naming zero crossings or irregularity."""
    rng = np.random.default_rng(3)
    result = acf_regularity(rng.normal(0.0, 1.0, size=3000), dt_s=1.0)

    assert result.regular is False
    assert result.reason == "too few ACF zero crossings" or result.reason.startswith("irregular")

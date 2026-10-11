"""Tests for the loop performance metrics on signals with a known answer."""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.metrics import (
    flatline_fraction,
    hagglund_oscillation,
    harris_index,
    saturation_fraction,
)

RNG = np.random.default_rng(7)


def ar1(phi: float, n: int = 60_000) -> np.ndarray:
    shocks = RNG.normal(size=n)
    x = np.zeros(n)
    for k in range(1, n):
        x[k] = phi * x[k - 1] + shocks[k]
    return x


def test_harris_index_of_white_noise_is_one_for_delay_one() -> None:
    assert harris_index(RNG.normal(size=50_000), delay_samples=1) == pytest.approx(1.0, abs=0.03)


def test_harris_index_of_ar1_with_delay_one_is_one_minus_phi_squared() -> None:
    assert harris_index(ar1(0.9), delay_samples=1) == pytest.approx(0.19, abs=0.03)


def test_harris_index_grows_with_the_process_delay() -> None:
    phi = 0.9
    expected = (1 - phi**2) * (1 + phi**2 + phi**4)
    assert harris_index(ar1(phi), delay_samples=3) == pytest.approx(expected, abs=0.04)


def test_harris_index_is_scale_and_offset_invariant() -> None:
    x = ar1(0.8, 20_000)
    assert harris_index(5.0 * x + 100.0, 2) == pytest.approx(harris_index(x, 2), rel=1e-6)


def test_harris_index_rejects_a_series_that_is_too_short() -> None:
    with pytest.raises(ValueError, match="short"):
        harris_index(np.zeros(10), delay_samples=1)


def test_sustained_sine_is_detected_as_oscillation_with_its_period() -> None:
    t = np.arange(0.0, 6 * 3600.0, 10.0)
    error = np.sin(2 * np.pi * t / 600.0) + RNG.normal(scale=0.05, size=len(t))
    result = hagglund_oscillation(error, dt_s=10.0, amplitude_limit=0.2, ultimate_period_s=600.0)
    assert result.detected is True
    assert result.period_s == pytest.approx(600.0, rel=0.05)


def test_noise_is_not_an_oscillation() -> None:
    error = RNG.normal(scale=0.05, size=2160)
    result = hagglund_oscillation(error, dt_s=10.0, amplitude_limit=0.2, ultimate_period_s=600.0)
    assert result.detected is False and result.period_s is None


def test_a_few_cycles_are_not_enough_to_call_it_an_oscillation() -> None:
    t = np.arange(0.0, 3600.0, 10.0)
    error = np.where(t < 2400.0, 0.0, np.sin(2 * np.pi * t / 600.0))
    result = hagglund_oscillation(error, dt_s=10.0, amplitude_limit=0.2, ultimate_period_s=600.0)
    assert result.detected is False


def test_saturation_fraction_counts_samples_at_either_limit() -> None:
    out = np.concatenate([np.full(30, 100.0), np.full(20, 0.0), np.full(50, 55.0)])
    assert saturation_fraction(out, low=0.0, high=100.0) == pytest.approx(0.5)


def test_flatline_fraction_counts_only_long_runs_of_identical_values() -> None:
    x = RNG.normal(size=1000)
    x[200:300] = x[200]  # 100 identical samples
    x[500:503] = x[500]  # 3 identical samples: below min_run
    assert flatline_fraction(x, min_run=10) == pytest.approx(0.1)

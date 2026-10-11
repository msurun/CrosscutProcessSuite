"""Tests for the first-order-plus-dead-time (FOPDT) identification routine.

The identification fits the discrete model
    y[k+1] = a * y[k] + b * u[k-d] + c
by least squares, scanning the integer delay d. These tests check that the fit
recovers a known plant simulated with `simulate_fopdt`, and that unidentifiable
or invalid inputs raise `ValueError`.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.identification import identify_fopdt

# How long each random input value is held, in samples. A long hold makes the
# step response visible in the data, which the least-squares fit needs.
HOLD_SAMPLES = 20

# A constant added to every output sample, so the tests prove the fit absorbs
# offsets through the intercept c instead of assuming y starts at zero.
OUTPUT_OFFSET = 5.0


def simulate_fopdt(
    gain: float,
    time_constant_s: float,
    delay_s: float,
    seed: int,
    n: int = 3000,
    dt_s: float = 1.0,
    noise: float = 0.01,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate a FOPDT loop with a piecewise-constant random input.

    The output follows the exact discretisation of the continuous first-order
    plant with a transport delay (the dead time is rounded to whole samples).

    Args:
        gain: Steady-state gain of the plant.
        time_constant_s: Time constant T in seconds.
        delay_s: Dead time in seconds.
        seed: Seed for the random number generator, for reproducible tests.
        n: Number of samples to generate.
        dt_s: Sampling period in seconds.
        noise: Standard deviation of the white noise added to the output.

    Returns:
        A tuple (u, y) of the input and the output arrays, both of length n.
    """
    rng = np.random.default_rng(seed)
    u = _random_holds(rng, n)
    delay_samples = round(delay_s / dt_s)
    decay = np.exp(-dt_s / time_constant_s)
    y = _simulate_response(u, gain, decay, delay_samples, noise, rng)
    return u, y + OUTPUT_OFFSET


def _random_holds(rng: np.random.Generator, n: int) -> np.ndarray:
    """Return n samples where each random value is held for HOLD_SAMPLES."""
    holds = rng.uniform(-1.0, 1.0, size=n // HOLD_SAMPLES + 1)
    return np.repeat(holds, HOLD_SAMPLES)[:n]


def _simulate_response(
    u: np.ndarray,
    gain: float,
    decay: float,
    delay_samples: int,
    noise: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Apply the discretised FOPDT recurrence to u, returning y before offset."""
    y = np.zeros_like(u)
    for k in range(len(u) - 1):
        delayed_u = u[k - delay_samples] if k - delay_samples >= 0 else 0.0
        y[k + 1] = decay * y[k] + gain * (1.0 - decay) * delayed_u + noise * rng.standard_normal()
    return y


def test_a_first_order_plant_is_recovered_within_tolerance() -> None:
    u, y = simulate_fopdt(gain=2.0, time_constant_s=30.0, delay_s=8.0, seed=1)

    model = identify_fopdt(u, y, dt_s=1.0, max_delay_s=20.0)

    assert model.gain == pytest.approx(2.0, rel=0.05)
    assert model.time_constant_s == pytest.approx(30.0, rel=0.10)
    assert model.delay_s == pytest.approx(8.0)


def test_a_slower_plant_with_a_longer_delay_is_recovered() -> None:
    u, y = simulate_fopdt(gain=0.5, time_constant_s=100.0, delay_s=15.0, seed=2, n=6000)

    model = identify_fopdt(u, y, dt_s=1.0, max_delay_s=20.0)

    assert model.gain == pytest.approx(0.5, rel=0.05)
    assert model.time_constant_s == pytest.approx(100.0, rel=0.10)
    assert model.delay_s == pytest.approx(15.0)


@pytest.mark.parametrize("seed", [3, 4, 5])
def test_gain_recovery_is_stable_over_seeds(seed: int) -> None:
    u, y = simulate_fopdt(gain=2.0, time_constant_s=30.0, delay_s=8.0, seed=seed)

    model = identify_fopdt(u, y, dt_s=1.0, max_delay_s=20.0)

    assert model.gain == pytest.approx(2.0, rel=0.10)


def test_a_negative_gain_plant_is_rejected() -> None:
    u, y = simulate_fopdt(gain=-1.0, time_constant_s=30.0, delay_s=8.0, seed=6, n=6000)

    with pytest.raises(ValueError):
        identify_fopdt(u, y, dt_s=1.0, max_delay_s=20.0)


def test_pure_white_noise_cannot_be_identified() -> None:
    rng = np.random.default_rng(7)
    u = rng.standard_normal(3000)
    y = rng.standard_normal(3000)

    with pytest.raises(ValueError):
        identify_fopdt(u, y, dt_s=1.0, max_delay_s=20.0)


def _valid_signals() -> tuple[np.ndarray, np.ndarray]:
    """Return a valid (u, y) pair used as the base case for invalid-input tests."""
    return simulate_fopdt(gain=2.0, time_constant_s=30.0, delay_s=8.0, seed=1)


def test_signals_of_different_lengths_are_rejected() -> None:
    u, y = _valid_signals()

    with pytest.raises(ValueError):
        identify_fopdt(u, y[:-1], dt_s=1.0, max_delay_s=20.0)


def test_signals_containing_nan_are_rejected() -> None:
    u, y = _valid_signals()
    y = y.copy()
    y[0] = np.nan

    with pytest.raises(ValueError):
        identify_fopdt(u, y, dt_s=1.0, max_delay_s=20.0)


@pytest.mark.parametrize(
    ("dt_s", "max_delay_s", "n"),
    [
        (0.0, 20.0, 3000),
        (-1.0, 20.0, 3000),
        (1.0, -1.0, 3000),
        (1.0, 20.0, 20),
    ],
)
def test_invalid_arguments_are_rejected(dt_s: float, max_delay_s: float, n: int) -> None:
    u, y = _valid_signals()

    with pytest.raises(ValueError):
        identify_fopdt(u[:n], y[:n], dt_s=dt_s, max_delay_s=max_delay_s)

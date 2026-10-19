"""Tests for the first-order-plus-dead-time (FOPDT) identification routine.

The identification fits the discrete model
    y[k+1] = a * y[k] + b * u[k-d] + c
by least squares, scanning the integer delay d. These tests check that the fit
recovers a known plant simulated with `simulate_fopdt`, and that unidentifiable
or invalid inputs raise `ValueError`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
from crosscut_loops.identification import identify_fopdt

# How long each random input value is held, in samples. A long hold makes the
# step response visible in the data, which the least-squares fit needs.
HOLD_SAMPLES = 20

# A constant added to every output sample, so the tests prove the fit absorbs
# offsets through the intercept c instead of assuming y starts at zero.
OUTPUT_OFFSET = 5.0


@dataclass(frozen=True)
class SimulationSettings:
    """Sampling and noise settings of a simulated FOPDT run.

    Attributes:
        seed: Seed for the random number generator, for reproducible tests.
        sample_count: Number of samples to generate.
        dt_s: Sampling period in seconds.
        noise: Standard deviation of the white noise added to the output.
    """

    seed: int = 0
    sample_count: int = 3000
    dt_s: float = 1.0
    noise: float = 0.01


def simulate_fopdt(
    gain: float,
    time_constant_s: float,
    delay_s: float,
    settings: SimulationSettings | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate a FOPDT loop with a piecewise-constant random input.

    The output follows the exact discretisation of the continuous first-order
    plant with a transport delay (the dead time is rounded to whole samples).

    Args:
        gain: Steady-state gain of the plant.
        time_constant_s: Time constant T in seconds.
        delay_s: Dead time in seconds.
        settings: Number of samples, sampling period and output noise level.

    Returns:
        A tuple (u, y) of the input and the output arrays, both of length settings.sample_count.
    """
    settings = settings or SimulationSettings()
    rng = np.random.default_rng(settings.seed)
    controller_output = _random_holds(rng, settings.sample_count)
    delay_samples = round(delay_s / settings.dt_s)
    decay = np.exp(-settings.dt_s / time_constant_s)
    # Delaying u by padding zeros in front keeps the recurrence free of index tests.
    delayed_u = np.concatenate([np.zeros(delay_samples), controller_output])[
        : len(controller_output)
    ]
    noise_samples = settings.noise * rng.standard_normal(len(controller_output) - 1)
    process_value = _simulate_response(delayed_u, decay, gain * (1.0 - decay), noise_samples)
    return controller_output, process_value + OUTPUT_OFFSET


def _random_holds(rng: np.random.Generator, sample_count: int) -> np.ndarray:
    """Return sample_count samples where each random value is held for HOLD_SAMPLES."""
    holds = rng.uniform(-1.0, 1.0, size=sample_count // HOLD_SAMPLES + 1)
    return np.repeat(holds, HOLD_SAMPLES)[:sample_count]


def _simulate_response(
    delayed_u: np.ndarray, decay: float, input_weight: float, noise_samples: np.ndarray
) -> np.ndarray:
    """Apply the discretised FOPDT recurrence to the delayed input, before the offset."""
    process_value = np.zeros_like(delayed_u)
    for k in range(len(delayed_u) - 1):
        process_value[k + 1] = (
            decay * process_value[k] + input_weight * delayed_u[k] + noise_samples[k]
        )
    return process_value


def test_a_first_order_plant_is_recovered_within_tolerance() -> None:
    controller_output, process_value = simulate_fopdt(
        gain=2.0, time_constant_s=30.0, delay_s=8.0, settings=SimulationSettings(seed=1)
    )

    model = identify_fopdt(controller_output, process_value, dt_s=1.0, max_delay_s=20.0)

    assert model.gain == pytest.approx(2.0, rel=0.05)
    assert model.time_constant_s == pytest.approx(30.0, rel=0.10)
    assert model.delay_s == pytest.approx(8.0)


def test_a_slower_plant_with_a_longer_delay_is_recovered() -> None:
    controller_output, process_value = simulate_fopdt(
        gain=0.5,
        time_constant_s=100.0,
        delay_s=15.0,
        settings=SimulationSettings(seed=2, sample_count=6000),
    )

    model = identify_fopdt(controller_output, process_value, dt_s=1.0, max_delay_s=20.0)

    assert model.gain == pytest.approx(0.5, rel=0.05)
    assert model.time_constant_s == pytest.approx(100.0, rel=0.10)
    assert model.delay_s == pytest.approx(15.0)


@pytest.mark.parametrize("seed", [3, 4, 5])
def test_gain_recovery_is_stable_over_seeds(seed: int) -> None:
    controller_output, process_value = simulate_fopdt(
        gain=2.0, time_constant_s=30.0, delay_s=8.0, settings=SimulationSettings(seed=seed)
    )

    model = identify_fopdt(controller_output, process_value, dt_s=1.0, max_delay_s=20.0)

    assert model.gain == pytest.approx(2.0, rel=0.10)


def test_a_negative_gain_plant_is_rejected() -> None:
    controller_output, process_value = simulate_fopdt(
        gain=-1.0,
        time_constant_s=30.0,
        delay_s=8.0,
        settings=SimulationSettings(seed=6, sample_count=6000),
    )

    with pytest.raises(ValueError):
        identify_fopdt(controller_output, process_value, dt_s=1.0, max_delay_s=20.0)


def test_pure_white_noise_cannot_be_identified() -> None:
    rng = np.random.default_rng(7)
    controller_output = rng.standard_normal(3000)
    process_value = rng.standard_normal(3000)

    with pytest.raises(ValueError):
        identify_fopdt(controller_output, process_value, dt_s=1.0, max_delay_s=20.0)


def _valid_signals() -> tuple[np.ndarray, np.ndarray]:
    """Return a valid (u, y) pair used as the base case for invalid-input tests."""
    return simulate_fopdt(
        gain=2.0, time_constant_s=30.0, delay_s=8.0, settings=SimulationSettings(seed=1)
    )


def test_signals_of_different_lengths_are_rejected() -> None:
    controller_output, process_value = _valid_signals()

    with pytest.raises(ValueError):
        identify_fopdt(controller_output, process_value[:-1], dt_s=1.0, max_delay_s=20.0)


def test_signals_containing_nan_are_rejected() -> None:
    controller_output, process_value = _valid_signals()
    process_value = process_value.copy()
    process_value[0] = np.nan

    with pytest.raises(ValueError):
        identify_fopdt(controller_output, process_value, dt_s=1.0, max_delay_s=20.0)


@pytest.mark.parametrize(
    ("dt_s", "max_delay_s", "sample_count"),
    [
        (0.0, 20.0, 3000),
        (-1.0, 20.0, 3000),
        (1.0, -1.0, 3000),
        (1.0, 20.0, 20),
    ],
)
def test_invalid_arguments_are_rejected(dt_s: float, max_delay_s: float, sample_count: int) -> None:
    controller_output, process_value = _valid_signals()

    with pytest.raises(ValueError):
        identify_fopdt(
            controller_output[:sample_count],
            process_value[:sample_count],
            dt_s=dt_s,
            max_delay_s=max_delay_s,
        )

"""Tests for closed-loop (instrumental-variable) FOPDT identification.

The controller adds a coloured load disturbance to the plant input, so the
input correlates with the disturbance and identifies with a two-stage fit.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.identification_cl import identify_fopdt_closed_loop
from crosscut_loops.tuning_rules import FopdtModel
from crosscut_sim.core import Fopdt

# Plant and controller settings of the closed-loop simulation.
PLANT_GAIN = 2.0
PLANT_TIME_CONSTANT_S = 50.0
PLANT_DELAY_S = 10.0
SAMPLE_PERIOD_S = 1.0
CONTROLLER_GAIN = 0.8
CONTROLLER_INTEGRAL_S = 50.0

# Square-wave setpoint and run length of the simulation.
SETPOINT_AMPLITUDE = 1.0
SETPOINT_PERIOD_S = 300
SAMPLE_COUNT = 12000
MAX_DELAY_FOR_FIT_S = 25.0

# AR(1) load disturbance added to the plant input: d[k] = phi * d[k-1] + e[k].
DISTURBANCE_PHI = 0.99
DISTURBANCE_INNOVATION_SD = 0.05
MEASUREMENT_NOISE_SD = 0.02


def _square_setpoint(sample_count: int, dt_s: float) -> np.ndarray:
    """Return a +-SETPOINT_AMPLITUDE square wave that flips every SETPOINT_PERIOD_S."""
    half_period_samples = int(SETPOINT_PERIOD_S / dt_s / 2)
    periods = np.arange(sample_count) // half_period_samples
    return SETPOINT_AMPLITUDE * np.where(periods % 2 == 0, 1.0, -1.0)


def _ar1_disturbance(rng: np.random.Generator, sample_count: int) -> np.ndarray:
    """Return a coloured load disturbance with unit-lag correlation DISTURBANCE_PHI."""
    innovations = DISTURBANCE_INNOVATION_SD * rng.standard_normal(sample_count)
    disturbance = np.zeros(sample_count)
    for k in range(1, sample_count):
        disturbance[k] = DISTURBANCE_PHI * disturbance[k - 1] + innovations[k]
    return disturbance


def _simulate_closed_loop(seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Simulate the PI loop and return (u, y, sp), each SAMPLE_COUNT samples long.

    The controller output u drives both the plant and the disturbance sum, while
    the measured y includes sensor noise. This is the regime where ordinary least
    squares is biased and the instrumental-variable fit is needed.
    """
    rng = np.random.default_rng(seed)
    setpoint = _square_setpoint(SAMPLE_COUNT, SAMPLE_PERIOD_S)
    disturbance = _ar1_disturbance(rng, SAMPLE_COUNT)
    plant = Fopdt(PLANT_GAIN, PLANT_TIME_CONSTANT_S, PLANT_DELAY_S, SAMPLE_PERIOD_S)
    u = np.zeros(SAMPLE_COUNT)
    y = np.zeros(SAMPLE_COUNT)
    integral = 0.0
    for k in range(SAMPLE_COUNT):
        error = setpoint[k] - plant.value
        integral += error * SAMPLE_PERIOD_S
        u[k] = CONTROLLER_GAIN * (error + integral / CONTROLLER_INTEGRAL_S)
        plant.update(u[k] + disturbance[k])
        y[k] = plant.value + MEASUREMENT_NOISE_SD * rng.standard_normal()
    return u, y, setpoint


def _fit(seed: int) -> FopdtModel:
    """Simulate one run and return its identified FOPDT model."""
    u, y, sp = _simulate_closed_loop(seed)
    return identify_fopdt_closed_loop(u, y, sp, SAMPLE_PERIOD_S, MAX_DELAY_FOR_FIT_S)


def test_the_iv_estimate_recovers_the_true_plant_parameters() -> None:
    gains = [_fit(seed).gain for seed in (1, 2, 3)]
    time_constants = [_fit(seed).time_constant_s for seed in (1, 2, 3)]
    delays = [_fit(seed).delay_s for seed in (1, 2, 3)]

    assert np.median(gains) == pytest.approx(PLANT_GAIN, rel=0.25)
    assert np.median(time_constants) == pytest.approx(PLANT_TIME_CONSTANT_S, rel=0.40)
    assert abs(np.median(delays) - PLANT_DELAY_S) <= 4 * SAMPLE_PERIOD_S


def test_a_constant_setpoint_raises_value_error() -> None:
    u, y, _ = _simulate_closed_loop(seed=1)
    sp = np.full_like(y, SETPOINT_AMPLITUDE)

    with pytest.raises(ValueError, match="did not move"):
        identify_fopdt_closed_loop(u, y, sp, SAMPLE_PERIOD_S, MAX_DELAY_FOR_FIT_S)


def test_a_setpoint_of_the_wrong_length_raises_value_error() -> None:
    u, y, sp = _simulate_closed_loop(seed=1)

    with pytest.raises(ValueError):
        identify_fopdt_closed_loop(u, y, sp[:-1], SAMPLE_PERIOD_S, MAX_DELAY_FOR_FIT_S)


def test_a_setpoint_with_nan_raises_value_error() -> None:
    u, y, sp = _simulate_closed_loop(seed=1)
    sp = sp.copy()
    sp[0] = np.nan

    with pytest.raises(ValueError):
        identify_fopdt_closed_loop(u, y, sp, SAMPLE_PERIOD_S, MAX_DELAY_FOR_FIT_S)


def test_a_non_positive_sampling_period_raises_value_error() -> None:
    u, y, sp = _simulate_closed_loop(seed=1)

    with pytest.raises(ValueError):
        identify_fopdt_closed_loop(u, y, sp, 0.0, MAX_DELAY_FOR_FIT_S)


def test_the_result_is_a_model_with_positive_fields() -> None:
    model = _fit(seed=1)

    assert isinstance(model, FopdtModel)
    assert model.gain > 0.0
    assert model.time_constant_s > 0.0
    assert model.delay_s > 0.0


def test_a_record_too_short_for_the_delay_scan_says_so_instead_of_blaming_the_data() -> None:
    samples = np.arange(100, dtype=float)
    with pytest.raises(ValueError, match="record"):
        identify_fopdt_closed_loop(samples, samples, np.sin(samples), 1.0, 30.0)


def test_plain_python_lists_are_accepted_like_arrays() -> None:
    u, y, sp = _simulate_closed_loop(1)
    model = identify_fopdt_closed_loop(
        u.tolist(), y.tolist(), sp.tolist(), SAMPLE_PERIOD_S, MAX_DELAY_FOR_FIT_S
    )
    assert model.gain > 0.0

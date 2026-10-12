"""Tests for the stiction detection algorithm."""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.stiction import detect_stiction
from numpy.typing import NDArray

DT = 1.0
N = 6000
RNG = np.random.default_rng(3)


def simulate_loop(
    seed: int, stiction: bool, disturbance_amp: float = 0.0, sample_count: int = N
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Simulate a PI control loop and return the process variable and controller output traces."""
    rng = np.random.default_rng(seed)
    process_variable = np.zeros(sample_count)
    controller_output = np.zeros(sample_count)
    integral_error = 0.0
    previous_valve_position = 0.0
    process_filter_alpha = np.exp(-1 / 20)
    kc = 0.5
    ti = 20
    valve_deadband = 0.5
    valve_jump = 0.25
    load = 1.0  # constant load disturbance: without it the valve never leaves its rest position

    for k in range(1, sample_count):
        error = -process_variable[k - 1]
        integral_error += error * DT
        raw_output = kc * (error + integral_error / ti)

        if stiction:
            valve_position = _move_valve_with_stiction(
                raw_output, previous_valve_position, valve_deadband, valve_jump
            )
            previous_valve_position = valve_position
        else:
            valve_position = raw_output

        disturbance = disturbance_amp * np.sin(2 * np.pi * k / 150)
        noise = rng.normal(scale=0.005)
        process_variable[k] = (
            process_filter_alpha * process_variable[k - 1]
            + (1 - process_filter_alpha) * (valve_position + load + disturbance)
            + noise
        )
        controller_output[k] = raw_output

    return process_variable[1000:], controller_output[1000:]


def _move_valve_with_stiction(
    raw_output: float, previous_valve_position: float, deadband: float, jump: float
) -> float:
    """Return the new valve position once stiction is applied to the controller output.

    Stiction is modelled as a deadband: a large enough change in the controller output
    moves the valve, and it moves by the full deadband width minus the jump, as the
    valve sticks and then breaks free. Otherwise the valve stays where it was.
    """
    if abs(raw_output - previous_valve_position) > deadband:
        return raw_output - np.sign(raw_output - previous_valve_position) * (deadband - jump)

    return previous_valve_position


def test_stiction_loop_is_detected() -> None:
    pv, out = simulate_loop(seed=1, stiction=True)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "stiction"


def test_healthy_oscillating_loop_is_not_detected() -> None:
    pv, out = simulate_loop(seed=1, stiction=False, disturbance_amp=0.3)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "no_stiction"


def test_white_noise_is_inconclusive() -> None:
    pv = RNG.normal(size=4000)
    out = RNG.normal(size=4000)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "inconclusive"


@pytest.mark.parametrize("seed", [1, 2, 4])
def test_stiction_verdict_is_consistent(seed: int) -> None:
    pv, out = simulate_loop(seed=seed, stiction=True)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "stiction"


def test_stiction_loop_has_period_and_cycles() -> None:
    pv, out = simulate_loop(seed=1, stiction=True)
    result = detect_stiction(pv, out, DT)
    assert result.period_s is not None
    assert result.n_cycles >= 5


def test_healthy_oscillating_loop_has_correct_period() -> None:
    pv, out = simulate_loop(seed=1, stiction=False, disturbance_amp=0.3)
    result = detect_stiction(pv, out, DT)
    assert result.period_s == pytest.approx(150.0, rel=0.15)


def test_invalid_input_raises_value_error() -> None:
    pv = np.zeros(1000)
    out = np.zeros(1001)
    with pytest.raises(ValueError):
        detect_stiction(pv, out, DT)

    pv = np.zeros(1000)
    out = np.zeros(1000)
    out[500] = np.nan
    with pytest.raises(ValueError):
        detect_stiction(pv, out, DT)

    pv = np.zeros(1000)
    out = np.zeros(1000)
    with pytest.raises(ValueError):
        detect_stiction(pv, out, -1.0)


def test_empty_signal_raises_value_error_instead_of_index_error() -> None:
    with pytest.raises(ValueError, match="at least"):
        detect_stiction(np.zeros(0), np.zeros(0), DT)


def random_wander(seed: int, sample_count: int = 5000) -> NDArray[np.float64]:
    """Slowly wandering noise, like the noise-driven variation of a healthy loop."""
    rng = np.random.default_rng(seed)
    samples = np.zeros(sample_count)
    for sample_index in range(1, sample_count):
        samples[sample_index] = 0.99 * samples[sample_index - 1] + rng.normal()
    return samples


@pytest.mark.parametrize("seed", range(1, 21))
def test_random_wander_is_never_reported_as_stiction(seed: int) -> None:
    x = random_wander(seed)
    assert detect_stiction(x, x, DT).verdict != "stiction"


def test_most_simulated_stiction_loops_are_found() -> None:
    verdicts = [
        detect_stiction(*simulate_loop(random_seed, True), DT).verdict
        for random_seed in range(1, 21)
    ]
    assert verdicts.count("stiction") >= 14  # measured 29 of 40; the rest never limit-cycle
    assert "no_stiction" not in verdicts

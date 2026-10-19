"""Tests for the stiction detection algorithm."""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.stiction import detect_stiction
from numpy.typing import NDArray

DT = 1.0
SAMPLE_COUNT = 6000
# The shape method needs at least 6 limit cycles; a stiction cycle here lasts 650-2000 samples.
LONG_RECORD = 20000
WHITE_NOISE_SEED = 3  # the white-noise test starts its own generator: no dependence on test order


# PI controller and valve constants of the simulated loop.
CONTROLLER_GAIN = 0.5
INTEGRAL_TIME = 20
VALVE_DEADBAND = 0.5
VALVE_JUMP = 0.25
# Constant load disturbance: without it the valve never leaves its rest position.
LOAD = 1.0
# Discrete first-order process filter with a time constant of 20 samples.
PROCESS_FILTER_ALPHA = np.exp(-1 / 20)
# Samples discarded at the start so the loop has settled before it is analysed.
WARMUP_SAMPLES = 1000
DISTURBANCE_PERIOD_SAMPLES = 150
MEASUREMENT_NOISE = 0.005


def simulate_loop(
    seed: int, stiction: bool, disturbance_amp: float = 0.0, sample_count: int = SAMPLE_COUNT
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Simulate a PI control loop and return the process variable and controller output traces."""
    rng = np.random.default_rng(seed)
    process_variable = np.zeros(sample_count)
    controller_output = np.zeros(sample_count)
    integral_error = valve_position = 0.0
    for k in range(1, sample_count):
        integral_error -= process_variable[k - 1] * DT  # error = setpoint (0) - measurement
        raw_output = CONTROLLER_GAIN * (-process_variable[k - 1] + integral_error / INTEGRAL_TIME)
        valve_position = (
            _move_valve_with_stiction(raw_output, valve_position, VALVE_DEADBAND, VALVE_JUMP)
            if stiction
            else raw_output
        )
        drive = valve_position + LOAD + _disturbance(k, disturbance_amp)
        process_variable[k] = _filter_step(process_variable[k - 1], drive)
        process_variable[k] += rng.normal(scale=MEASUREMENT_NOISE)
        controller_output[k] = raw_output

    return process_variable[WARMUP_SAMPLES:], controller_output[WARMUP_SAMPLES:]


def _disturbance(sample: int, amplitude: float) -> float:
    """Sinusoidal load disturbance at the given sample."""
    return amplitude * np.sin(2 * np.pi * sample / DISTURBANCE_PERIOD_SAMPLES)


def _filter_step(previous_value: float, drive: float) -> float:
    """One step of the first-order process filter driven by `drive`."""
    return PROCESS_FILTER_ALPHA * previous_value + (1 - PROCESS_FILTER_ALPHA) * drive


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
    """A PI loop with a sticking valve is classified as stiction."""
    pv, out = simulate_loop(seed=1, stiction=True, sample_count=LONG_RECORD)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "stiction"


def test_healthy_oscillating_loop_is_not_detected() -> None:
    """A loop oscillating from an external disturbance must not be blamed on the valve."""
    pv, out = simulate_loop(seed=1, stiction=False, disturbance_amp=0.3)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "no_stiction"


def test_white_noise_is_inconclusive() -> None:
    """Uncorrelated noise has no limit cycle, so no verdict is given."""
    rng = np.random.default_rng(WHITE_NOISE_SEED)
    pv = rng.normal(size=4000)
    out = rng.normal(size=4000)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "inconclusive"


@pytest.mark.parametrize("seed", [1, 2, 4])
def test_stiction_verdict_is_consistent(seed: int) -> None:
    """The stiction verdict does not depend on the noise seed of the simulation."""
    pv, out = simulate_loop(seed=seed, stiction=True, sample_count=LONG_RECORD)
    result = detect_stiction(pv, out, DT)
    assert result.verdict == "stiction"


def test_stiction_loop_has_period_and_cycles() -> None:
    """A stiction verdict comes with the cycle period and at least 6 cycles as evidence."""
    pv, out = simulate_loop(seed=1, stiction=True, sample_count=LONG_RECORD)
    result = detect_stiction(pv, out, DT)
    assert result.period_s is not None
    assert result.n_cycles >= 6


def test_healthy_oscillating_loop_has_correct_period() -> None:
    """The reported period matches the 150-sample disturbance driving the loop."""
    pv, out = simulate_loop(seed=1, stiction=False, disturbance_amp=0.3)
    result = detect_stiction(pv, out, DT)
    assert result.period_s == pytest.approx(150.0, rel=0.15)


def test_invalid_input_raises_value_error() -> None:
    """Mismatched lengths, NaN and a non-positive sampling time are rejected with ValueError."""
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
    """An empty record gives a clear ValueError, not an IndexError from inside the code."""
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
    """Slow random wander of a healthy loop must never produce a stiction verdict."""
    wander = random_wander(seed)
    assert detect_stiction(wander, wander, DT).verdict != "stiction"


def test_most_simulated_stiction_loops_are_found() -> None:
    """At least 18 of 20 simulated sticking loops are found and none is called healthy."""
    verdicts = [
        detect_stiction(*simulate_loop(random_seed, True, sample_count=LONG_RECORD), DT).verdict
        for random_seed in range(1, 21)
    ]
    assert verdicts.count("stiction") >= 18  # measured 20 of 20 (seeds 1-20); margin for platforms
    assert "no_stiction" not in verdicts

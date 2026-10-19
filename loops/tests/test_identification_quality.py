"""Behaviour tests for crosscut_loops.identification_quality.

We check how well a model free-runs on step-test data, how many input moves we
excited, and whether the fit deserves our confidence. The simulated plant is a
first-order plus dead time (FOPDT) process, y[k+1] = a*y[k] + K*(1-a)*u[k-d],
with a = exp(-dt/tau), so we can reason about the true parameters.
"""

import numpy as np
import pytest

# Make the package importable when pytest is run from the repository root.
from crosscut_loops.identification import identify_fopdt
from crosscut_loops.identification_quality import (
    assess_fit,
    count_excitation_events,
    free_run_r2,
)
from crosscut_loops.tuning_rules import FopdtModel

DT_S = 1.0
GAIN = 2.0
TIME_CONSTANT_S = 40.0
DELAY_SAMPLES = 5
SAMPLE_COUNT = 2000
NOISE_SD = 0.05
STEP_INDEX = 300


def simulate_fopdt(controller_output: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Simulate the true FOPDT plant with additive noise.

    a = exp(-dt/tau) is the discrete decay; the recursion is
    y[k+1] = a*y[k] + K*(1-a)*u[max(k-d, 0)]. Returns the noisy output.
    """
    decay = np.exp(-DT_S / TIME_CONSTANT_S)
    process_value = np.zeros(controller_output.size)
    for k in range(controller_output.size - 1):
        delayed = controller_output[max(k - DELAY_SAMPLES, 0)]
        process_value[k + 1] = decay * process_value[k] + GAIN * (1 - decay) * delayed
    return process_value + rng.normal(0.0, NOISE_SD, size=controller_output.size)


def true_model() -> FopdtModel:
    """The exact parameters used by simulate_fopdt, for reference fits."""
    return FopdtModel(gain=GAIN, time_constant_s=TIME_CONSTANT_S, delay_s=DELAY_SAMPLES * DT_S)


def single_step_input() -> np.ndarray:
    """A record with one step up at STEP_INDEX and constant afterwards."""
    controller_output = np.zeros(SAMPLE_COUNT)
    controller_output[STEP_INDEX:] = 1.0
    return controller_output


def test_a_single_step_counts_as_one_excitation_event():
    """One step is one input move; the counter is the basis of the low-confidence flag."""
    assert count_excitation_events(single_step_input()) == 1


def test_a_constant_signal_counts_no_excitation_events():
    """A flat input excites nothing, so the count must be zero."""
    assert count_excitation_events(np.ones(SAMPLE_COUNT)) == 0


def test_a_ramp_over_ten_samples_counts_once():
    """A move spread over several samples is still one event, not one per sample."""
    controller_output = np.zeros(SAMPLE_COUNT)
    controller_output[STEP_INDEX : STEP_INDEX + 10] = np.linspace(0.1, 1.0, 10)
    assert count_excitation_events(controller_output) == 1


def test_two_steps_count_two_excitation_events():
    """Separate moves are counted separately, so richer records earn more confidence."""
    controller_output = single_step_input()
    controller_output[1200:] = 0.0
    assert count_excitation_events(controller_output) == 2


def test_the_true_model_free_runs_with_high_r2():
    """The true parameters must reproduce noisy data with high free-run R2, or the metric is
    useless."""
    rng = np.random.default_rng(seed=7)
    controller_output = single_step_input()
    process_value = simulate_fopdt(controller_output, rng)
    assert free_run_r2(true_model(), controller_output, process_value, DT_S) > 0.95


def test_a_wrong_gain_model_free_runs_with_low_r2():
    """A wrong-gain model must score low, so the metric can tell good fits from bad ones."""
    rng = np.random.default_rng(seed=7)
    controller_output = single_step_input()
    process_value = simulate_fopdt(controller_output, rng)
    wrong = FopdtModel(gain=0.5, time_constant_s=TIME_CONSTANT_S, delay_s=DELAY_SAMPLES * DT_S)
    assert free_run_r2(wrong, controller_output, process_value, DT_S) < 0.6


def test_a_single_step_record_is_flagged_low_confidence():
    """A fit from a single step must be flagged low confidence with an input-move reason."""
    rng = np.random.default_rng(seed=11)
    controller_output = single_step_input()
    process_value = simulate_fopdt(controller_output, rng)
    model = identify_fopdt(controller_output, process_value, DT_S, max_delay_s=10.0)
    assessment = assess_fit(model, controller_output, process_value, DT_S)
    assert assessment.low_confidence is True
    assert any("input move" in reason for reason in assessment.reasons)


def test_a_multi_step_record_is_not_flagged_low_confidence():
    """A well-excited record must pass without any reasons, so the flag is not raised by default."""
    rng = np.random.default_rng(seed=13)
    controller_output = single_step_input()
    controller_output[1200:] = 0.0
    controller_output[1700:] = 1.0
    process_value = simulate_fopdt(controller_output, rng)
    model = identify_fopdt(controller_output, process_value, DT_S, max_delay_s=10.0)
    assessment = assess_fit(model, controller_output, process_value, DT_S)
    assert assessment.low_confidence is False
    assert assessment.reasons == ()


def test_a_constant_output_gives_zero_r2():
    """A constant output has no variance to explain, so R2 must be zero instead of dividing by
    zero."""
    controller_output = single_step_input()
    process_value = np.full(SAMPLE_COUNT, 3.14)
    assert free_run_r2(true_model(), controller_output, process_value, DT_S) == pytest.approx(0.0)

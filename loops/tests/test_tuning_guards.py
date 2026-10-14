"""Tests for the two refusals of build_tuning_report: poor model fit and stiction.

Both are "do not retune this loop yet" paths that must be visible in the report
so an operator never applies settings derived from data the model cannot explain.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.tuning_report import (
    POOR_FIT_PREFIX,
    STICTION_BLOCKED_REASON,
    build_tuning_report,
)

# Sampling period of the synthetic loop, in seconds per sample.
DT_S = 1.0

# Number of samples in the synthetic loop record.
SAMPLE_COUNT = 1500

# Samples per half cycle of the square wave applied to the controller output.
HALF_CYCLE_SAMPLES = 300

# First-order process parameters: y[k+1] = 0.95 * y[k] + 0.05 * gain * (u[k] - 50).
# In plain words: the measured value moves 5% of the way to its target each sample,
# giving a time constant of about 1 / (1 - 0.95) = 20 samples, i.e. 20 s here.
MODEL_MEMORY = 0.95
MODEL_STEP = 1.0 - MODEL_MEMORY

# Controller output levels, in %: the loop is stepped between a low and a high value.
LOW_OUTPUT_PERCENT = 50.0
HIGH_OUTPUT_PERCENT = 58.0

# Process gain, in %PV per %CO: an 8% output step moves the process value by 4 %PV.
PROCESS_GAIN = 0.5

# Noise standard deviations of the three data qualities used below, in %PV.
CLEAN_NOISE_SD = 0.05
MODERATE_NOISE_SD = 0.6
HEAVY_NOISE_SD = 2.0

# Seed of the noise generator; fixed so every run sees the same realisation.
NOISE_SEED = 1


@pytest.fixture
def clean_data() -> tuple[np.ndarray, np.ndarray]:
    """Return a noise-free (controller output, process value) pair for the loop."""
    return _noisy_pair(CLEAN_NOISE_SD)


@pytest.fixture
def moderate_noise_data() -> tuple[np.ndarray, np.ndarray]:
    """Return a (controller output, process value) pair with moderate noise."""
    return _noisy_pair(MODERATE_NOISE_SD)


@pytest.fixture
def heavy_noise_data() -> tuple[np.ndarray, np.ndarray]:
    """Return a (controller output, process value) pair with heavy noise."""
    return _noisy_pair(HEAVY_NOISE_SD)


def _noisy_pair(noise_sd: float) -> tuple[np.ndarray, np.ndarray]:
    """Return the stepped controller output and the process value with added noise.

    The process value follows a first-order response to a square wave of the
    controller output, then Gaussian noise of standard deviation ``noise_sd``
    (in %PV) is added. The generator seed is fixed so results are repeatable.
    """
    controller_output = _square_wave()
    process_value = _first_order_response(controller_output)
    noise = np.random.default_rng(NOISE_SEED).normal(0, noise_sd, SAMPLE_COUNT)
    return controller_output, process_value + noise


def _square_wave() -> np.ndarray:
    """Return the controller output, in %, alternating every half cycle."""
    # Alternate between the two levels: 300 samples low, 300 samples high, and so on.
    is_low_half = (np.arange(SAMPLE_COUNT) // HALF_CYCLE_SAMPLES) % 2 == 0
    return np.where(is_low_half, LOW_OUTPUT_PERCENT, HIGH_OUTPUT_PERCENT)


def _first_order_response(controller_output: np.ndarray) -> np.ndarray:
    """Return the noise-free process value, in %PV, for the given controller output.

    The recursion assumes the process rests at LOW_OUTPUT_PERCENT, so the driving
    signal is the deviation u - 50, in %CO, scaled by the process gain.
    """
    process_value = np.zeros(SAMPLE_COUNT)
    for k in range(SAMPLE_COUNT - 1):
        target_deviation = PROCESS_GAIN * (controller_output[k] - LOW_OUTPUT_PERCENT)
        process_value[k + 1] = MODEL_MEMORY * process_value[k] + MODEL_STEP * target_deviation
    return process_value


def test_clean_data_is_not_blocked_and_yields_simc_settings(clean_data):
    """A clean step should identify well enough to produce SIMC settings."""
    controller_output, process_value = clean_data

    report = build_tuning_report("FIC101", controller_output, process_value, DT_S)

    assert report.blocked_reason is None
    assert report.simc is not None


def test_stiction_verdict_blocks_the_retune(clean_data):
    """A stiction verdict alone must block the retune even on clean data."""
    controller_output, process_value = clean_data

    report = build_tuning_report(
        "FIC101", controller_output, process_value, DT_S, stiction_verdict="stiction"
    )

    assert report.blocked_reason is not None
    assert report.blocked_reason == STICTION_BLOCKED_REASON


def test_heavy_noise_blocks_the_retune_for_poor_fit(heavy_noise_data):
    """Heavy noise should leave a model that explains nothing, so the loop is blocked."""
    controller_output, process_value = heavy_noise_data

    report = build_tuning_report("FIC101", controller_output, process_value, DT_S)

    assert report.blocked_reason.startswith(POOR_FIT_PREFIX)
    assert report.blocked_reason in report.notes


def test_moderate_noise_is_not_blocked(moderate_noise_data):
    """Moderate noise should still leave a fit good enough to retune."""
    controller_output, process_value = moderate_noise_data

    report = build_tuning_report("FIC101", controller_output, process_value, DT_S)

    assert report.blocked_reason is None


def test_stiction_reason_wins_over_poor_fit(heavy_noise_data):
    """When both refusals apply, stiction is reported because the valve comes first."""
    controller_output, process_value = heavy_noise_data

    report = build_tuning_report(
        "FIC101", controller_output, process_value, DT_S, stiction_verdict="stiction"
    )

    assert report.blocked_reason == STICTION_BLOCKED_REASON
    assert any(note.startswith(POOR_FIT_PREFIX) for note in report.notes)

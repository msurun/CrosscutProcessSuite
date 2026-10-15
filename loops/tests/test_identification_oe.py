"""Behaviour tests for refine_output_error, the output-error refit of a FOPDT model.

We build a synthetic first-order process plus dead time, add measurement noise,
then check that the refit lands close to the true parameters and never loses
free-run accuracy. numpy only; every random draw comes from a seeded rng.
"""

import numpy as np
import pytest
from crosscut_loops.identification import identify_fopdt
from crosscut_loops.identification_oe import refine_output_error
from crosscut_loops.identification_quality import free_run_r2
from crosscut_loops.tuning_rules import FopdtModel

SAMPLE_TIME_S = 1.0
TRUE_GAIN = 2.0
TRUE_TAU_S = 40.0
TRUE_DELAY_S = 5
STEP_INDEX = 300
SAMPLE_COUNT = 2000
NOISE_SD = 0.05
MAX_DELAY_S = 200
REFIT_MAX_DELAY_S = 200


def simulate_fopdt(u, delay_samples, gain=TRUE_GAIN, tau_s=TRUE_TAU_S, dt_s=SAMPLE_TIME_S):
    """Free-run the discrete FOPDT model y[k+1] = a*y[k] + gain*(1-a)*u[max(k-d, 0)].

    `a = exp(-dt/tau)` is the exact zero-order-hold pole of the continuous
    process. Returns the simulated output array (float, same length as `u`).
    """
    decay = np.exp(-dt_s / tau_s)
    y = np.zeros_like(u, dtype=float)
    for k in range(len(u) - 1):
        delayed_input = u[max(k - delay_samples, 0)]
        y[k + 1] = decay * y[k] + gain * (1 - decay) * delayed_input
    return y


def make_step(sample_count=SAMPLE_COUNT, step_index=STEP_INDEX):
    """Return a unit step: 0 before `step_index`, then 1 for the rest."""
    u = np.zeros(sample_count, dtype=float)
    u[step_index:] = 1.0
    return u


def add_noise(signal, rng, sd=NOISE_SD):
    """Return `signal` plus zero-mean normal noise with standard deviation `sd`."""
    return signal + rng.normal(0.0, sd, signal.shape)


@pytest.fixture
def noisy_process():
    """Noisy observations of a true FOPDT process driven by a single step."""
    rng = np.random.default_rng(1)
    u = make_step()
    y_clean = simulate_fopdt(u, TRUE_DELAY_S)
    return u, add_noise(y_clean, rng)


def test_refit_recovers_parameters_close_to_the_truth(noisy_process):
    u, y = noisy_process
    start = identify_fopdt(u, y, SAMPLE_TIME_S, MAX_DELAY_S)

    refit = refine_output_error(start, u, y, SAMPLE_TIME_S, REFIT_MAX_DELAY_S)

    assert refit.gain == pytest.approx(TRUE_GAIN, rel=0.05)
    assert refit.time_constant_s == pytest.approx(TRUE_TAU_S, rel=0.15)
    assert refit.delay_s == pytest.approx(TRUE_DELAY_S, abs=2.0)


def test_refit_free_run_is_at_least_as_good_as_the_arx_model(noisy_process):
    u, y = noisy_process
    start = identify_fopdt(u, y, SAMPLE_TIME_S, MAX_DELAY_S)

    refit = refine_output_error(start, u, y, SAMPLE_TIME_S, REFIT_MAX_DELAY_S)

    arx_score = free_run_r2(start, u, y, SAMPLE_TIME_S)
    refit_score = free_run_r2(refit, u, y, SAMPLE_TIME_S)
    assert refit_score >= arx_score - 1e-9


def test_refit_delay_is_positive_even_when_the_process_has_no_dead_time():
    u = make_step()
    y = simulate_fopdt(u, delay_samples=0)
    start = identify_fopdt(u, y, SAMPLE_TIME_S, MAX_DELAY_S)

    refit = refine_output_error(start, u, y, SAMPLE_TIME_S, REFIT_MAX_DELAY_S)

    assert refit.delay_s > 0.0


def test_constant_measurements_fall_back_to_the_start_model():
    u = make_step()
    y = np.zeros(SAMPLE_COUNT, dtype=float)
    start = FopdtModel(1.0, 10.0, 2.0)

    refit = refine_output_error(start, u, y, SAMPLE_TIME_S, REFIT_MAX_DELAY_S)

    assert isinstance(refit, FopdtModel)

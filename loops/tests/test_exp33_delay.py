"""Sampling-resolution regression tests on seeded synthetic process records.

No experimental measurements are needed to distinguish bounds from fitted delays.
"""

import numpy as np
import pytest
from crosscut_loops.identification import identify_fopdt
from crosscut_loops.identification_cl import identify_fopdt_closed_loop
from crosscut_loops.identification_ipdt import IpdtSettings, identify_ipdt
from crosscut_loops.identification_oe import refine_output_error
from crosscut_loops.step_fit import fit_step

SAMPLE_PERIOD_S = 2.0
SAMPLE_COUNT = 400
HOLD_SAMPLES = 10


def _first_order_record(delay_samples: int) -> tuple[np.ndarray, np.ndarray]:
    """Return seeded OUT and PV vectors from an exact sampled first-order lag."""
    generator = np.random.default_rng(102)
    output = np.repeat(generator.normal(size=SAMPLE_COUNT // HOLD_SAMPLES), HOLD_SAMPLES)
    delayed = np.concatenate((np.zeros(delay_samples), output))[:SAMPLE_COUNT]
    process = np.zeros(SAMPLE_COUNT)
    # y[k+1] = a*y[k] + K*(1-a)*u[k-d]; PV and OUT are aligned 1-D arrays.
    decay = np.exp(-SAMPLE_PERIOD_S / 20.0)
    for k in range(SAMPLE_COUNT - 1):
        process[k + 1] = decay * process[k] + 2.0 * (1.0 - decay) * delayed[k]
    return output, process


def test_zero_sample_arx_delay_is_reported_as_a_sampling_bound() -> None:
    """The zero-delay optimum must not masquerade as a measured one-sample delay."""
    output, process = _first_order_record(0)
    model = identify_fopdt(output, process, SAMPLE_PERIOD_S, 10.0)
    assert model.delay_below_sample is True
    assert model.delay_s_max == SAMPLE_PERIOD_S


def test_resolved_arx_delay_does_not_have_a_sampling_bound() -> None:
    """A resolved three-sample delay retains the measured delay."""
    output, process = _first_order_record(3)
    model = identify_fopdt(output, process, SAMPLE_PERIOD_S, 10.0)
    assert model.delay_below_sample is False
    assert model.delay_s_max is None
    assert model.delay_s == pytest.approx(3 * SAMPLE_PERIOD_S)


def test_closed_loop_converter_preserves_zero_sample_delay_evidence() -> None:
    """Exogenous setpoint instruments preserve a zero-delay optimum's bound."""
    output, process = _first_order_record(0)
    model = identify_fopdt_closed_loop(output, process, output, SAMPLE_PERIOD_S, 10.0)
    assert model.delay_below_sample is True
    assert model.delay_s_max == SAMPLE_PERIOD_S


def test_output_error_refinement_keeps_unresolved_delay_explicit() -> None:
    """Refinement must not replace the bound with an unexplained half-sample value."""
    output, process = _first_order_record(0)
    initial = identify_fopdt(output, process, SAMPLE_PERIOD_S, 10.0)
    model = refine_output_error(initial, output, process, SAMPLE_PERIOD_S, 10.0)
    assert model.delay_below_sample is True
    assert model.delay_s_max == SAMPLE_PERIOD_S


def _integrating_record() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return a seeded staircase and its zero-delay held-input integral, in PV units."""
    generator = np.random.default_rng(103)
    stamps = np.arange(80, dtype=float) * SAMPLE_PERIOD_S
    output = np.repeat(generator.uniform(1.0, 4.0, size=8), 10)
    process = np.concatenate(([0.0], np.cumsum(output[:-1] - output[0]))) * SAMPLE_PERIOD_S
    return stamps, output, process


def test_step_fit_reports_the_delay_bound_without_changing_raw_optimizer_value() -> None:
    """Raw theta remains diagnostic while the public bound expresses resolution."""
    stamps, output, process = _integrating_record()
    fit = fit_step(stamps, process, output, 10, "ipdt")
    assert fit.theta_s.value == 0.0
    assert fit.delay_below_sample is True
    assert fit.delay_s_max == SAMPLE_PERIOD_S


def test_integrating_identification_reports_a_sampling_upper_bound() -> None:
    """An integrating fit must expose the same resolution evidence as a lag fit."""
    stamps, output, process = _integrating_record()
    fit = identify_ipdt(stamps, output, process, IpdtSettings(bootstrap_resamples=10))
    assert fit.delay_below_sample is True
    assert fit.delay_s_max == SAMPLE_PERIOD_S
    assert fit.delay_used_s >= SAMPLE_PERIOD_S

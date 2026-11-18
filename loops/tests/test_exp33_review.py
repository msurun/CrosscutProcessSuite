"""Regression checks for the exp33 review corrections.

Synthetic arrays pin compatibility and measurement boundaries without data files.
"""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import jsonschema
import numpy as np
import pytest
from crosscut_loops.history_windows import WindowSettings, _build_window, _StepEvent
from crosscut_loops.identification import IdentifiedFopdtModel
from crosscut_loops.identification_ipdt import (
    IpdtFit,
    IpdtIdentificationError,
    IpdtModel,
    IpdtSettings,
    identify_ipdt,
)
from crosscut_loops.identification_oe import _model_from_fit
from crosscut_loops.metrics import detected_quantisation_step, settling_band
from crosscut_loops.monitor import LoopSettings, _oscillation
from crosscut_loops.oscillation_acf import OscillationReference, oscillation_reference
from crosscut_loops.tuning_payload import _plain
from crosscut_loops.tuning_preview import _settling_time_s
from crosscut_loops.tuning_rules import FopdtModel


def test_history_detects_resolution_only_inside_the_post_step_window() -> None:
    """Unrelated lattice samples before and after the window cannot widen its band."""
    process = np.concatenate((np.tile([0.0, 2.0], 100), np.zeros(30),
                              np.tile([0.0, 2.0], 100)))
    settings = WindowSettings(pre_samples=0, max_samples=30)
    window = _build_window(_StepEvent(200, 1.0), np.ones(process.size), process, settings)
    assert window.settling_band == pytest.approx(0.05)
    assert window.band_widened is False


def test_history_does_not_detect_interpolated_sensor_codes() -> None:
    """Raw gaps remain gaps in the detector's input, even when settling uses interpolation."""
    process = np.tile([0.0, np.nan, 2.0, 2.0, 2.0, 2.0], 30)
    with patch('crosscut_loops.history_windows.settling_band', return_value=(0.05, False)) as band:
        _build_window(_StepEvent(1, 1.0), np.ones(process.size), process, WindowSettings())
    np.testing.assert_array_equal(band.call_args.args[0], process[1:])


def test_quantisation_never_connects_finite_samples_across_nan_gaps() -> None:
    """Removing missing samples would invent enough repeated increments to pass."""
    process = np.tile([0.0, np.nan, 1.0, np.nan], 40)
    assert detected_quantisation_step(process) == 0.0


@pytest.mark.parametrize('optimum, expected', [(0.0, 1.0), (0.75, 1.5)])
def test_output_error_keeps_the_historical_subsample_delay(optimum: float, expected: float) -> None:
    """Seconds = max(optimum in samples, 0.5) times the two-second sample period."""
    model = _model_from_fit(FopdtModel(1.0, 10.0, 2.0), (1.0, 10.0, optimum, 0.0), 2.0)
    assert model.delay_s == expected
    assert model.delay_below_sample is True
    assert model.delay_s_max == 2.0


def test_payload_resolution_fields_keep_base_model_constructor_compatible() -> None:
    """The base constructor accepts the same optional diagnostics as identification."""
    model = IdentifiedFopdtModel(1.0, 10.0, 1.0, True, 2.0)
    payload = _plain(model)
    assert payload['delay_below_sample'] is True
    assert payload['delay_s_max'] == 2.0
    assert FopdtModel(**payload) == FopdtModel(1.0, 10.0, 1.0, True, 2.0)


def test_unresolved_ipdt_uses_the_reported_sampling_bound() -> None:
    """The sampling bound takes precedence over a different profile upper endpoint."""
    fit = IpdtFit(IpdtModel(1.0, 0.0), 1.0, 0.0, None, 0.0, 'ok', (),
                  delay_upper_s=5.0, delay_below_sample=True, delay_s_max=2.0)
    assert fit.delay_used_s == 2.0
    assert replace(fit, delay_below_sample=False).delay_used_s == 5.0


@pytest.mark.parametrize('count', [0, 1])
def test_ipdt_requires_two_times_even_when_minimum_is_configured_lower(count: int) -> None:
    """Sample period validation must precede differences and all downstream fitting."""
    samples = np.zeros(count)
    with pytest.raises(IpdtIdentificationError, match='at least 2 samples'):
        identify_ipdt(samples, samples, samples, IpdtSettings(min_samples=0))


@pytest.mark.parametrize('count', [0, 3, 9])
def test_reference_rejects_short_input(count: int) -> None:
    """Robust reference estimates require at least ten samples."""
    with pytest.raises(ValueError, match='ten samples'):
        oscillation_reference(np.zeros(count), np.zeros(count))


@pytest.mark.parametrize('count', [0, 9])
def test_reference_guards_short_detrending_output(count: int) -> None:
    """An empty or shortened detrending result cannot reach percentile calculation."""
    with patch('crosscut_loops.oscillation_acf._detrend', return_value=np.zeros(count)):
        with pytest.raises(ValueError, match='retain at least ten'):
            oscillation_reference(np.zeros(20), np.zeros(20))


def test_configured_hagglund_limits_keep_their_verdict_below_the_new_gate() -> None:
    """Known engineering limits remain authoritative even for a resolution-sized cycle."""
    error = np.tile(np.repeat([0.0, 0.4], 30), 50)
    result = _oscillation(error, 1.0, LoopSettings(1.0, 60.0, 0.01),
                          OscillationReference(0.2, 0.0, 0.4))
    assert result.method == 'hagglund'
    assert result.period_s == pytest.approx(60.0)


def test_preview_uses_a_fixed_dimensionless_band() -> None:
    """Repeated simulated levels do not represent physical sensor quantisation."""
    response = np.concatenate((np.tile([0.9, 1.1], 40), [1.0]))
    assert _settling_time_s(response, 2.0) == 160.0


def test_precomputed_resolution_is_reused_for_multiple_bands() -> None:
    """Repeated tolerance decisions can reuse a single expensive lattice estimate."""
    process = np.tile([0.0, 0.4], 50)
    step = detected_quantisation_step(process)
    with patch('crosscut_loops.metrics.detected_quantisation_step') as detector:
        assert settling_band(process, 0.1, quantisation_step=step) == pytest.approx((1.2, True))
        assert settling_band(process, 2.0, quantisation_step=step) == (2.0, False)
    detector.assert_not_called()


@pytest.mark.parametrize('unresolved, bound', [(True, 2.0), (False, None)])
def test_proposal_schema_accepts_optional_resolution_fields(
    unresolved: bool, bound: float | None,
) -> None:
    """The strict model contract admits unresolved and resolved diagnostics."""
    schema_path = Path(__file__).resolve().parents[2] / 'schemas/tuning-proposal.schema.json'
    schema = json.loads(schema_path.read_text())['properties']['source']['properties']['model']
    model = {'K': 1.0, 'tau_s': 10.0, 'theta_s': 1.0, 'process_kind': 'self_regulating',
             'delay_below_sample': unresolved, 'delay_s_max': bound}
    jsonschema.validate(model, schema)


def test_proposal_schema_rejects_non_boolean_resolution_flags() -> None:
    """Strict schemas reject numeric substitutes for the boolean diagnostic."""
    schema_path = Path(__file__).resolve().parents[2] / 'schemas/tuning-proposal.schema.json'
    schema = json.loads(schema_path.read_text())['properties']['source']['properties']['model']
    model = {'K': 1.0, 'tau_s': 10.0, 'theta_s': 1.0, 'process_kind': 'self_regulating',
             'delay_below_sample': 1}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(model, schema)

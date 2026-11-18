"""Regressions for the regime-aware anomaly review findings.
Synthetic records isolate numerical scoring, persistence and boundary decisions.
"""

import json
from dataclasses import replace
from unittest.mock import patch

import numpy as np
import pytest
from crosscut_anomaly import detect
from crosscut_anomaly.config import AnomalyConfigError, load_config
from crosscut_anomaly.detect import ScanResult, combine_regime_results, scan_regimes
from crosscut_anomaly.pca_model import (
    PcaModel,
    RegimeModelSet,
    fit_from_config,
    fit_pca,
    fit_regimes,
    regime_keys,
    training_profiles,
)

DOCUMENT = {"schema_version": "1.0.0", "id": "review", "mode": "advisory",
            "tags": ["a", "b", "c", "d"]}


def training_rows() -> np.ndarray:
    """Return reproducible samples by four moving tags in engineering units."""
    return np.random.default_rng(211).normal(size=(400, 4))


def test_non_regime_fit_preserves_corrcoef_semantics():
    """Legacy PCA must continue using NumPy's correlation normalisation."""
    rows = training_rows()
    with patch.object(np, "corrcoef", wraps=np.corrcoef) as correlation:
        model = fit_pca(rows, DOCUMENT["tags"])
    assert correlation.call_count == 1
    expected = np.linalg.eigvalsh(np.corrcoef(rows, rowvar=False))[::-1]
    np.testing.assert_allclose(model.eigenvalues, expected, rtol=1e-14, atol=1e-14)


def test_half_quantum_setpoint_deviation_has_no_event():
    """A constant setpoint has no monitoring variance within its rounded regime."""
    config = load_config({**DOCUMENT, "regimes": {"by": ["a"], "quantum": {"a": 100}}})
    rows = training_rows()
    rows[:, 0] = 200
    models = fit_regimes(rows, config)
    record = np.tile(rows.mean(axis=0), (20, 1))
    record[:, 0] += 50
    result = scan_regimes(models, np.arange(20), record)
    assert result.n_valid == 20
    assert result.events == ()


def test_constant_columns_survive_model_serialisation():
    """All constant columns, including non-grouping tags, remain ignored on restore."""
    rows = training_rows()
    rows[:, 1] = 7
    model = fit_pca(rows, DOCUMENT["tags"], allow_constants=True)
    restored = PcaModel.from_dict(json.loads(json.dumps(model.to_dict())))
    record = rows[:10].copy()
    record[:, 1] += 100
    assert restored.constant_columns == model.constant_columns
    assert any(restored.constant_columns)
    np.testing.assert_array_equal(restored.t2(record), model.t2(rows[:10]))
    np.testing.assert_array_equal(restored.spe(record), model.spe(rows[:10]))


def test_nonconstant_grouping_tag_cannot_change_regime_statistics():
    """Variation inside one grouping bin describes regime identity, not an anomaly."""
    config = load_config({**DOCUMENT, "regimes": {"by": ["a"], "quantum": {"a": 100}}})
    rows = training_rows()
    rows[:, 0] = np.linspace(190, 210, len(rows))
    models = fit_regimes(rows, config)
    model = models.models["[2.0]"]
    low_record = rows[:10].copy()
    high_record = rows[:10].copy()
    low_record[:, 0] = 151
    high_record[:, 0] = 249
    assert model.constant_columns[0]
    np.testing.assert_array_equal(model.t2(low_record), model.t2(high_record))
    np.testing.assert_array_equal(model.spe(low_record), model.spe(high_record))


def test_regime_config_and_scan_survive_native_json_round_trip():
    """Serialized configuration uses JSON arrays and a quantum object."""
    config = load_config({**DOCUMENT, "regimes": {"by": ["a"], "quantum": {"a": 1}}})
    rows = training_rows()
    rows[:, 0] = 10
    models = fit_regimes(rows, config)
    document = models.to_dict()
    assert isinstance(document["config"]["tags"], list)
    assert isinstance(document["config"]["regimes"]["by"], list)
    assert document["config"]["regimes"]["quantum"] == {"a": 1.0}
    restored = RegimeModelSet.from_dict(json.loads(json.dumps(document)))
    assert restored.sha256() == models.sha256()
    assert scan_regimes(restored, np.arange(400), rows) == scan_regimes(
        models, np.arange(400), rows)


def test_combined_regime_results_retain_limit_methods():
    """The aggregate carries method metadata supplied by individual regimes."""
    first = ScanResult((), 2, 0, limit_methods={"t2": "hotelling_f"})
    second = ScanResult((), 3, 0, limit_methods={"spe": "empirical"})
    result = combine_regime_results([], [first, second], 0)
    assert result.limit_methods == {"t2": "hotelling_f", "spe": "empirical"}


def test_all_nan_training_column_has_an_empty_profile():
    """A missing tag has no extreme, resolution or legitimate held level."""
    profile = training_profiles(np.full((20, 1), np.nan), 3)[0]
    assert np.isnan(profile["min"])
    assert np.isnan(profile["max"])
    assert profile["resolution"] == 0
    assert profile["levels"] == []


@pytest.mark.parametrize("resolution", [0.0, float("nan")])
def test_invalid_resolution_disables_only_quantised_levels(resolution):
    """Absent quantisation evidence does not disable absolute training extremes."""
    config = load_config({**DOCUMENT, "stuck_samples": 3})
    profile = {"min": 0.0, "max": 10.0, "resolution": resolution, "levels": [5.0]}
    model = replace(fit_from_config(training_rows(), config), stuck_profiles=(profile,) * 4)
    assert detect.stuck_exemption(model, 0, (5.0, 20), config) is None
    assert detect.stuck_exemption(model, 0, (0.0, 20), config) == "training_limit"


@pytest.mark.parametrize("value, expected", [(1000000.05, "training_limit"),
                                            (1000001.0, None)])
def test_training_extreme_tolerance_is_absolute(value, expected):
    """Engineering resolution tolerates nearby extrema without relative scaling."""
    config = load_config({**DOCUMENT, "stuck_samples": 3})
    profile = {"min": 1000000.0, "max": 2000000.0, "resolution": 0.1, "levels": []}
    model = replace(fit_from_config(training_rows(), config), stuck_profiles=(profile,) * 4)
    assert detect.stuck_exemption(model, 0, (value, 20), config) == expected


def test_regime_minimum_counts_raw_rows_before_lag_augmentation():
    """A raw population at min_rows remains eligible despite lost lag history."""
    config = load_config({**DOCUMENT, "dynamic_lags": 1,
                          "regimes": {"by": ["a"], "min_rows": 200}})
    models = fit_regimes(training_rows(), config, [0] * 200 + [1] * 200)
    assert len(models.models) == 2
    assert models.models['"0"'].n_train == 199
    assert models.models['"1"'].n_train == 199


def test_training_lags_never_bridge_a_regime_boundary():
    """Returning to a regime requires fresh history rather than concatenating visits."""
    config = load_config({**DOCUMENT, "dynamic_lags": 1,
                          "regimes": {"by": ["a"], "min_rows": 100}})
    models = fit_regimes(training_rows(), config, [0] * 100 + [1] * 200 + [0] * 100)
    assert models.models['"0"'].n_train == 198


def test_regime_population_excludes_nonfinite_raw_rows():
    """A nominal population at the minimum is insufficient if one row is invalid."""
    config = load_config({**DOCUMENT, "regimes": {"by": ["a"], "min_rows": 200}})
    rows = training_rows()
    rows[0, 1] = np.nan
    models = fit_regimes(rows, config, [0] * 200 + [1] * 200)
    assert set(models.models) == {'"1"'}


@pytest.mark.parametrize("minimum", [0, -1])
def test_nonpositive_regime_minimum_is_rejected(minimum):
    """The parser agrees with the schema's positive minimum population."""
    with pytest.raises(AnomalyConfigError, match="min_rows"):
        load_config({**DOCUMENT, "regimes": {"by": ["a"], "min_rows": minimum}})


def test_regime_rounding_uses_half_to_even():
    """Ties follow np.rint rather than a half-away-from-zero convention."""
    config = load_config({**DOCUMENT, "regimes": {"by": ["a"], "quantum": {"a": 1}}})
    rows = np.zeros((4, 4))
    rows[:, 0] = [0.5, 1.5, 2.5, -1.5]
    assert regime_keys(rows, config) == ["[0.0]", "[2.0]", "[2.0]", "[-2.0]"]


def test_scoring_lags_restart_at_every_regime_boundary():
    """Each contiguous visit loses its first lagged observation conservatively."""
    config = load_config({**DOCUMENT, "dynamic_lags": 1, "regimes": {"by": ["a"]}})
    models = fit_regimes(training_rows(), config, [0] * 200 + [1] * 200)
    record = training_rows()[:12]
    result = scan_regimes(models, np.arange(12), record, mode_ids=[0] * 4 + [1] * 4 + [0] * 4)
    assert result.n_valid == 9
    assert result.skipped_reasons["lag"] == 3


def test_consecutive_exceedances_restart_at_a_regime_boundary():
    """Short anomalous visits cannot combine into a long enough event run."""
    config = load_config({**DOCUMENT, "min_consecutive": 5, "regimes": {"by": ["a"]}})
    models = fit_regimes(training_rows(), config, [0] * 200 + [1] * 200)
    record = np.full((8, 4), 100.0)
    result = scan_regimes(models, np.arange(8), record, mode_ids=[0] * 4 + [1] * 4)
    assert result.events == ()


def test_event_close_counter_restarts_at_a_regime_boundary():
    """Quiet samples in a new regime cannot close the previous regime's event."""
    config = load_config({**DOCUMENT, "min_consecutive": 3, "close_after": 3,
                          "regimes": {"by": ["a"]}})
    models = fit_regimes(training_rows(), config, [0] * 200 + [1] * 200)
    first_mean = models.models['"0"'].mean
    second_mean = models.models['"1"'].mean
    record = np.vstack([np.full((4, 4), 100.0), np.tile(first_mean, (2, 1)),
                        np.tile(second_mean, (4, 1))])
    result = scan_regimes(models, np.arange(10), record, mode_ids=[0] * 6 + [1] * 4)
    assert len(result.events) == 1
    assert result.events[0].closed is False


def test_stuck_thresholds_are_computed_once_for_multiple_runs():
    """Repeated holds reuse the same per-tag training thresholds within a scan."""
    config = load_config({**DOCUMENT, "stuck_samples": 3})
    model = fit_from_config(training_rows(), config)
    rows = np.repeat(np.arange(12, dtype=float), 3)[:, None] * np.ones((1, 4))
    index = np.arange(len(rows))
    with patch.object(detect, "stuck_thresholds", wraps=detect.stuck_thresholds) as thresholds:
        detect.scan_stuck(model, rows, (index, index), config)
    assert thresholds.call_count == 1

"""Exercise causal baseline comparison and the deployment decision on synthetic data.

Persistence must defeat irrelevant process signals, while real signals must earn skill.
"""

import numpy as np
import pytest
from crosscut_softsensor.comparison import (
    ComparisonData,
    ComparisonOptions,
    compare_preset,
    delayed_baselines,
)
from crosscut_softsensor.presets import load_presets
from crosscut_softsensor.runner import LabResults


def _preset() -> dict:
    """Use the real lab gate with one candidate so its evidence is easy to inspect."""
    preset = load_presets()["lab_quality_inference"]
    preset["model"]["allowed_now"] = ["ridge"]
    return preset


def _data(target: np.ndarray, features: np.ndarray) -> ComparisonData:
    """Create one released lab per second with a two-second reporting delay."""
    times = np.arange(len(target), dtype=float)
    return ComparisonData(features[:, None], times, LabResults.with_delay(times, target, 2),
                          ("process_tag_1",))


def test_persistence_wins_for_a_persistent_target_and_gate_refuses() -> None:
    features = np.random.default_rng(12).normal(size=400)
    table = compare_preset(_preset(), _data(np.arange(400, dtype=float), features))
    rows = {row["method"]: row for row in table.rows}
    assert rows["ridge"]["strongest_baseline"] == "age_aware_lab_persistence"
    assert rows["ridge"]["skill"] < 0
    assert rows["ridge"]["n"] == 320
    assert rows["ridge"]["coverage"] == 1
    assert not table.decisions["ridge"].deploy


def test_a_real_process_relation_beats_persistence_and_passes_gate() -> None:
    features = np.random.default_rng(42).normal(size=400)
    table = compare_preset(_preset(), _data(5 + 3 * features, features))
    rows = {row["method"]: row for row in table.rows}
    assert rows["ridge"]["rmse"] < 1e-6
    assert rows["ridge"]["mae"] < 1e-6
    assert rows["ridge"]["skill"] > 0.99
    assert table.decisions["ridge"].deploy


def test_delayed_baselines_use_release_time_and_sample_age() -> None:
    labs = LabResults(np.array([0., 2., 4.]), np.array([10., 20., 90.]),
                      np.array([1., 8., 5.]))
    persistence, ewma, ages = delayed_baselines(np.array([0., 4., 6., 9.]), labs)
    np.testing.assert_allclose(persistence, [np.nan, 10, 90, 90], equal_nan=True)
    np.testing.assert_allclose(ewma, [np.nan, 10, 26, 24.8], equal_nan=True)
    np.testing.assert_allclose(ages, [np.nan, 4, 2, 5], equal_nan=True)


def test_stale_labs_are_unscored_instead_of_inventing_coverage() -> None:
    features = np.random.default_rng(3).normal(size=400)
    table = compare_preset(_preset(), _data(3 * features, features),
                           ComparisonOptions(max_lab_age_s=1))
    assert not table.scored_mask.any()
    assert not table.decisions["ridge"].deploy


def test_missing_process_rows_reduce_common_coverage() -> None:
    features = np.random.default_rng(3).normal(size=400)
    data = _data(3 * features, features)
    data.x[200:300] = np.nan
    table = compare_preset(_preset(), data)
    assert table.rows[0]["coverage"] == pytest.approx(220 / 320)
    assert not table.decisions["ridge"].deploy


def test_unreleased_labels_cannot_change_the_first_fold_predictions() -> None:
    features = np.random.default_rng(3).normal(size=400)
    target = 3 * features
    original = compare_preset(_preset(), _data(target, features))
    target[80:] += 1000
    changed = compare_preset(_preset(), _data(target, features))
    np.testing.assert_array_equal(original.predictions["ridge"][80:160],
                                  changed.predictions["ridge"][80:160])


def test_negative_release_delay_is_refused() -> None:
    features = np.arange(100, dtype=float)
    data = _data(features, features)
    data.labs.available_s[0] = -1
    with pytest.raises(ValueError, match="release cannot precede"):
        compare_preset(_preset(), data)


def test_table_evaluates_every_allowed_data_driven_structure() -> None:
    features = np.random.default_rng(15).normal(size=400)
    table = compare_preset(load_presets()["lab_quality_inference"],
                           _data(5 + 3 * features, features))
    assert set(table.decisions) == {"pls", "ridge", "gradient_boosting"}
    assert table.decisions["pls"].deploy
    assert table.decisions["gradient_boosting"].deploy

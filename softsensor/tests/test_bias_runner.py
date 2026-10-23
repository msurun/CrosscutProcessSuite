"""Tests of the bias tracker and the causal soft sensor runner (no lab leakage, drift detection)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from crosscut_softsensor.bias import BiasTracker, BiasTrackerError
from crosscut_softsensor.config import SoftSensorConfig
from crosscut_softsensor.features import build_lagged
from crosscut_softsensor.pls import fit_pls
from crosscut_softsensor.runner import (
    LabResults,
    SoftSensorRun,
    carry_forward_baseline,
    evaluate_rmse,
    run_softsensor,
)

DAY = 86400.0
PERIOD = 300.0
CFG = SoftSensorConfig(
    id="t", target_tag="y", input_tags=("a", "b"), lags_s=(0.0, 300.0, 900.0),
    sample_period_s=PERIOD, lab_delay_s=3600.0, max_components=4,
)


def _tracker() -> BiasTracker:
    return BiasTracker(sigma_cv=1.0)


def test_sustained_bias_flagged_after_three_results_single_outlier_not() -> None:
    tr = _tracker()
    flags = [tr.update(i, 3.5, 0.0).drift for i in range(4)]
    assert flags == [False, False, True, True]
    tr = _tracker()
    seq = [0.0, 0.0, 10.0, 0.0, 0.0, 0.0]
    assert not any(tr.update(i, v, 0.0).drift for i, v in enumerate(seq))


def test_weight_arithmetic_and_reset_of_counter() -> None:
    tr = BiasTracker(sigma_cv=1.0, weight=0.3, k_sigma=2.0, consecutive=3)
    s1 = tr.update(0.0, 5.0, 1.0)
    assert s1.bias_ewma == 4.0 and s1.n_over == 1 and s1.n_updates == 1
    s2 = tr.update(1.0, 1.0, 1.0)
    assert s2.bias_ewma == pytest.approx(0.7 * 4.0) and s2.n_over == 2
    s3 = tr.update(2.0, -9.0, 1.0)
    assert s3.bias_ewma == pytest.approx(0.7 * 2.8 + 0.3 * -10.0) and s3.n_over == 0
    assert s3.last_t_s == 2.0
    tr.reset()
    assert tr.state.n_updates == 0 and np.isnan(tr.state.bias_ewma)


def test_nan_is_ignored_and_counted() -> None:
    tr = _tracker()
    tr.update(0.0, 1.0, 0.0)
    before = tr.state
    after = tr.update(1.0, float("nan"), 0.0)
    after = tr.update(2.0, 1.0, float("nan"))
    assert after.bias_ewma == before.bias_ewma and after.n_updates == 1
    assert after.n_ignored == 2 and after.last_t_s == 0.0
    with pytest.raises(BiasTrackerError):
        BiasTracker(sigma_cv=0.0)


def test_tracker_round_trip() -> None:
    tr = BiasTracker(0.7, weight=0.4, k_sigma=1.5, consecutive=2)
    for i in range(3):
        tr.update(float(i), 2.0, 0.5)
    again = BiasTracker.from_dict(json.loads(json.dumps(tr.to_dict())))
    assert again.state == tr.state and again.to_dict() == tr.to_dict()
    assert again.update(9.0, 2.0, 0.5) == tr.update(9.0, 2.0, 0.5)
    with pytest.raises(BiasTrackerError):
        BiasTracker.from_dict({"sigma_cv": 1.0})


def _record(drift: bool, seed: int = 1, days: int = 30) -> tuple[np.ndarray, dict, np.ndarray]:
    rng = np.random.default_rng(seed)
    n = int(days * DAY / PERIOD)
    t = np.arange(n) * PERIOD
    a = np.sin(2 * np.pi * t / (0.7 * DAY)) + 0.3 * rng.normal(size=n)
    b = np.cos(2 * np.pi * t / (1.3 * DAY)) + 0.3 * rng.normal(size=n)
    y = 10 + 2 * a - b + 0.1 * rng.normal(size=n)
    if drift:
        y = y + np.where(t > 15 * DAY, 1.5, 0.0)
    return t, {"a": a, "b": b}, y


def _fit_and_labs(drift: bool) -> tuple[object, np.ndarray, dict, np.ndarray, LabResults]:
    t, cols, y = _record(drift)
    ntrain = int(10 * DAY / PERIOD)
    x, _ = build_lagged(cols, CFG.input_tags, CFG.lags_s, PERIOD)
    model = fit_pls(x[:ntrain], y[:ntrain], CFG)
    idx = np.arange(0, len(t), 24)
    return model, t, cols, y, LabResults.with_delay(t[idx], y[idx], CFG.lab_delay_s)


def test_corrected_equals_estimate_plus_bias_after_updates() -> None:
    model, t, cols, _, labs = _fit_and_labs(False)
    run = run_softsensor(model, CFG, t, cols, labs)
    assert isinstance(run, SoftSensorRun) and run.n_lab_used > 0
    first = int(np.flatnonzero(~np.isnan(run.bias))[0])
    assert t[first] >= labs.available_s.min()
    assert np.isnan(run.corrected[:first]).all() or np.isnan(run.estimate[:first]).all()
    ok = ~np.isnan(run.estimate[first:])
    assert np.array_equal(run.corrected[first:][ok], (run.estimate + run.bias)[first:][ok])
    assert len(run.validity) == len(t)


def test_no_lab_leakage_before_availability() -> None:
    model, t, cols, _, labs = _fit_and_labs(True)
    base = run_softsensor(model, CFG, t, cols, labs)
    cut = 12 * DAY
    late = labs.available_s > cut
    rng = np.random.default_rng(5)
    values = labs.values.copy()
    values[late] = rng.permutation(values[late]) * 3.0 + 7.0
    other = run_softsensor(model, CFG, t, cols, LabResults(labs.t_s, values, labs.available_s))
    before = t < cut
    for name in ("estimate", "corrected", "bias", "drift"):
        assert np.array_equal(
            getattr(base, name)[before], getattr(other, name)[before], equal_nan=True
        ), name
    assert not np.array_equal(base.bias, other.bias, equal_nan=True)


def test_results_available_after_record_are_not_used() -> None:
    model, t, cols, _, labs = _fit_and_labs(False)
    late = LabResults(labs.t_s, labs.values, labs.available_s + 100 * DAY)
    run = run_softsensor(model, CFG, t, cols, late)
    assert run.n_lab_used == 0 and np.isnan(run.bias).all() and not run.drift.any()


def test_carry_forward_baseline_and_rmse() -> None:
    t = np.arange(10) * 10.0
    labs = LabResults(np.array([0.0, 30.0]), np.array([5.0, 8.0]), np.array([20.0, 60.0]))
    got = carry_forward_baseline(t, labs)
    expected = [np.nan, np.nan, 5, 5, 5, 5, 8, 8, 8, 8]
    assert np.array_equal(got, expected, equal_nan=True)
    est = np.array([1.0, 2.0, np.nan, 4.0])
    truth = np.array([1.0, 4.0, 9.0, 4.0])
    assert evaluate_rmse(est, truth) == pytest.approx(np.sqrt(4 / 3))
    assert evaluate_rmse(est, truth, np.array([0, 1, 1, 0], dtype=bool)) == pytest.approx(2.0)
    assert np.isnan(evaluate_rmse(est, truth, np.zeros(4, dtype=bool)))


def test_drift_detected_within_24h_and_stable_twin_quiet() -> None:
    model, t, cols, _, labs = _fit_and_labs(True)
    run = run_softsensor(model, CFG, t, cols, labs)
    onset = 15 * DAY
    hits = np.flatnonzero(run.drift & (t > onset))
    assert len(hits) > 0
    assert t[hits[0]] - onset <= DAY + CFG.lab_delay_s
    assert not run.drift[t <= onset].any()
    model, t, cols, _, labs = _fit_and_labs(False)
    assert not run_softsensor(model, CFG, t, cols, labs).drift.any()

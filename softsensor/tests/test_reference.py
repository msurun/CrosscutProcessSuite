"""Tests of the reference-input feature: window mean, coverage validity, config checks and the
EWMA bias check (a case where the correction helps and one where it hurts) on synthetic data."""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_softsensor.config import SoftSensorConfigError, load_config
from crosscut_softsensor.features import FeatureError
from crosscut_softsensor.pls import fit_pls
from crosscut_softsensor.reference import (
    build_model_features,
    model_feature_names,
    window_mean,
)
from crosscut_softsensor.reference_check import bias_check, reference_report
from crosscut_softsensor.runner import LabResults, run_softsensor

PERIOD = 60.0
REF = {"tag": "an", "window_s": 300, "shift_s": 120, "min_coverage": 0.6, "bias_weight": 0.3}


def _doc(**extra: object) -> dict[str, object]:
    return {
        "schema_version": "1.0.0", "id": "t", "target_tag": "y", "input_tags": ["a"],
        "mode": "advisory", "lags_s": [0], "sample_period_s": PERIOD, "lab_delay_s": 600,
        "max_components": 3, "cv_blocks": 3, **extra,
    }


def test_window_mean_is_causal_and_shifted() -> None:
    col = np.arange(10, dtype=float)
    mean, coverage = window_mean(col, n_bins=3, shift_bins=2)
    # row 5 averages bins 1..3 (end = 5 - 2); rows 0..1 have no bin yet
    assert mean[5] == pytest.approx(2.0) and coverage[5] == 1.0
    assert np.isnan(mean[0]) and np.isnan(mean[1]) and coverage[1] == 0.0
    assert coverage[2] == pytest.approx(1 / 3) and mean[2] == 0.0  # clipped at the record start


def test_coverage_counts_missing_bins_and_gates_the_feature() -> None:
    col = np.full(12, 5.0)
    col[[4, 5]] = np.nan  # a sparse analyser: two bins without data
    cfg = load_config(_doc(reference_inputs=[{**REF, "min_coverage": 0.7}]))
    feats = build_model_features({"a": np.zeros(12), "an": col}, cfg)
    # window 5 bins, shift 2: row 6 covers bins 0..4 (4 with data) -> 0.8; rows 7..10 hold 3 of 5
    assert feats.coverage[6, 0] == pytest.approx(0.8) and feats.reference_x[6, 0] == 5.0
    assert feats.coverage[8, 0] == pytest.approx(0.6) and np.isnan(feats.reference_x[8, 0])
    assert feats.coverage[11, 0] == pytest.approx(0.8) and feats.reference_x[11, 0] == 5.0
    assert feats.names == model_feature_names(cfg) and feats.x.shape == (12, 2)


def test_window_not_a_multiple_of_the_period_is_refused() -> None:
    cfg = load_config(_doc(reference_inputs=[{**REF, "window_s": 90}]))
    with pytest.raises(FeatureError, match="window_s"):
        build_model_features({"a": np.zeros(5), "an": np.zeros(5)}, cfg)


@pytest.mark.parametrize(
    "bad,field",
    [
        ({"window_s": 0}, "window_s"), ({"shift_s": -1}, "shift_s"),
        ({"min_coverage": 0}, "min_coverage"), ({"min_coverage": 1.5}, "min_coverage"),
        ({"bias_weight": 0}, "bias_weight"), ({"bias_weight": True}, "bias_weight"),
        ({"extra": 1}, "extra"),
    ],
)
def test_reference_config_errors_name_the_field(bad: dict[str, object], field: str) -> None:
    with pytest.raises(SoftSensorConfigError, match=field):
        load_config(_doc(reference_inputs=[{**REF, **bad}]))


@pytest.mark.parametrize("key", ["tag", "window_s", "shift_s", "min_coverage", "bias_weight"])
def test_reference_fields_have_no_defaults(key: str) -> None:
    entry = {k: v for k, v in REF.items() if k != key}
    with pytest.raises(SoftSensorConfigError, match=f"{key}: required"):
        load_config(_doc(reference_inputs=[entry]))


def test_no_reference_inputs_keep_the_old_behaviour() -> None:
    cfg = load_config(_doc())
    assert cfg.reference_inputs == ()
    feats = build_model_features({"a": np.arange(5.0)}, cfg)
    assert feats.x.shape == (5, 1) and feats.coverage.shape == (5, 0)


def _labs(t: np.ndarray, truth: np.ndarray, every: int, delay: float) -> LabResults:
    idx = np.arange(every, len(t), every)
    return LabResults.with_delay(t[idx], truth[idx], delay)


def _record(offset: float, noise: float, n: int = 600) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """truth(t) slow sine; reference = truth + offset + white noise; time in seconds."""
    t = PERIOD * np.arange(n)
    truth = 10.0 + 3.0 * np.sin(2 * np.pi * t / (PERIOD * 150))
    ref = truth + offset + np.random.default_rng(7).normal(0.0, noise, n)
    return t, truth, ref


def test_bias_correction_helps_when_the_reference_has_an_offset() -> None:
    t, truth, ref = _record(offset=2.0, noise=0.1)
    out = bias_check(t, ref, _labs(t, truth, 10, 600.0), weight=0.3)
    assert out["helps"] is True and out["n_pairs"] > 20
    assert out["rmse_raw"] == pytest.approx(2.0, abs=0.2) and out["rmse_corrected"] < 0.5


def test_bias_correction_hurts_when_the_reference_is_unbiased_and_noisy() -> None:
    t, truth, ref = _record(offset=0.0, noise=1.0)
    out = bias_check(t, ref, _labs(t, truth, 10, 600.0), weight=0.8)
    assert out["helps"] is False and out["rmse_corrected"] > out["rmse_raw"]


def test_bias_check_has_no_verdict_with_too_few_pairs() -> None:
    t, truth, ref = _record(offset=1.0, noise=0.0, n=60)
    out = bias_check(t, ref, _labs(t, truth, 30, 600.0), weight=0.3)
    assert out["helps"] is None


def test_lab_result_is_not_used_before_it_is_available() -> None:
    t, truth, ref = _record(offset=2.0, noise=0.0, n=100)
    labs = LabResults.with_delay(t[[10]], truth[[10]], 100 * PERIOD)  # available after the record
    out = bias_check(t, ref, labs, weight=0.3)
    assert out["n_pairs"] == 0 and out["rmse_corrected"] is None


def test_run_reports_coverage_validity_and_an_invalid_gap_flags_missing_input() -> None:
    n = 400
    t = PERIOD * np.arange(n)
    rng = np.random.default_rng(3)
    a, an = rng.normal(size=n), rng.normal(size=n)
    truth = 2.0 * np.convolve(an, np.ones(5) / 5, mode="full")[:n]  # y = 2 * 5-bin mean of an
    cfg = load_config(_doc(reference_inputs=[{**REF, "shift_s": 0}], input_tags=["a"]))
    cols = {"a": a, "an": an}
    feats = build_model_features(cols, cfg)
    ok = np.isfinite(feats.x).all(axis=1)
    y = np.where(ok, truth, np.nan)
    model = fit_pls(feats.x, y, cfg, x_domain=feats.x)
    gap = {"a": a, "an": np.where((t > 200 * PERIOD) & (t < 230 * PERIOD), np.nan, an)}
    labs = _labs(t, truth, 10, 600.0)
    run = run_softsensor(model, cfg, t, gap, labs)
    assert run.validity[215] == "missing_input" and run.validity[100] != "missing_input"
    report = reference_report(cfg, build_model_features(gap, cfg), t, labs)[0]
    assert report["tag"] == "an" and 0.8 < report["valid_share"] < 1.0
    assert report["latest_valid"] is True and report["latest_coverage"] == 1.0


def test_schema_and_hand_validation_agree_on_reference_inputs() -> None:
    import json
    from pathlib import Path

    import jsonschema

    path = Path(__file__).parents[2] / "schemas" / "softsensor.schema.json"
    schema = json.loads(path.read_text("utf-8"))
    good = _doc(reference_inputs=[REF])
    jsonschema.validate(good, schema)
    assert load_config(good).reference_inputs[0].tag == "an"
    for bad in ({**REF, "bias_weight": 0}, {k: v for k, v in REF.items() if k != "window_s"}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(_doc(reference_inputs=[bad]), schema)
        with pytest.raises(SoftSensorConfigError):
            load_config(_doc(reference_inputs=[bad]))

"""Does a lab bias correction of a reference input help or hurt on the user's own data?

For a reference that measures the same quantity as the lab target, the lab result minus the
reference window mean is a bias sample. An EWMA of these samples (weight ``bias_weight``) is added
to the reference; the check compares RMSE(lab, reference) with RMSE(lab, reference + bias) at the
lab sample times, using only lab results already available (sample time + lab delay) at that
time. When the reference has no bias, the EWMA only adds noise and the check says "hurts".
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from crosscut_softsensor.bias import BiasTracker
from crosscut_softsensor.config import SoftSensorConfig
from crosscut_softsensor.reference import ModelFeatures
from crosscut_softsensor.runner import LabResults, bias_series, evaluate_rmse

# Fewer lab/reference pairs than this give a verdict of None (RMSE of 1-4 points is noise).
MIN_CHECK_PAIRS = 5


def bias_check(
    t_s: np.ndarray, reference: np.ndarray, labs: LabResults, weight: float
) -> dict[str, Any]:
    """RMSE of the reference against the labs without and with the causal EWMA bias correction."""
    tracker = BiasTracker(sigma_cv=1.0, weight=weight)  # sigma_cv only scales the unused drift flag
    bias, _, _ = bias_series(t_s, reference, labs, tracker)
    rows = np.searchsorted(t_s, labs.t_s, side="right") - 1
    inside = rows >= 0
    raw, shift = reference[rows[inside]], bias[rows[inside]]
    truth = labs.values[inside]
    paired = np.isfinite(raw) & np.isfinite(shift) & np.isfinite(truth)
    n = int(paired.sum())
    before = evaluate_rmse(raw, truth, paired)
    after = evaluate_rmse(raw + shift, truth, paired)
    helps = None if n < MIN_CHECK_PAIRS else bool(after < before)
    return {"n_pairs": n, "rmse_raw": _num(before), "rmse_corrected": _num(after), "helps": helps}


def _num(value: float) -> float | None:
    """A float for JSON, None when it is NaN."""
    return None if math.isnan(value) else float(value)


def reference_report(
    config: SoftSensorConfig, features: ModelFeatures, t_s: np.ndarray, labs: LabResults
) -> list[dict[str, Any]]:
    """Per reference input: settings, coverage, validity share and the bias check."""
    out = []
    for j, ref in enumerate(config.reference_inputs):
        coverage, feature = features.coverage[:, j], features.reference_x[:, j]
        valid = np.isfinite(feature)
        out.append({
            "tag": ref.tag, "window_s": ref.window_s, "shift_s": ref.shift_s,
            "min_coverage": ref.min_coverage, "bias_weight": ref.bias_weight,
            "coverage_mean": _num(float(coverage.mean())) if len(coverage) else None,
            "valid_share": _num(float(valid.mean())) if len(valid) else None,
            "latest_coverage": _num(float(coverage[-1])) if len(coverage) else None,
            "latest_valid": bool(valid[-1]) if len(valid) else False,
            **bias_check(t_s, feature, labs, ref.bias_weight),
        })
    return out

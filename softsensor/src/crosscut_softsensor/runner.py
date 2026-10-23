"""Offline soft sensor run: estimate, validity and lab-bias correction without lab leakage.

A lab result is used only from its availability time (sample time + lab delay) onwards; its
partner estimate is the one at the sample time (nearest earlier row).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from crosscut_softsensor.bias import BiasTracker
from crosscut_softsensor.config import SoftSensorConfig
from crosscut_softsensor.features import build_lagged
from crosscut_softsensor.pls import PlsModel


@dataclass(frozen=True, eq=False)
class LabResults:
    """Lab samples: sample times, values and the times they become available."""

    t_s: np.ndarray
    values: np.ndarray
    available_s: np.ndarray

    @classmethod
    def with_delay(cls, t_s: np.ndarray, values: np.ndarray, lab_delay_s: float) -> LabResults:
        """Build with available_s = t_s + lab_delay_s."""
        t = np.asarray(t_s, dtype=float)
        return cls(t, np.asarray(values, dtype=float), t + lab_delay_s)


@dataclass(frozen=True, eq=False)
class SoftSensorRun:
    """Series produced by `run_softsensor`, one entry per input row."""

    t_s: np.ndarray
    estimate: np.ndarray
    validity: list[str]
    corrected: np.ndarray
    bias: np.ndarray
    drift: np.ndarray
    n_lab_used: int


def run_softsensor(
    model: PlsModel,
    config: SoftSensorConfig,
    t_s: np.ndarray,
    columns: Mapping[str, np.ndarray],
    labs: LabResults,
    tracker: BiasTracker | None = None,
) -> SoftSensorRun:
    """Run the model over a record and track the lab bias causally."""
    t = np.asarray(t_s, dtype=float)
    x, _ = build_lagged(columns, config.input_tags, config.lags_s, config.sample_period_s)
    est, validity = model.predict(x), model.validity(x)
    tr = tracker if tracker is not None else BiasTracker(model.cv_sigma)
    tr.reset()
    bias, drift, used = _bias_series(t, est, labs, tr)
    corrected = est + bias
    return SoftSensorRun(t, est, validity, corrected, bias, drift, used)


def _bias_series(
    t: np.ndarray, est: np.ndarray, labs: LabResults, tr: BiasTracker
) -> tuple[np.ndarray, np.ndarray, int]:
    """Bias and drift series from the lab results in order of availability."""
    bias, drift = np.full(len(t), np.nan), np.zeros(len(t), dtype=bool)
    used = 0
    for i in np.argsort(labs.available_s, kind="stable"):
        avail = float(labs.available_s[i])
        row = int(np.searchsorted(t, labs.t_s[i], side="right")) - 1
        if len(t) == 0 or avail > t[-1] or row < 0:
            continue
        state = tr.update(float(labs.t_s[i]), float(labs.values[i]), float(est[row]))
        used += 1
        start = int(np.searchsorted(t, avail, side="left"))
        bias[start:], drift[start:] = state.bias_ewma, state.drift
    return bias, drift, used


def evaluate_rmse(
    estimate: np.ndarray, truth: np.ndarray, mask: np.ndarray | None = None
) -> float:
    """RMSE over rows where both are finite (and `mask` is True); NaN if none."""
    e, y = np.asarray(estimate, dtype=float), np.asarray(truth, dtype=float)
    ok = np.isfinite(e) & np.isfinite(y)
    if mask is not None:
        ok &= np.asarray(mask, dtype=bool)
    return float(np.sqrt(np.mean((e[ok] - y[ok]) ** 2))) if ok.any() else float("nan")


def carry_forward_baseline(t_s: np.ndarray, labs: LabResults) -> np.ndarray:
    """Last lab value available at each time (by availability); NaN before the first."""
    t = np.asarray(t_s, dtype=float)
    out = np.full(len(t), np.nan)
    for i in np.argsort(labs.available_s, kind="stable"):
        start = int(np.searchsorted(t, labs.available_s[i], side="left"))
        out[start:] = labs.values[i]
    return out

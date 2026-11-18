"""Reference-measurement inputs of the soft sensor: causal window means with a coverage flag.

An online reference (analyser, inferential, any sparse or window-aggregated signal) enters the
model as one column per reference: its mean over the window (t - shift_s - window_s, t - shift_s]
of the binned series. The share of bins in that window that hold data is the coverage; below
``min_coverage`` the feature is NaN, so the model reports ``missing_input`` for that row.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from crosscut_softsensor.config import ReferenceInput, SoftSensorConfig
from crosscut_softsensor.features import FeatureError, build_lagged, feature_names, lag_samples


@dataclass(frozen=True, eq=False)
class ModelFeatures:
    """Model input matrix, its column names and, per reference input, the window coverage.

    ``coverage`` has one column per reference input (rows x references, in [0, 1]);
    ``reference_x`` holds the window means (NaN where the coverage is below the threshold).
    """

    x: np.ndarray
    names: list[str]
    coverage: np.ndarray
    reference_x: np.ndarray


def reference_name(ref: ReferenceInput) -> str:
    """Column name ``tag@mean<window>s-shift<shift>s`` of one reference feature."""
    return f"{ref.tag}@mean{ref.window_s:g}s-shift{ref.shift_s:g}s"


def model_feature_names(config: SoftSensorConfig) -> list[str]:
    """Lagged process columns followed by one column per reference input."""
    names = feature_names(config.input_tags, config.lags_s)
    return names + [reference_name(ref) for ref in config.reference_inputs]


def _bins(seconds: float, period_s: float, what: str) -> int:
    """Whole number of bins in ``seconds``; a fraction of a bin is refused."""
    k = round(seconds / period_s)
    if abs(k * period_s - seconds) > 1e-6 * max(1.0, period_s):
        raise FeatureError(f"{what} {seconds} s is not a multiple of {period_s} s")
    return int(k)


def window_mean(col: np.ndarray, n_bins: int, shift_bins: int) -> tuple[np.ndarray, np.ndarray]:
    """Causal window mean and coverage of ``col`` (NaN = no data in that bin).

    Row i averages bins i-shift-n+1 .. i-shift (clipped at the record start, which lowers the
    coverage). coverage = bins with data / n_bins. Uses cumulative sums, so cost is O(rows).
    """
    finite = np.isfinite(col)
    csum = np.concatenate(([0.0], np.cumsum(np.where(finite, col, 0.0))))
    ccount = np.concatenate(([0], np.cumsum(finite)))
    end = np.arange(len(col)) - shift_bins  # last bin of the window
    first = np.maximum(end - n_bins + 1, 0)
    ok = end >= 0
    stop = np.where(ok, end + 1, 0)
    count = np.where(ok, ccount[stop] - ccount[np.minimum(first, stop)], 0)
    total = np.where(ok, csum[stop] - csum[np.minimum(first, stop)], 0.0)
    mean = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    return mean, count / n_bins


def reference_feature(
    col: np.ndarray, ref: ReferenceInput, period_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """(feature, coverage) of one reference: the window mean, NaN below ``min_coverage``."""
    n = max(1, _bins(ref.window_s, period_s, "window_s"))
    mean, coverage = window_mean(col, n, _bins(ref.shift_s, period_s, "shift_s"))
    return np.where(coverage >= ref.min_coverage - 1e-12, mean, np.nan), coverage


def build_model_features(
    columns: Mapping[str, np.ndarray], config: SoftSensorConfig
) -> ModelFeatures:
    """Lagged process features plus the reference window means, in `model_feature_names` order."""
    x, _ = build_lagged(columns, config.input_tags, config.lags_s, config.sample_period_s)
    rows = x.shape[0]
    period = config.sample_period_s
    pairs = [_one_reference(columns, ref, period) for ref in config.reference_inputs]
    ref_x = _stack([p[0] for p in pairs], rows)
    coverage = _stack([p[1] for p in pairs], rows)
    return ModelFeatures(np.hstack([x, ref_x]), model_feature_names(config), coverage, ref_x)


def _one_reference(
    columns: Mapping[str, np.ndarray], ref: ReferenceInput, period_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """Feature and coverage of one reference tag taken from ``columns``."""
    if ref.tag not in columns:
        raise FeatureError(f"{ref.tag}: tag is missing from the data")
    return reference_feature(np.asarray(columns[ref.tag], dtype=float), ref, period_s)


def _stack(parts: Sequence[np.ndarray], rows: int) -> np.ndarray:
    """Columns side by side; an empty block has ``rows`` rows and no column."""
    return np.column_stack(parts) if parts else np.empty((rows, 0))


def lag_gap(config: SoftSensorConfig) -> int:
    """Rows without full history: the longest lag or reference window plus its shift."""
    lags = max(lag_samples(config.lags_s, config.sample_period_s))
    span = [
        _bins(r.window_s, config.sample_period_s, "window_s")
        + _bins(r.shift_s, config.sample_period_s, "shift_s")
        for r in config.reference_inputs
    ]
    return max([lags, *span])

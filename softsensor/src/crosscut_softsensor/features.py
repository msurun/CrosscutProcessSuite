"""Lagged feature matrix for the PLS soft sensor.

Every tag contributes one column per lag: the value at t - lag, taken by an index shift.
Only past values are used; the first rows (no history yet) are NaN.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np


class FeatureError(ValueError):
    """Raised when lagged features cannot be built (bad lag, missing or ragged tag)."""


def lag_samples(lags_s: Sequence[float], sample_period_s: float) -> tuple[int, ...]:
    """Lags in whole samples; a negative lag (future value) or a fractional one is refused."""
    if not sample_period_s > 0:
        raise FeatureError("sample_period_s must be above 0")
    out = []
    for lag in lags_s:
        if lag < 0:
            raise FeatureError(f"lag {lag} s is negative: future values are not allowed")
        k = round(lag / sample_period_s)
        if abs(k * sample_period_s - lag) > 1e-6 * max(1.0, sample_period_s):
            raise FeatureError(f"lag {lag} s is not a multiple of {sample_period_s} s")
        out.append(int(k))
    return tuple(out)


def feature_names(tags: Sequence[str], lags_s: Sequence[float]) -> list[str]:
    """Column names ``tag@lag`` in the order of `build_lagged` (tag-major, lag-minor)."""
    return [f"{tag}@{lag:g}" for tag in tags for lag in lags_s]


def _column(columns: Mapping[str, np.ndarray], tag: str) -> np.ndarray:
    """One tag as a float vector."""
    if tag not in columns:
        raise FeatureError(f"{tag}: tag is missing from the data")
    col = np.asarray(columns[tag], dtype=float)
    if col.ndim != 1:
        raise FeatureError(f"{tag}: must be a one-dimensional series")
    return col


def _shift(col: np.ndarray, k: int) -> np.ndarray:
    """Value at t - k samples; the first k rows are NaN."""
    out = np.full(len(col), np.nan)
    if k < len(col):
        out[k:] = col[: len(col) - k]
    return out


def build_lagged(
    columns: Mapping[str, np.ndarray],
    tags: Sequence[str],
    lags_s: Sequence[float],
    sample_period_s: float,
) -> tuple[np.ndarray, list[str]]:
    """Return (X, names) with X[t, tag@lag] = column[t - lag]; no future value is used."""
    shifts = lag_samples(lags_s, sample_period_s)
    cols = [_column(columns, tag) for tag in tags]
    if len({len(c) for c in cols}) > 1:
        raise FeatureError("tags have different lengths")
    parts = [_shift(col, k) for col in cols for k in shifts]
    x = np.column_stack(parts) if parts else np.empty((0, 0))
    return x, feature_names(tags, lags_s)

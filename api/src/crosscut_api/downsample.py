"""Downsample time series to min/max envelopes for trend viewing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Envelope:
    """Min/max envelope of a time series.

    Attributes:
        t: Timestamps of the envelope points.
        min: Minimum values of the buckets.
        max: Maximum values of the buckets.
        mean: Mean values of the buckets.
        downsampled: Whether the data was downsampled.
    """

    t: np.ndarray
    min: np.ndarray
    max: np.ndarray
    mean: np.ndarray
    downsampled: bool


def downsample_minmax(timestamps: np.ndarray, values: np.ndarray, max_points: int) -> Envelope:
    """Downsample a time series to min/max envelopes.

    Args:
        timestamps: Timestamps of the time series.
        values: Values of the time series.
        max_points: Maximum number of points in the downsampled series.

    Returns:
        Envelope: The downsampled time series.

    Raises:
        ValueError: If max_points is less than 2.
    """
    if max_points < 2:
        raise ValueError("max_points must be at least 2")

    if len(timestamps) <= max_points:
        return Envelope(timestamps, values, values, values, False)

    bucket_edges = np.linspace(0, len(timestamps), max_points + 1, dtype=np.int64)
    bucket_starts = bucket_edges[:-1]
    min_v, max_v, mean_v = _bucket_stats(values, bucket_starts)
    return Envelope(timestamps[bucket_starts], min_v, max_v, mean_v, True)


def _bucket_stats(
    values: np.ndarray, bucket_starts: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Minimum, maximum and mean per bucket; a bucket without finite samples gives NaN."""
    v_nan = np.where(np.isnan(values), np.nan, values)
    counts = np.add.reduceat(np.isfinite(values), bucket_starts)
    sum_v = np.add.reduceat(v_nan, bucket_starts)
    min_v = np.minimum.reduceat(v_nan, bucket_starts)
    max_v = np.maximum.reduceat(v_nan, bucket_starts)

    mean_downsampled = np.where(counts > 0, sum_v / counts, np.nan)
    min_downsampled = np.where(counts > 0, min_v, np.nan)
    max_downsampled = np.where(counts > 0, max_v, np.nan)
    return min_downsampled, max_downsampled, mean_downsampled

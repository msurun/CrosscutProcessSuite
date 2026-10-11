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


def downsample_minmax(t: np.ndarray, v: np.ndarray, max_points: int) -> Envelope:
    """Downsample a time series to min/max envelopes.

    Args:
        t: Timestamps of the time series.
        v: Values of the time series.
        max_points: Maximum number of points in the downsampled series.

    Returns:
        Envelope: The downsampled time series.

    Raises:
        ValueError: If max_points is less than 2.
    """
    if max_points < 2:
        raise ValueError("max_points must be at least 2")

    if len(t) <= max_points:
        return Envelope(t, v, v, v, False)

    n_buckets = max_points
    bucket_edges = np.linspace(0, len(t), n_buckets + 1, dtype=np.int64)
    bucket_indices = bucket_edges[:-1]

    t_downsampled = t[bucket_indices]
    v_nan = np.where(np.isnan(v), np.nan, v)
    counts = np.add.reduceat(np.isfinite(v), bucket_edges[:-1])
    sum_v = np.add.reduceat(v_nan, bucket_edges[:-1])
    min_v = np.minimum.reduceat(v_nan, bucket_edges[:-1])
    max_v = np.maximum.reduceat(v_nan, bucket_edges[:-1])

    mean_downsampled = np.where(counts > 0, sum_v / counts, np.nan)
    min_downsampled = np.where(counts > 0, min_v, np.nan)
    max_downsampled = np.where(counts > 0, max_v, np.nan)

    return Envelope(t_downsampled, min_downsampled, max_downsampled, mean_downsampled, True)

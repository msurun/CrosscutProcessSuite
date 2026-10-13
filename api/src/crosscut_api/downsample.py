"""Downsample time series to min/max envelopes for trend viewing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Envelope:
    """Min/max envelope of a time series.

    Attributes:
        timestamps: Timestamps of the envelope points.
        min: Minimum values of the buckets.
        max: Maximum values of the buckets.
        mean: Mean values of the buckets.
        downsampled: Whether the data was downsampled.
    """

    timestamps: np.ndarray
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
    """Minimum, maximum and mean per bucket; a bucket without finite samples gives NaN.

    Used by chart downsampling: instead of plotting every point, the x axis is cut into adjacent
    buckets and each bucket is drawn as one min/max envelope plus a mean line. Adjacent buckets
    may share a boundary sample, so a value can be counted in two buckets.

    values: 1-D array of y values (same unit as the plotted series), may contain NaN gaps.
    bucket_starts: 0-based index in `values` where each bucket starts, strictly increasing and
        within bounds; these indices are also the cut points used by np.add.reduceat below.
    Returns one array per bucket, in bucket order: (min, max, mean). A bucket with no finite
    value anywhere gets NaN for all three.
    """
    # np.add.reduceat, np.minimum.reduceat and np.maximum.reduceat have no NaN-aware
    # variant: reduceat over a slice that contains NaN gives NaN. We need min/max
    # to ignore NaN gaps, so we reduce a copy where NaN entries are kept as NaN.
    v_nan = np.where(np.isnan(values), np.nan, values)
    # counts uses np.isfinite(values), so NaN entries are not counted. It is used
    # only as a guard against dividing by zero and against promoting an empty
    # bucket to NaN below.
    counts = np.add.reduceat(np.isfinite(values), bucket_starts)
    # NaN propagates through +, so a bucket holding one NaN yields NaN here; the finite rows are
    # still summed correctly, which is what min/max need per bucket.
    sum_v = np.add.reduceat(v_nan, bucket_starts)
    # Both min_v and max_v ignore NaN because comparisons with NaN return False.
    min_v = np.minimum.reduceat(v_nan, bucket_starts)
    # Same NaN-skipping behaviour as np.minimum above.
    max_v = np.maximum.reduceat(v_nan, bucket_starts)

    # Guard each result: a bucket whose count is 0 is either empty or contains only
    # NaN entries, so report NaN rather than risking division by zero or keeping a
    # spurious NaN from reduceat over an empty slice.
    mean_downsampled = np.where(counts > 0, sum_v / counts, np.nan)
    min_downsampled = np.where(counts > 0, min_v, np.nan)
    max_downsampled = np.where(counts > 0, max_v, np.nan)
    return min_downsampled, max_downsampled, mean_downsampled

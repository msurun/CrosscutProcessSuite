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
    """Minimum, maximum and mean per bucket over the finite samples; none finite gives NaN.

    Used by chart downsampling: instead of plotting every point, the series is cut into
    adjacent buckets and each bucket is drawn as one min/max envelope plus a mean line. Bucket
    i covers ``values[bucket_starts[i]:bucket_starts[i + 1]]`` (the last one runs to the end),
    so every sample belongs to exactly one bucket.

    values: 1-D array of y values (same unit as the plotted series), may contain NaN gaps.
        NaN and infinite samples count as missing and are skipped.
    bucket_starts: 0-based index in `values` where each bucket starts, strictly increasing and
        within bounds; these indices are also the cut points used by the reduceat calls below.
    Returns one array per bucket, in bucket order: (min, max, mean). A bucket without any finite
    sample gets NaN for all three (shown as a gap), a bucket with some keeps the others' values.
    """
    finite = np.isfinite(values)
    counts = np.add.reduceat(finite.astype(np.int64), bucket_starts)  # finite samples per bucket
    # Sum over finite samples only: missing ones contribute 0 to the sum and 0 to the count.
    sum_v = np.add.reduceat(np.where(finite, values, 0.0), bucket_starts)
    # fmin / fmax skip NaN, so marking missing samples as NaN leaves only the finite ones.
    marked = np.where(finite, values, np.nan)
    min_v = np.fmin.reduceat(marked, bucket_starts)
    max_v = np.fmax.reduceat(marked, bucket_starts)

    has_data = counts > 0  # an empty bucket reports NaN instead of dividing by zero
    mean_downsampled = np.where(has_data, sum_v / np.maximum(counts, 1), np.nan)
    min_downsampled = np.where(has_data, min_v, np.nan)
    max_downsampled = np.where(has_data, max_v, np.nan)
    return min_downsampled, max_downsampled, mean_downsampled

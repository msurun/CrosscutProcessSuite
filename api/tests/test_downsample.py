"""Tests for the min/max envelope downsampling used by the trend viewer."""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_api.downsample import downsample_minmax


def test_short_series_is_returned_unchanged() -> None:
    """A series shorter than max_points is returned as-is with downsampled False."""
    timestamps = np.arange(10, dtype=np.int64)
    values = np.linspace(0.0, 1.0, 10)
    out = downsample_minmax(timestamps, values, max_points=20)
    assert out.downsampled is False
    assert out.timestamps.tolist() == timestamps.tolist()
    assert out.mean.tolist() == values.tolist()
    assert out.min.tolist() == values.tolist()
    assert out.max.tolist() == values.tolist()


def test_long_series_is_reduced_to_at_most_max_points() -> None:
    time_ns = np.arange(10_000, dtype=np.int64)
    downsampled_series = downsample_minmax(time_ns, np.sin(time_ns / 50.0), max_points=100)
    assert downsampled_series.downsampled is True
    assert 50 <= len(downsampled_series.timestamps) <= 100
    assert (
        len(downsampled_series.timestamps)
        == len(downsampled_series.min)
        == len(downsampled_series.max)
        == len(downsampled_series.mean)
    )


def test_a_single_spike_survives_downsampling() -> None:
    timestamps = np.arange(10_000, dtype=np.int64)
    values = np.zeros(10_000)
    values[4321] = 99.0
    downsampled = downsample_minmax(timestamps, values, max_points=100)
    assert downsampled.max.max() == 99.0


def test_envelope_brackets_the_mean_and_time_is_increasing() -> None:
    rng = np.random.default_rng(0)
    timestamps_ns = np.arange(5000, dtype=np.int64) * 1_000_000_000
    out = downsample_minmax(timestamps_ns, rng.normal(size=5000), max_points=60)
    assert np.all(out.min <= out.mean) and np.all(out.mean <= out.max)
    assert np.all(np.diff(out.timestamps) > 0)


def test_nan_samples_are_ignored_and_all_nan_buckets_become_nan() -> None:
    sample_timestamps = np.arange(1000, dtype=np.int64)
    sample_values = np.ones(1000)
    sample_values[:500] = np.nan
    downsampled = downsample_minmax(sample_timestamps, sample_values, max_points=10)
    assert np.isnan(downsampled.mean[0])
    assert downsampled.mean[-1] == 1.0


def test_a_single_nan_does_not_blank_the_bucket() -> None:
    """One missing sample inside a bucket must not hide the finite samples around it."""
    sample_timestamps = np.arange(1000, dtype=np.int64)
    sample_values = np.arange(1000, dtype=float)
    sample_values[5] = np.nan  # inside the first bucket of 100 samples
    downsampled = downsample_minmax(sample_timestamps, sample_values, max_points=10)
    assert downsampled.min[0] == 0.0
    assert downsampled.max[0] == 99.0
    expected_mean = (sum(range(100)) - 5) / 99  # 99 finite samples
    assert downsampled.mean[0] == pytest.approx(expected_mean)

def test_max_points_below_two_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_points"):
        downsample_minmax(np.arange(5, dtype=np.int64), np.zeros(5), max_points=1)

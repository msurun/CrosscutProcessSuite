"""Tests for the min/max envelope downsampling used by the trend viewer."""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_api.downsample import downsample_minmax


def test_short_series_is_returned_unchanged() -> None:
    t = np.arange(10, dtype=np.int64)
    v = np.linspace(0.0, 1.0, 10)
    out = downsample_minmax(t, v, max_points=20)
    assert out.downsampled is False
    assert out.t.tolist() == t.tolist()
    assert out.mean.tolist() == v.tolist()
    assert out.min.tolist() == v.tolist()
    assert out.max.tolist() == v.tolist()


def test_long_series_is_reduced_to_at_most_max_points() -> None:
    t = np.arange(10_000, dtype=np.int64)
    out = downsample_minmax(t, np.sin(t / 50.0), max_points=100)
    assert out.downsampled is True
    assert 50 <= len(out.t) <= 100
    assert len(out.t) == len(out.min) == len(out.max) == len(out.mean)


def test_a_single_spike_survives_downsampling() -> None:
    t = np.arange(10_000, dtype=np.int64)
    v = np.zeros(10_000)
    v[4321] = 99.0
    out = downsample_minmax(t, v, max_points=100)
    assert out.max.max() == 99.0


def test_envelope_brackets_the_mean_and_time_is_increasing() -> None:
    rng = np.random.default_rng(0)
    t = np.arange(5000, dtype=np.int64) * 1_000_000_000
    out = downsample_minmax(t, rng.normal(size=5000), max_points=60)
    assert np.all(out.min <= out.mean) and np.all(out.mean <= out.max)
    assert np.all(np.diff(out.t) > 0)


def test_nan_samples_are_ignored_and_all_nan_buckets_become_nan() -> None:
    t = np.arange(1000, dtype=np.int64)
    v = np.ones(1000)
    v[:500] = np.nan
    out = downsample_minmax(t, v, max_points=10)
    assert np.isnan(out.mean[0])
    assert out.mean[-1] == 1.0


def test_max_points_below_two_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_points"):
        downsample_minmax(np.arange(5, dtype=np.int64), np.zeros(5), max_points=1)

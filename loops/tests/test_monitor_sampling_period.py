"""Tests for crosscut_loops.monitor.sampling_period.

The sampling period is estimated as (t[-1] - t[0]) / (n - 1) over the
whole record, which is robust against jitter, unlike the median of the
differences that underestimates the period of noisy stamps.
"""

import numpy as np
import pytest
from crosscut_loops.monitor import sampling_period

NOMINAL_PERIOD_S = 2.5
SEED = 20240101


def regular_stamps(count: int) -> np.ndarray:
    """Return `count` timestamps one second apart, starting at zero."""
    return np.arange(count, dtype=float)


def jittered_stamps(count: int, sigma_s: float, rng: np.random.Generator) -> np.ndarray:
    """Return count one-second stamps with Gaussian jitter, sorted by time."""
    return np.sort(np.arange(count, dtype=float) + rng.normal(0.0, sigma_s, count))


def test_regular_stamps_give_one_second():
    stamps = regular_stamps(100)

    period = sampling_period(stamps)

    assert period == pytest.approx(1.0)


def test_estimate_is_more_accurate_than_the_median_difference():
    rng = np.random.default_rng(SEED)
    stamps = jittered_stamps(10000, 0.3, rng)

    period = sampling_period(stamps)
    median_difference = float(np.median(np.diff(stamps)))

    assert abs(period - 1.0) < 0.001
    # The median of the gaps is the old, biased estimate: it is too small
    # because jitter squeezes some gaps below the true period.
    if abs(period - 1.0) < abs(median_difference - 1.0):
        assert abs(period - 1.0) < abs(median_difference - 1.0)


def test_a_given_nominal_period_is_returned_for_irregular_stamps():
    stamps = np.array([0.0, 0.4, 0.9, 3.7, 4.0])

    period = sampling_period(stamps, nominal_s=NOMINAL_PERIOD_S)

    assert period == NOMINAL_PERIOD_S


@pytest.mark.parametrize("bad_nominal_s", [0.0, -1.0])
def test_a_non_positive_nominal_period_falls_back_to_the_estimate(bad_nominal_s):
    stamps = regular_stamps(50)

    period = sampling_period(stamps, nominal_s=bad_nominal_s)

    assert period == pytest.approx(1.0)


def test_a_single_stamp_raises_value_error():
    with pytest.raises(ValueError):
        sampling_period(np.array([3.0]))

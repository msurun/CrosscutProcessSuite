"""Behaviour tests for crosscut_loops.example_windows.example_window.

They pin down which slice of the record is returned for a given control loop code,
and how the window length is chosen when the oscillation period is known or unknown.
"""

import numpy as np
import pytest
from crosscut_loops.example_windows import (
    EXAMPLE_PERIODS,
    MIN_EXAMPLE_SAMPLES,
    WHOLE_RECORD_CODES,
    example_window,
)


def _times(sample_count: int, spacing_s: float = 1.0) -> np.ndarray:
    """Return sample_count timestamps spaced spacing_s seconds apart, starting at 0."""
    return np.arange(sample_count, dtype=float) * spacing_s


def test_a_noisy_burst_with_a_known_period_is_selected():
    """pv spikes for 60 samples in the middle: the window must cover exactly that burst."""
    t_s = _times(600)
    pv = np.zeros(600)
    pv[300:360] = 5.0
    sp = np.zeros(600)

    window = example_window("oscillating", t_s, pv, sp, period_s=10.0)

    assert window == (300.0, 359.0)


def test_the_same_burst_is_found_when_the_sampling_spacing_changes():
    """The window is measured in samples, so 60 samples at dt=5 s span 295 s of time."""
    t_s = _times(600, spacing_s=5.0)
    pv = np.zeros(600)
    pv[300:360] = 5.0
    sp = np.zeros(600)

    window = example_window("oscillating", t_s, pv, sp, period_s=50.0)

    assert window == (1500.0, 1795.0)


def test_an_unknown_period_falls_back_to_a_quarter_of_the_record():
    """Without a period the window is a quarter of the record: 100 of 400 samples."""
    t_s = _times(400)
    pv = np.zeros(400)
    pv[200:300] = 3.0
    sp = np.zeros(400)

    window = example_window("oscillating", t_s, pv, sp, period_s=None)

    assert window == (200.0, 299.0)


def test_a_nan_period_is_treated_as_an_unknown_period():
    """A missing period arrives as NaN from upstream, and must behave like None."""
    t_s = _times(400)
    pv = np.zeros(400)
    pv[200:300] = 3.0
    sp = np.zeros(400)

    window = example_window("oscillating", t_s, pv, sp, period_s=float("nan"))

    assert window == (200.0, 299.0)


def test_a_negative_period_is_treated_as_an_unknown_period():
    """A negative period is not physical, so it is ignored like a missing one."""
    t_s = _times(400)
    pv = np.zeros(400)
    pv[200:300] = 3.0
    sp = np.zeros(400)

    window = example_window("oscillating", t_s, pv, sp, period_s=-10.0)

    assert window == (200.0, 299.0)


def test_a_zero_period_is_treated_as_an_unknown_period():
    """A zero period would give a zero-length window, so it is ignored too."""
    t_s = _times(400)
    pv = np.zeros(400)
    pv[200:300] = 3.0
    sp = np.zeros(400)

    window = example_window("oscillating", t_s, pv, sp, period_s=0.0)

    assert window == (200.0, 299.0)


def test_a_huge_period_is_clamped_to_the_whole_record():
    """A window longer than the record is clamped, so the whole record is returned."""
    t_s = _times(100)
    pv = np.zeros(100)
    pv[40:60] = 1.0
    sp = np.zeros(100)

    window = example_window("oscillating", t_s, pv, sp, period_s=10_000.0)

    assert window == (t_s[0], t_s[-1])


def test_a_tiny_period_is_clamped_to_the_minimum_window():
    """A window shorter than 30 samples is widened to the minimum of 30 samples."""
    t_s = _times(100)
    pv = np.zeros(100)
    pv[10:50] = 1.0
    sp = np.zeros(100)

    window = example_window("oscillating", t_s, pv, sp, period_s=0.1)

    assert window == (t_s[10], t_s[39])


def test_a_nan_gap_never_wins_over_a_real_error():
    """Samples with NaN pv count as zero error, so the NaN stretch is not selected."""
    t_s = _times(400)
    pv = np.zeros(400)
    pv[0:100] = float("nan")
    pv[300:330] = 1.0
    sp = np.zeros(400)

    window = example_window("oscillating", t_s, pv, sp, period_s=None)

    # A window of a quarter of the record (100 samples) holds the whole burst from index 230 on;
    # the earliest such window wins.
    assert window == (t_s[230], t_s[329])


def test_an_all_zero_error_returns_the_earliest_window():
    """With no error anywhere, the tie is broken by taking the earliest window."""
    t_s = _times(400)
    pv = np.zeros(400)
    sp = np.zeros(400)

    window = example_window("oscillating", t_s, pv, sp, period_s=None)

    assert window == (t_s[0], t_s[99])


def test_a_code_outside_the_supported_set_returns_none():
    """A loop tagged 'manual' has no example window, so None signals 'not applicable'."""
    t_s = _times(400)
    pv = np.zeros(400)
    sp = np.zeros(400)

    window = example_window("manual", t_s, pv, sp, period_s=10.0)

    assert window is None


def test_every_supported_code_can_produce_a_window():
    """All codes in WHOLE_RECORD_CODES must be accepted and return a time interval."""
    t_s = _times(400)
    pv = np.zeros(400)
    pv[200:300] = 3.0
    sp = np.zeros(400)

    for code in WHOLE_RECORD_CODES:
        window = example_window(code, t_s, pv, sp, period_s=10.0)

        # period 10 s at 1 s spacing -> 60 samples; the burst is longer, the earliest window wins.
        assert window == (200.0, 259.0)


def test_too_few_samples_returns_none():
    """A record shorter than MIN_EXAMPLE_SAMPLES has no room for an example."""
    t_s = _times(MIN_EXAMPLE_SAMPLES - 1)
    pv = np.zeros(MIN_EXAMPLE_SAMPLES - 1)
    pv[10:20] = 1.0
    sp = np.zeros(MIN_EXAMPLE_SAMPLES - 1)

    window = example_window("oscillating", t_s, pv, sp, period_s=10.0)

    assert window is None


def test_arrays_of_different_lengths_raise_a_value_error():
    """Mismatched pv and t_s lengths are a programming error, not a missing example."""
    t_s = _times(400)
    pv = np.zeros(399)
    sp = np.zeros(400)

    with pytest.raises(ValueError):
        example_window("oscillating", t_s, pv, sp, period_s=10.0)


def test_the_period_is_interpreted_in_number_of_oscillations():
    """The window length is round(EXAMPLE_PERIODS * period_s / dt), by definition."""
    dt_s = 2.0
    t_s = _times(600, spacing_s=dt_s)
    pv = np.zeros(600)
    pv[300:360] = 1.0
    sp = np.zeros(600)

    window = example_window("oscillating", t_s, pv, sp, period_s=10.0)

    expected_samples = round(EXAMPLE_PERIODS * 10.0 / dt_s)
    assert window == (t_s[300], t_s[300 + expected_samples - 1])

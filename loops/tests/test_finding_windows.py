"""Tests for crosscut_loops.finding_windows.finding_window.

finding_window finds the longest contiguous stretch of samples matching a
quality code ("manual", "saturated", "flatline") and returns it as an inclusive
(start_s, end_s) pair, or None when nothing matches.
"""

import numpy as np
import pytest
from crosscut_loops.finding_windows import finding_window
from crosscut_loops.metrics import DEFAULT_MIN_FLAT_RUN

DT_S = 1.0


def _time_axis(n_samples: int, dt_s: float = DT_S) -> np.ndarray:
    """Return the sample timestamps of an n_samples-long run spaced by dt_s seconds."""
    return np.arange(n_samples) * dt_s


def test_manual_picks_the_longer_of_two_stretches():
    """Two manual stretches: the longer one wins."""
    t_s = _time_axis(8)
    manual = np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0])
    pv = np.zeros(8)
    out = np.zeros(8)

    window = finding_window("manual", t_s, pv, out, manual)

    assert window == (3.0, 5.0)


def test_saturated_detects_low_end_at_zero():
    """A run of out == 0 is saturated."""
    t_s = _time_axis(6)
    manual = np.zeros(6)
    pv = np.zeros(6)
    out = np.array([50.0, 0.0, 0.0, 0.0, 50.0, 50.0])

    window = finding_window("saturated", t_s, pv, out, manual)

    assert window == (1.0, 3.0)


def test_saturated_detects_high_end_at_one_hundred():
    """A run of out == 100 is saturated."""
    t_s = _time_axis(6)
    manual = np.zeros(6)
    pv = np.zeros(6)
    out = np.array([50.0, 100.0, 100.0, 100.0, 50.0, 50.0])

    window = finding_window("saturated", t_s, pv, out, manual)

    assert window == (1.0, 3.0)


def test_flatline_shorter_than_min_run_returns_none():
    """A repeated value that does not reach DEFAULT_MIN_FLAT_RUN yields no window."""
    n_samples = DEFAULT_MIN_FLAT_RUN - 1
    t_s = _time_axis(n_samples)
    manual = np.zeros(n_samples)
    pv = np.zeros(n_samples)
    out = np.zeros(n_samples)

    window = finding_window("flatline", t_s, pv, out, manual)

    assert window is None


def test_flatline_run_exactly_min_run_long_returns_its_window():
    """A repeated value of exactly DEFAULT_MIN_FLAT_RUN samples is a flatline run."""
    n_samples = DEFAULT_MIN_FLAT_RUN
    t_s = _time_axis(n_samples)
    manual = np.zeros(n_samples)
    pv = np.full(n_samples, 7.0)
    out = np.full(n_samples, 50.0)

    window = finding_window("flatline", t_s, pv, out, manual)

    assert window == (0.0, float(n_samples - 1))


def test_unknown_code_returns_none():
    """A code that names no rule yields no window."""
    t_s = _time_axis(4)
    manual = np.ones(4)
    pv = np.zeros(4)
    out = np.zeros(4)

    window = finding_window("teleport", t_s, pv, out, manual)

    assert window is None


def test_empty_arrays_return_none():
    """No samples means no window."""
    t_s = _time_axis(0)
    manual = np.zeros(0)
    pv = np.zeros(0)
    out = np.zeros(0)

    window = finding_window("manual", t_s, pv, out, manual)

    assert window is None


def test_length_mismatch_raises_value_error():
    """Arrays of different lengths cannot be aligned sample by sample."""
    t_s = _time_axis(4)
    manual = np.zeros(3)
    pv = np.zeros(4)
    out = np.zeros(4)

    with pytest.raises(ValueError):
        finding_window("manual", t_s, pv, out, manual)


def test_nan_breaks_a_manual_run():
    """A NaN sample never belongs to a run, so it splits the stretch."""
    t_s = _time_axis(6)
    manual = np.array([0.0, np.nan, 0.0, 0.0, 0.0, 0.0])
    pv = np.zeros(6)
    out = np.zeros(6)

    window = finding_window("manual", t_s, pv, out, manual)

    assert window == (2.0, 5.0)


def test_nan_breaks_a_saturated_run():
    """A NaN reading is not saturated, so it splits the stretch."""
    t_s = _time_axis(5)
    manual = np.zeros(5)
    pv = np.zeros(5)
    out = np.array([0.0, 0.0, np.nan, 0.0, 0.0])

    window = finding_window("saturated", t_s, pv, out, manual)

    assert window == (0.0, 1.0)


def test_a_stretch_running_to_the_last_sample_ends_there():
    """A run that reaches the end of the record stops at the final timestamp."""
    t_s = _time_axis(6)
    manual = np.array([1.0, 1.0, 0.0, 0.0, 0.0, 0.0])
    pv = np.zeros(6)
    out = np.zeros(6)

    window = finding_window("manual", t_s, pv, out, manual)

    assert window == (2.0, 5.0)


def test_a_one_sample_manual_stretch_gives_an_instantaneous_window():
    """A single matching sample spans zero time: start equals end."""
    t_s = _time_axis(4, dt_s=5.0)
    manual = np.array([1.0, 1.0, 0.0, 1.0])
    pv = np.zeros(4)
    out = np.zeros(4)

    window = finding_window("manual", t_s, pv, out, manual)

    assert window == (10.0, 10.0)


def test_non_unit_sample_spacing_uses_seconds_from_t_s():
    """With dt = 5 s the window is reported on the given time axis, not on indices."""
    t_s = _time_axis(6, dt_s=5.0)
    manual = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    pv = np.zeros(6)
    out = np.zeros(6)

    window = finding_window("manual", t_s, pv, out, manual)

    assert window == (0.0, 10.0)


def test_a_4_to_20_ma_output_flags_only_the_sample_at_four_as_saturated():
    """With the loop's own range 4..20 the margin is 0.08, so only the 4.0 sample is pinned."""
    t_s = _time_axis(3)
    manual = np.zeros(3)
    pv = np.zeros(3)
    out = np.array([4.0, 4.2, 4.1])

    window = finding_window("saturated", t_s, pv, out, manual, out_low=4.0, out_high=20.0)

    assert window == (0.0, 0.0)


def test_the_default_0_to_100_range_does_not_flag_a_4_to_20_output_near_its_bottom():
    """The default range has a 2.0 margin, so a 4 mA loop at 4.0 is not reported as saturated.

    This is why the range must be passed for a loop whose output does not span 0..100.
    """
    t_s = _time_axis(3)
    manual = np.zeros(3)
    pv = np.zeros(3)
    out = np.array([4.0, 4.2, 4.1])

    window = finding_window("saturated", t_s, pv, out, manual)

    assert window is None

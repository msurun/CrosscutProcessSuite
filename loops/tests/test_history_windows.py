"""Tests for crosscut_loops.history_windows.find_excitation_windows.

The function scans SP/PV histories for setpoint steps that the PV actually
follows and returns the sample ranges (windows) around each step, which a
later stage uses to fit local models. These tests pin the window geometry
and the step-detection rules.
"""

import numpy as np
import pytest
from crosscut_loops.history_windows import (
    WindowSettings,
    find_excitation_windows,
)

# --- Defaults mirrored here so the tests state the numbers they rely on ---
SAMPLE_TIME_S = 1.0
HISTORY_LENGTH = 1100
NOISE_STD = 0.05
PV_LAG_POLE = 0.05  # first-order lag pole per sample
SP_LOW = 50.0
SP_HIGH = 55.0
FIRST_STEP_INDEX = 300
SECOND_STEP_INDEX = 700
PRE_SAMPLES = 20

RAMP_START_INDEX = 300
RAMP_RISE_PER_SAMPLE = 0.5
RAMP_LENGTH = 10

MERGE_FIRST_STEP_INDEX = 300
MERGE_GAP_SAMPLES = 3


def build_step_history() -> tuple[np.ndarray, np.ndarray]:
    """Return (sp, pv) with SP stepping 50->55->50 and PV a lagged noisy copy."""
    sp = np.full(HISTORY_LENGTH, SP_LOW)
    sp[FIRST_STEP_INDEX:SECOND_STEP_INDEX] = SP_HIGH
    pv = _first_order_lag(sp)
    pv = pv + np.random.default_rng(0).normal(0.0, NOISE_STD, HISTORY_LENGTH)
    return sp, pv


def _first_order_lag(signal: np.ndarray) -> np.ndarray:
    """Return a first-order lag of signal, y[k] = y[k-1] + pole*(x[k-1]-y[k-1])."""
    lagged = np.empty_like(signal)
    lagged[0] = signal[0]
    for sample in range(1, signal.size):
        lagged[sample] = lagged[sample - 1] + PV_LAG_POLE * (
            signal[sample - 1] - lagged[sample - 1]
        )
    return lagged


def test_two_setpoint_steps_produce_two_windows():
    """A down-up SP sequence yields exactly two windows, one per step."""
    sp, pv = build_step_history()
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S)
    assert len(windows) == 2


def test_step_sizes_are_signed_in_sp_units():
    """The first step is +5, the second -5, both signed SP units."""
    sp, pv = build_step_history()
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S)
    assert windows[0].step_size == pytest.approx(SP_HIGH - SP_LOW)
    assert windows[1].step_size == pytest.approx(SP_LOW - SP_HIGH)


def test_window_starts_before_the_step():
    """Each window opens about pre_samples samples before its step."""
    sp, pv = build_step_history()
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S)
    assert windows[0].start == FIRST_STEP_INDEX - PRE_SAMPLES


def test_windows_do_not_overlap():
    """The stop of one window is at or before the start of the next."""
    sp, pv = build_step_history()
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S)
    assert windows[0].stop <= windows[1].start


def test_windows_are_settled():
    """With ample time after each step the PV settles, so both are settled."""
    sp, pv = build_step_history()
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S)
    assert all(window.settled for window in windows)


def test_constant_setpoint_gives_no_windows():
    """A flat SP is not excitation and produces an empty list."""
    sp = np.full(HISTORY_LENGTH, SP_LOW)
    pv = _first_order_lag(sp)
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S)
    assert windows == []


def test_step_below_noise_threshold_is_ignored():
    """A step inside the noise band must not be reported."""
    sp = np.full(HISTORY_LENGTH, SP_LOW)
    below_noise = SP_LOW + NOISE_STD * 0.5
    sp[FIRST_STEP_INDEX:] = below_noise
    pv = _first_order_lag(sp) + np.random.default_rng(0).normal(0.0, NOISE_STD, HISTORY_LENGTH)
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S)
    assert windows == []


def test_ramp_counts_as_one_event():
    """A short SP ramp is a single event, not one per sample."""
    sp = np.full(HISTORY_LENGTH, SP_LOW)
    rise = [RAMP_RISE_PER_SAMPLE * (i + 1) for i in range(RAMP_LENGTH)]
    sp[RAMP_START_INDEX : RAMP_START_INDEX + RAMP_LENGTH] = SP_LOW + np.array(rise)
    sp[RAMP_START_INDEX + RAMP_LENGTH :] = SP_LOW + RAMP_RISE_PER_SAMPLE * RAMP_LENGTH
    pv = _first_order_lag(sp)
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S)
    assert len(windows) == 1


def test_close_steps_merge_into_one_event():
    """Two steps only a few samples apart are reported as one window."""
    sp = np.full(HISTORY_LENGTH, SP_LOW)
    sp[MERGE_FIRST_STEP_INDEX:] = SP_HIGH
    sp[MERGE_FIRST_STEP_INDEX + MERGE_GAP_SAMPLES :] = SP_LOW
    pv = _first_order_lag(sp)
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S)
    assert len(windows) == 1


def test_window_length_within_max_samples():
    """No window longer than the configured max_samples."""
    settings = WindowSettings(max_samples=200)
    sp, pv = build_step_history()
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S, settings=settings)
    assert all(window.stop - window.start <= settings.max_samples for window in windows)


def test_window_does_not_pass_next_event():
    """A window stops before the next event's start."""
    settings = WindowSettings(max_samples=5000)
    sp, pv = build_step_history()
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S, settings=settings)
    assert windows[0].stop <= windows[1].start


def test_nan_gaps_are_interpolated():
    """A few percent of NaN samples are bridged and windows still return."""
    sp, pv = build_step_history()
    nan_count = int(HISTORY_LENGTH * 0.05)
    gap_indices = np.random.default_rng(1).choice(HISTORY_LENGTH, nan_count, replace=False)
    pv[gap_indices] = np.nan
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S)
    assert len(windows) == 2


def test_length_mismatch_raises_value_error():
    """SP and PV of different lengths is a caller bug."""
    sp = np.full(HISTORY_LENGTH, SP_LOW)
    pv = np.full(HISTORY_LENGTH - 1, SP_LOW)
    with pytest.raises(ValueError):
        find_excitation_windows(sp, pv, SAMPLE_TIME_S)


def test_non_positive_sample_time_raises_value_error():
    """A non-positive sample time is meaningless and must raise."""
    sp = np.full(HISTORY_LENGTH, SP_LOW)
    pv = np.full(HISTORY_LENGTH, SP_LOW)
    with pytest.raises(ValueError):
        find_excitation_windows(sp, pv, 0.0)


def test_too_many_nan_raises_value_error():
    """More than 20 percent NaN samples cannot be reliably interpolated."""
    sp = np.full(HISTORY_LENGTH, SP_LOW)
    pv = np.full(HISTORY_LENGTH, SP_LOW)
    pv[: int(HISTORY_LENGTH * 0.3)] = np.nan
    with pytest.raises(ValueError):
        find_excitation_windows(sp, pv, SAMPLE_TIME_S)


def test_returned_types_are_plain_scalars():
    """Fields are plain int/bool so callers can serialise them."""
    sp, pv = build_step_history()
    windows = find_excitation_windows(sp, pv, SAMPLE_TIME_S)
    window = windows[0]
    assert type(window.start) is int
    assert type(window.stop) is int
    assert type(window.settled) is bool

"""
Behaviour tests for crosscut_loops.step_events.

Synthetic historian records only (fixed-seed numpy rng): one behaviour per
test, arranged with explicit signals, then act, then assert.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.step_events import (
    AUTO_MODE,
    MANUAL_MODE,
    OUT_STEP_KIND,
    SP_STEP_KIND,
    WINDOW_TOO_SHORT_REASON,
    SkippedEvent,
    StepEvent,
    find_step_events,
    robust_noise_sd,
)

DT_S = 10.0
NUM_SAMPLES = 400

# Noise levels chosen to sit far below the 3-sigma detection thresholds so the
# injected steps dominate the median difference.
OUT_NOISE_SD = 0.02
PV_NOISE_SD = 0.1
SP_NOISE_SD = 0.0  # a setpoint is piecewise constant: noise on it would be spurious steps

# Tolerances on detected step sizes; the median filter preserves a clean step
# but SP merging sums noisy differences, so allow a couple of units.
OUT_SIZE_TOLERANCE = 0.5
SP_SIZE_TOLERANCE = 0.5


def _time_axis(num_samples: int = NUM_SAMPLES, dt_s: float = DT_S) -> np.ndarray:
    """Regular sample times in seconds, starting at zero."""
    return np.arange(num_samples, dtype=float) * dt_s


def _noise(rng: np.random.Generator, size: int, sd: float) -> np.ndarray:
    """White Gaussian noise with the requested standard deviation."""
    return rng.normal(0.0, sd, size)


def _out_step_at(num_samples: int, event_index: int, step_size: float, base: float) -> np.ndarray:
    """OUT samples: held at base, then at base + step_size from event_index on."""
    out = np.full(num_samples, base)
    out[event_index:] += step_size
    return out


def _sp_step_at(num_samples: int, event_index: int, step_size: float, base: float) -> np.ndarray:
    """SP samples: held at base, then at base + step_size from event_index on."""
    sp = np.full(num_samples, base)
    sp[event_index:] += step_size
    return sp


def _run_record(
    out: np.ndarray,
    sp: np.ndarray,
    pv: np.ndarray,
    mode: np.ndarray,
    t_s: np.ndarray | None = None,
) -> tuple[list[StepEvent], list[SkippedEvent]]:
    """Call find_step_events with the standard time axis unless overridden."""
    times = _time_axis(out.size) if t_s is None else t_s
    return find_step_events(times, pv, sp, out, mode, DT_S)


def _find_out_event(events: list[StepEvent]) -> StepEvent:
    """Return the single out_step event; fail loudly if the count is not one."""
    out_events = [event for event in events if event.kind == OUT_STEP_KIND]
    assert len(out_events) == 1, f"expected one out_step, got {len(out_events)}"
    return out_events[0]


def test_a_manual_out_step_is_reported_with_a_positive_size() -> None:
    rng = np.random.default_rng(seed=1)
    out = _out_step_at(NUM_SAMPLES, 120, step_size=7.0, base=40.0)
    out += _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = np.full(NUM_SAMPLES, 50.0)
    mode = np.full(NUM_SAMPLES, MANUAL_MODE)

    events, _skipped = _run_record(out, sp, pv, mode)

    event = _find_out_event(events)
    assert abs(event.i - 120) <= 2
    assert event.size == pytest.approx(7.0, abs=OUT_SIZE_TOLERANCE)
    assert event.mode == "manual"


def test_a_manual_out_step_keeps_the_pre_window_at_least_ten_samples() -> None:
    rng = np.random.default_rng(seed=2)
    out = _out_step_at(NUM_SAMPLES, 120, step_size=7.0, base=40.0)
    out += _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = np.full(NUM_SAMPLES, 50.0)
    mode = np.full(NUM_SAMPLES, MANUAL_MODE)

    events, _skipped = _run_record(out, sp, pv, mode)

    event = _find_out_event(events)
    assert event.pre >= 10
    assert event.i0 >= 0
    assert event.i1 <= NUM_SAMPLES


def test_two_far_apart_out_steps_are_both_found_in_index_order() -> None:
    rng = np.random.default_rng(seed=3)
    out = _out_step_at(NUM_SAMPLES, 100, step_size=5.0, base=40.0)
    out[200:] += 5.0
    out += _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = np.full(NUM_SAMPLES, 50.0)
    mode = np.full(NUM_SAMPLES, MANUAL_MODE)

    events, _skipped = _run_record(out, sp, pv, mode)

    out_indices = [event.i for event in events if event.kind == OUT_STEP_KIND]
    assert len(out_indices) == 2
    assert out_indices == sorted(out_indices)
    assert abs(out_indices[0] - 100) <= 2
    assert abs(out_indices[1] - 200) <= 2


def test_two_out_steps_thirty_samples_apart_are_two_events() -> None:
    rng = np.random.default_rng(seed=4)
    out = _out_step_at(NUM_SAMPLES, 150, step_size=5.0, base=40.0)
    out[180:] += 5.0
    out += _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = np.full(NUM_SAMPLES, 50.0)
    mode = np.full(NUM_SAMPLES, MANUAL_MODE)

    events, _skipped = _run_record(out, sp, pv, mode)

    out_events = [event for event in events if event.kind == OUT_STEP_KIND]
    assert len(out_events) == 2


def test_out_chatter_of_plus_minus_point_three_produces_no_event() -> None:
    rng = np.random.default_rng(seed=5)
    # Alternate between 40 and 40.3 every 20 samples: well below the 1.0 OUT
    # minimum step size, so nothing may be detected.
    out = np.full(NUM_SAMPLES, 40.0)
    out[(np.arange(NUM_SAMPLES) // 20) % 2 == 1] += 0.3
    out += _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = np.full(NUM_SAMPLES, 50.0)
    mode = np.full(NUM_SAMPLES, MANUAL_MODE)

    events, _skipped = _run_record(out, sp, pv, mode)

    assert events == []


def test_an_auto_sp_step_is_reported_as_one_auto_event() -> None:
    rng = np.random.default_rng(seed=6)
    out = np.full(NUM_SAMPLES, 40.0) + _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = _sp_step_at(NUM_SAMPLES, 150, step_size=3.0, base=50.0)
    sp += _noise(rng, NUM_SAMPLES, SP_NOISE_SD)
    mode = np.full(NUM_SAMPLES, AUTO_MODE)

    events, _skipped = _run_record(out, sp, pv, mode)

    sp_events = [event for event in events if event.kind == SP_STEP_KIND]
    assert len(sp_events) == 1
    assert sp_events[0].size == pytest.approx(3.0, abs=SP_SIZE_TOLERANCE)
    assert sp_events[0].mode == "auto"


def test_an_auto_sp_change_below_three_sigma_produces_no_event() -> None:
    rng = np.random.default_rng(seed=7)
    out = np.full(NUM_SAMPLES, 40.0) + _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = _sp_step_at(NUM_SAMPLES, 150, step_size=0.2, base=50.0)
    sp += _noise(rng, NUM_SAMPLES, SP_NOISE_SD)
    mode = np.full(NUM_SAMPLES, AUTO_MODE)

    events, _skipped = _run_record(out, sp, pv, mode)

    assert events == []


def test_sp_changes_within_sixty_seconds_merge_with_summed_size() -> None:
    rng = np.random.default_rng(seed=8)
    out = np.full(NUM_SAMPLES, 40.0) + _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    # Two 1.5-unit SP moves 30 s apart (3 samples at DT_S = 10 s) merge into
    # one event of about +3.
    sp = _sp_step_at(NUM_SAMPLES, 150, step_size=1.5, base=50.0)
    sp[153:] += 1.5
    sp += _noise(rng, NUM_SAMPLES, SP_NOISE_SD)
    mode = np.full(NUM_SAMPLES, AUTO_MODE)

    events, _skipped = _run_record(out, sp, pv, mode)

    sp_events = [event for event in events if event.kind == SP_STEP_KIND]
    assert len(sp_events) == 1
    assert sp_events[0].size == pytest.approx(3.0, abs=SP_SIZE_TOLERANCE)


def test_an_out_step_in_auto_mode_is_not_reported_as_out_step() -> None:
    rng = np.random.default_rng(seed=9)
    out = _out_step_at(NUM_SAMPLES, 150, step_size=7.0, base=40.0)
    out += _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = np.full(NUM_SAMPLES, 50.0)
    mode = np.full(NUM_SAMPLES, AUTO_MODE)

    events, _skipped = _run_record(out, sp, pv, mode)

    assert [event for event in events if event.kind == OUT_STEP_KIND] == []


def test_an_sp_step_in_manual_mode_is_not_reported() -> None:
    rng = np.random.default_rng(seed=10)
    out = np.full(NUM_SAMPLES, 40.0) + _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = _sp_step_at(NUM_SAMPLES, 150, step_size=3.0, base=50.0)
    sp += _noise(rng, NUM_SAMPLES, SP_NOISE_SD)
    mode = np.full(NUM_SAMPLES, MANUAL_MODE)

    events, _skipped = _run_record(out, sp, pv, mode)

    assert [event for event in events if event.kind == SP_STEP_KIND] == []


def test_an_event_with_too_few_pre_samples_is_skipped() -> None:
    rng = np.random.default_rng(seed=11)
    out = _out_step_at(NUM_SAMPLES, 5, step_size=7.0, base=40.0)
    out += _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = np.full(NUM_SAMPLES, 50.0)
    mode = np.full(NUM_SAMPLES, MANUAL_MODE)

    _events, skipped = _run_record(out, sp, pv, mode)

    assert len(skipped) == 1
    assert skipped[0].reason == WINDOW_TOO_SHORT_REASON


def test_a_step_right_after_a_time_gap_is_skipped() -> None:
    rng = np.random.default_rng(seed=12)
    # Drop 20 samples' worth of time between index 150 and 151 (a gap of
    # 200 s, well over 5 * DT_S), then step immediately after the gap.
    t_s = _time_axis(NUM_SAMPLES)
    t_s[151:] += 200.0
    out = _out_step_at(NUM_SAMPLES, 151, step_size=7.0, base=40.0)
    out += _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = np.full(NUM_SAMPLES, 50.0)
    mode = np.full(NUM_SAMPLES, MANUAL_MODE)

    events, skipped = _run_record(out, sp, pv, mode, t_s=t_s)

    # A step at the very start of a segment has no pre-step block to compare with: no event.
    assert [event for event in events if abs(event.i - 151) <= 2] == []
    assert all(abs(entry.i - 151) > 2 or entry.reason for entry in skipped)


def test_an_event_window_does_not_cross_a_time_gap() -> None:
    rng = np.random.default_rng(seed=13)
    # Step at index 100, then a large time gap after index 150. The window of
    # the step must end at the last sample before the gap.
    t_s = _time_axis(NUM_SAMPLES)
    t_s[151:] += 200.0
    out = _out_step_at(NUM_SAMPLES, 100, step_size=7.0, base=40.0)
    out += _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = np.full(NUM_SAMPLES, 50.0)
    mode = np.full(NUM_SAMPLES, MANUAL_MODE)

    events, _skipped = _run_record(out, sp, pv, mode, t_s=t_s)

    event = _find_out_event(events)
    assert event.i1 <= 151


def test_a_nan_mode_sample_produces_no_event() -> None:
    rng = np.random.default_rng(seed=14)
    out = _out_step_at(NUM_SAMPLES, 150, step_size=7.0, base=40.0)
    out += _noise(rng, NUM_SAMPLES, OUT_NOISE_SD)
    pv = np.full(NUM_SAMPLES, 50.0) + _noise(rng, NUM_SAMPLES, PV_NOISE_SD)
    sp = np.full(NUM_SAMPLES, 50.0)
    mode = np.full(NUM_SAMPLES, np.nan)

    events, _skipped = _run_record(out, sp, pv, mode)

    assert events == []


def test_robust_noise_sd_of_white_noise_is_close_to_sigma() -> None:
    rng = np.random.default_rng(seed=15)
    sigma = 0.5
    signal = rng.normal(0.0, sigma, 5000)

    estimate = robust_noise_sd(signal)

    assert estimate == pytest.approx(sigma, rel=0.10)


def test_robust_noise_sd_of_short_signal_is_zero() -> None:
    signal = np.array([1.0, 2.0])

    estimate = robust_noise_sd(signal)

    assert estimate == 0.0

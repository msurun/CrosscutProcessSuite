"""
Tests for crosscut_loops.health_kpis: control-loop health indicators computed
from valve position and process value time series.
Covers valve travel, reversal counting, quantisation detection, sizing hints,
period clustering and Kendall trend detection on deterministic synthetic data.
"""

import numpy as np
import pytest
from crosscut_loops import health_kpis as h

SAMPLE_DT_S = 1.0  # sampling interval of the synthetic series (s)
ONE_HOUR_S = 3600.0  # length of the synthetic series (s)
FULL_TRAVEL_PCT = 100.0  # a 0..100 % valve span (percent points)
SQUARE_WAVE_LOW = 0.0  # low level of the square wave (percent open)
SQUARE_WAVE_HIGH = 10.0  # high level of the square wave (percent open)
SQUARE_WAVE_SWITCH_EVERY_S = 10.0  # half period of the square wave (s)
EXPECTED_TRAVEL_PCT = (
    ONE_HOUR_S / SQUARE_WAVE_SWITCH_EVERY_S * SQUARE_WAVE_HIGH / FULL_TRAVEL_PCT * 100.0
)  # 360 switches of 10 % per hour over a 100 % span
EXPECTED_REVERSALS = ONE_HOUR_S / SQUARE_WAVE_SWITCH_EVERY_S  # 360 switches
TOLERANCE = 1e-6
LOOSE_TOLERANCE = 0.01  # the first and last switch of the record are partial


def _square_wave(dt_s: float, duration_s: float) -> np.ndarray:
    """Return a 0/10 % square wave sampled every dt_s for duration_s."""
    times_s = np.arange(0.0, duration_s, dt_s)
    cycle = (times_s // SQUARE_WAVE_SWITCH_EVERY_S).astype(int)
    return np.where(cycle % 2 == 0, SQUARE_WAVE_LOW, SQUARE_WAVE_HIGH)


def _sine_series(amplitude: float, dt_s: float, duration_s: float) -> np.ndarray:
    """Return a 1-cycle-per-hour sine of the given amplitude sampled every dt_s."""
    times_s = np.arange(0.0, duration_s, dt_s)
    return amplitude * np.sin(2.0 * np.pi * times_s / ONE_HOUR_S)


def test_square_wave_travel_per_hour_matches_expected_value():
    """A 0/10 % square wave switching every 10 s travels 20 % per hour."""
    series = _square_wave(SAMPLE_DT_S, ONE_HOUR_S)

    travel = h.valve_travel_per_hour(series, SAMPLE_DT_S, out_span=FULL_TRAVEL_PCT)

    assert travel == pytest.approx(EXPECTED_TRAVEL_PCT, rel=LOOSE_TOLERANCE)


def test_square_wave_reversals_per_hour_matches_switch_count():
    """The 0/10 % square wave switches direction 360 times per hour."""
    series = _square_wave(SAMPLE_DT_S, ONE_HOUR_S)

    reversals = h.reversals_per_hour(series, SAMPLE_DT_S, min_move=1.0)

    assert reversals == pytest.approx(EXPECTED_REVERSALS, rel=LOOSE_TOLERANCE)


def test_sine_above_hysteresis_counts_reversals():
    """A sine whose amplitude exceeds min_move produces two reversals per hour."""
    series = _sine_series(amplitude=20.0, dt_s=SAMPLE_DT_S, duration_s=ONE_HOUR_S)

    reversals = h.reversals_per_hour(series, SAMPLE_DT_S, min_move=5.0)

    assert reversals == pytest.approx(2.0, rel=1e-2)


def test_sine_below_hysteresis_is_ignored():
    """A sine whose amplitude is below min_move shows no reversals."""
    series = _sine_series(amplitude=1.0, dt_s=SAMPLE_DT_S, duration_s=ONE_HOUR_S)

    reversals = h.reversals_per_hour(series, SAMPLE_DT_S, min_move=5.0)

    assert reversals == 0.0


def test_nan_samples_are_ignored():
    """NaN samples do not contribute to travel."""
    series = np.array([0.0, 10.0, np.nan, 0.0, 10.0])
    dt_s = 1.0

    travel = h.valve_travel_per_hour(series, dt_s, out_span=FULL_TRAVEL_PCT)

    clean = np.array([0.0, 10.0, 0.0, 10.0])
    expected = h.valve_travel_per_hour(clean, dt_s, out_span=FULL_TRAVEL_PCT)
    assert travel == pytest.approx(expected, rel=TOLERANCE)


def test_zero_dt_raises_value_error():
    """A non-positive sampling interval is invalid."""
    with pytest.raises(ValueError):
        h.valve_travel_per_hour(np.zeros(10), dt_s=0.0)


def test_non_positive_out_span_raises_value_error():
    """A non-positive output span is invalid."""
    with pytest.raises(ValueError):
        h.valve_travel_per_hour(np.zeros(10), dt_s=1.0, out_span=-1.0)


def test_negative_min_move_raises_value_error():
    """A negative reversal hysteresis is invalid."""
    with pytest.raises(ValueError):
        h.reversals_per_hour(np.zeros(10), dt_s=1.0, min_move=-0.5)


def test_too_few_trend_points_raises_value_error():
    """kendall_trend rejects min_points below three."""
    with pytest.raises(ValueError):
        h.kendall_trend(np.arange(10), min_points=2)


def test_quantisation_step_of_rounded_walk_is_the_step():
    """Rounding a random walk to 0.1 yields a quantisation step of 0.1."""
    rng = np.random.default_rng(seed=42)
    walk = np.cumsum(rng.normal(0.0, 1.0, 500))
    rounded = np.round(walk, 1)

    step = h.quantisation_step(rounded)

    assert step == pytest.approx(0.1, rel=1e-6)


def test_quantisation_ratio_below_one_for_fine_signal():
    """A signal whose increment spread dominates its step is not limiting."""
    rng = np.random.default_rng(seed=7)
    fine = rng.normal(0.0, 5.0, 2000)

    ratio = h.quantisation_ratio(fine)

    assert ratio < h.QUANTISATION_LIMITING


def test_quantisation_ratio_above_one_for_coarse_rounding():
    """Rounding a low-noise signal to a coarse step flags quantisation as limiting."""
    rng = np.random.default_rng(seed=3)
    walk = 50.0 + np.cumsum(rng.normal(0.0, 0.3, 2000))
    coarse = np.round(walk, 0)

    ratio = h.quantisation_ratio(coarse)

    assert ratio > h.QUANTISATION_LIMITING


def test_quantisation_step_is_nan_when_too_few_increments():
    """Fewer than twenty non-zero increments cannot define a step."""
    short = np.array([0.0, 1.0, 2.0, 2.0])

    step = h.quantisation_step(short)

    assert np.isnan(step)


def test_valve_extremes_hint_oversized_for_small_median():
    """A valve spending time near 10 % travel is oversized."""
    operation = np.full(100, 10.0)

    extremes = h.valve_extremes(operation)

    assert extremes.sizing_hint == "oversized"


def test_valve_extremes_hint_is_none_for_mid_median():
    """A valve centred around 50 % is well sized."""
    operation = np.full(100, 50.0)

    extremes = h.valve_extremes(operation)

    assert extremes.sizing_hint is None


def test_valve_extremes_hint_undersized_for_large_median():
    """A valve operating near 90 % travel is undersized."""
    operation = np.full(100, 90.0)

    extremes = h.valve_extremes(operation)

    assert extremes.sizing_hint == "undersized"


def test_group_by_period_forms_two_clusters():
    """Periods 100/105 and 300/310 collapse into two clusters, invalid entries ignored."""
    periods = {
        "a": 100.0,
        "b": 105.0,
        "c": 300.0,
        "d": 310.0,
        "e": None,
        "f": float("nan"),
        "g": 0.0,
    }

    clusters = h.group_by_period(periods)

    assert len(clusters) == 2
    assert clusters[0] == ["a", "b"]
    assert clusters[1] == ["c", "d"]


def test_kendall_trend_increasing_series_is_worsening_when_higher_is_worse():
    """A steadily rising series with higher_is_worse reports worsening."""
    values = np.arange(10, dtype=float)

    trend = h.kendall_trend(values, higher_is_worse=True)

    assert trend.direction == "worsening"


def test_kendall_trend_increasing_series_is_improving_when_higher_is_better():
    """The same rising series reports improving when higher is better."""
    values = np.arange(10, dtype=float)

    trend = h.kendall_trend(values, higher_is_worse=False)

    assert trend.direction == "improving"


def test_kendall_trend_noise_is_flat():
    """White noise has no monotone trend and is reported flat."""
    rng = np.random.default_rng(seed=1)
    noise = rng.normal(0.0, 1.0, 200)

    trend = h.kendall_trend(noise)

    assert trend.direction == "flat"


def test_kendall_trend_flat_when_too_few_points():
    """Fewer than min_points observations cannot define a trend."""
    trend = h.kendall_trend(np.array([1.0, 2.0, 3.0]), min_points=6)

    assert trend.direction == "flat"

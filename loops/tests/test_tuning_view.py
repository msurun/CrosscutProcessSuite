"""Behaviour of the tuning screen numerics: model check, step preview, window hints."""

from __future__ import annotations

import time

import numpy as np
import pytest
from crosscut_loops.tuning_rules import FopdtModel, lambda_from_robustness, simc_pi
from crosscut_loops.tuning_view import (
    StepPreview,
    _run_pi_loop,
    closed_loop_step,
    fit_check,
    simulate_fopdt,
    suggest_windows,
)

MODEL = FopdtModel(gain=2.0, time_constant_s=30.0, delay_s=10.0)
DT_S = 1.0
N_SAMPLES = 600
STEP_INDEX = 100
STEP_PCT = 10.0
Y0_PCT = 50.0


def _step_input() -> np.ndarray:
    """Constant input that jumps from 0 to STEP_PCT at STEP_INDEX."""
    controller_output = np.zeros(N_SAMPLES)
    controller_output[STEP_INDEX:] = STEP_PCT
    return controller_output


def test_a_constant_input_leaves_the_output_at_the_starting_value():
    """With no input move the simulated PV must stay at its start, so the preview shows no
    phantom response."""
    controller_output = np.full(N_SAMPLES, 40.0)
    pv = simulate_fopdt(MODEL, controller_output, DT_S, Y0_PCT)
    assert np.all(pv == pytest.approx(Y0_PCT))


def test_the_output_does_not_move_before_the_delay_has_passed():
    """The PV must stay flat for the whole dead time after a step, as a real transport delay
    does."""
    pv = simulate_fopdt(MODEL, _step_input(), DT_S, Y0_PCT)
    assert pv[: STEP_INDEX + 10] == pytest.approx(Y0_PCT)


def test_the_output_settles_at_the_gain_times_the_step():
    """After a step the PV must settle at gain times step, the defining steady-state property."""
    pv = simulate_fopdt(MODEL, _step_input(), DT_S, Y0_PCT)
    final_change = MODEL.gain * STEP_PCT
    assert pv[-1] == pytest.approx(Y0_PCT + final_change, abs=0.25)


def test_the_output_has_reached_63_percent_one_time_constant_past_the_delay():
    """One time constant after the delay the response must be at 63 percent, which fixes the
    time-constant meaning."""
    pv = simulate_fopdt(MODEL, _step_input(), DT_S, Y0_PCT)
    final_change = MODEL.gain * STEP_PCT
    index = STEP_INDEX + int(MODEL.delay_s) + int(MODEL.time_constant_s)
    reached = (pv[index] - Y0_PCT) / final_change
    assert reached == pytest.approx(0.63, abs=0.03)


def test_a_model_that_reproduces_the_data_is_called_good():
    """A model that matches the noisy data must get a good verdict and R2 above 0.95, so users
    trust good fits."""
    controller_output = _step_input()
    process_value = simulate_fopdt(MODEL, controller_output, DT_S, Y0_PCT)
    process_value = process_value + np.random.default_rng(0).normal(
        0.0, 0.05, size=len(process_value)
    )
    check, simulated = fit_check(MODEL, controller_output, process_value, DT_S)
    assert check.verdict == "good"
    assert check.r_squared > 0.95
    assert len(simulated) == len(process_value)


def test_a_model_with_the_wrong_gain_is_called_poor():
    """A model with the wrong gain must be called poor, warning the user not to tune from it."""
    controller_output = _step_input()
    process_value = simulate_fopdt(MODEL, controller_output, DT_S, Y0_PCT)
    wrong = FopdtModel(gain=0.2, time_constant_s=MODEL.time_constant_s, delay_s=MODEL.delay_s)
    check, _ = fit_check(wrong, controller_output, process_value, DT_S)
    assert check.verdict == "poor"


def test_a_constant_measurement_gives_zero_r_squared():
    """A constant measurement has no variance to explain, so R2 must be zero instead of
    dividing by zero."""
    controller_output = _step_input()
    process_value = np.full(N_SAMPLES, Y0_PCT)
    check, _ = fit_check(MODEL, controller_output, process_value, DT_S)
    assert check.r_squared == pytest.approx(0.0)


def _preview_for(robustness: float) -> StepPreview:
    """Preview of the SIMC-tuned loop for one robustness value."""
    settings = simc_pi(MODEL, lambda_from_robustness(MODEL, robustness))
    return closed_loop_step(MODEL, settings)


def test_the_preview_settles_on_the_unit_setpoint():
    """The SIMC-tuned loop must settle at the unit setpoint, otherwise the preview misleads the
    user."""
    preview = _preview_for(0.5)
    assert preview.pv[-1] == pytest.approx(1.0, rel=0.02)


def test_the_preview_keeps_the_overshoot_modest():
    """The default tuning must not overshoot by more than 30 percent in the preview."""
    preview = _preview_for(0.5)
    assert float(np.max(preview.pv)) <= 1.3


def test_the_preview_arrays_have_equal_length_and_a_rising_time_axis():
    """The preview arrays must align and have a strictly rising time axis of at most 200 points
    so the chart draws correctly."""
    preview = _preview_for(0.5)
    assert len(preview.t_s) == len(preview.pv) == len(preview.out)
    assert len(preview.t_s) <= 200
    assert preview.t_s[0] == 0.0
    assert np.all(np.diff(preview.t_s) > 0.0)


def test_the_initial_controller_output_is_the_proportional_kick():
    """At t = 0 the controller output must be about Kc times the setpoint step (the
    proportional kick)."""
    # The first OUT sample at t = 0 also carries the integral gathered over one step of dt.
    settings = simc_pi(MODEL, lambda_from_robustness(MODEL, 0.5))
    preview = closed_loop_step(MODEL, settings)
    assert preview.out[0] > 0.0
    assert preview.out[0] == pytest.approx(settings.kc, rel=0.1)


def _time_to_reach_90_percent(robustness: float) -> float:
    """First preview time at which the PV has covered 90 % of the setpoint."""
    preview = _preview_for(robustness)
    reached = preview.t_s[preview.pv >= 0.9]
    return float(reached[0])


def test_a_more_robust_setting_reaches_the_setpoint_later():
    """A higher robustness must slow the response, which is the trade-off the slider promises."""
    assert _time_to_reach_90_percent(1.0) > _time_to_reach_90_percent(0.0)


def test_an_extreme_tau_to_delay_ratio_returns_quickly_with_bounded_arrays():
    """A huge time constant with a small delay must not hang the preview."""
    model = FopdtModel(gain=1.0, time_constant_s=1e6, delay_s=1.0)
    settings = simc_pi(model, lambda_from_robustness(model, 0.5))
    started = time.perf_counter()
    preview = closed_loop_step(model, settings)
    assert time.perf_counter() - started < 2.0
    assert len(preview.pv) <= 200
    assert len(preview.t_s) == len(preview.pv) == len(preview.out)
    assert np.all(np.isfinite(preview.pv))


def test_an_ordinary_model_keeps_the_uncapped_step_and_result():
    """For ordinary models the cap must not engage: the result equals the old-formula run."""
    settings = simc_pi(MODEL, lambda_from_robustness(MODEL, 0.5))
    old_dt_s = min(MODEL.time_constant_s, MODEL.delay_s) / 10
    n_steps = int(np.ceil(6.0 * (MODEL.time_constant_s + MODEL.delay_s) / old_dt_s))
    pv, out = _run_pi_loop(MODEL, settings, old_dt_s, n_steps)
    keep = np.linspace(0, n_steps - 1, min(200, n_steps)).astype(int)
    preview = closed_loop_step(MODEL, settings)
    assert preview.t_s == pytest.approx(keep * old_dt_s)
    assert preview.pv == pytest.approx(pv[keep])
    assert preview.out == pytest.approx(out[keep])


AUTO_MODE = 1.0
MANUAL_MODE = 0.0
MIN_LENGTH_S = 300.0


def _manual_stretch() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """7200 s of data: one MAN stretch from 600 s to 5000 s with an OUT step and back."""
    t_s = np.arange(0, 7200, 1.0)
    mode = np.full(len(t_s), AUTO_MODE)
    mode[600:5001] = MANUAL_MODE
    out = np.full(len(t_s), 50.0)
    out[1500:2700] = 58.0
    return t_s, mode, out


def test_the_manual_stretch_is_trimmed_to_lead_and_tail():
    """The suggested window must trim the lead and tail of a manual stretch so the settled
    parts are excluded."""
    t_s, mode, out = _manual_stretch()
    windows = suggest_windows(t_s, mode, out, MIN_LENGTH_S)
    assert len(windows) == 1
    start, end = windows[0]
    assert start == pytest.approx(1200.0, abs=5.0)
    assert end == pytest.approx(3600.0, abs=5.0)


def test_a_manual_stretch_without_output_movement_gives_no_window():
    """A manual stretch without an OUT move holds no identification information and must not be
    suggested."""
    t_s = np.arange(0, 7200, 1.0)
    mode = np.full(len(t_s), MANUAL_MODE)
    out = np.full(len(t_s), 50.0)
    assert suggest_windows(t_s, mode, out, MIN_LENGTH_S) == []


def test_a_manual_stretch_shorter_than_the_minimum_gives_no_window():
    """A stretch shorter than the minimum length is too short to identify and must be skipped."""
    t_s, mode, out = _manual_stretch()
    assert suggest_windows(t_s, mode, out, min_length_s=5000.0) == []


def test_the_stretch_with_the_bigger_output_movement_comes_first():
    """Windows must be ordered by output movement so the most informative one is offered first."""
    # Two MAN stretches: 600..2000 s moves OUT by 6 %, 3000..4400 s moves it by 20 %.
    t_s = np.arange(0, 7200, 1.0)
    mode = np.full(len(t_s), AUTO_MODE)
    mode[600:2001] = MANUAL_MODE
    mode[3000:4401] = MANUAL_MODE
    out = np.full(len(t_s), 50.0)
    out[1000:1400] = 56.0
    out[3500:3900] = 70.0
    windows = suggest_windows(t_s, mode, out, MIN_LENGTH_S)
    assert len(windows) == 2
    assert windows[0][0] == pytest.approx(3200.0, abs=5.0)


def test_an_automatic_only_trend_gives_no_window():
    """A trend entirely in automatic has no open-loop data and must give no window."""
    t_s = np.arange(0, 7200, 1.0)
    mode = np.full(len(t_s), AUTO_MODE)
    out = np.full(len(t_s), 50.0)
    assert suggest_windows(t_s, mode, out, MIN_LENGTH_S) == []

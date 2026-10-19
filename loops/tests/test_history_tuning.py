"""Tests for crosscut_loops.history_tuning.

Checks the behaviour of tune_from_history and cautious_step against a
closed-loop simulator with known plant parameters (K=2, tau=60, theta=8)
so the confidence, status and recommendation logic is verified end to end.
"""

import numpy as np
import pytest
from crosscut_loops.history_tuning import HistoryTuning, cautious_step, tune_from_history

# Plant: first-order plus dead time, K = 2 (PV units per % OP), tau = 60 s, theta = 8 samples
# (dt = 1 s). With these the dead time is short against tau, a typical self-regulating loop.
PLANT_GAIN = 2.0
PLANT_TAU_S = 60.0
PLANT_DELAY_SAMPLES = 8
# PI controller: Kc = 0.4 and Ti = 60 s (integral time equal to tau), output clipped to 0-100 %.
CONTROLLER_GAIN = 0.4
CONTROLLER_TI_S = 60.0
OUTPUT_BIAS = 25.0  # operating point of OP; the plant sits at PV = 50 for this OP
STEP_VALUES = (55, 48, 53, 47, 52)  # setpoint steps, one every 1000 samples from sample 800


def _setpoint_profile(sample_count, steps):
    """Return the setpoint: constant 50, plus the STEP_VALUES staircase when steps is set."""
    setpoint = np.full(sample_count, 50.0)
    if steps:
        for k, step_value in enumerate(STEP_VALUES):
            setpoint[800 + k * 1000 :] = step_value
    return setpoint


def _plant_update(plant_state, delayed_output, disturbance_input):
    """Advance the plant one sample (Euler step of the first-order lag) and return the new PV."""
    steady_pv = PLANT_GAIN * (delayed_output - OUTPUT_BIAS) + 50
    return plant_state + ((steady_pv - plant_state) / PLANT_TAU_S + disturbance_input)


def simulate(seed, dist=0.0, steps=True, sample_count=6000):
    """Simulate a closed loop with a known plant and return (sp, op, pv).

    Plant: first-order plus dead time with K=2, tau=60 s, theta=8 s.
    Controller: PI with Kc=0.4 and Ti=60 s, integral sum clipped to [0, 100].
    dist scales independent Gaussian disturbance injected into the plant.
    """
    rng = np.random.default_rng(seed)
    setpoint = _setpoint_profile(sample_count, steps)
    controller_output = np.zeros(sample_count)
    process_value = np.zeros(sample_count)
    plant_state = 50.0
    integral = 0.0
    delay_line = [OUTPUT_BIAS] * PLANT_DELAY_SAMPLES
    disturbance = 0.0
    for i in range(sample_count):
        disturbance = 0.99 * disturbance + rng.normal(0, 0.05)
        error = setpoint[i] - plant_state
        integral += error
        proportional_integral = CONTROLLER_GAIN * (error + integral / CONTROLLER_TI_S)
        output = float(np.clip(OUTPUT_BIAS + proportional_integral, 0, 100))
        controller_output[i] = output
        delay_line.append(output)
        plant_state = _plant_update(plant_state, delay_line.pop(0), disturbance * dist)
        process_value[i] = plant_state + rng.normal(0, 0.05)
    return setpoint, controller_output, process_value


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_clean_data_gives_high_confidence_retune(seed):
    """A clean simulation with several steps yields a high-confidence retune."""
    sp, op, pv = simulate(seed, dist=0.0)
    result = tune_from_history("loop_clean", sp, op, pv, dt_s=1.0)
    assert isinstance(result, HistoryTuning)
    assert result.status == "ok"
    assert result.confidence == "high"
    assert result.recommendation == "retune"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_clean_data_recovers_near_true_plant_parameters(seed):
    """The identified FOPDT model is close to the simulated plant parameters."""
    sp, op, pv = simulate(seed, dist=0.0)
    model = tune_from_history("loop_clean", sp, op, pv, dt_s=1.0).model
    assert abs(model.gain - 2.0) <= 0.10 * 2.0
    assert abs(model.time_constant_s - 60.0) <= 0.15 * 60.0
    assert abs(model.delay_s - 8.0) <= 3.0


def test_clean_data_includes_report_with_simc_settings():
    """A confident result carries a non-None report with SIMC tuning settings."""
    sp, op, pv = simulate(seed=1, dist=0.0)
    result = tune_from_history("loop_clean", sp, op, pv, dt_s=1.0)
    assert result.report is not None
    assert result.report.simc is not None


def test_constant_setpoint_has_no_excitation():
    """A run without setpoint steps reports no_excitation and asks for a bump test."""
    sp, op, pv = simulate(seed=1, dist=0.0, steps=False)
    result = tune_from_history("loop_flat", sp, op, pv, dt_s=1.0)
    assert result.status == "no_excitation"
    assert result.confidence == "none"
    assert result.recommendation == "bump_test"
    assert result.model is None
    assert result.report is None


def test_strongly_disturbed_data_never_returns_high_confidence():
    """A noisy disturbance degrades confidence below 'high'."""
    sp, op, pv = simulate(seed=1, dist=0.3)
    result = tune_from_history("loop_noisy", sp, op, pv, dt_s=1.0)
    assert result.confidence != "high"


def test_single_short_record_yields_low_confidence_bump_test():
    """One short step only gives a low-confidence result that asks for a bump test."""
    sp, op, pv = simulate(seed=1, dist=0.0, sample_count=1500)
    result = tune_from_history("loop_short", sp, op, pv, dt_s=1.0)
    assert result.confidence == "low"
    assert result.recommendation == "bump_test"


def test_cautious_step_clips_upward_proposal():
    """A proposed move above current*factor is clipped down to current*factor."""
    assert cautious_step(current=10.0, proposed=100.0, factor=1.5) == pytest.approx(15.0)


def test_cautious_step_clips_downward_proposal():
    """A proposed move below current/factor is clipped up to current/factor."""
    assert cautious_step(current=10.0, proposed=0.1, factor=1.5) == pytest.approx(10.0 / 1.5)


def test_cautious_step_passes_through_within_window():
    """A proposal inside the allowed window is returned unchanged."""
    assert cautious_step(current=10.0, proposed=12.0, factor=1.5) == pytest.approx(12.0)


def test_cautious_step_returns_proposed_when_current_not_positive():
    """A non-positive current value bypasses clipping entirely."""
    assert cautious_step(current=0.0, proposed=5.0) == pytest.approx(5.0)


def test_cautious_step_returns_proposed_when_proposed_not_positive():
    """A non-positive proposed value is returned as-is."""
    assert cautious_step(current=10.0, proposed=0.0) == pytest.approx(0.0)


def test_low_confidence_has_no_max_change_factor():
    """When confidence is 'low', max_change_factor is None."""
    sp, op, pv = simulate(seed=1, dist=0.0, sample_count=1500)
    result = tune_from_history("loop_short", sp, op, pv, dt_s=1.0)
    assert result.confidence == "low"  # pinned input: one short record never grades higher
    assert result.max_change_factor is None
    assert result.report is None  # low confidence carries no settings (exp26)
    assert result.recommendation == "bump_test"


def test_medium_confidence_has_max_change_factor_of_one_point_five():
    """When confidence is 'medium', max_change_factor equals 1.5."""
    sp, op, pv = simulate(seed=1, dist=0.02)  # light disturbance: windows agree only loosely
    result = tune_from_history("loop_noisy", sp, op, pv, dt_s=1.0)
    assert result.confidence == "medium"
    assert result.max_change_factor == pytest.approx(1.5)
    assert result.recommendation == "retune_cautiously"
    assert result.report is not None  # medium still carries settings, to be applied in small steps


def test_mismatched_array_lengths_raise_value_error():
    """Mismatched sp, op, pv lengths raise ValueError instead of a silent wrong answer."""
    sp, op, pv = simulate(seed=1, dist=0.0)
    with pytest.raises(ValueError):
        tune_from_history("loop_bad", sp, op, pv[:-10], dt_s=1.0)

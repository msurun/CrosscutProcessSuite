"""Tests for crosscut_loops.history_tuning.

Checks the behaviour of tune_from_history and cautious_step against a
closed-loop simulator with known plant parameters (K=2, tau=60, theta=8)
so the confidence, status and recommendation logic is verified end to end.
"""

import numpy as np
import pytest
from crosscut_loops.history_tuning import HistoryTuning, cautious_step, tune_from_history


def simulate(seed, dist=0.0, steps=True, n=6000):
    """Simulate a closed loop with a known plant and return (sp, op, pv).

    Plant: first-order plus dead time with K=2, tau=60 s, theta=8 s.
    Controller: PI with Kc=0.4 and Ti=60 s, integral sum clipped to [0, 100].
    dist scales independent Gaussian disturbance injected into the plant.
    """
    rng = np.random.default_rng(seed)
    K, tau, theta, kc, ti = 2.0, 60.0, 8, 0.4, 60.0
    sp = np.full(n, 50.0)
    if steps:
        for k, a in enumerate((55, 48, 53, 47, 52)):
            sp[800 + k * 1000 :] = a
    op = np.zeros(n)
    pv = np.zeros(n)
    y = 50.0
    u0 = 25.0
    integ = 0.0
    buf = [u0] * theta
    d = 0.0
    for i in range(n):
        d = 0.99 * d + rng.normal(0, 0.05)
        e = sp[i] - y
        integ += e
        u = float(np.clip(u0 + kc * (e + integ / ti), 0, 100))
        op[i] = u
        buf.append(u)
        uu = buf.pop(0)
        y += (K * (uu - u0) + 50 - y) / tau + d * dist
        pv[i] = y + rng.normal(0, 0.05)
    return sp, op, pv


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
    assert hasattr(result.report, "simc") or "simc" in str(result.report).lower()


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
    sp, op, pv = simulate(seed=1, dist=0.0, n=1500)
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
    sp, op, pv = simulate(seed=1, dist=0.0, n=1500)
    result = tune_from_history("loop_short", sp, op, pv, dt_s=1.0)
    if result.confidence == "low":
        assert result.max_change_factor is None


def test_medium_confidence_has_max_change_factor_of_one_point_five():
    """When confidence is 'medium', max_change_factor equals 1.5."""
    sp, op, pv = simulate(seed=1, dist=0.3)
    result = tune_from_history("loop_noisy", sp, op, pv, dt_s=1.0)
    if result.confidence == "medium":
        assert result.max_change_factor == pytest.approx(1.5)


def test_mismatched_array_lengths_raises_or_gives_non_ok_status():
    """Mismatched sp, op, pv lengths either raise ValueError or return non-'ok'."""
    sp, op, pv = simulate(seed=1, dist=0.0)
    with pytest.raises(ValueError):
        tune_from_history("loop_bad", sp, op, pv[:-10], dt_s=1.0)

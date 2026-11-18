"""Exercise staircase diagnostics using a seeded synthetic feedback loop.

These tests use simulated signals only, independently of the public exp33 data.
"""

from crosscut_loops.history_tuning import tune_from_history
from test_history_tuning import simulate


def test_disturbed_staircase_explains_why_tuning_is_withheld():
    """Several inconsistent step fits report a stable diagnostic and actionable detail."""
    setpoint, output, process_value = simulate(seed=1, dist=0.3)

    result = tune_from_history("synthetic", setpoint, output, process_value, dt_s=1.0)

    assert result.confidence == "low"
    assert "closed_loop_staircase" in result.reasons
    assert "OUT/PV" in result.reasons[1]
    assert result.report is None
    assert result.recommendation == "bump_test"


def test_clean_staircase_keeps_its_supported_confidence():
    """The staircase diagnosis does not downgrade mutually predictive models."""
    setpoint, output, process_value = simulate(seed=1, dist=0.0)

    result = tune_from_history("synthetic", setpoint, output, process_value, dt_s=1.0)

    assert result.confidence == "high"
    assert "closed_loop_staircase" not in result.reasons


def test_one_step_is_not_diagnosed_as_a_staircase():
    """One step retains its existing specific lack-of-replication explanation."""
    setpoint, output, process_value = simulate(seed=1, sample_count=1500)

    result = tune_from_history("synthetic", setpoint, output, process_value, dt_s=1.0)

    assert result.confidence == "low"
    assert "closed_loop_staircase" not in result.reasons
    assert "single window" in result.reasons[0]

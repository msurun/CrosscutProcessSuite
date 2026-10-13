"""Tests for stiction detection in the per-loop report."""

from __future__ import annotations

import numpy as np
from crosscut_loops.monitor import LoopReport, LoopSettings, analyze_loop
from crosscut_sim.core import AUTO, MAN
from test_stiction import simulate_loop

SETTINGS = LoopSettings(delay_s=1.0, ultimate_period_s=100.0, amplitude_limit=0.2)


def run_report(pv: np.ndarray, out: np.ndarray, mode_value: int = AUTO) -> LoopReport:
    """Run analyze_loop with the given PV, OUT and MODE, and default settings."""
    time_s = np.arange(len(pv)) * 1.0
    setpoint = np.zeros(len(pv))
    mode = np.full(len(pv), mode_value)
    return analyze_loop(time_s, pv, setpoint, out, mode, settings=SETTINGS)


def test_stiction_loop_is_detected() -> None:
    """Stiction loop is detected and reported."""
    process_values, controller_output = simulate_loop(seed=1, stiction=True)
    report = run_report(process_values, controller_output)
    assert report.stiction_verdict == "stiction"
    assert any("stiction" in message.lower() for message in report.findings)


def test_healthy_valve_with_disturbance_is_not_detected() -> None:
    """Healthy valve with disturbance is not detected as stiction."""
    process_value, controller_output = simulate_loop(seed=2, stiction=False, disturbance_amp=0.3)
    report = run_report(process_value, controller_output)
    assert report.stiction_verdict == "no_stiction"
    assert not any("stiction" in finding.lower() for finding in report.findings)


def test_white_noise_pv_with_constant_out_is_inconclusive() -> None:
    """White noise PV with constant OUT is inconclusive."""
    rng = np.random.default_rng(5)
    pv = rng.normal(scale=0.1, size=4000)
    out = np.full(4000, 50.0)
    report = run_report(pv, out)
    assert report.stiction_verdict == "inconclusive"


def test_stiction_loop_in_manual_is_not_checked() -> None:
    """Stiction loop in manual is not checked."""
    pv, out = simulate_loop(seed=1, stiction=True)
    report = run_report(pv, out, mode_value=MAN)
    assert report.stiction_verdict == "not_checked"

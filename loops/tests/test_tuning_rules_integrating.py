"""Tests for the SIMC integrating-process rules in ``tuning_rules_integrating``."""

from __future__ import annotations

import math

import pytest
from crosscut_loops.tuning_rules import FopdtModel, PiSettings, simc_pi
from crosscut_loops.tuning_rules_integrating import (
    lambda_from_robustness_integrating,
    simc_pi_integrating,
    tau_c_for_max_swing,
)


def test_closed_form_example() -> None:
    s = simc_pi_integrating(0.01, 20.0, 40.0)
    assert s.kc == pytest.approx(1.0 / (0.01 * 60.0))
    assert s.ti_s == pytest.approx(240.0)


def test_matches_fopdt_rule_for_huge_lag() -> None:
    lag = 1e9
    slope = 0.01
    fopdt = simc_pi(FopdtModel(gain=slope * lag, time_constant_s=lag, delay_s=20.0), 40.0)
    integ = simc_pi_integrating(slope, 20.0, 40.0)
    assert integ.kc == pytest.approx(fopdt.kc, rel=1e-3)
    assert integ.ti_s == pytest.approx(fopdt.ti_s, rel=1e-3)


def test_max_swing_round_trip() -> None:
    slope, delay, load, swing = 0.01, 20.0, 10.0, 5.0
    tau_c = tau_c_for_max_swing(slope, delay, load, swing)
    assert tau_c > delay
    assert simc_pi_integrating(slope, delay, tau_c).kc == pytest.approx(load / swing)


def test_max_swing_floored_at_delay() -> None:
    assert tau_c_for_max_swing(0.01, 20.0, 1000.0, 1.0) == 20.0


def test_robustness_endpoints() -> None:
    assert lambda_from_robustness_integrating(20.0, 0.0) == pytest.approx(20.0)
    assert lambda_from_robustness_integrating(20.0, 1.0) == pytest.approx(100.0)


def test_negative_slope_gives_same_magnitudes() -> None:
    assert simc_pi_integrating(-0.01, 20.0, 40.0) == simc_pi_integrating(0.01, 20.0, 40.0)


@pytest.mark.parametrize(
    "args",
    [
        (0.0, 20.0, 40.0),
        (math.nan, 20.0, 40.0),
        (0.01, 0.0, 40.0),
        (0.01, 20.0, -1.0),
        (0.01, math.inf, 40.0),
        (0.01, 20.0, math.nan),
    ],
)
def test_invalid_inputs_raise(args: tuple[float, float, float]) -> None:
    with pytest.raises(ValueError):
        simc_pi_integrating(*args)


def test_invalid_swing_and_robustness_raise() -> None:
    with pytest.raises(ValueError):
        tau_c_for_max_swing(0.01, 20.0, 0.0, 5.0)
    with pytest.raises(ValueError):
        tau_c_for_max_swing(0.01, 20.0, 5.0, -1.0)
    with pytest.raises(ValueError):
        lambda_from_robustness_integrating(20.0, 1.5)
    with pytest.raises(ValueError):
        lambda_from_robustness_integrating(math.nan, 0.5)


def _simulate_setpoint_step(
    slope: float, delay: float, settings: PiSettings, t_end: float, dt: float
) -> list[float]:
    """Euler simulation of an integrator with dead time under PI control of a unit step."""
    buffer = [0.0] * round(delay / dt)
    pv = integral = 0.0
    trace = []
    for _ in range(round(t_end / dt)):
        error = 1.0 - pv
        integral += error * dt / settings.ti_s
        buffer.append(settings.kc * (error + integral))
        pv += slope * buffer.pop(0) * dt
        trace.append(pv)
    return trace


def test_closed_loop_setpoint_response_settles() -> None:
    """SIMC integrating tuning overshoots noticeably on a setpoint step, but settles."""
    slope, delay, dt = 0.01, 20.0, 0.5
    tau_c = 2.0 * delay
    settings = simc_pi_integrating(slope, delay, tau_c)
    trace = _simulate_setpoint_step(slope, delay, settings, 60.0 * (tau_c + delay), dt)
    assert max(trace) - 1.0 < 0.6
    assert abs(trace[-1] - 1.0) < 0.02

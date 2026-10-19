"""Tests for the PID controller used inside the simulators."""

from __future__ import annotations

import math

import pytest
from crosscut_sim.pid import PID, OutputLimits, PidTuning


def make(**kwargs: float | bool) -> PID:
    """Build a PID controller from the given parameters, using defaults for any that are omitted."""
    params: dict[str, float | bool] = {
        "kc": 2.0,
        "ti_s": math.inf,
        "dt_s": 1.0,
        "out_min": -1000.0,
        "out_max": 1000.0,
    }
    params.update(kwargs)
    tuning = PidTuning(
        kc=float(params["kc"]),
        ti_s=float(params["ti_s"]),
        td_s=float(params.get("td_s", 0.0)),
        td_filter_n=float(params.get("td_filter_n", 10.0)),
    )
    limits = OutputLimits(low=float(params["out_min"]), high=float(params["out_max"]))
    return PID(tuning, dt_s=float(params["dt_s"]), limits=limits, direct=bool(params.get("direct")))


def test_proportional_only_reverse_and_direct_acting() -> None:
    assert make().update(pv=1.0, sp=3.0, mode="AUTO") == pytest.approx(4.0)
    assert make(direct=True).update(pv=3.0, sp=1.0, mode="AUTO") == pytest.approx(4.0)
    assert make(direct=True).update(pv=1.0, sp=3.0, mode="AUTO") == pytest.approx(-4.0)


def test_integral_action_accumulates_before_output() -> None:
    pid = make(kc=1.0, ti_s=10.0)
    out = 0.0
    for _ in range(10):
        out = pid.update(pv=0.0, sp=1.0, mode="AUTO")
    # out_n = kc * e + n * kc * e * dt / ti  with e = 1, n = 10
    assert out == pytest.approx(1.0 + 10 * 0.1)


def test_output_is_clipped() -> None:
    pid = make(out_min=0.0, out_max=100.0)
    assert pid.update(pv=0.0, sp=1000.0, mode="AUTO") == 100.0
    assert pid.update(pv=1000.0, sp=0.0, mode="AUTO") == 0.0


def test_manual_mode_returns_clipped_manual_output() -> None:
    pid = make(out_min=0.0, out_max=100.0)
    assert pid.update(pv=0.0, sp=5.0, mode="MAN", man_out=40.0) == 40.0
    assert pid.update(pv=0.0, sp=5.0, mode="MAN", man_out=500.0) == 100.0
    assert pid.update(pv=0.0, sp=5.0, mode="MAN", man_out=-5.0) == 0.0


@pytest.mark.parametrize("direct", [False, True])
def test_bumpless_transfer_from_manual_to_auto(direct: bool) -> None:
    pid = make(kc=2.0, ti_s=20.0, out_min=0.0, out_max=100.0, direct=direct)
    for _ in range(50):
        pid.update(pv=3.0, sp=10.0, mode="MAN", man_out=40.0)
    out = pid.update(pv=3.0, sp=10.0, mode="AUTO")
    assert out == pytest.approx(40.0, abs=1e-6)


def test_anti_windup_leaves_saturation_immediately_when_error_reverses() -> None:
    pid = make(kc=1.0, ti_s=10.0, out_min=0.0, out_max=100.0)
    for _ in range(1000):
        assert pid.update(pv=0.0, sp=1000.0, mode="AUTO") == 100.0
    # the error flips sign: a wound-up integrator would keep the output at 100
    out = pid.update(pv=1005.0, sp=1000.0, mode="AUTO")
    assert out < 100.0


def test_derivative_acts_on_measurement_and_converges_to_ramp_value() -> None:
    pid = make(kc=1.0, ti_s=math.inf, td_s=10.0, td_filter_n=10.0)
    # constant measurement: no derivative contribution, no kick on the first call
    assert pid.update(pv=5.0, sp=5.0, mode="AUTO") == pytest.approx(0.0)
    # setpoint step must not create a derivative kick
    assert pid.update(pv=5.0, sp=6.0, mode="AUTO") == pytest.approx(1.0)
    pv = 5.0
    out = 0.0
    for _ in range(300):
        pv += 1.0
        out = pid.update(pv=pv, sp=6.0, mode="AUTO")
    # steady ramp of 1 unit/step: derivative term -> -kc * td / dt = -10
    assert out - (6.0 - pv) == pytest.approx(-10.0, abs=1e-3)


def test_reset_clears_state() -> None:
    pid = make(kc=1.0, ti_s=10.0)
    for _ in range(20):
        pid.update(pv=0.0, sp=1.0, mode="AUTO")
    pid.reset()
    assert pid.update(pv=0.0, sp=1.0, mode="AUTO") == pytest.approx(1.0 + 0.1)


def test_invalid_mode_and_parameters() -> None:
    with pytest.raises(ValueError):
        make().update(pv=0.0, sp=0.0, mode="CAS")  # CAS is resolved by the plant (it picks the SP)
    with pytest.raises(ValueError):
        make(out_min=10.0, out_max=0.0)
    with pytest.raises(ValueError):
        make(dt_s=0.0)
    with pytest.raises(ValueError):
        make(ti_s=0.0)


def test_derivative_state_follows_the_measurement_in_manual() -> None:
    """Back in AUTO after a long MAN stretch the output stays at the manual value (no kick).

    In MAN the measurement ramps from 0 to 10 and then stands still while the operator holds
    the output at 40. The derivative state must follow the real one-step changes in MAN; with a
    stale previous measurement it kept a phantom change of 10 per step and released it as a
    jump on the SECOND AUTO step (about +33 output units here).
    """
    pid = make(kc=1.0, ti_s=10.0, td_s=5.0)
    for pv in (0.0, 0.0, 0.0):
        pid.update(pv=pv, sp=0.0, mode="AUTO")
    for step in range(1, 11):
        pid.update(pv=float(step), sp=10.0, mode="MAN", man_out=40.0)
    for _ in range(20):
        pid.update(pv=10.0, sp=10.0, mode="MAN", man_out=40.0)
    first_auto = pid.update(pv=10.0, sp=10.0, mode="AUTO")
    second_auto = pid.update(pv=10.0, sp=10.0, mode="AUTO")
    assert first_auto == pytest.approx(40.0, abs=0.1)
    assert second_auto == pytest.approx(40.0, abs=0.1)
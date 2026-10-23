"""Tests of identify_ipdt on synthetic integrating records (numpy, fixed seeds)."""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.identification_ipdt import IpdtIdentificationError, identify_ipdt

DT = 1.0
K = 0.002  # PV unit per second per % OUT
THETA = 20.0


def _t(n: int = 1200) -> np.ndarray:
    """Time axis of n samples at DT."""
    return np.arange(n) * DT


def _steps(t: np.ndarray, moves: list[tuple[float, float]], base: float = 50.0) -> np.ndarray:
    """OUT with steps (time, delta) added to base."""
    u = np.full_like(t, base)
    for at, delta in moves:
        u[t >= at] += delta
    return u


def _ramp_pv(
    t: np.ndarray, u: np.ndarray, drift: float = 0.0, noise: float = 0.0, seed: int = 1
) -> np.ndarray:
    """Integrating PV: delayed integral of OUT deviation plus drift and noise."""
    ud = np.interp(t - THETA, t, u) - u[0]
    integral = np.concatenate(([0.0], np.cumsum(0.5 * (ud[1:] + ud[:-1]) * np.diff(t))))
    y = 10.0 + drift * t + K * integral
    if noise:
        y = y + np.random.default_rng(seed).normal(0.0, noise, len(t))
    return y


def test_single_step_recovers_slope_and_delay() -> None:
    """A clean ramp gives slope within 5 % and delay within one sample."""
    t = _t()
    u = _steps(t, [(300, 5)])
    fit = identify_ipdt(t, u, _ramp_pv(t, u))
    assert fit.verdict == "ok"
    assert fit.model.slope_per_s == pytest.approx(K, rel=0.05)
    assert abs(fit.model.delay_s - THETA) <= DT
    assert fit.up_down_ratio is None


def test_doublet_has_up_down_ratio_near_one() -> None:
    """Up and down slopes agree on a symmetric process."""
    t = _t()
    u = _steps(t, [(250, 5), (500, -10), (750, 5)])
    fit = identify_ipdt(t, u, _ramp_pv(t, u, noise=0.002))
    assert fit.verdict == "ok"
    assert fit.up_down_ratio == pytest.approx(1.0, abs=0.1)
    assert fit.model.slope_per_s == pytest.approx(K, rel=0.05)


def test_step_train() -> None:
    """Several steps in both directions still recover the slope."""
    t = _t(1500)
    u = _steps(t, [(300, 4), (500, 4), (700, -6), (900, -2)])
    fit = identify_ipdt(t, u, _ramp_pv(t, u, noise=0.002, seed=3))
    assert fit.model.slope_per_s == pytest.approx(K, rel=0.05)
    assert fit.verdict in ("ok", "low_confidence")


def test_drift_does_not_bias_slope() -> None:
    """A baseline drift lands in baseline_slope, not in the slope."""
    t = _t()
    u = _steps(t, [(300, 5), (700, -5)])
    fit = identify_ipdt(t, u, _ramp_pv(t, u, drift=0.004, noise=0.002, seed=4))
    assert fit.model.slope_per_s == pytest.approx(K, rel=0.1)
    assert fit.baseline_slope == pytest.approx(0.004, rel=0.2)


def test_noisy_ramp_not_blocked() -> None:
    """Noise lowers confidence at most."""
    t = _t()
    u = _steps(t, [(300, 5)])
    fit = identify_ipdt(t, u, _ramp_pv(t, u, noise=0.05, seed=5))
    assert fit.verdict in ("ok", "low_confidence")


def test_settling_process_is_not_ok() -> None:
    """A self-regulating response (tau 60 s) must not give a confident slope."""
    t = _t()
    u = _steps(t, [(300, 5)])
    rise = np.clip(t - 300 - THETA, 0, None)
    y = 10.0 + 0.5 * (1 - np.exp(-rise / 60.0)) * (t > 300 + THETA)
    y = y + np.random.default_rng(6).normal(0, 0.01, len(t))
    assert identify_ipdt(t, u, y).verdict != "ok"


def test_short_post_move_window_blocked() -> None:
    """Too little time after the last move is refused."""
    t = _t(600)
    u = _steps(t, [(300, 5)])
    fit = identify_ipdt(t, u, _ramp_pv(t, u))
    assert fit.verdict == "blocked"
    assert "post_move_too_short" in fit.reasons


def test_no_out_move_blocked() -> None:
    """A constant OUT is refused with the no_out_move code."""
    t = _t()
    u = np.full_like(t, 50.0)
    fit = identify_ipdt(t, u, _ramp_pv(t, u, drift=0.01))
    assert fit.verdict == "blocked"
    assert fit.reasons == ("no_out_move",)


def test_deterministic() -> None:
    """Same input, same output (fixed bootstrap seed)."""
    t = _t()
    u = _steps(t, [(300, 5)])
    y = _ramp_pv(t, u, noise=0.05, seed=7)
    assert identify_ipdt(t, u, y) == identify_ipdt(t, u, y)


def test_malformed_input_raises() -> None:
    """Length mismatch raises the specific error."""
    with pytest.raises(IpdtIdentificationError):
        identify_ipdt(np.arange(100.0), np.zeros(99), np.zeros(100))

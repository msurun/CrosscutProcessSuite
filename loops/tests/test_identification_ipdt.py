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
    # plant fed by the zero-order-hold reading of the record: brute-force integral on a 0.01 s grid
    fine = np.arange(t[0], t[-1] + 1e-9, 0.01)
    held = u[np.clip(np.searchsorted(t, fine - THETA, side="right") - 1, 0, len(t) - 1)] - u[0]
    held[fine < t[0] + THETA] = 0.0
    cum = np.concatenate(([0.0], np.cumsum(held[:-1]) * 0.01))
    integral = cum[np.round((t - t[0]) / 0.01).astype(int)]
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


def test_step_held_between_samples_gives_theta_within_0_2_s() -> None:
    """Zero-order-hold record with a fractional dead time: clean data, theta_hat within 0.2 s."""
    t = _t()
    u = _steps(t, [(300, 5)])
    y = 10.0 + K * 5.0 * np.maximum(t - 300.0 - 20.3, 0.0)
    assert abs(identify_ipdt(t, u, y).model.delay_s - 20.3) <= 0.2


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


def _ou_noise(n: int, std: float, tau: float, seed: int) -> np.ndarray:
    """Ornstein-Uhlenbeck noise (stationary std, correlation time tau samples)."""
    a = np.exp(-1.0 / tau)
    shocks = np.random.default_rng(seed).normal(0.0, std * np.sqrt(1 - a * a), n)
    out = np.zeros(n)
    for i in range(1, n):
        out[i] = a * out[i - 1] + shocks[i]
    return out


def test_autocorrelated_residuals_give_a_larger_slope_se_than_white_noise() -> None:
    """Same residual variance: slow (tau 200 s) noise widens the bootstrap SE and the block."""
    t = _t()
    u = _steps(t, [(300, 5)])
    clean = _ramp_pv(t, u)
    white = identify_ipdt(t, u, clean + np.random.default_rng(5).normal(0.0, 0.3, len(t)))
    slow = identify_ipdt(t, u, clean + _ou_noise(len(t), 0.3, 200.0, 5))
    assert slow.slope_rel_se > 2.0 * white.slope_rel_se


def test_block_length_follows_the_autocorrelation_time() -> None:
    """White residuals keep the minimum block; slow residuals get a longer one, capped at n / 5."""
    from crosscut_loops.identification_ipdt import DEFAULT_SETTINGS, _block_length

    white = np.random.default_rng(6).normal(size=1000)
    slow = _ou_noise(1000, 1.0, 100.0, 6)
    assert _block_length(white, DEFAULT_SETTINGS) == DEFAULT_SETTINGS.bootstrap_min_block
    assert _block_length(white, DEFAULT_SETTINGS) < _block_length(slow, DEFAULT_SETTINGS) <= 200


def _interval(k: float, noise: float, seed: int) -> tuple[float, float, float]:
    """(lower, theta_hat, upper) of a single-step record with slope k."""
    t = _t()
    u = _steps(t, [(300, 5)])
    y = 10.0 + (_ramp_pv(t, u) - 10.0) * (k / K)
    y = y + np.random.default_rng(seed).normal(0.0, noise, len(t))
    fit = identify_ipdt(t, u, y)
    return fit.delay_lower_s, fit.model.delay_s, fit.delay_upper_s


@pytest.mark.parametrize("noise", [0.0, 0.01])
def test_delay_interval_contains_true_theta(noise: float) -> None:
    """The profile interval brackets the point estimate and the true delay in most runs."""
    hits = 0
    for seed in range(20):
        lower, theta, upper = _interval(K, noise, seed)
        assert lower <= theta <= upper
        hits += lower <= THETA <= upper
    assert hits >= 18


def test_delay_interval_wider_for_slow_ramp() -> None:
    """A slow ramp (k=0.002) pins the dead time less than a fast one (k=0.05)."""
    slow = np.mean([np.subtract(*_interval(0.002, 0.01, s)[::-2]) for s in range(5)])
    fast = np.mean([np.subtract(*_interval(0.05, 0.01, s)[::-2]) for s in range(5)])
    assert slow > fast


def test_correlated_residuals_widen_the_delay_interval() -> None:
    """Same residual variance: slow (tau 100 s) noise gives a wider profile interval than white."""
    t = _t()
    u = _steps(t, [(300, 5)])
    clean = _ramp_pv(t, u)
    widths = []
    white = np.random.default_rng(8).normal(0.0, 0.05, len(t))
    for noise in (white, _ou_noise(len(t), 0.05, 100.0, 8)):
        fit = identify_ipdt(t, u, clean + noise)
        widths.append(fit.delay_upper_s - fit.delay_lower_s)
    assert widths[1] > 2.0 * widths[0]

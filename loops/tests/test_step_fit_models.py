"""Behavioural tests for StepFit on synthetic step responses.

Synthetic data follow the same discretisations the module documents: FOPDT is the exact
first-order lag on the delayed OUT shift, IPDT is the cumulative sum of the delayed OUT shift.
Fixed rng seeds and a 10 s sample time make every scenario reproducible.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.step_fit import StepFitError, fit_step

DT_S = 10.0
N_SAMPLES = 300
PRE_SAMPLES = 60
OUT_BASELINE = 40.0
OUT_STEPPED = 47.0


def _sample_times() -> np.ndarray:
    """Return the uniformly spaced sample times starting at zero."""
    return np.arange(N_SAMPLES) * DT_S


def _out_with_step() -> np.ndarray:
    """Return the OUT signal: baseline before the event, stepped value after it."""
    out = np.full(N_SAMPLES, OUT_BASELINE)
    out[PRE_SAMPLES:] = OUT_STEPPED
    return out


def _delayed_shift(t: np.ndarray, u: np.ndarray, theta: float, u_ref: float) -> np.ndarray:
    """Return u(t - theta) - u_ref, linearly interpolated and held at the edges."""
    if theta <= 0.0:
        return u - u_ref
    tau_times = t - theta
    k = np.clip(np.searchsorted(t, tau_times, side="right") - 1, 0, len(t) - 1)
    fraction = (tau_times - t[k]) / np.maximum(np.diff(t)[k], 1.0)
    interpolated = u[k] + (u[np.minimum(k + 1, len(t) - 1)] - u[k]) * fraction
    shifted = np.where(tau_times <= t[0], u[0], interpolated)
    return shifted - u_ref


def _fopdt_response(t: np.ndarray, u: np.ndarray, gain: float, tau_s: float,
                    theta_s: float) -> np.ndarray:
    """Return the FOPDT response with the module's exact per-sample discretisation."""
    u_ref = float(np.mean(u[:PRE_SAMPLES]))
    dt = np.diff(t)
    alpha = np.exp(-dt / tau_s)
    delayed = _delayed_shift(t, u, theta_s, u_ref)
    x = np.zeros_like(t)
    for k in range(len(t) - 1):
        x[k + 1] = alpha[k] * x[k] + (1.0 - alpha[k]) * delayed[k]
    return gain * x


def _ipdt_response(t: np.ndarray, u: np.ndarray, slope: float, theta_s: float) -> np.ndarray:
    """Return the IPDT response as k times the cumulative sum of the delayed OUT shift."""
    u_ref = float(np.mean(u[:PRE_SAMPLES]))
    delayed = _delayed_shift(t, u, theta_s, u_ref)
    return slope * np.cumsum(delayed) * DT_S


def _with_noise(signal: np.ndarray, noise_sd: float, seed: int) -> np.ndarray:
    """Add Gaussian noise of the given standard deviation with a fixed seed."""
    rng = np.random.default_rng(seed)
    return signal + rng.normal(0.0, noise_sd, size=len(signal))


def _fopdt_case(noise_sd: float = 0.2, seed: int = 101) -> tuple[np.ndarray, np.ndarray,
                                                                  np.ndarray]:
    """Return (t, pv, out) for the canonical FOPDT scenario with noise."""
    t = _sample_times()
    out = _out_with_step()
    response = _fopdt_response(t, out, gain=0.8, tau_s=120.0, theta_s=40.0)
    return t, _with_noise(OU_BASELINE + response, noise_sd, seed), out


OU_BASELINE = 50.0  # PV baseline level in PV units


def _ipdt_case(seed: int = 202) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (t, pv, out) for the canonical IPDT scenario with small noise."""
    t = _sample_times()
    out = _out_with_step()
    response = _ipdt_response(t, out, slope=-0.004, theta_s=30.0)
    return t, _with_noise(OU_BASELINE + response, 0.1, seed), out


def test_fopdt_recovers_gain_within_three_standard_errors():
    t, pv, out = _fopdt_case()
    result = fit_step(t, pv, out, PRE_SAMPLES, "fopdt")
    assert result.gain is not None
    assert abs(result.gain.value - 0.8) <= 3.0 * result.gain.se


def test_fopdt_recovers_gain_within_five_percent_of_truth():
    t, pv, out = _fopdt_case()
    result = fit_step(t, pv, out, PRE_SAMPLES, "fopdt")
    assert result.gain is not None
    assert abs(result.gain.value - 0.8) / 0.8 <= 0.05


def test_fopdt_recovers_tau_within_three_standard_errors_or_fifteen_percent():
    t, pv, out = _fopdt_case()
    result = fit_step(t, pv, out, PRE_SAMPLES, "fopdt")
    assert result.tau_s is not None
    within_se = abs(result.tau_s.value - 120.0) <= 3.0 * result.tau_s.se
    within_fraction = abs(result.tau_s.value - 120.0) / 120.0 <= 0.15
    assert within_se or within_fraction


def test_fopdt_recovers_theta_within_fifteen_seconds():
    t, pv, out = _fopdt_case()
    result = fit_step(t, pv, out, PRE_SAMPLES, "fopdt")
    assert abs(result.theta_s.value - 40.0) <= 15.0


def test_fopdt_has_high_r_squared():
    t, pv, out = _fopdt_case()
    result = fit_step(t, pv, out, PRE_SAMPLES, "fopdt")
    assert result.r2 > 0.95


def test_fopdt_reports_model_name_and_no_edges():
    t, pv, out = _fopdt_case()
    result = fit_step(t, pv, out, PRE_SAMPLES, "fopdt")
    assert result.model == "fopdt"
    assert result.edges == ()


def test_fopdt_standard_errors_are_finite_and_positive():
    t, pv, out = _fopdt_case()
    result = fit_step(t, pv, out, PRE_SAMPLES, "fopdt")
    assert result.gain is not None
    assert result.tau_s is not None
    standard_errors = (result.gain.se, result.tau_s.se, result.theta_s.se)
    assert all(np.isfinite(se) and se > 0.0 for se in standard_errors)


def test_ipdt_recovers_slope_within_three_percent_of_truth():
    t, pv, out = _ipdt_case()
    result = fit_step(t, pv, out, PRE_SAMPLES, "ipdt")
    assert result.slope is not None
    assert abs(result.slope.value - (-0.004)) / 0.004 <= 0.03


def test_ipdt_recovers_theta_within_one_sample_of_truth():
    # The discrete sum uses delayed values at sample k, matching the module's analytic
    # integral convention, so the fitted theta sits at the true value (within one sample).
    t, pv, out = _ipdt_case()
    result = fit_step(t, pv, out, PRE_SAMPLES, "ipdt")
    assert abs(result.theta_s.value - 30.0) <= DT_S


def test_ipdt_on_fopdt_data_has_worse_bic_than_fopdt():
    t, pv, out = _fopdt_case()
    fopdt_result = fit_step(t, pv, out, PRE_SAMPLES, "fopdt")
    ipdt_result = fit_step(t, pv, out, PRE_SAMPLES, "ipdt")
    assert ipdt_result.bic > fopdt_result.bic


def test_fopdt_on_ipdt_data_has_worse_bic_than_ipdt():
    t, pv, out = _ipdt_case()
    ipdt_result = fit_step(t, pv, out, PRE_SAMPLES, "ipdt")
    fopdt_result = fit_step(t, pv, out, PRE_SAMPLES, "fopdt")
    assert fopdt_result.bic > ipdt_result.bic


def test_larger_noise_gives_larger_gain_standard_error():
    t_quiet, pv_quiet, out_quiet = _fopdt_case(noise_sd=0.2, seed=101)
    t_loud, pv_loud, out_loud = _fopdt_case(noise_sd=1.0, seed=101)
    quiet_result = fit_step(t_quiet, pv_quiet, out_quiet, PRE_SAMPLES, "fopdt")
    loud_result = fit_step(t_loud, pv_loud, out_loud, PRE_SAMPLES, "fopdt")
    assert quiet_result.gain is not None
    assert loud_result.gain is not None
    assert loud_result.gain.se > quiet_result.gain.se


def test_too_short_window_raises_too_few_samples():
    t = np.arange(20) * DT_S
    pv = np.linspace(0.0, 1.0, 20)
    out = np.concatenate((np.zeros(10), np.ones(10)))
    with pytest.raises(StepFitError, match="too_few_samples"):
        fit_step(t, pv, out, pre=10, model="fopdt")


def test_constant_out_raises_no_out_move():
    t = _sample_times()
    pv = np.linspace(0.0, 1.0, N_SAMPLES)
    out = np.full(N_SAMPLES, OUT_BASELINE)
    with pytest.raises(StepFitError, match="no_out_move"):
        fit_step(t, pv, out, PRE_SAMPLES, "fopdt")


def test_unknown_model_name_raises_value_error():
    t = _sample_times()
    pv = np.linspace(0.0, 1.0, N_SAMPLES)
    out = _out_with_step()
    with pytest.raises(ValueError, match="model must be"):
        fit_step(t, pv, out, PRE_SAMPLES, "abc")


def test_nan_samples_in_pv_are_tolerated_and_gain_is_recovered():
    t, pv, out = _fopdt_case()
    pv_with_nans = pv.copy()
    pv_with_nans[100] = np.nan
    pv_with_nans[150] = np.nan
    pv_with_nans[200] = np.nan
    result = fit_step(t, pv_with_nans, out, PRE_SAMPLES, "fopdt")
    assert result.gain is not None
    assert abs(result.gain.value - 0.8) / 0.8 <= 0.10


def test_unsettled_response_flags_tau_at_edge_or_reports_large_tau_se():
    t = _sample_times()
    out = _out_with_step()
    response = _fopdt_response(t, out, gain=0.8, tau_s=2500.0, theta_s=40.0)
    pv = _with_noise(OU_BASELINE + response, 0.2, seed=303)
    result = fit_step(t, pv, out, PRE_SAMPLES, "fopdt")
    assert result.tau_s is not None
    flagged = "tau_at_edge" in result.edges
    large_se = np.isfinite(result.tau_s.se) and result.tau_s.se > 0.1 * result.tau_s.value
    assert flagged or large_se


def test_fitted_array_has_window_length_and_starts_near_baseline():
    t, pv, out = _fopdt_case()
    result = fit_step(t, pv, out, PRE_SAMPLES, "fopdt")
    assert len(result.fitted) == len(t)
    assert abs(result.fitted[0] - OU_BASELINE) <= 1.0

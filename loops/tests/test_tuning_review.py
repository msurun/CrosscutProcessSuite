"""
Tests for tuning_review: verdicts, insufficient-data reasons, window bounds and KPIs.
All series are synthetic and deterministic (numpy default_rng(11), 1 s sampling).
"""

import numpy as np
import pytest
from crosscut_loops.tuning_review import (
    DEFAULT_THRESHOLDS,
    ReviewThresholds,
    WindowData,
    compare_windows,
    early_check,
    window_bounds,
    window_metrics,
)

N = 3600
VALID_VERDICTS = {"improved", "neutral", "worse", "insufficient_data"}


def make_window(
    err: np.ndarray,
    sp: np.ndarray | None = None,
    out: np.ndarray | None = None,
    mode: np.ndarray | None = None,
) -> WindowData:
    """Build a window where pv = error + sp, so the error is exactly `err`."""
    n = len(err)
    t = np.arange(n, dtype=float)
    sp_arr = np.zeros(n) if sp is None else sp
    if out is None:
        out = 50.0 + 5.0 * np.sin(2.0 * np.pi * t / 600.0)
    if mode is None:
        mode = np.ones(n, dtype=int)
    return WindowData(t_s=t, pv=err + sp_arr, sp=sp_arr, out=out, mode=mode)


def noise(scale: float, n: int = N) -> np.ndarray:
    return np.random.default_rng(11).normal(0.0, scale, n)


def test_improved_when_error_std_drops_40_percent() -> None:
    before = make_window(noise(1.0))
    after = make_window(noise(0.6))
    result = compare_windows(before, after)
    assert result["verdict"] == "improved"
    assert result["reasons"] == ["error_std_down_travel_ok"]


def test_worse_when_error_std_rises_30_percent() -> None:
    before = make_window(noise(1.0))
    after = make_window(noise(1.3))
    result = compare_windows(before, after)
    assert result["verdict"] == "worse"
    assert "error_std_up" in result["reasons"]


def test_worse_via_new_oscillation() -> None:
    t = np.arange(N, dtype=float)
    before = make_window(0.5 + 0.0001 * t)
    after_err = np.sin(2.0 * np.pi * t / 200.0) + noise(0.05)
    after = make_window(after_err)
    result = compare_windows(before, after)
    assert result["verdict"] == "worse"
    assert "new_oscillation" in result["reasons"]
    assert result["before"]["oscillating"] is False
    assert result["after"]["oscillating"] is True


def test_worse_via_saturation_up() -> None:
    err = noise(1.0)
    t = np.arange(N, dtype=float)
    before = make_window(err, out=50.0 + 40.0 * np.sin(2.0 * np.pi * t / 600.0))
    after_out = np.clip(50.0 + 80.0 * np.sin(2.0 * np.pi * t / 600.0), 10.0, 90.0)
    after = make_window(err, out=after_out)
    result = compare_windows(before, after)
    assert result["verdict"] == "worse"
    assert result["reasons"] == ["saturation_up"]


@pytest.mark.parametrize("ratio", [0.95, 1.05])
def test_neutral_within_5_percent(ratio: float) -> None:
    before = make_window(noise(1.0))
    after = make_window(noise(ratio))
    result = compare_windows(before, after)
    assert result["verdict"] == "neutral"
    assert result["reasons"] == []


def test_insufficient_few_samples() -> None:
    before = make_window(noise(1.0, n=20))
    after = make_window(noise(1.0, n=20))
    result = compare_windows(before, after)
    assert result["verdict"] == "insufficient_data"
    assert "few_samples" in result["reasons"]


def test_insufficient_low_service_factor_open_loop() -> None:
    mode = np.ones(N, dtype=int)
    mode[::5] = 0
    before = make_window(noise(1.0), mode=mode)
    after = make_window(noise(1.0))
    result = compare_windows(before, after)
    assert result["verdict"] == "insufficient_data"
    assert "low_service_factor" in result["reasons"]


def test_insufficient_low_service_factor_nan() -> None:
    pv_err = noise(1.0)
    pv_err[::9] = np.nan
    before = make_window(noise(1.0))
    after = make_window(pv_err)
    result = compare_windows(before, after)
    assert result["verdict"] == "insufficient_data"
    assert "low_service_factor" in result["reasons"]


def test_insufficient_sp_activity_differs() -> None:
    sp = np.zeros(N)
    sp[600:] = 1.0
    sp[1200:] = 2.0
    sp[2400:] = 3.0
    before = make_window(noise(1.0))
    after = make_window(noise(1.0), sp=sp)
    result = compare_windows(before, after)
    assert result["verdict"] == "insufficient_data"
    assert result["reasons"] == ["sp_activity_differs"]


def test_zero_before_std_stays_neutral_when_after_is_flat() -> None:
    before = make_window(np.zeros(N))
    after = make_window(np.zeros(N))
    result = compare_windows(before, after)
    assert result["verdict"] == "neutral"
    assert result["reasons"] == []


def test_zero_before_std_is_worse_when_after_has_error() -> None:
    before = make_window(np.zeros(N))
    after = make_window(noise(1.0))
    result = compare_windows(before, after)
    assert result["verdict"] == "worse"
    assert "error_std_up" in result["reasons"]


def test_window_bounds_uses_minimum_window() -> None:
    before, after = window_bounds(10000.0, theta_s=10.0, tau_s=20.0)
    assert before == (10000.0 - 1800.0, 10000.0)
    assert after == (10000.0 + 90.0, 10000.0 + 90.0 + 1800.0)


def test_window_bounds_scales_with_dynamics() -> None:
    before, after = window_bounds(10000.0, theta_s=60.0, tau_s=240.0)
    assert before == (4000.0, 10000.0)
    assert after == (10900.0, 16900.0)


def test_early_check_flags_oscillating_start() -> None:
    t = np.arange(N, dtype=float)
    after = make_window(np.sin(2.0 * np.pi * t / 20.0))
    assert early_check(after, cycle_s=60.0) == "worse_early"


def test_early_check_quiet_start_is_none() -> None:
    t = np.arange(N, dtype=float)
    after = make_window(0.5 + 0.0001 * t)
    assert early_check(after, cycle_s=60.0) is None


def test_window_metrics_constant_error_iae_is_3600_per_hour() -> None:
    n = 3601
    data = make_window(np.ones(n), out=np.full(n, 50.0))
    metrics = window_metrics(data, DEFAULT_THRESHOLDS)
    assert metrics.n == n
    assert metrics.service_factor == 1.0
    assert metrics.iae_per_h == pytest.approx(3600.0, rel=1e-9)
    assert metrics.error_std == pytest.approx(0.0, abs=1e-12)
    assert metrics.out_travel_per_h == 0.0
    assert metrics.sp_moves == 0
    assert metrics.oscillating is False


def test_window_metrics_out_travel_per_hour() -> None:
    n = 3601
    out = np.tile([0.0, 1.0], n // 2 + 1)[:n]
    data = make_window(np.zeros(n), out=out)
    metrics = window_metrics(data, DEFAULT_THRESHOLDS)
    assert metrics.out_travel_per_h == pytest.approx(3600.0, rel=1e-9)


def test_non_finite_inputs_do_not_raise() -> None:
    rng = np.random.default_rng(11)
    err = rng.normal(0.0, 1.0, N)
    err[::7] = np.nan
    err[::11] = np.inf
    out = 50.0 + 5.0 * rng.normal(size=N)
    out[::13] = np.inf
    before = make_window(noise(1.0))
    after = make_window(err, out=out)
    result = compare_windows(before, after)
    assert result["verdict"] in VALID_VERDICTS


def test_all_nan_window_does_not_raise() -> None:
    before = make_window(np.full(N, np.nan))
    after = make_window(np.full(N, np.nan))
    result = compare_windows(before, after)
    assert result["verdict"] == "insufficient_data"
    assert early_check(after, cycle_s=60.0) is None


def test_empty_arrays_do_not_raise() -> None:
    empty = make_window(np.array([], dtype=float))
    metrics = window_metrics(empty, DEFAULT_THRESHOLDS)
    assert metrics.n == 0
    assert metrics.service_factor == 0.0
    result = compare_windows(empty, empty)
    assert result["verdict"] == "insufficient_data"
    assert early_check(empty, cycle_s=60.0) is None


def test_result_structure() -> None:
    before = make_window(noise(1.0))
    after = make_window(noise(0.6))
    result = compare_windows(before, after, ReviewThresholds())
    assert set(result) == {"verdict", "reasons", "before", "after", "note"}
    assert isinstance(result["verdict"], str)
    reasons = result["reasons"]
    assert isinstance(reasons, list)
    assert all(isinstance(r, str) for r in reasons)
    assert isinstance(result["before"], dict)
    assert isinstance(result["after"], dict)
    assert set(result["before"]) == set(result["after"])
    assert "error_std" in result["before"]
    assert isinstance(result["note"], str)
    assert result["note"]

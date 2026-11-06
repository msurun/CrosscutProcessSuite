"""
Evaluates PID tuning changes by comparing windowed loop data before and after the change.
Provides a pure, deterministic verdict on tuning performance (Phase 3, #48).
"""

import dataclasses
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ReviewThresholds:
    """Thresholds for determining if a tuning change improved or worsened performance."""
    error_std_change: float = 0.20
    travel_increase_limit: float = 0.50
    min_service_factor: float = 0.9
    sp_move_ratio_limit: float = 2.0
    early_cycles: int = 3
    min_samples: int = 30


DEFAULT_THRESHOLDS = ReviewThresholds()


@dataclass(frozen=True)
class WindowData:
    """
    Time-series data for a single evaluation window.
    mode: Numeric loop mode; 1 means AUTO or CAS (closed-loop), others mean open-loop.
    """
    t_s: np.ndarray
    pv: np.ndarray
    sp: np.ndarray
    out: np.ndarray
    mode: np.ndarray


@dataclass(frozen=True)
class WindowMetrics:
    """Calculated metrics for a specific window of data."""
    n: int
    service_factor: float
    error_std: float
    iae_per_h: float
    out_travel_per_h: float
    oscillating: bool
    sp_moves: int
    saturation_share: float


MIN_WINDOW_S = 1800.0  # shortest before/after window in production (ADR 014 section 5)


def window_bounds(
    t_apply_s: float, theta_s: float, tau_s: float, min_window_s: float = MIN_WINDOW_S
) -> tuple[tuple[float, float], tuple[float, float]]:
    """
    Calculate (before, after) time windows based on process dynamics.
    theta_s: dead time in seconds.
    tau_s: time constant in seconds.
    min_window_s: shortest window; only a test of a fast process lowers it.
    Returns: ((before_start, before_end), (after_start, after_end)) in seconds.
    """
    window_s = max(min_window_s, 20.0 * (theta_s + tau_s))
    settle_time_s = 3.0 * (theta_s + tau_s)
    
    before = (t_apply_s - window_s, t_apply_s)
    after_start = t_apply_s + settle_time_s
    after = (after_start, after_start + window_s)
    
    return before, after


def _is_oscillating(detrended_error: np.ndarray) -> bool:
    """
    Detects if the detrended error signal is oscillating.
    Requires at least 4 zero-crossings and amplitude > 3 noise-sigmas.
    Noise is estimated via the first-difference standard deviation.
    """
    if len(detrended_error) < 4:
        return False
        
    # A zero-crossing happens when the product of adjacent samples is negative
    crossings = np.sum(detrended_error[:-1] * detrended_error[1:] < 0)
    
    diff_std = np.std(np.diff(detrended_error))
    noise_sigma = diff_std / np.sqrt(2.0)
    
    # Avoid division by zero if signal is perfectly flat
    if noise_sigma < 1e-12:
        return False
        
    max_amp = np.max(np.abs(detrended_error))
    return bool(crossings >= 4 and max_amp > 3.0 * noise_sigma)


def _count_sp_moves(sp: np.ndarray) -> int:
    """Counts setpoint changes > 0.5% of the range or > 1e-9 (absolute) over the whole window."""
    valid_sp = sp[np.isfinite(sp)]
    if len(valid_sp) < 2:
        return 0
    sp_range = np.max(valid_sp) - np.min(valid_sp)
    threshold = max(1e-9, 0.005 * sp_range)
    return int(np.sum(np.abs(np.diff(valid_sp)) > threshold))


def _calculate_rates(
    t_s: np.ndarray, pv: np.ndarray, sp: np.ndarray, out: np.ndarray, valid: np.ndarray
) -> tuple[float, float]:
    """
    Calculates IAE and OUT travel scaled to one hour using the actual window span.
    Explicitly aligns error samples with forward dt intervals to handle gaps.
    """
    if len(t_s) < 2:
        return 0.0, 0.0
        
    duration_s = t_s[-1] - t_s[0]
    if duration_s <= 0.0:
        return 0.0, 0.0
        
    scale_to_h = 3600.0 / duration_s
    dt = np.diff(t_s)
    
    # Align valid mask and error with the dt intervals
    v_mask = valid[:-1]
    err = (pv[:-1] - sp[:-1])[v_mask]
    iae = np.sum(np.abs(err) * dt[v_mask])
    
    out_valid = out[valid]
    travel = np.sum(np.abs(np.diff(out_valid))) if len(out_valid) > 1 else 0.0
    
    return float(iae * scale_to_h), float(travel * scale_to_h)


def window_metrics(data: WindowData, thresholds: ReviewThresholds) -> WindowMetrics:
    """Extracts KPIs from a window of data, considering closed-loop finite samples."""
    valid = (data.mode == 1) & np.isfinite(data.pv) & np.isfinite(data.sp) & np.isfinite(data.out)
    n_valid = int(np.sum(valid))
    service_factor = n_valid / len(data.t_s) if len(data.t_s) > 0 else 0.0
    
    if n_valid < 2:
        return WindowMetrics(
            n=n_valid, service_factor=service_factor, error_std=0.0, iae_per_h=0.0,
            out_travel_per_h=0.0, oscillating=False, sp_moves=0, saturation_share=0.0
        )
        
    t_valid = data.t_s[valid]
    error = data.pv[valid] - data.sp[valid]
    out_valid = data.out[valid]
    
    iae_per_h, out_travel_per_h = _calculate_rates(data.t_s, data.pv, data.sp, data.out, valid)
    
    # Linear detrend of the closed-loop error for oscillation detection
    detrended_error = error - np.polyval(np.polyfit(t_valid, error, 1), t_valid)
    
    # Saturation based on 1% of the actual overall OUT limits across the entire window
    valid_out_all = data.out[np.isfinite(data.out)]
    out_min, out_max = np.min(valid_out_all), np.max(valid_out_all)
    sat_thresh = max(1e-9, 0.01 * (out_max - out_min))
    is_sat = (out_valid <= out_min + sat_thresh) | (out_valid >= out_max - sat_thresh)
    
    return WindowMetrics(
        n=n_valid,
        service_factor=service_factor,
        error_std=float(np.std(error)),
        iae_per_h=iae_per_h,
        out_travel_per_h=out_travel_per_h,
        oscillating=_is_oscillating(detrended_error),
        sp_moves=_count_sp_moves(data.sp),
        saturation_share=float(np.mean(is_sat))
    )


def _check_insufficient_data(
    mb: WindowMetrics, ma: WindowMetrics, thr: ReviewThresholds
) -> list[str]:
    """Returns reasons if data is insufficient to make a comparison, empty otherwise."""
    reasons = []
    if mb.n < thr.min_samples or ma.n < thr.min_samples:
        reasons.append("few_samples")
    if mb.service_factor < thr.min_service_factor or ma.service_factor < thr.min_service_factor:
        reasons.append("low_service_factor")
        
    sp_ratio = max(ma.sp_moves, 1) / max(mb.sp_moves, 1)
    inv_sp_ratio = max(mb.sp_moves, 1) / max(ma.sp_moves, 1)
    if sp_ratio > thr.sp_move_ratio_limit or inv_sp_ratio > thr.sp_move_ratio_limit:
        reasons.append("sp_activity_differs")
        
    return reasons


def _check_worse(mb: WindowMetrics, ma: WindowMetrics, thr: ReviewThresholds) -> list[str]:
    """Returns reasons if the tuning is worse, empty otherwise."""
    reasons = []
    
    # Handle zero standard deviation in the before window
    if mb.error_std < 1e-12:
        if ma.error_std > 1e-9:
            reasons.append("error_std_up")
    elif ma.error_std >= mb.error_std * (1.0 + thr.error_std_change):
        reasons.append("error_std_up")
        
    if ma.oscillating and not mb.oscillating:
        reasons.append("new_oscillation")
        
    if ma.saturation_share > mb.saturation_share + 0.05:
        reasons.append("saturation_up")
        
    return reasons


def compare_windows(
    before: WindowData, after: WindowData, thresholds: ReviewThresholds = DEFAULT_THRESHOLDS
) -> dict[str, object]:
    """
    Compares before and after windows to reach a verdict on tuning performance.
    Returns a dictionary with verdict, reasons, metrics, and a standard note.
    """
    mb = window_metrics(before, thresholds)
    ma = window_metrics(after, thresholds)
    
    insufficient = _check_insufficient_data(mb, ma, thresholds)
    worse = _check_worse(mb, ma, thresholds)
    
    verdict = "neutral"
    reasons = []
    
    if insufficient:
        verdict = "insufficient_data"
        reasons = insufficient
    elif worse:
        verdict = "worse"
        reasons = worse
    elif mb.error_std > 1e-12 and (
        ma.error_std <= mb.error_std * (1.0 - thresholds.error_std_change)
    ):
        if ma.out_travel_per_h < mb.out_travel_per_h * (1.0 + thresholds.travel_increase_limit):
            verdict = "improved"
            reasons = ["error_std_down_travel_ok"]

    return {
        "verdict": verdict,
        "reasons": reasons,
        "before": dataclasses.asdict(mb),
        "after": dataclasses.asdict(ma),
        "note": "observed after the change; other causes (feed, SP activity) not excluded"
    }


def early_check(
    after: WindowData, cycle_s: float, thresholds: ReviewThresholds = DEFAULT_THRESHOLDS
) -> str | None:
    """
    Checks if the loop is oscillating in the first few cycles after a change.
    Returns 'worse_early' if it is, None otherwise.
    """
    if len(after.t_s) == 0:
        return None
        
    end_time_s = after.t_s[0] + thresholds.early_cycles * cycle_s
    early_mask = after.t_s <= end_time_s
    
    early_data = WindowData(
        t_s=after.t_s[early_mask],
        pv=after.pv[early_mask],
        sp=after.sp[early_mask],
        out=after.out[early_mask],
        mode=after.mode[early_mask]
    )
    
    metrics = window_metrics(early_data, thresholds)
    if metrics.n >= 8 and metrics.oscillating:
        return "worse_early"
        
    return None

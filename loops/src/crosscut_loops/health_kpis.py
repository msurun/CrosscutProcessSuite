"""Health KPIs for control-loop monitoring: valve wear, quantisation and trends.

These pure functions turn raw trend and OP signals into a few interpretable numbers
(travel per hour, reversals, quantisation ratio, sizing hints, oscillation clusters,
Kendall trend). They keep decisions apart from side effects so they can be unit-tested
and reused by several reports.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

SECONDS_PER_HOUR = 3600.0
SIGNIFICANT_DIGITS_STEP = 6
MIN_NONZERO_INCREMENTS = 20
MAD_TO_SIGMA = 1.4826  # MAD * 1.4826 estimates the standard deviation of a normal noise
DIFF_VARIANCE_FACTOR = np.sqrt(2.0)  # Var(diff) = 2 * Var(noise) for i.i.d. samples
QUANTISATION_LIMITING = 1.0  # ratio >= this means quantisation limits control
OVERSIZED_MEDIAN = 15.0  # OP median below this (percent) suggests an oversized valve
UNDERSIZED_MEDIAN = 85.0  # OP median above this (percent) suggests an undersized valve
DEFAULT_LOW_PERCENT = 5.0
DEFAULT_HIGH_PERCENT = 95.0
TREND_TAU_THRESHOLD = 0.5  # |Kendall tau| at or above this is a real trend
DEFAULT_MIN_TREND_POINTS = 6
MIN_TREND_POINTS = 3


@dataclass(frozen=True)
class ValveExtremes:
    """Summary of where OP spends its time, plus a sizing hint."""

    median: float
    share_low: float
    share_high: float
    sizing_hint: str | None


@dataclass(frozen=True)
class TrendResult:
    """Kendall trend strength and direction for a KPI series."""

    n: int
    tau: float
    slope_per_step: float
    direction: str


def _as_valid_signal(values: ArrayLike) -> np.ndarray:
    """Return a 1-D float array with NaN samples dropped."""
    signal = np.asarray(values, dtype=float).ravel()
    return signal[~np.isnan(signal)]


def _median_absolute_deviation(values: np.ndarray) -> float:
    """Return the MAD of values about their median."""
    return float(np.median(np.abs(values - np.median(values))))


def valve_travel_per_hour(op: ArrayLike, dt_s: float, out_span: float = 100.0) -> float:
    """Return total OP movement per hour as percent of out_span.

    Travel is sum|diff(OP)| / out_span * 100, spread over the record duration.
    Raises ValueError if dt_s <= 0, out_span <= 0 or fewer than 2 valid samples.
    """
    if dt_s <= 0:
        raise ValueError(f"dt_s must be positive, got {dt_s}")
    if out_span <= 0:
        raise ValueError(f"out_span must be positive, got {out_span}")
    signal = _as_valid_signal(op)
    if signal.size < 2:
        raise ValueError(f"need at least 2 valid samples, got {signal.size}")

    total_travel_percent = np.sum(np.abs(np.diff(signal))) / out_span * 100.0
    record_hours = (signal.size - 1) * dt_s / SECONDS_PER_HOUR
    return float(total_travel_percent / record_hours)


def reversals_per_hour(op: ArrayLike, dt_s: float, min_move: float) -> float:
    """Count direction changes per hour using min_move hysteresis.

    A reversal is registered only when OP retraces by at least min_move since the
    running extreme. Raises ValueError if dt_s <= 0, min_move < 0 or fewer than 2 samples.
    """
    if dt_s <= 0:
        raise ValueError(f"dt_s must be positive, got {dt_s}")
    if min_move < 0:
        raise ValueError(f"min_move must be non-negative, got {min_move}")
    signal = _as_valid_signal(op)
    if signal.size < 2:
        raise ValueError(f"need at least 2 valid samples, got {signal.size}")

    reversal_count = _count_reversals(signal, min_move)
    record_hours = (signal.size - 1) * dt_s / SECONDS_PER_HOUR
    return reversal_count / record_hours


def _count_reversals(signal: np.ndarray, min_move: float) -> int:
    """Return the number of hysteresis reversals in signal."""
    lowest = highest = signal[0]
    going_up = True
    reversal_count = 0
    for sample in signal[1:]:
        lowest = min(lowest, sample)
        highest = max(highest, sample)
        if going_up and highest - sample >= min_move:
            reversal_count += 1
            going_up = False
            lowest = sample
        elif not going_up and sample - lowest >= min_move:
            reversal_count += 1
            going_up = True
            highest = sample
    return reversal_count


def quantisation_step(x: ArrayLike) -> float:
    """Return the resolution of a signal: 5th percentile of nonzero |diff(x)|.

    The step is rounded to 6 significant digits. Returns NaN when there are
    fewer than 20 nonzero increments, i.e. when the signal is too smooth to tell.
    """
    signal = _as_valid_signal(x)
    increments = np.abs(np.diff(signal))
    nonzero = increments[increments > 0.0]
    if nonzero.size < MIN_NONZERO_INCREMENTS:
        return float("nan")

    raw_step = float(np.percentile(nonzero, 5))
    return float(f"{raw_step:.{SIGNIFICANT_DIGITS_STEP}g}")


def quantisation_ratio(x: ArrayLike) -> float:
    """Return quantisation_step(x) over the noise sigma from MAD(diff(x)).

    sigma = 1.4826 * MAD(diff) / sqrt(2). A ratio >= QUANTISATION_LIMITING means
    quantisation, not the process noise, limits how finely OP is moved.
    Returns inf when sigma is 0 with a finite step, NaN when the step is NaN.
    """
    signal = _as_valid_signal(x)
    step = quantisation_step(signal)
    if np.isnan(step):
        return float("nan")

    increments = np.diff(signal)
    if increments.size == 0:
        return float("inf")
    sigma = MAD_TO_SIGMA * _median_absolute_deviation(increments) / DIFF_VARIANCE_FACTOR
    if sigma == 0.0:
        return float("inf")
    return float(step / sigma)


def valve_extremes(
    op: ArrayLike, low: float = DEFAULT_LOW_PERCENT, high: float = DEFAULT_HIGH_PERCENT
) -> ValveExtremes:
    """Summarise OP distribution and suggest valve sizing.

    Shares are fractions of valid samples below low / above high (OP in percent).
    Raises ValueError if low >= high or there are no valid samples.
    """
    if low >= high:
        raise ValueError(f"low must be below high, got low={low} high={high}")
    signal = _as_valid_signal(op)
    if signal.size == 0:
        raise ValueError("need at least one valid sample")

    median = float(np.median(signal))
    share_low = float(np.count_nonzero(signal < low) / signal.size)
    share_high = float(np.count_nonzero(signal > high) / signal.size)
    return ValveExtremes(median, share_low, share_high, _sizing_hint(median))


def _sizing_hint(median: float) -> str | None:
    """Return the sizing hint for an OP median, or None when well ranged."""
    if median < OVERSIZED_MEDIAN:
        return "oversized"
    if median > UNDERSIZED_MEDIAN:
        return "undersized"
    return None


def group_by_period(periods: dict[str, float], tolerance: float = 0.1) -> list[list[str]]:
    """Cluster loop names whose oscillation periods are close.

    Loops sharing a period likely share one disturbance source. Periods are in
    seconds; None, NaN and non-positive values are ignored. Returns clusters of at
    least two loops, each sorted by name, ordered by their median period.
    """
    valid_periods = _valid_periods(periods)
    ordered = sorted(valid_periods.items(), key=lambda item: item[1])
    clusters = _build_clusters(ordered, tolerance)
    clusters.sort(key=lambda cluster: _cluster_median_period(cluster, valid_periods))
    return clusters


def _valid_periods(periods: dict[str, float]) -> dict[str, float]:
    """Return periods with None, NaN and non-positive values removed."""
    valid: dict[str, float] = {}
    for name, period in periods.items():
        if period is None:
            continue
        period = float(period)
        if not np.isnan(period) and period > 0:
            valid[name] = period
    return valid


def _build_clusters(ordered: list[tuple[str, float]], tolerance: float) -> list[list[str]]:
    """Group ordered (name, period) pairs into clusters wider than tolerance."""
    clusters: list[list[str]] = []
    current: list[str] = []
    first_period = 0.0
    for name, period in ordered:
        if current and period > first_period * (1.0 + tolerance):
            _keep_cluster(clusters, current)
            current = []
        if not current:
            first_period = period
        current.append(name)
    _keep_cluster(clusters, current)
    return clusters


def _keep_cluster(clusters: list[list[str]], members: list[str]) -> None:
    """Append a sorted cluster when it has at least two loops."""
    if len(members) >= 2:
        clusters.append(sorted(members))


def _cluster_median_period(cluster: list[str], periods: dict[str, float]) -> float:
    """Return the median period of loops in a cluster."""
    return float(np.median([periods[name] for name in cluster]))


def kendall_trend(
    values: ArrayLike, higher_is_worse: bool = True, min_points: int = DEFAULT_MIN_TREND_POINTS
) -> TrendResult:
    """Return the Kendall trend of a KPI series.

    tau is Kendall tau-a (pairs); slope_per_step is the Theil-Sen median slope.
    direction is "worsening"/"improving" when there are enough points and
    |tau| >= 0.5, otherwise "flat". NaN values are dropped.
    Raises ValueError if min_points < 3.
    """
    if min_points < MIN_TREND_POINTS:
        raise ValueError(f"min_points must be >= {MIN_TREND_POINTS}, got {min_points}")
    signal = _as_valid_signal(values)
    n = signal.size
    if n < 2:
        return TrendResult(n, 0.0, 0.0, "flat")

    row_indices, col_indices = np.triu_indices(n, k=1)
    deltas = signal[col_indices] - signal[row_indices]
    slope_per_step = float(np.median(deltas / (col_indices - row_indices)))
    tau = _kendall_tau_a(np.sign(deltas))
    direction = _trend_direction(tau, higher_is_worse, n, min_points)
    return TrendResult(n, tau, slope_per_step, direction)


def _kendall_tau_a(signs: np.ndarray) -> float:
    """Return Kendall tau-a from the signs of pairwise differences."""
    if signs.size == 0:
        return 0.0
    return float((np.count_nonzero(signs > 0) - np.count_nonzero(signs < 0)) / signs.size)


def _trend_direction(tau: float, higher_is_worse: bool, n: int, min_points: int) -> str:
    """Return "worsening", "improving" or "flat" from tau and sample size."""
    if n < min_points or abs(tau) < TREND_TAU_THRESHOLD:
        return "flat"
    rising = tau > 0
    is_worsening = rising == higher_is_worse
    return "worsening" if is_worsening else "improving"

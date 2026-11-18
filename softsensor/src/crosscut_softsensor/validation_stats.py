"""Agreement statistics between an online analyser and a lab series (issue #40).

Pure numpy functions on paired arrays. Differences are analyser minus lab, in the tag unit.
Nothing here knows a plant, a tag name or a threshold.
"""

from __future__ import annotations

import numpy as np

SECONDS_PER_DAY = 86400.0
MIN_PAIRS_FOR_SPREAD = 3  # A standard deviation and a straight-line fit need a few points.


def pair_statistics(analyser: np.ndarray, lab: np.ndarray, z: float) -> dict[str, float | int]:
    """Bias, RMSE, MAE, correlation and Bland-Altman limits of paired values."""
    diff = analyser - lab
    spread = float(np.std(diff, ddof=1)) if len(diff) >= MIN_PAIRS_FOR_SPREAD else float("nan")
    bias = float(np.mean(diff))
    return {
        "pairs": int(len(diff)),
        "bias": bias,
        "rmse": float(np.sqrt(np.mean(diff**2))),
        "mae": float(np.mean(np.abs(diff))),
        "correlation": correlation(analyser, lab),
        "diff_sd": spread,
        "loa_lower": bias - z * spread,
        "loa_upper": bias + z * spread,
    }


def correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Pearson r; NaN when either input is constant or has fewer than two points."""
    if len(x) < 2 or np.std(x) == 0.0 or np.std(y) == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def drift_statistics(t_s: np.ndarray, diff: np.ndarray, bins: int) -> dict:
    """Trend of the difference per day and its mean in `bins` equal-count time slices."""
    enough = len(diff) >= MIN_PAIRS_FOR_SPREAD
    slope_per_s = np.polyfit(t_s - t_s[0], diff, 1)[0] if enough else np.nan
    rows = []
    for index in np.array_split(np.arange(len(diff)), bins):
        if len(index) == 0:
            continue
        rows.append({"first_s": float(t_s[index[0]]), "last_s": float(t_s[index[-1]]),
                     "pairs": int(len(index)), "mean_difference": float(np.mean(diff[index]))})
    return {"trend_per_day": float(slope_per_s * SECONDS_PER_DAY), "bins": rows}


def gap_count(t_s: np.ndarray, gap_factor: float) -> tuple[float, int]:
    """Median sample period (s) and the number of steps longer than `gap_factor` periods."""
    if len(t_s) < 2:
        return float("nan"), 0
    steps = np.diff(t_s)
    period = float(np.median(steps))
    return period, int(np.count_nonzero(steps > gap_factor * period))

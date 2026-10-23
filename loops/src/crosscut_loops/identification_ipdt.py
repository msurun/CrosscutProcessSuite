"""Identification of an integrator-plus-dead-time (IPDT) model from a level-loop record.

Model: y(t) = y0 + beta*t + k * integral(u(s - theta) - u[0]) ds. The linear term beta
absorbs baseline drift and the unknown balance output, so steps, doublets and step trains
all work. theta is scanned on a grid (coarse, then a finer grid around the best point);
for each theta the other coefficients are ordinary least squares. Quality: R^2, a
moving-block bootstrap of the residuals for the slope, and separate up/down slopes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class IpdtSettings:
    """Thresholds and grid parameters of the IPDT identification."""

    max_delay_fraction: float = 0.25  # largest theta, as a fraction of the window
    grid_step_samples: float = 1.0  # coarse theta grid step, in sample periods
    refine_points: int = 41  # points of the fine grid spanning +-1 coarse step
    min_samples: int = 30
    min_out_range: float = 0.5  # OUT range below this (%) is "no move"
    move_threshold: float = 0.25  # OUT deviation (%) that counts as a move
    min_r2: float = 0.8
    min_pre_move_fraction: float = 0.2
    min_post_move_s: float = 300.0
    post_move_delay_factor: float = 5.0
    max_slope_rel_se: float = 0.2
    max_up_down_diff: float = 0.25
    min_direction_travel: float = 0.5  # OUT travel (%) needed per direction for up/down
    bootstrap_resamples: int = 200
    bootstrap_block: int = 10  # samples per residual block (keeps short-range correlation)
    bootstrap_seed: int = 12345


DEFAULT_SETTINGS = IpdtSettings()


@dataclass(frozen=True)
class IpdtModel:
    """Integrator with dead time; slope in PV unit per second per % OUT."""

    slope_per_s: float
    delay_s: float


@dataclass(frozen=True)
class IpdtFit:
    """Fitted model with quality figures and a verdict: ok, low_confidence or blocked."""

    model: IpdtModel
    r_squared: float
    slope_rel_se: float
    up_down_ratio: float | None
    baseline_slope: float
    verdict: str
    reasons: tuple[str, ...]


class IpdtIdentificationError(ValueError):
    """Raised when the signals are malformed (shape, length, non-finite, time order)."""


def _validate(
    t_s: object, out: object, pv: object, settings: IpdtSettings
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return float arrays (t, u, y) or raise IpdtIdentificationError."""
    t, u, y = (np.asarray(a, dtype=float) for a in (t_s, out, pv))
    if not (t.ndim == u.ndim == y.ndim == 1 and len(t) == len(u) == len(y)):
        raise IpdtIdentificationError("t, OUT and PV must be 1-D arrays of equal length")
    if len(t) < settings.min_samples:
        raise IpdtIdentificationError(f"need at least {settings.min_samples} samples")
    if not (np.all(np.isfinite(t)) and np.all(np.isfinite(u)) and np.all(np.isfinite(y))):
        raise IpdtIdentificationError("signals contain non-finite values")
    if np.any(np.diff(t) <= 0):
        raise IpdtIdentificationError("time must be strictly increasing")
    return t, u, y


def _cum_integral(t: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Cumulative trapezoid integral of x over t, starting at 0."""
    steps = 0.5 * (x[1:] + x[:-1]) * np.diff(t)
    return np.concatenate(([0.0], np.cumsum(steps)))


def _delayed_integral(t: np.ndarray, u: np.ndarray, theta: float) -> np.ndarray:
    """Integral of u(s - theta) - u[0]; u is held at u[0] before the record starts."""
    return _cum_integral(t, np.interp(t - theta, t, u) - u[0])


def _design(t: np.ndarray, u: np.ndarray, theta: float) -> np.ndarray:
    """Regressors [1, t, integral of delayed OUT]."""
    return np.column_stack([np.ones_like(t), t - t[0], _delayed_integral(t, u, theta)])


def _solve(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    """Least-squares coefficients and the sum of squared errors."""
    coef = np.linalg.lstsq(x, y, rcond=None)[0]
    return coef, float(np.sum((y - x @ coef) ** 2))


def _best_theta(t: np.ndarray, u: np.ndarray, y: np.ndarray, thetas: np.ndarray) -> int:
    """Index of the theta with the smallest SSE."""
    sse = [_solve(_design(t, u, th), y)[1] for th in thetas]
    return int(np.argmin(sse))


def _scan_delay(
    t: np.ndarray, u: np.ndarray, y: np.ndarray, s: IpdtSettings
) -> tuple[float, bool]:
    """Delay estimate (coarse grid, then fine grid) and whether it sits on a grid edge."""
    step = s.grid_step_samples * float(np.median(np.diff(t)))
    count = max(int(s.max_delay_fraction * (t[-1] - t[0]) / step), 3)
    coarse = np.arange(count + 1) * step
    i = _best_theta(t, u, y, coarse)
    edge = i == 0 or i == count
    fine = np.linspace(max(coarse[i] - step, 0.0), coarse[i] + step, s.refine_points)
    return float(fine[_best_theta(t, u, y, fine)]), edge


def _move_span(t: np.ndarray, u: np.ndarray, s: IpdtSettings) -> tuple[float, float]:
    """Time of the first OUT move and of the end of the last one."""
    first = np.nonzero(np.abs(u - u[0]) > s.move_threshold)[0]
    last = np.nonzero(np.abs(u - u[-1]) > s.move_threshold)[0]
    t_first = t[first[0]] if len(first) else t[-1]
    t_last = t[min(last[-1] + 1, len(t) - 1)] if len(last) else t[0]
    return float(t_first), float(t_last)


def _up_down_ratio(
    t: np.ndarray, u: np.ndarray, y: np.ndarray, theta: float, s: IpdtSettings
) -> float | None:
    """k(after increases) / k(after decreases); None when OUT moved one way only."""
    du = np.diff(u)
    up = np.concatenate(([0.0], np.cumsum(np.maximum(du, 0.0)))) + u[0]
    dn = np.concatenate(([0.0], np.cumsum(np.minimum(du, 0.0)))) + u[0]
    if up[-1] - u[0] < s.min_direction_travel or u[0] - dn[-1] < s.min_direction_travel:
        return None
    cols = [np.ones_like(t), t - t[0], _delayed_integral(t, up, theta)]
    cols.append(_delayed_integral(t, dn, theta))
    coef = _solve(np.column_stack(cols), y)[0]
    return float(coef[2] / coef[3]) if abs(coef[3]) > 1e-15 else None


def _block_resample(res: np.ndarray, block: int, rng: np.random.Generator) -> np.ndarray:
    """Moving-block bootstrap resample of the residual vector."""
    n = len(res)
    starts = rng.integers(0, n - block + 1, size=-(-n // block))
    return np.concatenate([res[a : a + block] for a in starts])[:n]


def _slope_rel_se(x: np.ndarray, y: np.ndarray, s: IpdtSettings) -> float:
    """Relative standard error of the slope from a moving-block bootstrap (fixed seed)."""
    coef = _solve(x, y)[0]
    fitted = x @ coef
    res = y - fitted
    pinv = np.linalg.pinv(x)
    rng = np.random.default_rng(s.bootstrap_seed)
    block = min(s.bootstrap_block, len(res))
    slopes = [
        float((pinv @ (fitted + _block_resample(res, block, rng)))[2])
        for _ in range(s.bootstrap_resamples)
    ]
    return float(np.std(slopes, ddof=1) / abs(coef[2])) if abs(coef[2]) > 1e-15 else float("inf")


def _r_squared(x: np.ndarray, y: np.ndarray) -> float:
    """1 - SSE/SST of the fit (0.0 when y is constant)."""
    sst = float(np.sum((y - y.mean()) ** 2))
    return 1.0 - _solve(x, y)[1] / sst if sst > 0 else 0.0


def _blocked_reasons(
    t: np.ndarray, u: np.ndarray, fit: tuple[float, float, bool], s: IpdtSettings
) -> list[str]:
    """Refusal codes from fit quality and the timing of the OUT moves; fit = (r2, theta, edge)."""
    r2, theta, edge = fit
    t_first, t_last = _move_span(t, u, s)
    window = float(t[-1] - t[0])
    reasons = []
    if r2 < s.min_r2:
        reasons.append("r2_below_0.8")
    if (t_first - t[0]) < s.min_pre_move_fraction * window:
        reasons.append("pre_move_lead_under_20pct")
    if (t[-1] - t_last) < max(s.post_move_delay_factor * theta, s.min_post_move_s):
        reasons.append("post_move_too_short")
    if edge:
        reasons.append("theta_on_grid_edge")
    return reasons


def _confidence_reasons(se: float, ratio: float | None, s: IpdtSettings) -> list[str]:
    """Low-confidence codes from the bootstrap error and the up/down comparison."""
    reasons = []
    if se > s.max_slope_rel_se:
        reasons.append("slope_se_over_20pct")
    if ratio is not None and abs(ratio - 1.0) > s.max_up_down_diff:
        reasons.append("up_down_differ_over_25pct")
    return reasons


def identify_ipdt(
    t_s: np.ndarray, out: np.ndarray, pv: np.ndarray, settings: IpdtSettings = DEFAULT_SETTINGS
) -> IpdtFit:
    """Identify slope (PV unit/s per % OUT) and dead time of an integrating process.

    Args:
        t_s: sample times in seconds, strictly increasing.
        out: controller output in % (open loop / manual data).
        pv: process value, same length.
        settings: thresholds; the bootstrap uses a fixed seed so results are reproducible.
    Returns:
        IpdtFit; verdict 'blocked' lists refusal codes in ``reasons``.
    Raises:
        IpdtIdentificationError: malformed input.
    """
    t, u, y = _validate(t_s, out, pv, settings)
    if float(np.ptp(u)) < settings.min_out_range:
        nothing = IpdtModel(0.0, 0.0)
        return IpdtFit(nothing, 0.0, float("inf"), None, 0.0, "blocked", ("no_out_move",))
    theta, edge = _scan_delay(t, u, y, settings)
    x = _design(t, u, theta)
    coef = _solve(x, y)[0]
    r2 = _r_squared(x, y)
    ratio = _up_down_ratio(t, u, y, theta, settings)
    blocked = _blocked_reasons(t, u, (r2, theta, edge), settings)
    se = _slope_rel_se(x, y, settings)
    low = _confidence_reasons(se, ratio, settings)
    verdict = "blocked" if blocked else ("low_confidence" if low else "ok")
    model = IpdtModel(float(coef[2]), theta)
    return IpdtFit(model, r2, se, ratio, float(coef[1]), verdict, tuple(blocked + low))


def fitted_pv(t_s: np.ndarray, out: np.ndarray, pv: np.ndarray, delay_s: float) -> np.ndarray:
    """Modelled PV y0 + beta*t + k' * integral(u(s - theta) - u[0]) ds over the record.

    y0, beta and k' are the least-squares coefficients at the identified delay ``delay_s``, i.e.
    the curve the fit drew through ``pv``; same length as the input.

    Raises:
        IpdtIdentificationError: malformed input.
    """
    t, u, y = _validate(t_s, out, pv, DEFAULT_SETTINGS)
    x = _design(t, u, delay_s)
    return np.asarray(x @ _solve(x, y)[0])

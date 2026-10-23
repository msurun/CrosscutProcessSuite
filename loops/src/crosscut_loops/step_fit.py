"""Step fitting for single loop events: FOPDT and IPDT models with uncertainty estimates.

Fits a dynamic model to a window of PV and OUT samples around one detected step event.
Uses variable projection (scan nonlinear parameters, linear least squares for the rest)
and reports parameter standard errors from the linear covariance and profile likelihood.
Numpy only; no scipy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from crosscut_loops.identification_ipdt import _effective_n, _f95_one

# Minimum samples required for a fit; below this the window is too short to identify.
MIN_SAMPLES = 30
# Minimum OUT range (in OUT units) required for a fit; below this there is no detectable move.
MIN_OUT_PTP = 1e-9
# Number of points in the coarse tau log grid.
TAU_GRID_POINTS = 25
# Fraction of tau_max defining the tau edge region (within this fraction of the upper bound means
# "at edge").
TAU_EDGE_FRACTION = 0.05
# Fraction of the window span or 600 s, whichever is smaller, used as the upper bound for theta.
THETA_MAX_WINDOW_FRACTION = 1 / 3
THETA_MAX_SECONDS = 600.0
# Number of points in the fine grid refinement around the best coarse cell.
REFINE_POINTS = 41
# Number of parameters in each model: y0, beta, K/tau/theta (FOPDT) or y0, beta, k/theta (IPDT).
N_PARAMS_FOPDT = 5
N_PARAMS_IPDT = 4
# Minimum allowed effective sample size fraction for autocorrelation inflation.
MIN_EFF_N_FRACTION = 0.05


@dataclass(frozen=True)
class Param:
    """A fitted parameter value and its standard error.

    ``se`` is NaN when the standard error is not available (e.g., the profile interval hit a
    grid edge).
    """

    value: float
    se: float


@dataclass(frozen=True)
class StepFit:
    """Result of fitting one step event.

    Attributes:
        model: 'fopdt' or 'ipdt'.
        gain: For FOPDT, K in PV units per OUT unit; None for IPDT.
        tau_s: For FOPDT, the time constant in seconds; None for IPDT.
        theta_s: Dead time in seconds for both models.
        slope: For IPDT, k in PV units per second per OUT unit; None for FOPDT.
        r2: Coefficient of determination (1 - SSE/SST of PV).
        rmse: Root mean squared error of the fit, in PV units.
        n: Number of samples in the fit.
        bic: Bayesian information criterion.
        fitted: Model PV values on the window samples, same length as inputs.
        edges: Subset of ('theta_at_edge', 'tau_at_edge') that apply.
    """

    model: str
    gain: Param | None
    tau_s: Param | None
    theta_s: Param
    slope: Param | None
    r2: float
    rmse: float
    n: int
    bic: float
    fitted: np.ndarray
    edges: tuple[str, ...]


class StepFitError(ValueError):
    """Raised when a step window cannot be fitted (too few samples, no move, degenerate)."""


def _clean_samples(
    t_s: np.ndarray, pv: np.ndarray, out: np.ndarray, pre: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Drop leading/trailing NaNs consistently; return cleaned arrays and the adjusted pre index.

    NaNs inside the window would break the model; we linear-interpolate them later for the
    delayed OUT lookup, but for the design matrix they are removed by dropping rows where any
    of the three signals is NaN. The caller adjusts ``pre`` to the new index of the original
    pre-th sample.
    """
    finite = np.isfinite(t_s) & np.isfinite(pv) & np.isfinite(out)
    t_clean, pv_clean, out_clean = t_s[finite], pv[finite], out[finite]
    if len(t_clean) < MIN_SAMPLES:
        raise StepFitError("too_few_samples")
    # Find the new index of the sample that was at position `pre` in the original arrays.
    pre_new = int(np.searchsorted(np.where(finite)[0], pre))
    return t_clean, pv_clean, out_clean, pre_new


def _validate_fit_inputs(
    t_s: np.ndarray, pv: np.ndarray, out: np.ndarray, pre: int, model: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Validate shapes, model name, and pre; clean NaNs; return cleaned arrays and pre index."""
    if model not in ("fopdt", "ipdt"):
        raise ValueError(f"model must be 'fopdt' or 'ipdt', got {model!r}")
    if not (t_s.ndim == pv.ndim == out.ndim == 1 and len(t_s) == len(pv) == len(out)):
        raise StepFitError("t_s, pv and out must be 1-D arrays of equal length")
    if not (np.all(np.isfinite(t_s)) and np.any(np.isfinite(pv)) and np.any(np.isfinite(out))):
        raise StepFitError("too_few_samples")
    if np.any(np.diff(t_s) <= 0):
        raise StepFitError("time must be strictly increasing")
    if pre < 5 or pre >= len(t_s):
        raise StepFitError("pre must be at least 5 and less than the window length")
    t_clean, pv_clean, out_clean, pre_new = _clean_samples(t_s, pv, out, pre)
    if np.ptp(out_clean) < MIN_OUT_PTP:
        raise StepFitError("no_out_move")
    return t_clean, pv_clean, out_clean, pre_new


def _delayed_input_fopdt(
    t: np.ndarray, u: np.ndarray, theta: float, u_ref: float
) -> np.ndarray:
    """Return u(t - theta), linearly interpolated between samples, shifted by u_ref.

    The delayed input feeds the first-order lag model. Linear interpolation handles the
    fractional delay between samples; u is held constant before the first sample and after the
    last sample.
    """
    if theta <= 0.0:
        return u - u_ref
    tau = t - theta
    k = np.clip(np.searchsorted(t, tau, side="right") - 1, 0, len(t) - 1)
    # Linear interpolation between samples k and k+1; before the first sample use u[0].
    result = np.where(tau <= t[0], u[0], u[k] + (u[np.minimum(k + 1, len(t) - 1)] - u[k]) *
                      (tau - t[k]) / np.where(np.diff(t)[k] > 0, np.diff(t)[k], 1.0))
    return result - u_ref


def _fopdt_design(
    t: np.ndarray, u: np.ndarray, theta: float, tau: float, u_ref: float
) -> np.ndarray:
    """Build the FOPDT design matrix [1, t, x(t)] where x is the lag response.

    x is computed by exact per-sample discretisation of x' = (u(t-theta) - u_ref - x)/tau.
    """
    dt = np.diff(t)
    if np.any(dt <= 0):
        raise StepFitError("degenerate")
    alpha = np.exp(-dt / tau)
    u_delayed = _delayed_input_fopdt(t, u, theta, u_ref)
    x = np.empty_like(t)
    x[0] = 0.0
    # Exact discretisation: x[k+1] = alpha[k] * x[k] + (1 - alpha[k]) * u_delayed[k].
    for k in range(len(t) - 1):
        x[k + 1] = alpha[k] * x[k] + (1.0 - alpha[k]) * u_delayed[k]
    return np.column_stack([np.ones_like(t), t - t[0], x])


def _ipdt_design(t: np.ndarray, u: np.ndarray, theta: float, u_ref: float) -> np.ndarray:
    """Build the IPDT design matrix [1, t, integral of delayed OUT shift].

    The integral of u(s - theta) - u_ref is evaluated analytically with zero-order-hold OUT,
    as in ``identification_ipdt._design`` but with the pre-event reference u_ref.
    """
    u_shifted = u - u_ref
    knots = np.concatenate(([0.0], np.cumsum(u_shifted[:-1] * np.diff(t))))
    tau = t - theta
    k = np.clip(np.searchsorted(t, tau, side="right") - 1, 0, len(t) - 1)
    integral = np.where(tau <= t[0], 0.0, knots[k] + u_shifted[k] * (tau - t[k]))
    return np.column_stack([np.ones_like(t), t - t[0], integral])


def _solve_linear(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    """Least-squares coefficients and SSE; raises StepFitError if the design is rank deficient."""
    try:
        coef, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    except np.linalg.LinAlgError as exc:
        raise StepFitError("degenerate") from exc
    if rank < x.shape[1]:
        raise StepFitError("degenerate")
    sse = float(np.sum((y - x @ coef) ** 2))
    return coef, sse


def _linear_sse(x: np.ndarray, y: np.ndarray) -> float:
    """SSE of the linear least-squares fit; used for profile scanning."""
    return _solve_linear(x, y)[1]


def _theta_grid(t: np.ndarray, dt: float) -> np.ndarray:
    """Coarse theta grid: 0 to theta_max (min(window/3, 600 s)) in steps of dt/2."""
    window_span = float(t[-1] - t[0])
    theta_max = min(window_span * THETA_MAX_WINDOW_FRACTION, THETA_MAX_SECONDS)
    step = dt / 2.0
    count = max(int(theta_max / step), 1)
    return np.arange(count + 1) * step


def _tau_grid(t: np.ndarray, dt: float) -> np.ndarray:
    """Log-spaced tau grid from dt to the window span, 25 points."""
    tau_min = dt
    tau_max = float(t[-1] - t[0])
    return np.geomspace(tau_min, tau_max, TAU_GRID_POINTS)


def _profile_se_from_grid(
    grid: np.ndarray, sse: np.ndarray, n_eff: float, n_params: int, best_index: int,
    edge_name: str = "theta_at_edge",
) -> tuple[float, tuple[float, float], tuple[str, ...]]:
    """Compute the profile standard error and edge flags for one nonlinear parameter.

    Returns:
        se: half of the 95% profile interval width divided by 1.96; NaN when an edge is hit
            and the interval cannot be estimated symmetrically.
        interval: (lower, upper) of the 95% profile interval.
        edges: tuple of edge flag strings (e.g., ('theta_at_edge',)).
    """
    dof = n_eff - n_params
    if dof <= 0:
        return float("nan"), (grid[best_index], grid[best_index]), ()
    limit = float(sse.min()) * (1.0 + _f95_one(dof) / dof)
    inside = grid[sse <= limit]
    lower, upper = float(inside.min()), float(inside.max())
    edges = []
    if best_index == 0 or best_index == len(grid) - 1:
        # At a grid edge, the interval is truncated; only flag if it is the upper edge.
        if best_index == len(grid) - 1:
            edges.append(edge_name)
        # If the interval hits the edge on one side, we cannot estimate the other side reliably;
        # use twice the one-sided width as a crude SE.
        se = (upper - lower) / 1.96
        return float(se), (lower, upper), tuple(edges)
    se = (upper - lower) / 1.96
    return float(se), (lower, upper), tuple(edges)


def _residual_autocorr_inflation(res: np.ndarray, n_params: int) -> float:
    """Inflation factor sqrt(n / n_eff) for residual autocorrelation.

    n_eff = clip(n * (1 - r1) / (1 + r1), 0.05*n, n), where r1 is the lag-1 autocorrelation.
    """
    if len(res) < 2:
        return 1.0
    r1 = float(np.corrcoef(res[:-1], res[1:])[0, 1]) if np.std(res) > 0 else 0.0
    n = len(res)
    n_eff_raw = n * (1.0 - r1) / (1.0 + r1) if r1 < 1.0 else 0.0
    n_eff = float(np.clip(n_eff_raw, MIN_EFF_N_FRACTION * n, n))
    return float(np.sqrt(n / max(n_eff, n_params + 1)))


def _fopdt_fit(
    t: np.ndarray, pv: np.ndarray, out: np.ndarray, pre: int
) -> StepFit:
    """Fit a first-order-plus-dead-time model."""
    u_ref = float(np.mean(out[:pre]))
    dt = float(np.median(np.diff(t)))
    theta_grid = _theta_grid(t, dt)
    tau_grid_full = _tau_grid(t, dt)

    # Coarse scan over theta and tau.
    best_sse = float("inf")
    best_theta_idx = 0
    best_tau_idx = 0
    for i, theta in enumerate(theta_grid):
        for j, tau in enumerate(tau_grid_full):
            x = _fopdt_design(t, out, theta, tau, u_ref)
            if np.linalg.matrix_rank(x) < x.shape[1]:
                continue
            sse = _linear_sse(x, pv)
            if sse < best_sse:
                best_sse = sse
                best_theta_idx = i
                best_tau_idx = j

    # Refine tau around the best cell.
    if best_tau_idx == 0:
        tau_refine = np.linspace(tau_grid_full[0], tau_grid_full[1], REFINE_POINTS)
    elif best_tau_idx == len(tau_grid_full) - 1:
        tau_refine = np.linspace(tau_grid_full[-2], tau_grid_full[-1], REFINE_POINTS)
    else:
        tau_refine = np.linspace(
            tau_grid_full[best_tau_idx - 1], tau_grid_full[best_tau_idx + 1], REFINE_POINTS
        )
    for j, tau in enumerate(tau_refine):
        x = _fopdt_design(t, out, theta_grid[best_theta_idx], tau, u_ref)
        if np.linalg.matrix_rank(x) < x.shape[1]:
            continue
        sse = _linear_sse(x, pv)
        if sse < best_sse:
            best_sse = sse
            best_tau_idx = j
            tau_grid_full = tau_refine  # Use the refined grid for profile intervals
    tau_opt = tau_grid_full[best_tau_idx]
    theta_opt = theta_grid[best_theta_idx]

    # Final fit and profile intervals.
    x_opt = _fopdt_design(t, out, theta_opt, tau_opt, u_ref)
    coef, sse = _solve_linear(x_opt, pv)
    if np.linalg.matrix_rank(x_opt) < x_opt.shape[1]:
        raise StepFitError("degenerate")
    n = len(pv)
    p = N_PARAMS_FOPDT
    bic = n * np.log(sse / n) + p * np.log(n)
    fitted = x_opt @ coef
    res = pv - fitted
    r2 = 1.0 - sse / float(np.sum((pv - np.mean(pv)) ** 2)) if np.var(pv) > 0 else 0.0
    rmse = float(np.sqrt(sse / n))

    # Standard error of K (gain) from linear covariance, with autocorrelation inflation.
    cov = np.linalg.inv(x_opt.T @ x_opt) * (sse / (n - p))
    infl = _residual_autocorr_inflation(res, p)
    se_gain = float(np.sqrt(cov[2, 2]) * infl)

    # Profile SEs for tau and theta.
    # Theta profile on the coarse grid.
    sse_theta = np.array(
        [_linear_sse(_fopdt_design(t, out, th, tau_opt, u_ref), pv) for th in theta_grid]
    )
    n_eff_theta = _effective_n(res, p)
    se_theta, _, edges_theta = _profile_se_from_grid(
        theta_grid, sse_theta, n_eff_theta, p, best_theta_idx
    )
    # Tau profile on the (possibly refined) grid.
    sse_tau = np.array(
        [_linear_sse(_fopdt_design(t, out, theta_opt, ta, u_ref), pv) for ta in tau_grid_full]
    )
    se_tau, _, edges_tau = _profile_se_from_grid(
        tau_grid_full, sse_tau, n_eff_theta, p, best_tau_idx, "tau_at_edge"
    )

    # Edge for tau: within 5% of the upper bound.
    tau_max = float(t[-1] - t[0])
    if tau_opt >= (1.0 - TAU_EDGE_FRACTION) * tau_max:
        edges_tau = tuple(dict.fromkeys(edges_tau + ("tau_at_edge",)))
    edges = tuple(dict.fromkeys(edges_theta + edges_tau))

    return StepFit(
        model="fopdt",
        gain=Param(float(coef[2]), se_gain),
        tau_s=Param(tau_opt, se_tau),
        theta_s=Param(theta_opt, se_theta),
        slope=None,
        r2=r2,
        rmse=rmse,
        n=n,
        bic=bic,
        fitted=fitted,
        edges=edges,
    )


def _ipdt_fit(t: np.ndarray, pv: np.ndarray, out: np.ndarray, pre: int) -> StepFit:
    """Fit an integrator-plus-dead-time model."""
    u_ref = float(np.mean(out[:pre]))
    dt = float(np.median(np.diff(t)))
    theta_grid = _theta_grid(t, dt)

    # Scan theta.
    best_sse = float("inf")
    best_theta_idx = 0
    for i, theta in enumerate(theta_grid):
        x = _ipdt_design(t, out, theta, u_ref)
        if np.linalg.matrix_rank(x) < x.shape[1]:
            continue
        sse = _linear_sse(x, pv)
        if sse < best_sse:
            best_sse = sse
            best_theta_idx = i
    theta_opt = theta_grid[best_theta_idx]

    x_opt = _ipdt_design(t, out, theta_opt, u_ref)
    coef, sse = _solve_linear(x_opt, pv)
    if np.linalg.matrix_rank(x_opt) < x_opt.shape[1]:
        raise StepFitError("degenerate")
    n = len(pv)
    p = N_PARAMS_IPDT
    bic = n * np.log(sse / n) + p * np.log(n)
    fitted = x_opt @ coef
    res = pv - fitted
    r2 = 1.0 - sse / float(np.sum((pv - np.mean(pv)) ** 2)) if np.var(pv) > 0 else 0.0
    rmse = float(np.sqrt(sse / n))

    # Standard error of k (slope) with autocorrelation inflation.
    cov = np.linalg.inv(x_opt.T @ x_opt) * (sse / (n - p))
    infl = _residual_autocorr_inflation(res, p)
    se_slope = float(np.sqrt(cov[2, 2]) * infl)

    # Profile SE for theta.
    sse_theta = np.array(
        [_linear_sse(_ipdt_design(t, out, th, u_ref), pv) for th in theta_grid]
    )
    n_eff_theta = _effective_n(res, p)
    se_theta, _, edges_theta = _profile_se_from_grid(
        theta_grid, sse_theta, n_eff_theta, p, best_theta_idx
    )

    return StepFit(
        model="ipdt",
        gain=None,
        tau_s=None,
        theta_s=Param(theta_opt, se_theta),
        slope=Param(float(coef[2]), se_slope),
        r2=r2,
        rmse=rmse,
        n=n,
        bic=bic,
        fitted=fitted,
        edges=edges_theta,
    )


def fit_step(
    t_s: np.ndarray, pv: np.ndarray, out: np.ndarray, pre: int, model: str
) -> StepFit:
    """Fit one step event window to an FOPDT or IPDT model.

    Args:
        t_s: sample times in seconds from any origin, strictly increasing, near-uniform.
        pv: process value samples.
        out: controller output samples (measured, whatever moved the process).
        pre: number of baseline samples before the event (>= 5).
        model: 'fopdt' or 'ipdt'.

    Returns:
        StepFit with parameter values, standard errors, quality metrics, and edge flags.

    Raises:
        StepFitError: 'too_few_samples', 'no_out_move', or 'degenerate'.
        ValueError: unknown model.
    """
    t, pv_clean, out_clean, pre_new = _validate_fit_inputs(t_s, pv, out, pre, model)
    if model == "fopdt":
        return _fopdt_fit(t, pv_clean, out_clean, pre_new)
    return _ipdt_fit(t, pv_clean, out_clean, pre_new)

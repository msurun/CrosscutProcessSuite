"""PLS1 soft sensor model: NIPALS fit, blocked cross-validation with a gap, validity flags.

Inputs and target are centred by the training mean and scaled by the sample standard deviation
(ddof=1). The number of components is chosen by contiguous-block K-fold cross-validation in
which a gap of the longest lag (in samples) is removed from the training side around each
validation block, then by the one-standard-error rule. Validity per row: missing_input,
out_of_range, extrapolation (Hotelling T2 of the scores or SPE of the x residual above the
empirical 99 % training limit) or ok.

The validity domain (feature min/max, T2 and SPE limits) normally comes from the labelled
training rows. Labels are sparse, so ``fit_pls(..., x_domain=rows)`` takes all valid lagged
rows of the training window (labelled or not) and computes the domain from them, projected
with the fitted model; ``domain_rows`` then records their number (0 = labelled rows used).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from crosscut_softsensor.config import SoftSensorConfig
from crosscut_softsensor.features import feature_names, lag_samples

SCHEMA_VERSION = "1.0.0"
RANGE_MARGIN = 0.05
LIMIT_QUANTILE = 0.99
_TINY = 1e-12
_ARRAYS = (
    "x_mean", "x_scale", "weights", "loadings", "y_loadings", "beta",
    "x_train_min", "x_train_max", "score_var",
)


class PlsModelError(ValueError):
    """Raised when a PLS model cannot be fitted or loaded."""


def nipals_pls1(
    x: np.ndarray, y: np.ndarray, a_max: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """PLS1 by NIPALS on centred data: weights W, x loadings P (p x A), y loadings q (A).

    Stops early when the deflated data hold no further covariance.
    """
    xr, yr = x.copy(), y.copy()
    ws: list[np.ndarray] = []
    ps: list[np.ndarray] = []
    qs: list[float] = []
    for _ in range(a_max):
        w = xr.T @ yr
        norm = float(np.linalg.norm(w))
        if norm < _TINY:
            break
        w = w / norm
        t = xr @ w
        tt = float(t @ t)
        if tt < _TINY:
            break
        p, q = xr.T @ t / tt, float(yr @ t) / tt
        xr, yr = xr - np.outer(t, p), yr - q * t
        ws.append(w)
        ps.append(p)
        qs.append(q)
    if not ws:
        raise PlsModelError("no PLS component: the target is uncorrelated with the inputs")
    return np.column_stack(ws), np.column_stack(ps), np.array(qs)


def _coefficients(w: np.ndarray, p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Regression vector in standardised space for the first len(q) components."""
    out: np.ndarray = w @ np.linalg.solve(p.T @ w, q)
    return out


def _all_betas(w: np.ndarray, p: np.ndarray, q: np.ndarray, a_max: int) -> np.ndarray:
    """Standardised coefficients for 1..a_max components (columns); padded with the last."""
    cols = [_coefficients(w[:, :k], p[:, :k], q[:k]) for k in range(1, w.shape[1] + 1)]
    cols += [cols[-1]] * (a_max - len(cols))
    return np.column_stack(cols)


def _stats(a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Column mean and sample standard deviation (ddof=1)."""
    return a.mean(axis=0), a.std(axis=0, ddof=1)


def cv_split(
    idx: np.ndarray, n_blocks: int, gap: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Contiguous validation blocks and their training positions.

    ``idx`` holds the (sorted) original sample index of every valid row. Training rows whose
    index lies within ``gap`` samples of a validation block (either side) are removed.
    """
    splits = []
    for val in np.array_split(np.arange(len(idx)), n_blocks):
        lo, hi = idx[val[0]] - gap, idx[val[-1]] + gap
        train = np.flatnonzero((idx < lo) | (idx > hi))
        if len(train) < 3:
            raise PlsModelError("the cross-validation gap leaves too few training rows")
        splits.append((train, val))
    return splits


def _fold_errors(
    x: np.ndarray, y: np.ndarray, split: tuple[np.ndarray, np.ndarray], a_max: int
) -> np.ndarray:
    """Squared validation errors (rows x 1..a_max components) for one fold."""
    train, val = split
    mx, sx = _stats(x[train])
    my, sy = _stats(y[train])
    sx = np.where(sx > 0, sx, 1.0)
    sy_f = float(sy) if sy > 0 else 1.0
    w, p, q = nipals_pls1((x[train] - mx) / sx, (y[train] - my) / sy_f, a_max)
    pred = ((x[val] - mx) / sx) @ _all_betas(w, p, q, a_max) * sy_f + my
    err: np.ndarray = (y[val][:, None] - pred) ** 2
    return err


def _cv_errors(
    x: np.ndarray, y: np.ndarray, splits: list[tuple[np.ndarray, np.ndarray]], a_max: int
) -> np.ndarray:
    """Squared cross-validation errors, one row per sample, one column per component count."""
    sq = np.zeros((len(y), a_max))
    for split in splits:
        sq[split[1]] = _fold_errors(x, y, split, a_max)
    return sq


def select_components(sq: np.ndarray) -> tuple[list[float], int]:
    """CV RMSE per count and the one-standard-error choice (smallest count within 1 SE)."""
    n = sq.shape[0]
    rmse = np.sqrt(sq.mean(axis=0))
    best = int(np.argmin(rmse))
    se = float(sq[:, best].std(ddof=1) / np.sqrt(n) / (2.0 * max(rmse[best], _TINY)))
    chosen = int(np.flatnonzero(rmse <= rmse[best] + se)[0]) + 1
    return [float(v) for v in rmse], chosen


def _valid_rows(
    x: np.ndarray, y: np.ndarray, names: list[str], min_rows: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Drop rows with NaN in x or y; return x, y and the original row indices."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.ndim != 2 or x.shape[1] != len(names) or y.shape != (x.shape[0],):
        raise PlsModelError(f"x must be samples by {len(names)} features and y a vector")
    keep = ~(np.isnan(x).any(axis=1) | np.isnan(y))
    if keep.sum() < min_rows:
        raise PlsModelError(f"too few valid rows: {int(keep.sum())} < {min_rows}")
    xv, yv = x[keep], y[keep]
    for j, name in enumerate(names):
        if not xv[:, j].std(ddof=1) > _TINY * max(1.0, abs(xv[:, j].mean())):
            raise PlsModelError(f"constant column: {name}")
    if not yv.std(ddof=1) > _TINY * max(1.0, abs(yv.mean())):
        raise PlsModelError("constant column: target")
    return xv, yv, np.flatnonzero(keep)


def fit_pls(
    x: np.ndarray,
    y: np.ndarray,
    config: SoftSensorConfig,
    n_components: int | None = None,
    x_domain: np.ndarray | None = None,
) -> PlsModel:
    """Fit a PLS1 model on lagged features ``x`` (rows = samples) and target ``y``.

    ``n_components`` overrides the cross-validated choice (for checks); the CV result is still
    reported. ``x_domain`` (all valid lagged rows of the training window) defines the validity
    domain instead of the labelled rows. Raises PlsModelError for constant columns, too few
    rows or a bad shape.
    """
    names = feature_names(config.input_tags, config.lags_s)
    gap = max(lag_samples(config.lags_s, config.sample_period_s))
    xv, yv, idx = _valid_rows(x, y, names, max(10, 3 * config.cv_blocks))
    a_max = min(config.max_components, len(names), len(yv) - 1)
    splits = cv_split(idx, config.cv_blocks, gap)
    rmse, chosen = select_components(_cv_errors(xv, yv, splits, a_max))
    used = chosen if n_components is None else _check_forced(n_components, len(names))
    domain = None if x_domain is None else _clean_domain(x_domain, len(names))
    return _final_model(xv, yv, config, (rmse, chosen, used), domain)


def _clean_domain(x_domain: np.ndarray, n_features: int) -> np.ndarray:
    """Rows of the domain sample without NaN; at least 10 are needed."""
    d = np.asarray(x_domain, dtype=float)
    if d.ndim != 2 or d.shape[1] != n_features:
        raise PlsModelError(f"x_domain must be samples by {n_features} features")
    d = d[~np.isnan(d).any(axis=1)]
    if len(d) < 10:
        raise PlsModelError(f"x_domain has too few valid rows: {len(d)}")
    return d


def _check_forced(n_components: int, n_features: int) -> int:
    """A forced component count must lie in 1..number of features."""
    if not 1 <= n_components <= n_features:
        raise PlsModelError(f"n_components {n_components} outside 1..{n_features}")
    return n_components


def _final_model(
    x: np.ndarray,
    y: np.ndarray,
    config: SoftSensorConfig,
    choice: tuple[list[float], int, int],
    domain: np.ndarray | None = None,
) -> PlsModel:
    """Fit on all valid rows with the chosen component count and derive the limits."""
    rmse, chosen, used = choice
    mx, sx = _stats(x)
    my, sy = _stats(y)
    w, p, q = nipals_pls1((x - mx) / sx, (y - my) / sy, used)
    beta = _coefficients(w, p, q) * sy / sx
    model = PlsModel(
        feature_names=tuple(feature_names(config.input_tags, config.lags_s)),
        x_mean=mx, x_scale=sx, y_mean=float(my), y_scale=float(sy),
        weights=w, loadings=p, y_loadings=q, n_components=w.shape[1],
        beta=beta, intercept=float(my - mx @ beta), cv_rmse=tuple(rmse),
        chosen_components=chosen, x_train_min=x.min(axis=0), x_train_max=x.max(axis=0),
        score_var=np.ones(w.shape[1]), t2_limit=0.0, spe_limit=0.0,
        lag_s=tuple(float(v) for v in config.lags_s),
        sample_period_s=float(config.sample_period_s), n_train=len(y),
    )
    return model._with_limits(x, domain)


@dataclass(frozen=True, eq=False)
class PlsModel:
    """Frozen PLS1 model in standardised space plus original-unit coefficients and limits."""

    feature_names: tuple[str, ...]
    x_mean: np.ndarray
    x_scale: np.ndarray
    y_mean: float
    y_scale: float
    weights: np.ndarray
    loadings: np.ndarray
    y_loadings: np.ndarray
    n_components: int
    beta: np.ndarray
    intercept: float
    cv_rmse: tuple[float, ...]
    chosen_components: int
    x_train_min: np.ndarray
    x_train_max: np.ndarray
    score_var: np.ndarray
    t2_limit: float
    spe_limit: float
    lag_s: tuple[float, ...]
    sample_period_s: float
    n_train: int
    domain_rows: int = 0

    @property
    def cv_sigma(self) -> float:
        """Cross-validated RMSE of the chosen component count (original units)."""
        return float(self.cv_rmse[self.chosen_components - 1])

    def _with_limits(self, x_train: np.ndarray, domain: np.ndarray | None = None) -> PlsModel:
        """Copy with score variances, the x range and empirical 99 % T2 / SPE limits.

        Score variances come from the labelled rows; range and limits from ``domain`` when
        given, else from the labelled rows.
        """
        t = ((x_train - self.x_mean) / self.x_scale) @ self._projection()
        var = t.var(axis=0, ddof=1) if len(t) > 1 else np.ones(t.shape[1])
        var = np.where(var > _TINY, var, 1.0)
        draft = replace(self, score_var=var)
        ref = x_train if domain is None else domain
        t2, spe = draft._diagnostics(ref)
        floor = 1e-10 * x_train.shape[1]
        return replace(
            draft, x_train_min=ref.min(axis=0), x_train_max=ref.max(axis=0),
            domain_rows=0 if domain is None else len(domain),
            t2_limit=float(np.quantile(t2, LIMIT_QUANTILE)),
            spe_limit=float(max(np.quantile(spe, LIMIT_QUANTILE), floor)),
        )

    def _diagnostics(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Hotelling T2 of the scores and SPE of the x residual per row (no NaN allowed)."""
        z = (x - self.x_mean) / self.x_scale
        t = z @ self._projection()
        return np.sum(t**2 / self.score_var, axis=1), np.sum((z - t @ self.loadings.T) ** 2, axis=1)

    def _projection(self) -> np.ndarray:
        """R = W (P^T W)^-1: maps standardised rows to scores."""
        out: np.ndarray = self.weights @ np.linalg.inv(self.loadings.T @ self.weights)
        return out

    def _as_rows(self, x: np.ndarray) -> np.ndarray:
        """Input as a 2-D float array with the right number of features."""
        a = np.atleast_2d(np.asarray(x, dtype=float))
        if a.shape[1] != len(self.feature_names):
            raise PlsModelError(f"x must have {len(self.feature_names)} columns")
        return a

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Estimates in original units; NaN for any row with a NaN input."""
        a = self._as_rows(x)
        out: np.ndarray = a @ self.beta + self.intercept
        out[np.isnan(a).any(axis=1)] = np.nan
        return out

    def validity(self, x: np.ndarray) -> list[str]:
        """Per row: missing_input > out_of_range > extrapolation > ok."""
        a = self._as_rows(x)
        missing = np.isnan(a).any(axis=1)
        filled = np.where(np.isnan(a), 0.0, a)
        span = self.x_train_max - self.x_train_min
        low, high = self.x_train_min - RANGE_MARGIN * span, self.x_train_max + RANGE_MARGIN * span
        outside = ((filled < low) | (filled > high)).any(axis=1)
        t2, spe = self._diagnostics(filled)
        extra = (t2 > self.t2_limit) | (spe > self.spe_limit)
        names = ["missing_input", "out_of_range", "extrapolation"]
        return [str(v) for v in np.select([missing, outside, extra], names, "ok")]

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary (lists and floats only)."""
        d: dict[str, Any] = {k: getattr(self, k).tolist() for k in _ARRAYS}
        d.update(
            kind="pls", schema_version=SCHEMA_VERSION,
            feature_names=list(self.feature_names), y_mean=self.y_mean,
            y_scale=self.y_scale, n_components=self.n_components,
            intercept=self.intercept, cv_rmse=list(self.cv_rmse),
            chosen_components=self.chosen_components, t2_limit=self.t2_limit,
            spe_limit=self.spe_limit, lag_s=list(self.lag_s),
            sample_period_s=self.sample_period_s, n_train=self.n_train,
        )
        if self.domain_rows:
            d["domain_rows"] = self.domain_rows
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PlsModel:
        """Rebuild a model from `to_dict` output."""
        if d.get("kind") != "pls" or d.get("schema_version") != SCHEMA_VERSION:
            raise PlsModelError("not a PLS model of schema 1.0.0")
        arr = {k: np.array(d[k], dtype=float) for k in _ARRAYS}
        return cls(
            feature_names=tuple(d["feature_names"]), y_mean=float(d["y_mean"]),
            y_scale=float(d["y_scale"]), n_components=int(d["n_components"]),
            intercept=float(d["intercept"]), cv_rmse=tuple(d["cv_rmse"]),
            chosen_components=int(d["chosen_components"]), t2_limit=float(d["t2_limit"]),
            spe_limit=float(d["spe_limit"]), lag_s=tuple(d["lag_s"]),
            sample_period_s=float(d["sample_period_s"]), n_train=int(d["n_train"]),
            domain_rows=int(d.get("domain_rows", 0)), **arr,
        )

    def sha256(self) -> str:
        """SHA-256 of the canonical JSON (sorted keys, compact separators)."""
        text = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

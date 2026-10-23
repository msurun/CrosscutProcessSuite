"""PCA monitoring model: Hotelling T2 and SPE (Q) with control limits.

Fits a standardised PCA, derives the T2 limit (Tracy, Young and Mason 1992;
MacGregor and Kourti 1995) and the SPE limit (Jackson and Mudholkar 1979).
Provides per-tag contributions and a JSON-ready, hashable representation.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from crosscut_anomaly.config import AnomalyConfig
from crosscut_anomaly.distributions import f_ppf, normal_ppf

SCHEMA_VERSION = "1.0.0"


class PcaModelError(ValueError):
    """Raised when a PCA model cannot be fitted or loaded."""


def t2_limit(n: int, k: int, alpha: float) -> float:
    """Hotelling T2 limit for new observations (phase 2), n training rows."""
    return k * (n * n - 1) / (n * (n - k)) * f_ppf(alpha, k, n - k)


def spe_limit(eigenvalues: Sequence[float], k: int, alpha: float) -> float:
    """Jackson-Mudholkar SPE limit from all eigenvalues and k retained."""
    resid = [float(v) for v in eigenvalues[k:]]
    th1, th2, th3 = (sum(v**i for v in resid) for i in (1, 2, 3))
    h0 = 1.0 - 2.0 * th1 * th3 / (3.0 * th2**2)
    c_alpha = normal_ppf(alpha)
    inner = (
        c_alpha * math.sqrt(2.0 * th2 * h0**2) / th1
        + 1.0
        + th2 * h0 * (h0 - 1.0) / th1**2
    )
    return float(th1 * inner ** (1.0 / h0))


def _choose_k(eigenvalues: np.ndarray, fraction: float) -> int:
    """Smallest k reaching the explained-variance fraction, in [1, p-1]."""
    cum = np.cumsum(eigenvalues) / eigenvalues.sum()
    k = int(np.searchsorted(cum, fraction - 1e-12) + 1)
    return max(1, min(k, len(eigenvalues) - 1))


def _clean_rows(x: np.ndarray, n_tags: int) -> np.ndarray:
    """Drop rows with NaN or +-inf and validate size and variance."""
    if x.ndim != 2 or x.shape[1] != n_tags:
        raise PcaModelError("x must be samples by tags")
    valid = x[np.isfinite(x).all(axis=1)]
    if len(valid) < max(50, 10 * n_tags):
        raise PcaModelError(f"too few valid rows: {len(valid)}")
    if np.any(valid.std(axis=0, ddof=1) <= 0.0):
        raise PcaModelError("a tag has zero variance")
    return valid


def _eigen_sorted(corr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Descending eigenpairs; largest-magnitude loading of each is positive."""
    values, vectors = np.linalg.eigh(corr)
    order = np.argsort(values)[::-1]
    values, vectors = values[order], vectors[:, order].copy()
    for i in range(vectors.shape[1]):
        if vectors[np.argmax(np.abs(vectors[:, i])), i] < 0:
            vectors[:, i] = -vectors[:, i]
    return np.clip(values, 0.0, None), vectors


def fit_pca(
    x: np.ndarray,
    tags: Sequence[str],
    variance_fraction: float = 0.90,
    alpha: float = 0.99,
) -> PcaModel:
    """Fit a PCA monitoring model on samples-by-tags data.

    The signature is ``fit_pca(x, tags, variance_fraction, alpha)``; to fit from an
    ``AnomalyConfig`` use ``fit_from_config(x, config)``. Rows with a non-finite value
    (NaN or +-inf) are dropped, never imputed.
    """
    tags = tuple(tags)
    if len(tags) < 2:
        raise PcaModelError("at least two tags are required")
    valid = _clean_rows(np.asarray(x, dtype=float), len(tags))
    mean, scale = valid.mean(axis=0), valid.std(axis=0, ddof=1)
    z = (valid - mean) / scale
    values, vectors = _eigen_sorted(np.atleast_2d(np.corrcoef(z, rowvar=False)))
    k = _choose_k(values, variance_fraction)
    n = len(valid)
    return PcaModel(
        tags=tags, mean=mean, scale=scale, loadings=vectors[:, :k],
        eigenvalues=values, k=k, n_train=n, alpha=alpha,
        t2_limit=t2_limit(n, k, alpha), spe_limit=spe_limit(values.tolist(), k, alpha),
    )


def fit_from_config(x: np.ndarray, config: AnomalyConfig) -> PcaModel:
    """Thin helper: ``fit_pca`` with the tags, variance_fraction and alpha of ``config``."""
    return fit_pca(x, config.tags, config.variance_fraction, config.alpha)


@dataclass(frozen=True)
class PcaModel:
    """Fitted standardised PCA model with T2 and SPE limits."""

    tags: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    loadings: np.ndarray
    eigenvalues: np.ndarray
    k: int
    n_train: int
    alpha: float
    t2_limit: float
    spe_limit: float

    def _standardise(self, x: np.ndarray) -> np.ndarray:
        """Standardise rows; rows with a non-finite value become all-NaN (no warnings)."""
        rows = np.atleast_2d(np.asarray(x, dtype=float))
        bad = ~np.isfinite(rows).all(axis=1)
        z: np.ndarray = (np.where(bad[:, None], np.nan, rows) - self.mean) / self.scale
        return z

    def scores(self, x: np.ndarray) -> np.ndarray:
        """Scores on the first k components (NaN rows give NaN)."""
        s: np.ndarray = self._standardise(x) @ self.loadings
        return s

    def t2(self, x: np.ndarray) -> np.ndarray:
        """Hotelling T2 per row (NaN rows give NaN)."""
        t = self.scores(x)
        out: np.ndarray = np.sum(t**2 / self.eigenvalues[: self.k], axis=1)
        return out

    def _residual(self, z: np.ndarray) -> np.ndarray:
        """Residual of standardised rows after projection on the model."""
        r: np.ndarray = z - (z @ self.loadings) @ self.loadings.T
        return r

    def spe(self, x: np.ndarray) -> np.ndarray:
        """Squared residual norm per row (NaN rows give NaN)."""
        out: np.ndarray = np.sum(self._residual(self._standardise(x)) ** 2, axis=1)
        return out

    def contributions(self, row: np.ndarray) -> dict[str, dict[str, float]]:
        """Per-tag shares of SPE and T2 for one row, each summing to 1.

        SPE: squared residual per tag over its total. T2: c_j = sum_i
        (t_i / lambda_i) p_ji x_j over the k components, truncated at 0 and
        renormalised; if all are <= 0 the shares are uniform.
        """
        z = self._standardise(row)
        if np.isnan(z).any():
            raise PcaModelError("contributions need a row without NaN or inf")
        res2 = self._residual(z)[0] ** 2
        t = z @ self.loadings
        c = np.clip(((t / self.eigenvalues[: self.k]) @ self.loadings.T)[0] * z[0], 0, None)
        return {
            "spe": dict(zip(self.tags, _normalise(res2).tolist(), strict=True)),
            "t2": dict(zip(self.tags, _normalise(c).tolist(), strict=True)),
        }

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary (lists and floats only)."""
        return {
            "kind": "pca", "schema_version": SCHEMA_VERSION,
            "tags": list(self.tags), "mean": self.mean.tolist(),
            "scale": self.scale.tolist(), "loadings": self.loadings.tolist(),
            "eigenvalues": self.eigenvalues.tolist(), "k": self.k,
            "n_train": self.n_train, "alpha": self.alpha,
            "t2_limit": self.t2_limit, "spe_limit": self.spe_limit,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PcaModel:
        """Rebuild a model from `to_dict` output."""
        if d.get("kind") != "pca" or d.get("schema_version") != SCHEMA_VERSION:
            raise PcaModelError("not a PCA model of schema 1.0.0")
        return cls(
            tags=tuple(d["tags"]), mean=np.array(d["mean"], dtype=float),
            scale=np.array(d["scale"], dtype=float),
            loadings=np.array(d["loadings"], dtype=float),
            eigenvalues=np.array(d["eigenvalues"], dtype=float),
            k=int(d["k"]), n_train=int(d["n_train"]), alpha=float(d["alpha"]),
            t2_limit=float(d["t2_limit"]), spe_limit=float(d["spe_limit"]),
        )

    def sha256(self) -> str:
        """SHA-256 of the canonical JSON (sorted keys, compact separators)."""
        text = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalise(v: np.ndarray) -> np.ndarray:
    """Scale non-negative values to sum 1 (uniform if the sum is zero)."""
    total = float(v.sum())
    return v / total if total > 0 else np.full(len(v), 1.0 / len(v))

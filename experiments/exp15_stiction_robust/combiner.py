"""Candidate C6 of exp15: logistic combiner on epoch-folded-wave features, one model per kind.

Features (fixed in amendment 1 of the README): he_fold, h3_out, h3_pv, Horch oddness, log2 of the
half period, ln of the peak prominence. Trained on synth14 dev seeds only; see train_c6.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import cand15
import numpy as np
from crosscut_loops import stiction_suspicion as ss
from crosscut_loops.stiction_curvefit import _detrend
from feature_study import harmonic_ratio

NAMES = ("he_fold", "h3_out", "h3_pv", "odd", "log2_half", "ln_prom")
L2 = 1.0
MODEL_PATH = Path(__file__).resolve().parent / "c6_model.json"
THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)


def features_c6(sp: np.ndarray, pv: np.ndarray, out: np.ndarray, kind: str) -> np.ndarray | None:
    """The six features on the C5 segment, or None when the record is not ranked."""
    sig = pv if kind == "L" else out
    seg = cand15.c5_segment(sp, pv, out, sig)
    if seg is None:
        return None
    sl, period = seg
    prominence = cand15.peak_prominence(_detrend(sig[sl]))
    if prominence is None:
        return None
    he = cand15.folded_index(_detrend(sig[sl]), period)
    odd = 0.0 if kind == "L" else ss._horch_oddness(out[sl], pv[sl], period)
    return np.array(
        [
            0.5 if he is None else he,
            harmonic_ratio(_detrend(out[sl]), period),
            harmonic_ratio(_detrend(pv[sl]), period),
            odd,
            float(np.log2(period / 2.0)),
            float(np.log(prominence[1])),
        ]
    )


class Combiner:
    """L2 logistic regression with balanced class weights on standardised features."""

    def __init__(self, keep: list[int] | None = None) -> None:
        """``keep`` selects feature columns (ablation); None keeps all six."""
        self.keep = list(range(len(NAMES))) if keep is None else keep
        self.mu = np.zeros(len(self.keep))
        self.sd = np.ones(len(self.keep))
        self.w = np.zeros(len(self.keep) + 1)

    def _design(self, x: np.ndarray) -> np.ndarray:
        z = (x[:, self.keep] - self.mu) / self.sd
        return np.hstack([np.ones((z.shape[0], 1)), z])

    def fit(self, x: np.ndarray, y: np.ndarray) -> Combiner:
        """Fit on feature rows ``x`` and 0/1 labels ``y`` (Newton steps, balanced weights)."""
        xs = x[:, self.keep]
        self.mu, self.sd = xs.mean(axis=0), xs.std(axis=0) + 1e-9
        a = self._design(x)
        weight = np.where(y == 1, 0.5 / max(y.mean(), 1e-9), 0.5 / max(1 - y.mean(), 1e-9))
        pen = L2 * np.eye(a.shape[1])
        pen[0, 0] = 0.0
        w = np.zeros(a.shape[1])
        for _ in range(40):
            p = 1.0 / (1.0 + np.exp(-a @ w))
            grad = a.T @ (weight * (p - y)) + pen @ w
            hess = a.T @ (a * (weight * p * (1 - p))[:, None]) + pen
            w -= np.linalg.solve(hess, grad)
        self.w = w
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Probability of stiction for each row."""
        return 1.0 / (1.0 + np.exp(-self._design(x) @ self.w))

    def to_dict(self) -> dict:
        """JSON-able parameters."""
        return {
            "keep": self.keep,
            "mu": self.mu.tolist(),
            "sd": self.sd.tolist(),
            "w": self.w.tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Combiner:
        """Rebuild from :meth:`to_dict`."""
        m = cls(d["keep"])
        m.mu, m.sd, m.w = np.array(d["mu"]), np.array(d["sd"]), np.array(d["w"])
        return m


def load_models() -> tuple[dict[str, Combiner], float]:
    """Per-kind models and the frozen threshold from c6_model.json."""
    d = json.loads(MODEL_PATH.read_text())
    return {k: Combiner.from_dict(v) for k, v in d["models"].items()}, float(d["threshold"])


def score_c6(
    sp: np.ndarray, pv: np.ndarray, out: np.ndarray, kind: str, models: dict[str, Combiner]
) -> float | None:
    """Stiction probability of the record, or None when it is not ranked."""
    f = features_c6(sp, pv, out, kind)
    return None if f is None else float(models[kind].predict(f[None, :])[0])

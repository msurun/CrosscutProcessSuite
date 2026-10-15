"""Features of one loop record and a small L2 logistic regression in numpy (exp14).

The features come from the exp13 oscillation window and tests; a missing test is encoded as a
neutral value plus a flag so the model can learn how much to trust the others.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
for sub in ("exp12_stiction_scoreboard", "exp13_stiction_suspicion"):
    sys.path.insert(0, str(HERE / sub))
import suspicion as su  # noqa: E402
from candidate_a import curve_fit_index_a  # noqa: E402

FEATURES = ("he", "he_missing", "horch", "horch_missing", "log_half", "regularity", "is_level")
L2 = 1.0


def features(sp: np.ndarray, pv: np.ndarray, op: np.ndarray, dt_s: float, kind: str):
    """Feature vector on the oscillation window, or None if the record has no window."""
    w = su.find_window(sp, pv)
    if w is None:
        return None
    sl = slice(w.start, w.stop)
    he = curve_fit_index_a((pv if kind == "L" else op)[sl], dt_s).index
    level = kind == "L"
    horch = 0.0 if level else su.horch_oddness(op[sl], pv[sl], w.period)
    return np.array(
        [
            0.5 if he is None else he,
            float(he is None),
            horch,
            float(level),
            np.log2(w.period / 2.0),
            w.regularity,
            float(level),
        ]
    )


class Logistic:
    """Standardised logistic regression with an L2 penalty, fitted by Newton steps."""

    def __init__(self, keep: list[int] | None = None) -> None:
        """``keep`` selects feature columns (ablation); None keeps all."""
        self.keep = keep
        self.mu = self.sd = self.w = None

    def _prep(self, x: np.ndarray) -> np.ndarray:
        x = x if self.keep is None else x[:, self.keep]
        return np.hstack([np.ones((x.shape[0], 1)), (x - self.mu) / self.sd])

    def fit(self, x: np.ndarray, y: np.ndarray) -> Logistic:
        """Fit on rows ``x`` and labels ``y`` (0/1)."""
        xs = x if self.keep is None else x[:, self.keep]
        self.mu, self.sd = xs.mean(axis=0), xs.std(axis=0) + 1e-9
        a = self._prep(x)
        w = np.zeros(a.shape[1])
        pen = L2 * np.eye(a.shape[1])
        pen[0, 0] = 0.0
        for _ in range(30):
            p = 1.0 / (1.0 + np.exp(-a @ w))
            grad = a.T @ (p - y) + pen @ w
            hess = a.T @ (a * (p * (1 - p))[:, None]) + pen
            w -= np.linalg.solve(hess, grad)
        self.w = w
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Probability of stiction for each row."""
        return 1.0 / (1.0 + np.exp(-self._prep(x) @ self.w))

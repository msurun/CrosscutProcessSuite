"""Lab bias tracker for the soft sensor: EWMA of (lab - estimate) and a drift flag.

A lab result is 'over' when the smoothed bias exceeds k_sigma times the cross-validated RMSE;
drift is raised after `consecutive` overs in a row. NaN pairs are ignored and counted.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


class BiasTrackerError(ValueError):
    """Raised for an invalid tracker setting or state."""


@dataclass(frozen=True)
class BiasState:
    """Tracker state after an update (bias_ewma is NaN before the first valid result)."""

    bias_ewma: float = math.nan
    n_updates: int = 0
    n_over: int = 0
    drift: bool = False
    last_t_s: float = math.nan
    n_ignored: int = 0


class BiasTracker:
    """EWMA bias of lab minus estimate with a consecutive-exceedance drift rule."""

    def __init__(
        self, sigma_cv: float, weight: float = 0.3, k_sigma: float = 2.0, consecutive: int = 3
    ) -> None:
        if not sigma_cv > 0 or not 0 < weight <= 1 or not k_sigma > 0 or consecutive < 1:
            raise BiasTrackerError("need sigma_cv>0, 0<weight<=1, k_sigma>0, consecutive>=1")
        self.sigma_cv = float(sigma_cv)
        self.weight = float(weight)
        self.k_sigma = float(k_sigma)
        self.consecutive = int(consecutive)
        self._state = BiasState()

    @property
    def state(self) -> BiasState:
        """Current state."""
        return self._state

    def reset(self) -> None:
        """Forget all lab results."""
        self._state = BiasState()

    def update(self, t_s: float, y_lab: float, y_hat: float) -> BiasState:
        """Fold in one lab result against the estimate at its sample time."""
        s = self._state
        if math.isnan(y_lab) or math.isnan(y_hat):
            self._state = BiasState(
                s.bias_ewma, s.n_updates, s.n_over, s.drift, s.last_t_s, s.n_ignored + 1
            )
            return self._state
        e = float(y_lab) - float(y_hat)
        bias = e if s.n_updates == 0 else (1 - self.weight) * s.bias_ewma + self.weight * e
        over = abs(bias) > self.k_sigma * self.sigma_cv
        n_over = s.n_over + 1 if over else 0
        self._state = BiasState(
            bias, s.n_updates + 1, n_over, n_over >= self.consecutive, float(t_s), s.n_ignored
        )
        return self._state

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready settings and state."""
        return {
            "sigma_cv": self.sigma_cv, "weight": self.weight, "k_sigma": self.k_sigma,
            "consecutive": self.consecutive, "state": asdict(self._state),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BiasTracker:
        """Rebuild a tracker from `to_dict` output."""
        try:
            tracker = cls(d["sigma_cv"], d["weight"], d["k_sigma"], d["consecutive"])
            tracker._state = BiasState(**d["state"])
        except (KeyError, TypeError) as exc:
            raise BiasTrackerError(f"invalid tracker dictionary: {exc}") from exc
        return tracker

"""Describe the reference controller's limits and numerical settings.

Limits use signal engineering units; rates use engineering units per second.
"""

from dataclasses import dataclass

import numpy as np

from .model import Array, FopdtModel


@dataclass(frozen=True)
class Limits:
    """Store hard MV intervals, soft CV intervals and per-variable tuning.

    Smaller CV priority numbers mean higher priority; equal numbers relax together.
    """

    mv_lower: Array
    mv_upper: Array
    cv_lower: Array
    cv_upper: Array
    priorities: Array
    move_max: Array
    rate_max: Array
    target_rate: Array
    funnel_start: Array
    funnel_end: Array

    def __post_init__(self) -> None:
        """Own finite vectors so caller mutation cannot change a controller."""
        for name in self.__dataclass_fields__:
            values = np.array(getattr(self, name), dtype=float, copy=True)
            if values.ndim != 1 or not values.size or not np.all(np.isfinite(values)):
                raise ValueError(f"{name} must be a nonempty finite vector")
            values.setflags(write=False)
            object.__setattr__(self, name, values)
        validate_limits(self)


def validate_limits(limits: Limits) -> None:
    """Reject mismatched dimensions, reversed intervals and negative tuning."""
    for names in (("mv_upper", "move_max", "rate_max"), (
        "cv_upper", "priorities", "target_rate", "funnel_start", "funnel_end"
    )):
        expected = limits.mv_lower.shape if names[0] == "mv_upper" else limits.cv_lower.shape
        if any(getattr(limits, name).shape != expected for name in names):
            raise ValueError("Limit and tuning vectors must match their MV or CV dimensions")
    if np.any(limits.mv_lower > limits.mv_upper) or np.any(limits.cv_lower > limits.cv_upper):
        raise ValueError("Lower limits must not exceed upper limits")
    for name in ("priorities", "move_max", "rate_max", "target_rate", "funnel_end"):
        if np.any(getattr(limits, name) < 0):
            raise ValueError(f"{name} must be nonnegative")
    if np.any(limits.funnel_start < limits.funnel_end):
        raise ValueError("Funnel start widths must be at least the end widths")


@dataclass(frozen=True)
class Settings:
    """Set horizons in samples and the move penalty in squared CV/MV units."""

    prediction_horizon: int = 60
    move_horizon: int = 8
    move_suppression: float = 1.0

    def __post_init__(self) -> None:
        """Reject invalid horizons and an indefinite move cost."""
        if not 1 <= self.move_horizon <= self.prediction_horizon:
            raise ValueError("Require 1 <= move horizon <= prediction horizon")
        if not np.isfinite(self.move_suppression) or self.move_suppression <= 0:
            raise ValueError("Move suppression must be finite and positive")


@dataclass(frozen=True)
class Controller:
    """Bundle immutable model, limits and tuning; first columns are the MVs."""

    model: FopdtModel
    limits: Limits
    settings: Settings = Settings()

    def __post_init__(self) -> None:
        """Check that every CV and MV has a model path."""
        outputs, inputs = self.model.gains.shape
        if outputs != len(self.limits.cv_lower) or inputs < len(self.limits.mv_lower):
            raise ValueError("Model dimensions must cover every declared CV and MV")


def priority_weights(priorities: Array) -> Array:
    """Return positive quadratic weights following the declared CV ordering."""
    # Rank-based weights avoid dependence on arbitrary priority-number spacing.
    # Q is a relative cost per squared CV unit; lower priority gets a smaller weight.
    ranks = np.searchsorted(np.unique(priorities), priorities)
    return 10.0 ** (-ranks.astype(float))

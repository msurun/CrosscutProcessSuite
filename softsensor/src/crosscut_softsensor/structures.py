"""Fit interchangeable data-driven, physics and residual soft-sensor structures.

Inputs are numeric arrays (samples, features) in declared role units; targets and
predictions are (samples,) in the target unit. Scaling is fitted on training rows only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, Self

import numpy as np

DEFAULT_PENALTY = 1e-6  # Dimensionless penalty on standardised ridge coefficients.
DEFAULT_ESTIMATORS = 200  # Number of additive decision stumps.
DEFAULT_LEARNING_RATE = 0.1  # Dimensionless shrinkage of each residual update.


class Structure(Protocol):
    """Common train/predict contract; predictions retain the fitted target's unit."""

    def fit(self, x: np.ndarray, y: np.ndarray) -> Self:
        """Fit on finite (samples, features) inputs and (samples,) labels."""
        ...

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Return (samples,) estimates, with NaN for rows with missing inputs."""
        ...


def _training_arrays(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Validate finite paired training arrays without silently dropping labels."""
    features, target = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if features.ndim != 2 or features.shape[1] == 0 or target.shape != (len(features),):
        raise ValueError("training shape must be (samples, features) and target (samples,)")
    if len(features) < 2 or not np.isfinite(features).all() or not np.isfinite(target).all():
        raise ValueError("fit requires at least two finite training rows; filter missing rows")
    return features, target


def _prediction_array(x: np.ndarray, feature_count: int) -> np.ndarray:
    """Check prediction columns against the training role order."""
    features = np.asarray(x, dtype=float)
    if features.ndim != 2 or features.shape[1] != feature_count:
        raise ValueError(f"prediction shape must be (samples, {feature_count})")
    return features


class RidgeStructure:
    """Standardised ridge with an unpenalised intercept and closed-form solution."""

    def __init__(self, penalty: float = DEFAULT_PENALTY) -> None:
        """Set a nonnegative dimensionless coefficient penalty."""
        if not np.isfinite(penalty) or penalty < 0:
            raise ValueError("ridge penalty must be finite and nonnegative")
        self.penalty = penalty
        self.is_fitted = False

    def fit(self, x: np.ndarray, y: np.ndarray) -> Self:
        """Fit beta = (Z'Z + penalty I)^-1 Z'(y - mean(y))."""
        features, target = _training_arrays(x, y)
        self.mean = features.mean(axis=0)
        self.scale = features.std(axis=0)
        self.scale = np.where(self.scale > 0, self.scale, 1.0)
        # Z is dimensionless (n,p); beta and the unpenalised intercept have target units.
        standardised = (features - self.mean) / self.scale
        self.intercept = float(target.mean())
        gram = standardised.T @ standardised + self.penalty * np.eye(features.shape[1])
        self.coefficients = np.linalg.lstsq(
            gram, standardised.T @ (target - self.intercept), rcond=None
        )[0]
        self.is_fitted = True
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Return target-unit estimates using the training mean and scale."""
        if not self.is_fitted:
            raise ValueError("fit the ridge structure before predict")
        features = _prediction_array(x, len(self.mean))
        prediction = (features - self.mean) / self.scale @ self.coefficients + self.intercept
        return np.where(np.isfinite(features).all(axis=1), prediction, np.nan)


@dataclass(frozen=True)
class _Stump:
    """A threshold in one input's units and two leaf means in target units."""

    column: int
    threshold: float
    left: float
    right: float

    def predict(self, features: np.ndarray) -> np.ndarray:
        """Choose the constant leaf on either side of the fitted threshold."""
        return np.where(features[:, self.column] <= self.threshold, self.left, self.right)


def _column_stump(values: np.ndarray, residual: np.ndarray, column: int) -> tuple[float, _Stump]:
    """Find the least-squares threshold by prefix sums, without enumerating row masks."""
    order = np.argsort(values, kind="stable")
    sorted_values, sorted_residual = values[order], residual[order]
    counts = np.arange(1, len(values))
    totals = np.cumsum(sorted_residual)[:-1]
    remaining = residual.sum() - totals
    # SSE = sum(r²) - sum(r_left)²/n_left - sum(r_right)²/n_right, in target units².
    scores = np.sum(residual**2) - totals**2 / counts - remaining**2 / (len(values) - counts)
    scores[sorted_values[:-1] == sorted_values[1:]] = np.inf
    best = int(np.argmin(scores))
    threshold = float((sorted_values[best] + sorted_values[best + 1]) / 2)
    stump = _Stump(column, threshold, float(totals[best] / counts[best]),
                   float(remaining[best] / (len(values) - counts[best])))
    return float(scores[best]), stump


def _fit_stump(features: np.ndarray, residual: np.ndarray) -> _Stump:
    """Choose the best feature threshold, or the residual mean if all inputs are constant."""
    candidates = [_column_stump(features[:, column], residual, column)
                  for column in range(features.shape[1])]
    score, stump = min(candidates, key=lambda candidate: candidate[0])
    if not np.isfinite(score):
        return _Stump(0, float(features[0, 0]), float(residual.mean()), float(residual.mean()))
    return stump


class GradientBoostingStructure:
    """Squared-error gradient boosting with exact one-split numpy regression trees."""

    def __init__(self, n_estimators: int = DEFAULT_ESTIMATORS,
                 learning_rate: float = DEFAULT_LEARNING_RATE) -> None:
        """Set the number of residual fits and their dimensionless shrinkage."""
        if not isinstance(n_estimators, int) or n_estimators < 1:
            raise ValueError("n_estimators must be a positive integer")
        if not np.isfinite(learning_rate) or not 0 < learning_rate <= 1:
            raise ValueError("learning_rate must be finite and in (0, 1]")
        self.n_estimators, self.learning_rate = n_estimators, learning_rate
        self.is_fitted = False

    def fit(self, x: np.ndarray, y: np.ndarray) -> Self:
        """Fit F_m = F_(m-1) + learning_rate * stump(y - F_(m-1))."""
        features, target = _training_arrays(x, y)
        self.feature_count = features.shape[1]
        self.intercept = float(target.mean())
        estimate = np.full(len(target), self.intercept)
        self.stumps = []
        # Negative squared-error gradient y-F has target units, as does each stump leaf.
        for _ in range(self.n_estimators):
            stump = _fit_stump(features, target - estimate)
            estimate += self.learning_rate * stump.predict(features)
            self.stumps.append(stump)
        self.is_fitted = True
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Sum fitted residual corrections in target units."""
        if not self.is_fitted:
            raise ValueError("fit the gradient boosting structure before predict")
        features = _prediction_array(x, self.feature_count)
        prediction = np.full(len(features), self.intercept)
        for stump in self.stumps:
            prediction += self.learning_rate * stump.predict(features)
        return np.where(np.isfinite(features).all(axis=1), prediction, np.nan)


class PhysicsStructure:
    """Calibrate a declared formula as y = offset + gain * formula(role inputs)."""

    def __init__(self, formula: Callable[[np.ndarray], np.ndarray]) -> None:
        """Accept a pure formula mapping (n,p) role-unit inputs to (n,) physical values."""
        self.formula = formula
        self.is_fitted = False

    def physical_values(self, x: np.ndarray) -> np.ndarray:
        """Evaluate the declared formula, requiring exactly one physical value per row."""
        values = np.asarray(self.formula(x), dtype=float)
        if values.shape != (len(x),):
            raise ValueError("physics formula must return shape (samples,)")
        return values

    def fit(self, x: np.ndarray, y: np.ndarray) -> Self:
        """Fit gain and offset by ordinary least squares on finite physical values."""
        features, target = _training_arrays(x, y)
        physical = self.physical_values(features)
        if not np.isfinite(physical).all():
            raise ValueError("physics formula must be finite on training rows; check role domains")
        # Formula values are (n,) in declared physical units; gain converts them to target units.
        design = np.column_stack((np.ones(len(physical)), physical))
        self.offset, self.gain = np.linalg.lstsq(design, target, rcond=None)[0]
        self.feature_count = features.shape[1]
        self.is_fitted = True
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Return calibrated formula values in the target unit."""
        if not self.is_fitted:
            raise ValueError("fit the physics structure before predict")
        features = _prediction_array(x, self.feature_count)
        prediction = self.offset + self.gain * self.physical_values(features)
        return np.where(np.isfinite(features).all(axis=1), prediction, np.nan)


class HybridStructure:
    """Calibrated physics plus standardised ridge fitted to its target-unit residual."""

    def __init__(self, formula: Callable[[np.ndarray], np.ndarray],
                 penalty: float = DEFAULT_PENALTY) -> None:
        """Create independent physics and residual fits with a shared role order."""
        self.physics = PhysicsStructure(formula)
        self.residual = RidgeStructure(penalty)

    def fit(self, x: np.ndarray, y: np.ndarray) -> Self:
        """Fit physics first, then ridge to y minus its calibrated prediction."""
        features, target = _training_arrays(x, y)
        self.physics.fit(features, target)
        self.residual.fit(features, target - self.physics.predict(features))
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Return physics plus process residual correction, both in target units."""
        return self.physics.predict(x) + self.residual.predict(x)

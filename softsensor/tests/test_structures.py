"""Check the common structure interface on independent synthetic relations.

No process records or fitted plant parameters are used in these recovery checks.
"""

import numpy as np
import pytest
from crosscut_softsensor.structures import (
    GradientBoostingStructure,
    HybridStructure,
    PhysicsStructure,
    RidgeStructure,
)


def ratio_formula(features: np.ndarray) -> np.ndarray:
    """Return a dimensionless ratio for positive denominator inputs."""
    return features[:, 0] / features[:, 1]


def test_ridge_recovers_a_scaled_linear_relation() -> None:
    """Train-only scaling preserves the target unit despite unequal feature scales."""
    features = np.random.default_rng(23).normal(size=(200, 2)) * [1, 1000]
    target = 7 + features @ np.array([3, -0.002])
    model = RidgeStructure().fit(features[:150], target[:150])
    np.testing.assert_allclose(model.predict(features[150:]), target[150:], atol=1e-5)


def test_boosting_recovers_a_piecewise_relation() -> None:
    """Squared-error stumps recover a nonlinear step without sklearn."""
    features = np.linspace(-2, 2, 200)[:, None]
    target = np.where(features[:, 0] < 0, -3.0, 5.0)
    model = GradientBoostingStructure().fit(features[::2], target[::2])
    np.testing.assert_allclose(model.predict(features[1::2]), target[1::2], atol=0.01)


def test_physics_recovers_gain_and_offset_of_a_ratio() -> None:
    """Calibrated ratio output is in target units."""
    features = np.random.default_rng(23).uniform(1, 4, size=(200, 2))
    target = 2 + 3 * ratio_formula(features)
    model = PhysicsStructure(ratio_formula).fit(features[:150], target[:150])
    np.testing.assert_allclose(model.predict(features[150:]), target[150:], atol=1e-10)


def test_hybrid_recovers_process_correction_to_physics() -> None:
    """A linear correction supplies information absent from the physics ratio."""
    physical_inputs = np.random.default_rng(23).uniform(1, 4, size=(500, 2))
    # Paired opposite corrections make the process residual independent of the ratio.
    features = np.column_stack((np.repeat(physical_inputs, 2, axis=0),
                                np.tile([-1.0, 1.0], len(physical_inputs))))
    target = 2 + 3 * ratio_formula(features) + 2 * features[:, 2]
    model = HybridStructure(ratio_formula).fit(features, target)
    np.testing.assert_allclose(model.predict(features), target, atol=1e-5)


@pytest.mark.parametrize("model", [RidgeStructure(), GradientBoostingStructure()])
def test_predict_requires_a_fitted_structure(model: object) -> None:
    """Misuse fails with actionable errors instead of arbitrary attribute failures."""
    with pytest.raises(ValueError, match="fit"):
        model.predict(np.ones((3, 1)))


def test_ridge_rejects_a_target_with_the_wrong_shape() -> None:
    """The one-target interface refuses matrices of labels."""
    with pytest.raises(ValueError, match="shape"):
        RidgeStructure().fit(np.ones((3, 1)), np.ones((3, 1)))

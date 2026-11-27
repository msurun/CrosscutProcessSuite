"""Exercise validation of the reference controller's limits and settings.

Every dataclass in config.py must accept a minimal valid instance and reject
every input its __post_init__ checks, one parametrized case per check.
"""

import numpy as np
import pytest
from crosscut_mpc import Controller, FopdtModel, Limits, Settings
from mpc_helpers import make_controller

ALL_LIMIT_FIELDS = [
    "mv_lower", "mv_upper", "cv_lower", "cv_upper",
    "priorities", "move_max", "rate_max", "target_rate",
    "funnel_start", "funnel_end",
]


def limits_values(**changes: object) -> dict[str, object]:
    """Copy mpc_helpers' 1 MV / 1 CV defaults so a test can override one field.

    The values mirror make_controller's defaults, so Limits tests do not need
    the model; Limits rejects before Controller sees the dimensions.
    """
    values = dict(
        mv_lower=np.full(1, -5.0),
        mv_upper=np.full(1, 5.0),
        cv_lower=np.full(1, -10.0),
        cv_upper=np.full(1, 10.0),
        priorities=np.arange(1),
        move_max=np.full(1, 0.5),
        rate_max=np.full(1, 0.5),
        target_rate=np.full(1, 10.0),
        funnel_start=np.full(1, 20.0),
        funnel_end=np.full(1, 10.0),
    )
    values.update(changes)
    return values


def test_a_minimal_limits_instance_stores_its_bands() -> None:
    limits = Limits(**limits_values())
    assert np.all(limits.mv_lower == -5.0)
    assert np.all(limits.cv_upper == 10.0)
    assert np.all(np.isfinite(limits.funnel_end))


def test_a_limits_instance_does_not_share_arrays_with_the_caller() -> None:
    raw = np.array([-5.0])
    limits = Limits(**limits_values(mv_lower=raw))
    raw[0] = 99.0
    assert limits.mv_lower[0] == -5.0


@pytest.mark.parametrize("field", ALL_LIMIT_FIELDS)
def test_limits_rejects_fields_that_are_not_one_dimensional(field: str) -> None:
    with pytest.raises(ValueError, match=f"{field} must be a nonempty finite vector"):
        Limits(**limits_values(**{field: [[-5.0]]}))


@pytest.mark.parametrize(("field", "value"), [
    ("mv_lower", np.array([], dtype=float)),
    ("priorities", 0.0),
])
def test_limits_rejects_empty_or_scalar_fields(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=f"{field} must be a nonempty finite vector"):
        Limits(**limits_values(**{field: value}))


@pytest.mark.parametrize(("field", "value"), [
    ("mv_lower", np.nan),
    ("cv_upper", np.inf),
    ("funnel_end", -np.inf),
])
def test_limits_rejects_nonfinite_fields(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=f"{field} must be a nonempty finite vector"):
        Limits(**limits_values(**{field: [value]}))


@pytest.mark.parametrize(("field", "value"), [
    ("mv_upper", [1.0, 2.0]),
    ("move_max", [0.1, 0.2]),
    ("rate_max", [0.1, 0.2]),
    ("cv_upper", [1.0, 2.0]),
    ("priorities", [0.0, 1.0]),
    ("target_rate", [1.0, 2.0]),
    ("funnel_start", [20.0, 30.0]),
    ("funnel_end", [10.0, 20.0]),
])
def test_limits_rejects_mismatched_mv_or_cv_dimensions(field: str, value: list[float]) -> None:
    message = "Limit and tuning vectors must match their MV or CV dimensions"
    with pytest.raises(ValueError, match=message):
        Limits(**limits_values(**{field: value}))


@pytest.mark.parametrize(("field", "value"), [
    ("mv_lower", [10.0]),
    ("mv_upper", [-6.0]),
    ("cv_lower", [20.0]),
    ("cv_upper", [-20.0]),
])
def test_limits_rejects_lower_bounds_above_upper_bounds(field: str, value: list[float]) -> None:
    with pytest.raises(ValueError, match="Lower limits must not exceed upper limits"):
        Limits(**limits_values(**{field: value}))


@pytest.mark.parametrize(
    "field", ["priorities", "move_max", "rate_max", "target_rate", "funnel_end"]
)
def test_limits_rejects_negative_tuning_values(field: str) -> None:
    with pytest.raises(ValueError, match=f"{field} must be nonnegative"):
        Limits(**limits_values(**{field: [-1.0]}))


def test_limits_rejects_funnel_start_below_funnel_end() -> None:
    message = "Funnel start widths must be at least the end widths"
    with pytest.raises(ValueError, match=message):
        Limits(**limits_values(funnel_start=[5.0], funnel_end=[10.0]))


def test_default_settings_are_usable() -> None:
    settings = Settings()
    assert settings.prediction_horizon == 60
    assert settings.move_horizon == 8
    assert settings.move_suppression == 1.0


@pytest.mark.parametrize(("prediction", "moves"), [(0, 1), (60, 0), (8, 9), (3, 5)])
def test_settings_rejects_invalid_horizons(prediction: int, moves: int) -> None:
    message = "Require 1 <= move horizon <= prediction horizon"
    with pytest.raises(ValueError, match=message):
        Settings(prediction, moves)


@pytest.mark.parametrize("suppression", [0.0, -1.0, np.nan, np.inf])
def test_settings_rejects_nonpositive_or_nonfinite_suppression(suppression: float) -> None:
    message = "Move suppression must be finite and positive"
    with pytest.raises(ValueError, match=message):
        Settings(60, 8, suppression)


def test_a_controller_with_matching_model_limits_and_settings() -> None:
    controller = make_controller([[1.0]])
    assert controller.model.gains.shape == (1, 1)
    assert controller.limits.cv_lower.shape == (1,)
    assert controller.settings.prediction_horizon == 25


def test_a_controller_accepts_inputs_after_the_declared_mvs() -> None:
    template = make_controller([[1.0, 1.0]])
    matrix = np.full((1, 3), 1.0)
    model = FopdtModel(matrix, np.full(matrix.shape, 4.0), np.ones(matrix.shape), 1.0)
    controller = Controller(model, template.limits, template.settings)
    assert controller.model.gains.shape == (1, 3)


@pytest.mark.parametrize(("gains", "reason"), [
    ([[1.0, 1.0], [2.0, 2.0]], "two CVs; limits declare one"),
    ([[1.0]], "one input; limits declare two MVs"),
])
def test_a_model_that_cannot_drive_every_declared_signal_is_rejected(
    gains: list[list[float]], reason: str
) -> None:
    template = make_controller([[1.0, 1.0]])
    matrix = np.asarray(gains, dtype=float)
    model = FopdtModel(matrix, np.full(matrix.shape, 4.0), np.ones(matrix.shape), 1.0)
    message = "Model dimensions must cover every declared CV and MV"
    with pytest.raises(ValueError, match=message):
        Controller(model, template.limits, template.settings)

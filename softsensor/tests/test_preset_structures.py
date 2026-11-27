"""Tests for executable preset structures and role-bound physics transforms.

Synthetic arrays use the engineering units declared by each packaged preset.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest
from crosscut_softsensor.preset_structures import create_structure, physics_formula
from crosscut_softsensor.presets import PresetError, load_presets, validate_preset


def test_planned_structures_are_enabled() -> None:
    preset = load_presets()["lab_quality_inference"]
    assert preset["model"]["allowed_now"] == ["pls", "ridge", "gradient_boosting"]
    assert preset["model"]["planned"] == []


def test_factory_refuses_a_structure_outside_the_preset() -> None:
    preset = load_presets()["valve_flowmeter"]
    with pytest.raises(ValueError, match="not allowed"):
        create_structure(preset, "ridge", ["cv_curve"])


def test_factory_fits_ridge_to_role_ordered_features() -> None:
    preset = load_presets()["lab_quality_inference"]
    features = np.arange(80.0).reshape(40, 2)
    target = 3 * features[:, 0] + 2
    model = create_structure(preset, "ridge", ["process_tag_1", "process_tag_2"])
    assert np.allclose(model.fit(features, target).predict(features), target, atol=1e-4)


def test_belt_physics_uses_net_power_and_running_state() -> None:
    preset = load_presets()["belt_scale_backup"]
    formula = physics_formula(preset, ["belt_speed", "empty_belt_power", "drive_power"])
    assert np.allclose(formula(np.array([[2.0, 10.0, 30.0]])), [20.0])
    assert np.isnan(formula(np.array([[0.0, 10.0, 30.0]]))[0])


def test_pump_physics_converts_seconds_to_hours() -> None:
    preset = load_presets()["pump_flowmeter_backup"]
    roles = preset["model"]["physics"]["roles"]
    assert np.allclose(physics_formula(preset, roles)(np.array([[10, 300, 100, 1000]])), [180])


def test_valve_physics_respects_pressure_and_density_units() -> None:
    preset = load_presets()["valve_flowmeter"]
    roles = preset["model"]["physics"]["roles"]
    assert np.allclose(physics_formula(preset, roles)(np.array([[20, 300, 100, 2000]])), [20])


def test_slurry_physics_conserves_mass_and_volume() -> None:
    preset = load_presets()["slurry_solids_flow_density"]
    roles = preset["model"]["physics"]["roles"]
    assert np.allclose(physics_formula(preset, roles)(np.array([[100, 1500, 2.5]])), [250 / 3])


def test_inventory_requires_a_causal_integrated_feature() -> None:
    preset = load_presets()["inventory_mass_balance"]
    with pytest.raises(ValueError, match="integrated_net_mass"):
        create_structure(preset, "physics_template", ["stream_in", "stream_out"])


def test_inventory_predictions_do_not_depend_on_batch_boundaries() -> None:
    preset = load_presets()["inventory_mass_balance"]
    formula = physics_formula(preset, ["integrated_net_mass"])
    features = np.arange(20.0)[:, None]
    assert np.array_equal(formula(features)[10:], formula(features[10:]))


def test_unknown_formula_is_refused_by_validation() -> None:
    preset = copy.deepcopy(load_presets()["valve_flowmeter"])
    preset["model"]["physics"]["formula"] = "execute_code"
    with pytest.raises(PresetError, match="formula"):
        validate_preset(preset)


def test_physics_roles_must_be_declared_inputs() -> None:
    preset = copy.deepcopy(load_presets()["valve_flowmeter"])
    preset["model"]["physics"]["roles"][0] = "unknown_role"
    with pytest.raises(PresetError, match="physics.roles"):
        validate_preset(preset)


def test_cyclone_loading_proxy_uses_flow_per_open_cyclone() -> None:
    preset = load_presets()["cyclone_overflow_size"]
    roles = preset["model"]["physics"]["roles"]
    formula = physics_formula(preset, roles)
    assert np.allclose(formula(np.array([[100.0, 2.0, 25.0]])), [10.0])
    assert np.isnan(formula(np.array([[100.0, 0.0, 25.0]]))[0])


def test_pls_adapter_recovers_a_synthetic_linear_relation() -> None:
    preset = load_presets()["lab_quality_inference"]
    features = np.random.default_rng(156).normal(size=(120, 2))
    target = 4 + 3 * features[:, 0] - 2 * features[:, 1]
    model = create_structure(preset, "pls", ["process_tag_1", "process_tag_2"])
    assert np.allclose(model.fit(features, target).predict(features), target, atol=1e-8)


@pytest.mark.parametrize("gravity,density", [(0.0, 1500.0), (1.0, 1500.0), (2.5, 500.0),
                                              (2.5, 3000.0)])
def test_slurry_physics_rejects_impossible_mixture_densities(
    gravity: float, density: float
) -> None:
    preset = load_presets()["slurry_solids_flow_density"]
    roles = preset["model"]["physics"]["roles"]
    with np.errstate(all="raise"):
        prediction = physics_formula(preset, roles)(np.array([[100.0, density, gravity]]))
    assert np.isnan(prediction[0])

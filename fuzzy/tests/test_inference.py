"""Behaviour of membership, rule strength and full system evaluation.

Every test builds its own tiny rule base with :func:`system_from_dict` so the expected numbers can
be read straight off the documents.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_fuzzy.inference import UNIVERSE_POINTS, evaluate, membership
from crosscut_fuzzy.model import Rule, Term, system_from_dict

# A falling ramp on 0..10: degree 1.0 at 0 and degree 0.0 at 10.
FALLING_TERM = {"name": "falling", "shape": "tri", "params": [0.0, 0.0, 10.0]}
# A rising ramp on 0..10: degree 0.0 at 0 and degree 1.0 at 10.
RISING_TERM = {"name": "rising", "shape": "trap", "params": [0.0, 10.0, 10.0, 10.0]}

# A system with one input "x" and one output "y", each split into a low and a high term.
TWO_RULE_DOCUMENT = {
    "name": "two_rules",
    "inputs": [
        {
            "id": "x",
            "low": 0.0,
            "high": 10.0,
            "terms": [
                {"name": "low", "shape": "tri", "params": [0.0, 0.0, 5.0]},
                {"name": "high", "shape": "tri", "params": [5.0, 10.0, 10.0]},
            ],
        }
    ],
    "outputs": [
        {
            "id": "y",
            "low": 0.0,
            "high": 10.0,
            "terms": [
                {"name": "small", "shape": "tri", "params": [0.0, 0.0, 5.0]},
                {"name": "big", "shape": "tri", "params": [5.0, 10.0, 10.0]},
            ],
        }
    ],
    "rules": [
        {
            "id": "r_small",
            "if": [{"variable": "x", "is": "low"}],
            "then": {"variable": "y", "is": "small"},
        },
        {
            "id": "r_big",
            "if": [{"variable": "x", "is": "high"}],
            "then": {"variable": "y", "is": "big"},
        },
    ],
}


def test_a_triangle_is_zero_at_both_feet_one_at_the_peak_and_half_way_at_the_midpoint():
    triangle = Term("mid", "tri", (0.0, 5.0, 10.0))
    assert membership(triangle, np.array([0.0, 10.0, 5.0, 2.5])) == pytest.approx(
        [0.0, 0.0, 1.0, 0.5]
    )


def test_a_triangle_is_zero_outside_its_foot():
    triangle = Term("mid", "tri", (0.0, 5.0, 10.0))
    assert membership(triangle, np.array([-3.0, 12.0])) == pytest.approx([0.0, 0.0])


def test_a_trapezoid_is_one_across_its_plateau_and_half_way_up_each_slope():
    trapezoid = Term("plateau", "trap", (0.0, 2.0, 4.0, 6.0))
    assert membership(trapezoid, np.array([2.0, 3.0, 4.0, 1.0, 5.0])) == pytest.approx(
        [1.0, 1.0, 1.0, 0.5, 0.5]
    )


def test_a_left_shoulder_triangle_is_one_at_its_low_end():
    left_shoulder = Term("low", "tri", (0.0, 0.0, 5.0))
    assert membership(left_shoulder, np.array([0.0, 2.5, 5.0])) == pytest.approx([1.0, 0.5, 0.0])


def test_a_right_shoulder_triangle_is_one_at_its_high_end():
    right_shoulder = Term("high", "tri", (5.0, 10.0, 10.0))
    assert membership(right_shoulder, np.array([10.0, 7.5, 5.0])) == pytest.approx([1.0, 0.5, 0.0])


def test_a_right_shoulder_trapezoid_is_one_across_its_plateau():
    shoulder = Term("high", "trap", (5.0, 8.0, 10.0, 10.0))
    assert membership(shoulder, np.array([10.0, 8.0, 6.5])) == pytest.approx([1.0, 1.0, 0.5])


def test_a_gaussian_is_one_at_its_mean_and_exp_minus_half_one_sigma_away():
    gaussian = Term("around_five", "gauss", (5.0, 2.0))
    assert membership(gaussian, np.array([5.0, 7.0])) == pytest.approx([1.0, np.exp(-0.5)])


def test_membership_accepts_an_array_and_returns_an_array_of_the_same_shape():
    triangle = Term("mid", "tri", (0.0, 5.0, 10.0))
    result = membership(triangle, np.array([[0.0, 5.0], [10.0, 2.5]]))
    assert isinstance(result, np.ndarray)
    assert result.shape == (2, 2)


def _two_condition_system(operator: str, weight: float = 1.0, enabled: bool = True) -> object:
    """Two inputs, each in its own term, feeding one output rule whose strength is easy to read.

    Input "a" uses a falling ramp (degree 1.0 at 0, 0.0 at 10) and "b" a rising ramp (0.0 at 0,
    1.0 at 10), so a = 2.5 gives 0.75 and b = 7.5 gives 0.75.
    """
    return system_from_dict(
        {
            "name": "two_conditions",
            "inputs": _two_condition_inputs(),
            "outputs": _two_condition_outputs(),
            "rules": [_two_condition_rule(operator, weight, enabled)],
        }
    )


def _two_condition_inputs() -> list:
    """Return the two input definitions: "a" falls over 0..10, "b" rises over 0..10."""
    return [
        {"id": "a", "low": 0.0, "high": 10.0, "terms": [FALLING_TERM]},
        {"id": "b", "low": 0.0, "high": 10.0, "terms": [RISING_TERM]},
    ]


def _two_condition_outputs() -> list:
    """Return the single output "y", a triangular term peaking at 0.0 with width 5.0."""
    return [
        {
            "id": "y",
            "low": 0.0,
            "high": 10.0,
            "terms": [{"name": "small", "shape": "tri", "params": [0.0, 0.0, 5.0]}],
        }
    ]


def _two_condition_rule(operator: str, weight: float, enabled: bool) -> dict:
    """Return the rule combining the falling "a" and rising "b" into output "y"."""
    return {
        "id": "r",
        "if": [
            {"variable": "a", "is": "falling"},
            {"variable": "b", "is": "rising"},
        ],
        "then": {"variable": "y", "is": "small"},
        "operator": operator,
        "weight": weight,
        "enabled": enabled,
    }


def test_an_and_rule_fires_at_the_minimum_of_its_condition_degrees():
    system = _two_condition_system("and")
    # a = 2.5 gives 0.75, b = 10 gives 1.0: the minimum is 0.75.
    inference = evaluate(system, {"a": np.array([2.5]), "b": np.array([10.0])})
    assert inference.firing["r"][0] == pytest.approx(0.75)


def test_an_or_rule_fires_at_the_maximum_of_its_condition_degrees():
    system = _two_condition_system("or")
    inference = evaluate(system, {"a": np.array([2.5]), "b": np.array([10.0])})
    assert inference.firing["r"][0] == pytest.approx(1.0)


def test_a_weight_halves_the_firing_strength():
    system = _two_condition_system("and", weight=0.5)
    inference = evaluate(system, {"a": np.array([0.0]), "b": np.array([10.0])})
    assert inference.firing["r"][0] == pytest.approx(0.5)


def test_a_disabled_rule_has_zero_firing_strength():
    system = _two_condition_system("and", enabled=False)
    inference = evaluate(system, {"a": np.array([0.0]), "b": np.array([10.0])})
    assert inference.firing["r"][0] == pytest.approx(0.0)


def test_a_single_condition_rule_fires_at_its_condition_degree_times_its_weight():
    base = system_from_dict(TWO_RULE_DOCUMENT)
    inputs = base.inputs
    outputs = base.outputs
    # One rule only: "if x is low then y is small", with a weight of 0.5.
    rule = Rule("r_small", (base.rules[0].conditions[0],), base.rules[0].consequent, weight=0.5)
    system = base.__class__("one_rule", inputs, outputs, (rule,))
    inference = evaluate(system, {"x": np.array([0.0])})
    assert inference.firing["r_small"][0] == pytest.approx(0.5)


def test_the_two_rule_system_is_near_its_low_end_at_x_zero():
    system = system_from_dict(TWO_RULE_DOCUMENT)
    inference = evaluate(system, {"x": np.array([0.0])})
    assert inference.outputs["y"].crisp[0] < 2.0


def test_the_two_rule_system_is_near_its_high_end_at_x_ten():
    system = system_from_dict(TWO_RULE_DOCUMENT)
    inference = evaluate(system, {"x": np.array([10.0])})
    assert inference.outputs["y"].crisp[0] > 8.0


def test_no_rule_fires_at_x_five_where_both_memberships_are_zero():
    system = system_from_dict(TWO_RULE_DOCUMENT)
    inference = evaluate(system, {"x": np.array([5.0])})
    assert np.isnan(inference.outputs["y"].crisp[0])


def test_the_crisp_output_grows_monotonically_as_x_rises_from_zero_to_four():
    system = system_from_dict(TWO_RULE_DOCUMENT)
    inference = evaluate(system, {"x": np.arange(0.0, 5.0)})
    crisp = inference.outputs["y"].crisp
    assert np.all(np.diff(crisp) > 0.0)


def test_an_array_of_n_samples_gives_arrays_of_shape_n():
    system = system_from_dict(TWO_RULE_DOCUMENT)
    inference = evaluate(system, {"x": np.array([0.0, 5.0, 10.0])})
    assert inference.degrees["x"]["low"].shape == (3,)
    assert inference.firing["r_small"].shape == (3,)
    assert inference.outputs["y"].crisp.shape == (3,)


def test_the_aggregated_shape_has_one_row_per_sample_and_the_universe_resolution():
    system = system_from_dict(TWO_RULE_DOCUMENT)
    inference = evaluate(system, {"x": np.array([0.0, 5.0, 10.0])})
    assert inference.outputs["y"].aggregated.shape == (3, UNIVERSE_POINTS)


def test_a_scalar_input_behaves_like_an_array_of_one_sample():
    system = system_from_dict(TWO_RULE_DOCUMENT)
    inference = evaluate(system, {"x": 0.0})
    assert inference.firing["r_small"].shape == (1,)
    assert inference.outputs["y"].crisp[0] < 2.0


def test_two_symmetric_rules_meet_in_the_middle_of_the_universe():
    system = system_from_dict(
        {
            "name": "symmetric",
            "inputs": [
                {
                    "id": "x",
                    "low": 0.0,
                    "high": 10.0,
                    "terms": [{"name": "any", "shape": "trap", "params": [0.0, 0.0, 10.0, 10.0]}],
                }
            ],
            "outputs": [
                {
                    "id": "y",
                    "low": 0.0,
                    "high": 10.0,
                    "terms": [
                        {"name": "left", "shape": "tri", "params": [0.0, 2.0, 4.0]},
                        {"name": "right", "shape": "tri", "params": [6.0, 8.0, 10.0]},
                    ],
                }
            ],
            "rules": [
                {
                    "id": "r_left",
                    "if": [{"variable": "x", "is": "any"}],
                    "then": {"variable": "y", "is": "left"},
                },
                {
                    "id": "r_right",
                    "if": [{"variable": "x", "is": "any"}],
                    "then": {"variable": "y", "is": "right"},
                },
            ],
        }
    )
    inference = evaluate(system, {"x": np.array([1.0])})
    assert inference.outputs["y"].crisp[0] == pytest.approx(5.0, abs=0.05)

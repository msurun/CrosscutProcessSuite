"""Validation of rule base documents and the behaviour of the bundled mill feed example."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from crosscut_fuzzy.inference import evaluate
from crosscut_fuzzy.model import FuzzyModelError, system_from_dict

# The test file lives in fuzzy/tests/, so the repo root is two levels up.
EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "fuzzy" / "examples" / "mill_feed_supervisor.json"
)


def _input_variable(variable_id: str = "power") -> dict[str, Any]:
    """One input variable with a low and a high term, on the range 0..100."""
    return {
        "id": variable_id,
        "low": 0.0,
        "high": 100.0,
        "terms": [
            {"name": "low", "shape": "tri", "params": [0.0, 0.0, 50.0]},
            {"name": "high", "shape": "tri", "params": [50.0, 100.0, 100.0]},
        ],
    }


def _output_variable(variable_id: str = "feed") -> dict[str, Any]:
    """One output variable with a low and a high term, on the range -10..10."""
    return {
        "id": variable_id,
        "low": -10.0,
        "high": 10.0,
        "terms": [
            {"name": "low", "shape": "tri", "params": [-10.0, -10.0, 0.0]},
            {"name": "high", "shape": "tri", "params": [0.0, 10.0, 10.0]},
        ],
    }


def _rule(rule_id: str = "r1", **overrides: Any) -> dict[str, Any]:
    """One rule "IF power IS high THEN feed IS high", with named fields overridable."""
    rule: dict[str, Any] = {
        "id": rule_id,
        "if": [{"variable": "power", "is": "high"}],
        "then": {"variable": "feed", "is": "high"},
    }
    rule.update(overrides)
    return rule


def _document(**overrides: Any) -> dict[str, Any]:
    """A minimal valid rule base document, with named fields overridable."""
    document: dict[str, Any] = {
        "name": "minimal",
        "inputs": [_input_variable()],
        "outputs": [_output_variable()],
        "rules": [_rule()],
    }
    document.update(overrides)
    return document


# --- 6. system_from_dict rejections -------------------------------------------------


def test_a_term_with_the_wrong_number_of_parameters_is_rejected():
    document = _document(
        inputs=[
            {**_input_variable(), "terms": [{"name": "low", "shape": "tri", "params": [0.0, 50.0]}]}
        ]
    )
    with pytest.raises(FuzzyModelError):
        system_from_dict(document)


def test_a_triangle_with_decreasing_parameters_is_rejected():
    document = _document(
        inputs=[
            {
                **_input_variable(),
                "terms": [{"name": "low", "shape": "tri", "params": [50.0, 40.0, 0.0]}],
            }
        ]
    )
    with pytest.raises(FuzzyModelError):
        system_from_dict(document)


def test_a_gaussian_with_zero_sigma_is_rejected():
    document = _document(
        inputs=[
            {
                **_input_variable(),
                "terms": [{"name": "low", "shape": "gauss", "params": [50.0, 0.0]}],
            }
        ]
    )
    with pytest.raises(FuzzyModelError):
        system_from_dict(document)


def test_a_rule_referring_to_an_unknown_variable_is_rejected():
    document = _document(rules=[_rule(**{"if": [{"variable": "torque", "is": "high"}]})])
    with pytest.raises(FuzzyModelError):
        system_from_dict(document)


def test_a_rule_referring_to_an_unknown_term_is_rejected():
    document = _document(rules=[_rule(**{"if": [{"variable": "power", "is": "medium"}]})])
    with pytest.raises(FuzzyModelError):
        system_from_dict(document)


def test_two_variables_with_the_same_id_are_rejected():
    document = _document(inputs=[_input_variable(), _input_variable()])
    with pytest.raises(FuzzyModelError):
        system_from_dict(document)


def test_two_rules_with_the_same_id_are_rejected():
    document = _document(rules=[_rule("r1"), _rule("r1")])
    with pytest.raises(FuzzyModelError):
        system_from_dict(document)


def test_a_variable_whose_low_is_not_below_its_high_is_rejected():
    document = _document(inputs=[{**_input_variable(), "low": 100.0}])
    with pytest.raises(FuzzyModelError):
        system_from_dict(document)


def test_a_rule_weight_above_one_is_rejected():
    document = _document(rules=[_rule(weight=1.5)])
    with pytest.raises(FuzzyModelError):
        system_from_dict(document)


def test_an_input_used_as_a_consequent_is_rejected():
    document = _document(rules=[_rule(then={"variable": "power", "is": "high"})])
    with pytest.raises(FuzzyModelError):
        system_from_dict(document)


# --- 7. the bundled mill feed example ----------------------------------------------


@pytest.fixture(scope="module")
def mill_supervisor():
    """The bundled mill feed supervisor, loaded from its JSON file."""
    document = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    return system_from_dict(document)


def _feed_change(mill_supervisor, mill_power: float, p80: float) -> float:
    """Crisp feed change of the supervisor for a single sample."""
    inference = evaluate(
        mill_supervisor,
        {"mill_power": np.array([mill_power]), "p80": np.array([p80])},
    )
    return float(inference.outputs["feed_change"].crisp[0])


def test_the_bundled_example_file_exists():
    assert EXAMPLE_PATH.is_file()


def test_the_bundled_example_loads_into_a_system(mill_supervisor):
    assert mill_supervisor.name


def test_at_the_nominal_operating_point_the_feed_change_is_about_zero(mill_supervisor):
    assert _feed_change(mill_supervisor, mill_power=3000.0, p80=150.0) == pytest.approx(
        0.0, abs=1.0
    )


def test_a_high_power_asks_for_a_negative_feed_change(mill_supervisor):
    assert _feed_change(mill_supervisor, mill_power=3300.0, p80=150.0) < -5.0


def test_a_low_power_asks_for_a_positive_feed_change(mill_supervisor):
    assert _feed_change(mill_supervisor, mill_power=2700.0, p80=150.0) > 5.0


def test_far_outside_every_term_no_rule_fires_and_the_change_is_nan(mill_supervisor):
    assert np.isnan(_feed_change(mill_supervisor, mill_power=2500.0, p80=300.0))

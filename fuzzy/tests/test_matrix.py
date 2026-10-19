"""Tests for rule matrix extraction from fuzzy systems."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from crosscut_fuzzy.library import load_document
from crosscut_fuzzy.matrix import rule_matrix
from crosscut_fuzzy.model import FuzzyModelError, system_from_dict


def _make_input(variable_id: str) -> dict[str, Any]:
    """Return a test input variable with low and high terms on [0.0, 100.0]."""
    return {
        "id": variable_id,
        "low": 0.0,
        "high": 100.0,
        "terms": [
            {"name": "low", "shape": "tri", "params": [0.0, 0.0, 50.0]},
            {"name": "high", "shape": "tri", "params": [50.0, 100.0, 100.0]},
        ],
    }


def _make_output(variable_id: str = "o") -> dict[str, Any]:
    """Return a test output variable with down and up terms on [-10.0, 10.0]."""
    return {
        "id": variable_id,
        "low": -10.0,
        "high": 10.0,
        "terms": [
            {"name": "down", "shape": "tri", "params": [-10.0, -10.0, 0.0]},
            {"name": "up", "shape": "tri", "params": [0.0, 10.0, 10.0]},
        ],
    }


# Defaults for the keyword options of _make_rule: variable ids, clause order and rule flags.
_RULE_DEFAULTS: dict[str, Any] = {
    "row_var": "a",
    "col_var": "b",
    "out_var": "o",
    "reversed_order": False,
    "operator": "and",
    "weight": 1.0,
    "enabled": True,
}


def _rule_settings(options: dict[str, Any]) -> dict[str, Any]:
    """Merge `options` over _RULE_DEFAULTS, refusing a misspelled option name."""
    unknown = set(options) - set(_RULE_DEFAULTS)
    if unknown:
        raise TypeError(f"unknown rule options: {sorted(unknown)}")
    return {**_RULE_DEFAULTS, **options}


def _make_rule(
    rule_id: str, row_term: str, col_term: str, output_term: str = "up", **options: Any
) -> dict[str, Any]:
    """Return a two-clause rule; `options` override the entries of _RULE_DEFAULTS."""
    settings = _rule_settings(options)
    clauses = [
        {"variable": settings["row_var"], "is": row_term},
        {"variable": settings["col_var"], "is": col_term},
    ]
    if settings["reversed_order"]:
        clauses.reverse()
    return {
        "id": rule_id,
        "if": clauses,
        "then": {"variable": settings["out_var"], "is": output_term},
        "operator": settings["operator"],
        "weight": settings["weight"],
        "enabled": settings["enabled"],
    }


def _build_system(
    rules: list[dict[str, Any]],
    inputs: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
):
    """Assemble and validate a test FuzzySystem."""
    document = {
        "schema_version": "0.1.0",
        "name": "test_system",
        "inputs": inputs or [_make_input("a"), _make_input("b")],
        "outputs": outputs or [_make_output("o")],
        "rules": rules,
    }
    return system_from_dict(document)


def _expected_entry(rule_id: str, output_term: str) -> dict[str, Any]:
    """Return the matrix cell entry of an enabled rule with weight 1.0."""
    return {"rule_id": rule_id, "output_term": output_term, "weight": 1.0, "enabled": True}


def test_a_two_by_two_matrix_with_four_and_rules_fills_every_cell():
    """All 4 cells of a 2x2 grid are populated with matching output terms."""
    rules = [
        _make_rule("r1", "low", "low", "down"),
        _make_rule("r2", "low", "high", "up"),
        _make_rule("r3", "high", "low", "up"),
        _make_rule("r4", "high", "high", "down"),
    ]
    system = _build_system(rules)

    matrix = rule_matrix(system, row_id="a", column_id="b", output_id="o")

    assert matrix["row_variable"] == "a"
    assert matrix["column_variable"] == "b"
    assert matrix["output"] == "o"
    assert matrix["rows"] == ["low", "high"]
    assert matrix["columns"] == ["low", "high"]
    assert matrix["unplaced"] == []
    assert matrix["cells"][0][0] == [_expected_entry("r1", "down")]
    assert matrix["cells"][0][1] == [_expected_entry("r2", "up")]
    assert matrix["cells"][1][0] == [_expected_entry("r3", "up")]
    assert matrix["cells"][1][1] == [_expected_entry("r4", "down")]


def test_swapping_row_and_column_swaps_the_cells_positions():
    """Transposing row and column variables places rules at transposed cell indices."""
    rules = [_make_rule("r1", "low", "high", "up")]
    system = _build_system(rules)

    direct = rule_matrix(system, row_id="a", column_id="b", output_id="o")
    swapped = rule_matrix(system, row_id="b", column_id="a", output_id="o")

    assert direct["cells"][0][1][0]["rule_id"] == "r1"
    assert direct["cells"][1][0] == []
    assert swapped["cells"][1][0][0]["rule_id"] == "r1"
    assert swapped["cells"][0][1] == []


def test_a_rule_with_the_clauses_written_in_the_opposite_order_is_still_placed():
    """Antecedents ordered column-first instead of row-first are placed in the expected cell."""
    rules = [_make_rule("r1", "low", "high", "up", reversed_order=True)]
    system = _build_system(rules)

    matrix = rule_matrix(system, row_id="a", column_id="b", output_id="o")

    assert matrix["cells"][0][1][0]["rule_id"] == "r1"
    assert matrix["unplaced"] == []


def test_an_or_rule_is_unplaced():
    """Rules using the OR operator are excluded from the matrix and added to unplaced."""
    rules = [_make_rule("r1", "low", "high", "up", operator="or")]
    system = _build_system(rules)

    matrix = rule_matrix(system, row_id="a", column_id="b", output_id="o")

    assert matrix["cells"][0][1] == []
    assert matrix["unplaced"] == ["r1"]


def test_a_one_clause_rule_is_unplaced():
    """A rule with only one condition does not form a 2D matrix cell and is unplaced."""
    rules = [
        {
            "id": "r1",
            "if": [{"variable": "a", "is": "low"}],
            "then": {"variable": "o", "is": "up"},
        }
    ]
    system = _build_system(rules)

    matrix = rule_matrix(system, row_id="a", column_id="b", output_id="o")

    assert matrix["cells"][0][0] == []
    assert matrix["unplaced"] == ["r1"]


def test_a_disabled_rule_is_placed_with_enabled_false_and_its_weight_kept():
    """A disabled rule is placed in its corresponding cell with preserved weight and status."""
    rules = [_make_rule("r1", "high", "low", "down", weight=0.75, enabled=False)]
    system = _build_system(rules)

    matrix = rule_matrix(system, row_id="a", column_id="b", output_id="o")

    cell = matrix["cells"][1][0]
    assert len(cell) == 1
    assert cell[0] == {"rule_id": "r1", "output_term": "down", "weight": 0.75, "enabled": False}
    assert matrix["unplaced"] == []


def test_two_rules_in_the_same_cell_both_appear():
    """Multiple rules matching the same input terms both appear in the target cell."""
    rules = [
        _make_rule("r1", "low", "low", "down", weight=0.5),
        _make_rule("r2", "low", "low", "up", weight=1.0),
    ]
    system = _build_system(rules)

    matrix = rule_matrix(system, row_id="a", column_id="b", output_id="o")

    rule_ids = [entry["rule_id"] for entry in matrix["cells"][0][0]]
    assert rule_ids == ["r1", "r2"]
    assert matrix["unplaced"] == []


def test_rule_for_another_output_is_unplaced():
    """Rules targeting a different output variable are added to unplaced."""
    rules = [
        _make_rule("r1", "low", "low", "up", out_var="p"),
        _make_rule("r2", "low", "high", "down", out_var="o"),
    ]
    system = _build_system(rules, outputs=[_make_output("o"), _make_output("p")])

    matrix = rule_matrix(system, row_id="a", column_id="b", output_id="o")

    assert matrix["cells"][0][0] == []
    assert matrix["cells"][0][1][0]["rule_id"] == "r2"
    assert matrix["unplaced"] == ["r1"]


def test_same_row_and_column_raises():
    """Passing the same variable id for both row and column raises FuzzyModelError."""
    system = _build_system([])

    with pytest.raises(FuzzyModelError):
        rule_matrix(system, row_id="a", column_id="a", output_id="o")


def test_unknown_input_raises():
    """Passing an unknown variable id as row or column raises FuzzyModelError."""
    system = _build_system([])

    with pytest.raises(FuzzyModelError):
        rule_matrix(system, row_id="missing_input", column_id="b", output_id="o")


def test_unknown_output_raises():
    """Passing an unknown variable id as output raises FuzzyModelError."""
    system = _build_system([])

    with pytest.raises(FuzzyModelError):
        rule_matrix(system, row_id="a", column_id="b", output_id="missing_output")


def test_the_bundled_mill_feed_supervisor_gives_a_three_by_three_matrix(tmp_path: Path):
    """The bundled mill feed example produces a 3x3 matrix with placed rules."""
    document = load_document("mill_feed_supervisor", tmp_path)
    system = system_from_dict(document)

    matrix = rule_matrix(
        system,
        row_id="mill_power",
        column_id="p80",
        output_id="feed_change",
    )

    assert len(matrix["rows"]) == 3
    assert len(matrix["columns"]) == 3
    total_placed = sum(len(cell) for row in matrix["cells"] for cell in row)
    assert total_placed >= 1

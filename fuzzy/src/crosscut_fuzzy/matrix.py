"""Rule-matrix view of a fuzzy rule base: which rule fires for each pair of input terms.

A rule using AND between two input variables occupies exactly one cell of the grid
"terms of the first input x terms of the second input". The web screen renders that grid,
so this module turns a FuzzySystem into plain JSON-ready data.
"""

from __future__ import annotations

from typing import Any

from crosscut_fuzzy.model import AND, FuzzyModelError, FuzzySystem

# A placed rule must combine exactly these many clauses (one per matrix axis).
REQUIRED_CONDITION_COUNT = 2


def rule_matrix(system: FuzzySystem, row_id: str, column_id: str, output_id: str) -> dict[str, Any]:
    """Build the rule matrix for two input variables of ``system`` and one output variable.

    Args:
        system: the rule base to read.
        row_id: id of the input variable whose terms are the rows.
        column_id: id of the input variable whose terms are the columns; must differ from row_id.
        output_id: id of the output variable the placed rules must write to.

    Returns:
        A JSON-ready dict with the row and column term names in order, a ``cells`` grid where
        ``cells[i][j]`` lists the rules placed at that intersection, and ``unplaced`` holding the
        ids of every rule that does not fit the grid, in rule order.

    Raises:
        FuzzyModelError: if row_id equals column_id, or an id is not an input/output of ``system``.
    """
    _check_ids_differ(row_id, column_id)
    row_variable = _input_variable(system, row_id)
    column_variable = _input_variable(system, column_id)
    _output_variable(system, output_id)
    cells, unplaced = _place_rules(system, row_variable, column_variable, output_id)
    return {
        "row_variable": row_id,
        "column_variable": column_id,
        "output": output_id,
        "rows": [term.name for term in row_variable.terms],
        "columns": [term.name for term in column_variable.terms],
        "cells": cells,
        "unplaced": unplaced,
    }


def _input_variable(system: FuzzySystem, variable_id: str) -> Any:
    """The input variable called ``variable_id``; raises FuzzyModelError when it is unknown.

    ``FuzzySystem.input`` raises StopIteration on a missing id, so membership is tested first.
    """
    if variable_id not in [variable.id for variable in system.inputs]:
        raise FuzzyModelError(f"not an input variable: {variable_id}")
    return system.input(variable_id)


def _output_variable(system: FuzzySystem, variable_id: str) -> Any:
    """The output variable called ``variable_id``; raises FuzzyModelError when it is unknown."""
    if variable_id not in [variable.id for variable in system.outputs]:
        raise FuzzyModelError(f"not an output variable: {variable_id}")
    return system.output(variable_id)


def _check_ids_differ(row_id: str, column_id: str) -> None:
    """Reject a matrix whose two axes are the same variable (its diagonal is meaningless)."""
    if row_id == column_id:
        raise FuzzyModelError(f"row and column variable are the same: {row_id}")


def _place_rules(
    system: FuzzySystem, row_variable: Any, column_variable: Any, output_id: str
) -> tuple[list[list[list[dict[str, Any]]]], list[str]]:
    """Sort every rule into the cell it fills, or into the unplaced list.

    Returns:
        The ``cells`` grid (indexed by row term then column term) and the ids of the unplaced rules.
    """
    rows = [term.name for term in row_variable.terms]
    columns = [term.name for term in column_variable.terms]
    cells: list[list[list[dict[str, Any]]]] = [[[] for _ in columns] for _ in rows]
    unplaced: list[str] = []
    for rule in system.rules:
        position = _cell_position(
            rule, row_variable.id, column_variable.id, output_id, rows, columns
        )
        if position is None:
            unplaced.append(rule.id)
            continue
        row_index, column_index = position
        cells[row_index][column_index].append(_cell_entry(rule))
    return cells, unplaced


def _cell_position(
    rule: Any,
    row_id: str,
    column_id: str,
    output_id: str,
    rows: list[str],
    columns: list[str],
) -> tuple[int, int] | None:
    """Where the rule belongs in the grid, or None when it cannot be placed.

    A rule is placed only when it uses AND, writes to ``output_id`` and has exactly one clause
    on each axis. The two clauses may come in either order, so both assignments are tried.
    """
    if rule.operator != AND or rule.consequent.variable != output_id:
        return None
    if len(rule.conditions) != REQUIRED_CONDITION_COUNT:
        return None
    first, second = rule.conditions
    if _clause_matches(first, row_id, rows) and _clause_matches(second, column_id, columns):
        return rows.index(first.term), columns.index(second.term)
    if _clause_matches(first, column_id, columns) and _clause_matches(second, row_id, rows):
        return rows.index(second.term), columns.index(first.term)
    return None


def _clause_matches(clause: Any, variable_id: str, term_names: list[str]) -> bool:
    """Whether the clause reads ``variable_id IS <one of term_names>``."""
    return clause.variable == variable_id and clause.term in term_names


def _cell_entry(rule: Any) -> dict[str, Any]:
    """The JSON-ready summary of a placed rule: what it is, what it writes and how strongly."""
    return {
        "rule_id": rule.id,
        "output_term": rule.consequent.term,
        "weight": rule.weight,
        "enabled": rule.enabled,
    }

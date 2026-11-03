"""Acceptance tests executing and verifying the L5 Virtual DCS matrix (Phase 1/2, issue #53).

Validates schema invariants, module mappings, and gateway scenario coverage, skipping
execution rows until RougherSim provides the required milestone capabilities.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from golden import checkout_problem, load_pin, roughersim_dir
from matrix import MATRIX, VALID_MODULES, VALID_STATUSES, MatrixRow


def _load_gateway_scenario_names() -> set[str]:
    """Parse test function names from gateway/tests/test_gateway_scenarios.py."""
    repo_root = Path(__file__).resolve().parents[2]
    scenario_file = repo_root / "gateway" / "tests" / "test_gateway_scenarios.py"
    tree = ast.parse(scenario_file.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }


def test_matrix_invariants() -> None:
    """Verify matrix uniqueness and gateway scenario coverage across all rows."""
    row_ids = [row.row_id for row in MATRIX]
    assert len(row_ids) == len(set(row_ids)), "row_id values must be unique"

    gateway_refs = {row.scenario_ref for row in MATRIX if row.row_id.startswith("L5-G")}
    expected_scenarios = _load_gateway_scenario_names()
    missing = expected_scenarios - gateway_refs
    assert gateway_refs == expected_scenarios, f"Missing gateway scenarios: {missing}"


@pytest.mark.parametrize("row", MATRIX, ids=[r.row_id for r in MATRIX])
def test_l5_matrix_row(row: MatrixRow) -> None:
    """Assert matrix row invariants and skip execution until RougherSim hooks are ready."""
    assert row.row_id
    assert row.claim.strip()
    assert row.module in VALID_MODULES
    assert row.status in VALID_STATUSES
    if row.row_id.startswith("L5-G"):
        assert row.scenario_ref is not None

    if row.status == "pending":
        pytest.skip(f"{row.row_id}: needs {row.needs}")

    problem = checkout_problem(roughersim_dir(), load_pin())
    if problem:
        pytest.skip(f"{row.row_id}: {problem}")

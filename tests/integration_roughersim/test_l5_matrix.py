"""Acceptance tests for the L5 Virtual DCS matrix (Phase 1/2, issue #53).

Checks the matrix against the gateway test file and the L5 table in docs/TESTING_STRATEGY.md,
and runs ready rows through EXECUTORS. Pending rows skip until RougherSim provides the milestone.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from golden import checkout_problem, load_pin, roughersim_dir
from matrix import EXECUTORS, MATRIX, VALID_PHASES, VALID_STATUSES, MatrixRow

REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_TESTS = REPO_ROOT / "gateway" / "tests" / "test_gateway_scenarios.py"
STRATEGY_DOC = REPO_ROOT / "docs" / "TESTING_STRATEGY.md"
GATEWAY_ROW_PREFIX = "L5-G"
EXPECTED_GATEWAY_TESTS = 12


def _gateway_test_nodes() -> dict[str, ast.FunctionDef]:
    """Map each top-level test function in the gateway scenario file to its AST node."""
    tree = ast.parse(GATEWAY_TESTS.read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }


def _doc_matrix_rows() -> dict[tuple[str, str], str]:
    """Map (milestone, scenario) to the pass criterion of each row in the doc's L5 table."""
    section = STRATEGY_DOC.read_text(encoding="utf-8").split("### L5 acceptance matrix", 1)[1]
    section = section.split("\n#", 1)[0]
    rows: dict[tuple[str, str], str] = {}
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith("| Crosscut phase"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        milestone, scenario, criterion = cells[1:]
        rows[(milestone, scenario)] = criterion
    return rows


def run_ready_row(row: MatrixRow, problem: str | None) -> None:
    """Run a ready row's executor; fail if none is registered, skip if the checkout is unusable."""
    executor = EXECUTORS.get(row.row_id)
    if executor is None:
        pytest.fail(f"no executor registered for {row.row_id}")
    if problem:
        pytest.skip(f"{row.row_id}: {problem}")
    executor()


def test_row_ids_are_unique() -> None:
    """Every row_id appears once in the matrix."""
    row_ids = [row.row_id for row in MATRIX]
    assert len(row_ids) == len(set(row_ids)), "row_id values must be unique"


def test_phases_and_statuses_are_valid() -> None:
    """Every row uses a known phase and a known status."""
    for row in MATRIX:
        assert row.phase in VALID_PHASES, f"{row.row_id}: unknown phase {row.phase}"
        assert row.status in VALID_STATUSES, f"{row.row_id}: unknown status {row.status}"


def test_scenario_ref_only_on_gateway_rows() -> None:
    """Only the gateway rows carry a scenario_ref."""
    for row in MATRIX:
        is_gateway = row.row_id.startswith(GATEWAY_ROW_PREFIX)
        assert (row.scenario_ref is not None) == is_gateway, row.row_id


def test_gateway_rows_cover_each_test_once() -> None:
    """Twelve gateway rows, one per gateway test function, with unique scenario_refs."""
    gateway_rows = [row for row in MATRIX if row.row_id.startswith(GATEWAY_ROW_PREFIX)]
    refs = [row.scenario_ref for row in gateway_rows]
    expected = set(_gateway_test_nodes())
    assert len(expected) == EXPECTED_GATEWAY_TESTS
    assert len(gateway_rows) == EXPECTED_GATEWAY_TESTS
    assert len(set(refs)) == len(refs), "scenario_ref values must be unique"
    assert set(refs) == expected


def test_gateway_criteria_match_test_docstrings() -> None:
    """The criterion of each gateway row is the docstring of its test function."""
    nodes = _gateway_test_nodes()
    for row in MATRIX:
        if row.scenario_ref is None:
            continue
        node = nodes.get(row.scenario_ref)
        assert node is not None, f"{row.row_id}: no test named {row.scenario_ref}"
        assert row.criterion == ast.get_docstring(node), f"{row.row_id}: criterion differs"


def test_matrix_mirrors_doc_table() -> None:
    """Every non-gateway row matches one row of the doc's L5 table, criterion included."""
    doc_rows = _doc_matrix_rows()
    matrix_rows = [row for row in MATRIX if not row.row_id.startswith(GATEWAY_ROW_PREFIX)]
    assert len(matrix_rows) == len(doc_rows)
    for row in matrix_rows:
        key = (row.milestone, ", ".join(row.scenarios))
        assert key in doc_rows, f"{row.row_id}: no doc row for {key}"
        assert row.criterion == doc_rows[key], f"{row.row_id}: criterion differs from doc"


@pytest.mark.parametrize("row", MATRIX, ids=[r.row_id for r in MATRIX])
def test_l5_matrix_row(row: MatrixRow) -> None:
    """Run a ready row through its executor; pending rows are skipped."""
    if row.status == "pending":
        pytest.skip(f"{row.row_id}: pending until RougherSim provides {row.milestone}")
    run_ready_row(row, checkout_problem(roughersim_dir(), load_pin()))


def _fake_row() -> MatrixRow:
    """Build a ready row that is not in the real matrix, for exercising run_ready_row."""
    return MatrixRow(
        row_id="L5-FAKE",
        phase="P1",
        milestone="M5",
        scenarios=("nominal",),
        criterion="fake criterion",
        status="ready",
    )


def test_ready_row_without_executor_fails() -> None:
    """A ready row with no registered executor fails and names the row."""
    with pytest.raises(pytest.fail.Exception, match="no executor registered for L5-FAKE"):
        run_ready_row(_fake_row(), None)


def test_ready_row_with_executor_runs_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ready row with a registered executor calls that executor once."""
    calls: list[str] = []
    monkeypatch.setitem(EXECUTORS, "L5-FAKE", lambda: calls.append("ran"))
    run_ready_row(_fake_row(), None)
    assert calls == ["ran"]


def test_checkout_problem_skips_after_executor_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """With an executor registered, an unusable checkout skips and the executor is not called."""
    calls: list[str] = []
    monkeypatch.setitem(EXECUTORS, "L5-FAKE", lambda: calls.append("ran"))
    with pytest.raises(pytest.skip.Exception):
        run_ready_row(_fake_row(), "checkout is not the pinned commit")
    assert calls == []

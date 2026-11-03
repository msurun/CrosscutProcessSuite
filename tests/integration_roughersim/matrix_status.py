"""CLI tool displaying L5 Virtual DCS matrix status and readiness counts.

Prints a Markdown table of all acceptance rows (phase, milestone, scenarios, status,
criterion), then totals by status and a row count per phase. No side effects beyond stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Support running directly via `python tests/integration_roughersim/matrix_status.py`
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from matrix import MATRIX, VALID_PHASES, MatrixRow  # noqa: E402


def _render_row(row: MatrixRow) -> str:
    """Format a single MatrixRow into a Markdown table row."""
    ref_part = f" (`{row.scenario_ref}`)" if row.scenario_ref else ""
    scenarios = f"{', '.join(row.scenarios)}{ref_part}"
    fields = [row.row_id, row.phase, row.milestone, scenarios, row.status, row.criterion]
    return f"| {' | '.join(fields)} |"


def _build_summary(rows: tuple[MatrixRow, ...]) -> str:
    """Compute totals by status and a row count for each phase."""
    pending_count = sum(1 for r in rows if r.status == "pending")
    ready_count = sum(1 for r in rows if r.status == "ready")
    totals = f"**Total:** {len(rows)} | **Pending:** {pending_count} | **Ready:** {ready_count}"
    per_phase = " | ".join(
        f"**{phase}:** {sum(1 for r in rows if r.phase == phase)}"
        for phase in sorted(VALID_PHASES)
    )
    return f"{totals}\n\n{per_phase}"


def print_matrix_status() -> None:
    """Print the complete L5 acceptance matrix in Markdown format to stdout."""
    headers = [
        "# L5 Virtual DCS Acceptance Matrix Status\n",
        "| ID | Phase | Milestone | Scenarios | Status | Criterion |",
        "|---|---|---|---|---|---|",
    ]
    lines = headers + [_render_row(row) for row in MATRIX]
    lines.append("")
    lines.append(_build_summary(MATRIX))
    print("\n".join(lines))


if __name__ == "__main__":
    print_matrix_status()

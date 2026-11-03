"""CLI tool displaying L5 Virtual DCS matrix status and readiness counts.

Prints a formatted Markdown table of all acceptance rows, tracking required RougherSim
hooks, associated modules, and implementation readiness without any side effects.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Support running directly via `python tests/integration_roughersim/matrix_status.py`
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from matrix import MATRIX, MatrixRow  # noqa: E402


def _render_row(row: MatrixRow) -> str:
    """Format a single MatrixRow into a Markdown table row."""
    ref_part = f" (`{row.scenario_ref}`)" if row.scenario_ref else ""
    claim_text = f"{row.claim}{ref_part}"
    fields = [row.row_id, row.module, row.scenario_id, row.status, row.needs, claim_text]
    return f"| {' | '.join(fields)} |"


def _build_summary(rows: tuple[MatrixRow, ...]) -> str:
    """Compute and format summary counts for pending and ready matrix rows."""
    pending_count = sum(1 for r in rows if r.status == "pending")
    ready_count = sum(1 for r in rows if r.status == "ready")
    total_count = len(rows)
    return f"**Total:** {total_count} | **Pending:** {pending_count} | **Ready:** {ready_count}"


def print_matrix_status() -> None:
    """Print the complete L5 acceptance matrix in Markdown format to stdout."""
    headers = [
        "# L5 Virtual DCS Acceptance Matrix Status\n",
        "| ID | Module | Scenario | Status | Needs | Claim |",
        "|---|---|---|---|---|---|",
    ]
    lines = headers + [_render_row(row) for row in MATRIX]
    lines.append("")
    lines.append(_build_summary(MATRIX))
    print("\n".join(lines))


if __name__ == "__main__":
    print_matrix_status()

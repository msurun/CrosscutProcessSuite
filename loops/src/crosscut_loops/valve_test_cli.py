"""Command-line front end for the guided valve stroke test.

Prints the operator procedure for a stroke test plan and analyses a recorded test
from a CSV file. Advisory only: nothing here writes to a control system.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from crosscut_loops.valve_test import (
    StrokePlan,
    StrokeResult,
    analyze_stroke_test,
    plan_stroke_test,
    procedure_text,
)

SECONDS_PER_MINUTE = 60
CAVEAT = "Synthetic validation only (exp25); PV is used as a proxy for valve position."


@dataclass(frozen=True)
class PlanOptions:
    """Plan inputs shared by the `plan` and `analyze` subcommands, in % of span."""

    op_start: float
    dwell_s: int
    op_low: float
    op_high: float
    pv_band: float | None


def _build_plan(options: PlanOptions) -> StrokePlan:
    """Build a stroke test plan from command-line options."""
    return plan_stroke_test(
        op_start=options.op_start,
        dwell_s=options.dwell_s,
        op_low=options.op_low,
        op_high=options.op_high,
        pv_band=options.pv_band,
    )


def _total_test_minutes(plan: StrokePlan) -> int:
    """Total test time in whole minutes: initial dwell plus every step dwell, rounded up."""
    total_s = plan.dwell_s * (len(plan.steps) + 1)
    return -(-total_s // SECONDS_PER_MINUTE)  # ceiling division


def _print_plan(plan: StrokePlan) -> None:
    """Print the numbered procedure and the total test time."""
    for line in procedure_text(plan):
        print(line)
    print(f"Total test time: {_total_test_minutes(plan)} min")


def _read_column(rows: list[dict[str, str]], column: str) -> np.ndarray:
    """Return one CSV column as float64; raise ValueError if the column is missing."""
    try:
        return np.array([float(row[column]) for row in rows], dtype=float)
    except KeyError as exc:
        raise ValueError(f"missing column {column!r} in CSV header") from exc


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a comma-separated CSV with a header row into a list of row dicts."""
    try:
        with path.open(newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise ValueError(f"cannot read CSV file {path}: {exc}") from exc


def _load_record(
    path: Path, time_col: str, op_col: str, pv_col: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load the time, OP, and PV columns from a CSV file as float arrays."""
    rows = _read_csv(path)
    if not rows:
        raise ValueError(f"CSV file {path} has no data rows")
    return _read_column(rows, time_col), _read_column(rows, op_col), _read_column(rows, pv_col)


def _format_deadband(result: StrokeResult) -> str:
    """Format the deadband estimate, its bracket, or the lower bound, in % of span."""
    if result.deadband is not None and result.deadband_bracket is not None:
        low, high = result.deadband_bracket
        return f"{result.deadband:.2f} % of span, bracket ({low:.2f}, {high:.2f}]"
    if result.deadband_lower_bound is not None:
        return f"> {result.deadband_lower_bound:.2f} % (no move after a reversal)"
    return "not identifiable"


def _format_resolution(result: StrokeResult) -> str:
    """Format the resolution certificate in % of span."""
    if result.resolution_le is None:
        return "not certified"
    return f"<= {result.resolution_le:.2f} %"


def _print_report(result: StrokeResult) -> None:
    """Print the analysis report lines."""
    if result.gain is None:
        print("Gain: not identifiable")
    else:
        print(f"Gain: {result.gain:.2f} PV units per % of span")
    print(f"PV noise sigma: {result.sigma_pv:.2f} PV units")
    print(f"Deadband: {_format_deadband(result)}")
    print(f"Resolution: {_format_resolution(result)}")
    print(f"PV left the abort band: {'yes' if result.pv_left_band else 'no'}")
    if result.reason:
        print(f"Reason: {result.reason}")
    print(CAVEAT)


def _add_plan_options(parser: argparse.ArgumentParser) -> None:
    """Add the plan options shared by the `plan` and `analyze` subcommands."""
    parser.add_argument("--op-start", type=float, required=True, help="starting OP in %% of span")
    parser.add_argument("--dwell-s", type=int, required=True, help="dwell time per step in s")
    parser.add_argument("--op-low", type=float, default=0.0, help="lower OP limit in %% of span")
    parser.add_argument("--op-high", type=float, default=100.0, help="upper OP limit in %% of span")
    parser.add_argument("--pv-band", type=float, default=None, help="abort band in PV units")


def _parse_options(args: argparse.Namespace) -> PlanOptions:
    """Collect the shared plan options from parsed arguments."""
    return PlanOptions(
        op_start=args.op_start,
        dwell_s=args.dwell_s,
        op_low=args.op_low,
        op_high=args.op_high,
        pv_band=args.pv_band,
    )


def _run_plan(args: argparse.Namespace) -> None:
    """Handle the `plan` subcommand."""
    _print_plan(_build_plan(_parse_options(args)))


def _run_analyze(args: argparse.Namespace) -> None:
    """Handle the `analyze` subcommand."""
    plan = _build_plan(_parse_options(args))
    t_s, op, pv = _load_record(Path(args.csv), args.time_col, args.op_col, args.pv_col)
    _print_report(analyze_stroke_test(t_s, op, pv, plan))


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with the `plan` and `analyze` subcommands."""
    parser = argparse.ArgumentParser(description="Guided valve stroke test (advisory only).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="print the operator procedure")
    _add_plan_options(plan_parser)
    plan_parser.set_defaults(handler=_run_plan)

    analyze_parser = subparsers.add_parser("analyze", help="analyse a recorded CSV test")
    analyze_parser.add_argument("csv", help="path to the CSV record")
    _add_plan_options(analyze_parser)
    analyze_parser.add_argument("--time-col", default="t_s", help="time column name")
    analyze_parser.add_argument("--op-col", default="op", help="OP column name")
    analyze_parser.add_argument("--pv-col", default="pv", help="PV column name")
    analyze_parser.set_defaults(handler=_run_analyze)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line front end.

    Returns:
        0 on success, 2 on a ValueError (bad inputs, missing file or column).
    """
    args = _build_parser().parse_args(argv)
    try:
        args.handler(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

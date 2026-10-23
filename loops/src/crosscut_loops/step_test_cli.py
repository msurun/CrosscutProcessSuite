"""Command-line intake of a recorded level step test: `check` it, then `make-dataset` from it.

`check` prints what is wrong with the record and what the tuning wizard will say (a dry run of
the dead-time and slope identification). `make-dataset` writes a dataset directory plus a
project.json marking the loop integrating. Advisory only: nothing here writes to a plant.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from crosscut_loops.identification_ipdt import IpdtIdentificationError
from crosscut_loops.step_test_check import (
    DryRun,
    StepTestCheck,
    check_step_test,
    minutes_text,
)
from crosscut_loops.step_test_dataset import DatasetSpec, write_step_test_dataset
from crosscut_loops.step_test_io import ReadOptions, Record, read_record

OPTION_FIELDS = {
    "time_col": "--time-col", "pv_col": "--pv-col", "out_col": "--out-col",
    "sp_col": "--sp-col", "mode_col": "--mode-col", "tag_pv": "--tag-pv", "tag_out": "--tag-out",
    "tag_sp": "--tag-sp", "tag_mode": "--tag-mode", "tag_col": "--tag-col",
    "value_col": "--value-col", "quality_col": "--quality-col",
}  # fmt: skip


def _add_input_options(p: argparse.ArgumentParser) -> None:
    """Options that describe the input CSV (shared by both subcommands)."""
    p.add_argument("file", type=Path, help="CSV file from the historian")
    for dest, flag in OPTION_FIELDS.items():
        p.add_argument(flag, dest=dest, default=None)
    p.add_argument("--time-format", choices=["auto", "iso", "seconds"], default="auto")
    p.add_argument("--decimal", choices=["auto", "comma", "dot"], default="auto")
    p.add_argument("--delimiter", default="auto", help="auto, ',', ';' or a tab")
    p.add_argument("--manual-value", type=float, default=0.0, help="MODE value meaning manual")


def _build_parser() -> argparse.ArgumentParser:
    """Argument parser with the `check` and `make-dataset` subcommands."""
    parser = argparse.ArgumentParser(prog="python -m crosscut_loops.step_test_cli")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check a recorded step test and dry-run the wizard")
    _add_input_options(check)
    check.add_argument("--json", action="store_true", help="print the result as JSON")
    make = sub.add_parser("make-dataset", help="write a dataset directory the web app can open")
    _add_input_options(make)
    make.add_argument("--out", type=Path, required=True, help="<data root>/<dataset id>")
    make.add_argument("--loop-name", default="LIC1")
    make.add_argument("--process-kind", choices=["integrating", "self_regulating"],
                      default="integrating")  # fmt: skip
    make.add_argument("--pv-unit", default="%")
    make.add_argument("--out-unit", default="%")
    make.add_argument("--step-s", type=float, default=None, help="resampling period (s)")
    return parser


def _options(args: argparse.Namespace) -> ReadOptions:
    """ReadOptions from the parsed arguments."""
    given = {k: getattr(args, k) for k in OPTION_FIELDS}
    delimiter = "\t" if args.delimiter in ("\\t", "tab") else args.delimiter
    return ReadOptions(
        **given, time_format=args.time_format, decimal=args.decimal, delimiter=delimiter,
        manual_value=args.manual_value,
    )  # fmt: skip


def _dry_run_lines(dry: DryRun) -> list[str]:
    """Report lines of the identify_ipdt dry run."""
    if dry.error:
        return [f"Wizard dry run: blocked ({dry.error})"]
    head = f"Wizard dry run: {dry.verdict}"
    if dry.reasons:
        head += " (" + ", ".join(dry.reasons) + ")"
    assert dry.delay_s is not None and dry.slope_per_s is not None
    return [
        head,
        f"  slope {dry.slope_per_s:.3g} PV unit/s per % OUT, R2 {dry.r_squared:.2f}",
        f"  dead time {dry.delay_s:.0f} s, interval {dry.delay_lower_s:.0f} to "
        f"{dry.delay_upper_s:.0f} s; the tuning settings use {dry.delay_upper_s:.0f} s",
    ]


def _figure_lines(c: StepTestCheck) -> list[str]:
    """Report lines with the measured figures."""
    lines = [
        f"Samples {c.n}, record {minutes_text(c.duration_s)}, period median {c.dt_median_s:g} s, "
        f"largest gap {c.dt_max_s:g} s" + (" (UNEVEN)" if c.uneven_sampling else ""),
        f"OUT range {c.out_range:g}, {c.n_out_moves} move(s) of 0.5 % or more; "
        f"PV range {c.pv_range:g}",
    ]
    if c.first_move_s is not None and c.lead_share is not None:
        lines.append(
            f"First move at {minutes_text(c.first_move_s)} (quiet lead {c.lead_share:.0%}); "
            f"time after the last move {minutes_text(c.post_last_move_s or 0.0)}"
        )
    mode = "no MODE given" if c.manual_share is None else f"{c.manual_share:.0%} in manual"
    lines.append(
        f"Mode: {mode}; smallest step PV {c.pv_quantisation:g}, OUT {c.out_quantisation:g}"
    )
    return lines


def format_report(c: StepTestCheck, notes: tuple[str, ...] = ()) -> str:
    """Short readable report of a check."""
    lines = [f"Read as: {n}" for n in notes] + _figure_lines(c)
    if c.dry_run is not None:
        lines += _dry_run_lines(c.dry_run)
    lines.append(f"VERDICT: {c.verdict}")
    for f in c.findings:
        lines.append(f"- {'[BLOCKING] ' if f.blocking else ''}{f.text}\n    To do: {f.what_to_do}")
    return "\n".join(lines)


def _result_json(c: StepTestCheck, rec: Record) -> str:
    """JSON text of the check and what was assumed when reading."""
    return json.dumps({"check": asdict(c), "read_as": list(rec.assumptions)}, indent=2)


def _run_check(args: argparse.Namespace) -> int:
    """`check`: print the report (or JSON); exit 0 unless the record is not usable (1)."""
    rec = read_record(args.file, _options(args))
    t = rec.t_s - rec.t_s[0]
    result = check_step_test(t, rec.out, rec.pv, rec.sp, rec.mode)
    print(_result_json(result, rec) if args.json else format_report(result, rec.assumptions))
    return 1 if result.verdict == "not_usable" else 0


def _run_make(args: argparse.Namespace) -> int:
    """`make-dataset`: write the dataset directory and print what was assumed."""
    rec = read_record(args.file, _options(args))
    spec = DatasetSpec(args.loop_name, args.process_kind, args.pv_unit, args.out_unit, args.step_s)
    notes = write_step_test_dataset(rec, args.out, spec)
    print(f"Dataset written to {args.out} ({len(rec.t_s)} raw rows).")
    print("Assumed:\n" + "\n".join(f"  - {n}" for n in notes))
    print(f"Next: point the app's data root at {args.out.parent} and open the Tuning view.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns 0 ok, 1 record not usable (check), 2 bad input or refused."""
    args = _build_parser().parse_args(argv)
    try:
        return _run_check(args) if args.command == "check" else _run_make(args)
    except (ValueError, OSError, IpdtIdentificationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

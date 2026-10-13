# sim/src/crosscut_sim/run.py
"""Command-line runner for the Crosscut simulation suite.

The public API consists of:

* :func:`parse_duration` – parse a duration string into seconds.
* :func:`main` – run the simulation and record the results.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from crosscut_sim.core import Plant, Scenario
from crosscut_sim.dataset import DEFAULT_START_UTC, RunInfo, record
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.plants.wood_berry import WoodBerryPlant
from crosscut_sim.scenarios import build_scenario

PLANTS: dict[str, Callable[[], Plant]] = {
    "wood_berry": WoodBerryPlant,
    "mill_circuit": MillCircuitPlant,
}


def parse_duration(text: str) -> float:
    """Parse a duration string into seconds.

    Parameters
    ----------
    text:
        Duration string with an optional unit suffix 's', 'm', or 'h'.
        No suffix means seconds. Examples: "6h" -> 21600.0, "30m" -> 1800.0,
        "90s" -> 90.0, "1.5h" -> 5400.0, "45" -> 45.0.

    Returns
    -------
    float
        Duration in seconds.

    Raises
    ------
    ValueError
        If the text is empty, missing a number, non-numeric, has an unknown unit,
        or is zero or negative.
    """
    if not text:
        raise ValueError("empty duration string")
    number_text, unit = _split_number_and_unit(text)
    seconds = _to_positive_seconds(number_text, text)
    return _convert_to_seconds(seconds, unit)


def _split_number_and_unit(text: str) -> tuple[str, str]:
    """Split a duration string into its number part and its unit letter.

    A missing suffix means seconds, so the unit defaults to "s".

    Returns
    -------
    tuple[str, str]
        The number text and the unit letter.
    """
    # The suffix is optional, so the last character is only a unit if it is one
    # of the known unit letters. Otherwise the whole text is the number.
    unit = text[-1]
    if unit in ("s", "m", "h"):
        return text[:-1], unit
    return text, "s"


def _to_positive_seconds(number_text: str, text: str) -> float:
    """Convert the number part of a duration string to a positive float.

    Returns
    -------
    float
        The parsed number.

    Raises
    ------
    ValueError
        If the number is not numeric, or is zero or negative.
    """
    # float() accepts "1.5" and scientific notation, but rejects anything with
    # leftover characters, so it doubles as the numeric-syntax check here.
    try:
        seconds = float(number_text)
    except ValueError as e:
        raise ValueError(f"invalid duration: {text}") from e
    if seconds <= 0:
        raise ValueError(f"duration must be positive: {text}")
    return seconds


def _convert_to_seconds(seconds: float, unit: str) -> float:
    """Scale a number expressed in the given unit to seconds.

    Units are: "s" = 1 s, "m" = 60 s, "h" = 3600 s.

    Returns
    -------
    float
        The duration in seconds.

    Raises
    ------
    ValueError
        If the unit is not one of "s", "m", or "h".
    """
    if unit == "m":
        return seconds * 60
    if unit == "h":
        return seconds * 3600
    if unit != "s":
        # Defensive: the caller only ever passes s, m, or h.
        raise ValueError(f"unknown unit: {unit}")
    return seconds


def _build_parser() -> argparse.ArgumentParser:
    """Define the command line; the parser exits with usage (code 2) on a wrong command line."""
    parser = argparse.ArgumentParser(
        prog="python -m crosscut_sim.run",
        description="Run the Crosscut simulation suite and record the results.",
    )
    parser.add_argument("--plant", required=True, choices=sorted(PLANTS), help="plant identifier")
    parser.add_argument("--scenario", default="nominal", help="scenario name (default: nominal)")
    parser.add_argument("--duration", default="6h", help="simulation duration (default: 6h)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    parser.add_argument("--out", required=True, type=Path, help="output directory")
    parser.add_argument(
        "--sample-period", default=None, help="sample period (default: scenario.dt_s)"
    )
    parser.add_argument(
        "--start-utc",
        default=DEFAULT_START_UTC,
        help="start time in UTC (default: 2026-01-01T00:00:00Z)",
    )
    return parser


def _parse_duration_or_exit(parser: argparse.ArgumentParser, text: str) -> float:
    """Parse a duration string; parser.error() prints usage and exits with code 2 on failure."""
    try:
        return parse_duration(text)
    except ValueError as error:
        parser.error(str(error))


def _current_git_commit() -> str | None:
    """Return the short git revision of this repository, or None when it cannot be determined.

    The revision is stored for reproducibility. No git history (or no git installed) is not
    fatal: record() then stores "unknown".
    """
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.SubprocessError:
        return None


def _make_run_info(
    args: argparse.Namespace, dataset_id: str, sample_period_s: float | None
) -> RunInfo:
    """Collect the identity and provenance of this run for the dataset metadata."""
    return RunInfo(
        seed=args.seed,
        dataset_id=dataset_id,
        plant_name=args.plant,
        scenario_name=args.scenario,
        start_utc=args.start_utc,
        sample_period_s=sample_period_s,
        git_commit=_current_git_commit(),
    )


def _record_run(
    args: argparse.Namespace, scenario_obj: Scenario, sample_period_s: float | None
) -> int:
    """Write the dataset for the parsed arguments; return the exit code (1 if it exists)."""
    # A dataset is identified by plant, scenario and seed so that repeated runs
    # can be told apart; the directory name repeats that identity on disk.
    dataset_id = f"{args.plant}_{args.scenario}_seed{args.seed}"
    dataset_dir = args.out / dataset_id
    run_info = _make_run_info(args, dataset_id, sample_period_s)
    # record() refuses to overwrite an existing dataset_dir and raises FileExistsError,
    # which we translate to code 1.
    try:
        record(PLANTS[args.plant](), scenario_obj, dataset_dir, run_info)
    except FileExistsError as error:
        print(str(error), file=sys.stderr)
        return 1

    # Print the path on stdout so callers can pipe it into other tools.
    print(str(dataset_dir))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the simulation and record the results.

    Parse the command line, build the plant and scenario objects, run the
    simulation and write the resulting dataset to disk.

    Parameters
    ----------
    argv:
        Command-line arguments. If None, use sys.argv[1:].

    Returns
    -------
    int
        Exit code: 0 for success, 1 if the dataset directory already exists,
        2 if the scenario is unknown.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    duration = _parse_duration_or_exit(parser, args.duration)

    # None means "use the scenario's own default sampling interval"; only an
    # explicit --sample-period is parsed, so we can tell the two cases apart.
    sample_period_s = None
    if args.sample_period is not None:
        sample_period_s = _parse_duration_or_exit(parser, args.sample_period)

    try:
        scenario_obj = build_scenario(args.plant, args.scenario, duration_s=duration)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    return _record_run(args, scenario_obj, sample_period_s)


if __name__ == "__main__":
    raise SystemExit(main())

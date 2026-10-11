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

from crosscut_sim.core import Plant
from crosscut_sim.dataset import DEFAULT_START_UTC, record
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
    unit = text[-1]
    if unit in ("s", "m", "h"):
        num = text[:-1]
    else:
        num = text
        unit = "s"
    try:
        seconds = float(num)
    except ValueError as e:
        raise ValueError(f"invalid duration: {text}") from e
    if seconds <= 0:
        raise ValueError(f"duration must be positive: {text}")
    if unit == "m":
        seconds *= 60
    elif unit == "h":
        seconds *= 3600
    elif unit != "s":
        raise ValueError(f"unknown unit: {unit}")
    return seconds


def main(argv: Sequence[str] | None = None) -> int:
    """Run the simulation and record the results.

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
    parser = argparse.ArgumentParser(
        prog="python -m crosscut_sim.run",
        description="Run the Crosscut simulation suite and record the results.",
    )
    parser.add_argument(
        "--plant",
        required=True,
        choices=sorted(PLANTS),
        help="plant identifier",
    )
    parser.add_argument(
        "--scenario",
        default="nominal",
        help="scenario name (default: nominal)",
    )
    parser.add_argument(
        "--duration",
        default="6h",
        help="simulation duration (default: 6h)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="random seed (default: 42)",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output directory",
    )
    parser.add_argument(
        "--sample-period",
        default=None,
        help="sample period (default: scenario.dt_s)",
    )
    parser.add_argument(
        "--start-utc",
        default=DEFAULT_START_UTC,
        help="start time in UTC (default: 2026-01-01T00:00:00Z)",
    )

    args = parser.parse_args(argv)

    try:
        duration = parse_duration(args.duration)
    except ValueError as e:
        parser.error(str(e))

    sample_period_s = None
    if args.sample_period is not None:
        try:
            sample_period_s = parse_duration(args.sample_period)
        except ValueError as e:
            parser.error(str(e))

    try:
        scenario_obj = build_scenario(args.plant, args.scenario, duration_s=duration)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    dataset_id = f"{args.plant}_{args.scenario}_seed{args.seed}"
    dataset_dir = args.out / dataset_id

    try:
        git_commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.SubprocessError:
        git_commit = None

    try:
        record(
            PLANTS[args.plant](),
            scenario_obj,
            dataset_dir,
            seed=args.seed,
            dataset_id=dataset_id,
            plant_name=args.plant,
            scenario_name=args.scenario,
            start_utc=args.start_utc,
            sample_period_s=sample_period_s,
            git_commit=git_commit,
        )
    except FileExistsError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(str(dataset_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

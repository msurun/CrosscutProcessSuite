"""exp35 harness: Crosscut's guided stroke test analysis on the public Marques valve data (#84).

Reads the open-loop CSV files of Mendeley Data 10.17632/y7jkjt9jjf (CC BY 4.0) from a data folder
outside the repo, rebuilds a stroke-test record from each file, analyses it with
crosscut_loops.valve_test and compares the deadband with the published Choudhury S. The protocol
and targets are frozen in README.md. A missing folder or file is a clean skip (exit 0).
Usage: python run35.py --data DIR [--out results.json]   (DIR also from env EXP35_DATA)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from crosscut_loops.valve_test import analyze_stroke_test, plan_stroke_test

FILES = {"ramps": "graphite_data_ol_ramps.csv", "sinusoidal": "graphite_data_ol_sinusoidal.csv"}
TS_S = {"ramps": 0.026752, "sinusoidal": 0.01}  # sample period from the first rows of each file
P_MIN_PA, P_MAX_PA = 41368.0, 180000.0  # PARAM_VALVULA p_min, p_max (valve_models.h)
S_REF, J_REF = 26.4235916, 0.0861440961  # GRAPHITE_CHOUDHURY S, J in % of input span
BLOCK = 50  # samples per block (one block = one dwell of the rebuilt record)
STEP_SIZE = 2.0  # plan step size, % of span
TOL = 5.0  # acceptance tolerance on the deadband, % of span
ZIGZAG_MIN = 20.0  # minimum run between two reversals in the reference computation, % of span
MOVE_SIGMAS = 5.0  # reference computation: stem move gate in noise sigmas


def load(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (u in % of input span, stem position x in m); the time column is not used."""
    data = np.loadtxt(path, delimiter=",")
    return (data[:, 1] - P_MIN_PA) / (P_MAX_PA - P_MIN_PA) * 100.0, data[:, 2]


def blocks(values: np.ndarray) -> np.ndarray:
    """Reshape to (n_blocks, BLOCK), dropping the incomplete last block."""
    count = len(values) // BLOCK
    return values[: count * BLOCK].reshape(count, BLOCK)


def rebuild_record(u: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Staircase OP (block mean held flat), real PV samples, time with one block = 1 s."""
    op = np.repeat(blocks(u).mean(axis=1), BLOCK)
    pv = blocks(x).ravel()
    return np.arange(len(op)) / BLOCK, op, pv


def zigzag_pivots(level: np.ndarray, min_run: float) -> list[tuple[int, int]]:
    """(index, direction after it) of reversals of ``level`` that follow a run of >= min_run."""
    pivots: list[tuple[int, int]] = []
    extreme, direction = 0, 0
    for k in range(1, len(level)):
        move = level[k] - level[extreme]
        if direction == 0:
            if abs(move) >= min_run:
                extreme, direction = k, int(np.sign(move))
        elif direction * move > 0:
            extreme = k  # the run goes on: a new extreme
        elif abs(move) >= min_run:
            direction = -direction
            pivots.append((extreme, direction))
            extreme = k
    return pivots


def reference_deadband(u: np.ndarray, x: np.ndarray) -> list[float]:
    """Independent estimate: input travel from each reversal until the stem visibly moves."""
    level, stem = blocks(u).mean(axis=1), np.median(blocks(x), axis=1)
    gate = MOVE_SIGMAS * 1.4826 * float(np.median(np.abs(blocks(x) - stem[:, None])))
    travels = []
    for pivot, sign in zigzag_pivots(level, ZIGZAG_MIN):
        for k in range(pivot + 1, len(level)):
            if sign * (stem[k] - stem[pivot]) > gate and sign * (level[k] - level[pivot]) > 0:
                travels.append(float(abs(level[k] - level[pivot])))
                break
    return travels


def analyse(name: str, folder: Path) -> dict:
    """Run the stroke test analysis and the reference computation on one file."""
    u, x = load(folder / FILES[name])
    t_s, op, pv = rebuild_record(u, x)
    plan = plan_stroke_test(0.0, 1, -10.0, 130.0, None, (STEP_SIZE,), (20,))
    res = analyze_stroke_test(t_s, op, pv, plan)
    ref = reference_deadband(u, x)
    est, bracket = res.deadband, res.deadband_bracket
    return {
        "file": FILES[name], "samples": len(u), "blocks": len(u) // BLOCK,
        "deadband": est, "bracket": bracket, "lower_bound": res.deadband_lower_bound,
        "resolution_le": res.resolution_le, "reason": res.reason,
        "reference_n": len(ref), "reference_median": float(np.median(ref)) if ref else None,
        "reference_q25_q75": [float(v) for v in np.percentile(ref, [25, 75])] if ref else None,
        "T1_pass": est is not None and abs(est - S_REF) <= TOL,
        "T2_pass": bool(ref) and abs(float(np.median(ref)) - S_REF) <= TOL,
        "T3_bracket_contains_S": bracket is not None and bracket[0] <= S_REF <= bracket[1],
    }


def main(argv: list[str]) -> int:
    """CLI entry; prints SKIP and returns 0 when the data is absent."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=os.environ.get("EXP35_DATA", ""))
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    folder = Path(args.data) if args.data else None
    if folder is None or not all((folder / f).is_file() for f in FILES.values()):
        print(f"SKIP exp35: expected {list(FILES.values())} in {folder}")
        return 0
    result = {name: analyse(name, folder) for name in FILES}
    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

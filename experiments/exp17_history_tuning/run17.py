"""exp17: how many real loops contain natural setpoint steps, and how confident is the fit?

Usage: python run17.py <SACAC folder> <ISDB npz folder> <isdb_labels.csv>
Counts only (no per-loop ISDB numbers are printed): loops with at least one excitation window,
and the confidence distribution of tune_from_history. No ground truth: this answers "how many
loops could be tuned from history", not "is the tuning right".
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp12_stiction_scoreboard"))
sys.path.insert(0, str(HERE.parent / "exp13_stiction_suspicion"))
import run13  # noqa: E402
from crosscut_loops.history_tuning import tune_from_history  # noqa: E402
from scoreboard import load_loops  # noqa: E402


def grade(name: str, sp, pv, op, dt_s: float) -> tuple[int, str]:
    """(windows found, confidence) of one record; the tuner never raises on bad data."""
    mask = ~(np.isnan(sp) | np.isnan(pv) | np.isnan(op))
    if mask.sum() < 200:
        return 0, "none"
    r = tune_from_history(name, sp, op, pv, dt_s)
    return r.windows_found, r.confidence


def summary(label: str, rows: list[tuple[int, str]]) -> None:
    """Print how many records have windows and the confidence histogram."""
    with_windows = sum(w > 0 for w, _ in rows)
    conf = Counter(c for _, c in rows)
    print(f"{label}: {with_windows}/{len(rows)} records with a setpoint step; confidence {dict(conf)}")


def main(sacac: Path, isdb: Path, labels: Path) -> None:
    """Run the count on SACAC files and on the ISDB labelled loops."""
    rows = []
    for lp in load_loops():
        for stem in lp.stems:
            sp, pv, op = run13.read_spo(sacac, stem)
            rows.append(grade(lp.name, sp, pv, op, lp.dt_s))
    summary("SACAC files", rows)
    rows = []
    for r in csv.DictReader(labels.open(encoding="utf-8")):
        with np.load(isdb / (r["loop"].replace("/", "_") + ".npz")) as z:
            rows.append(grade(r["loop"], z["sp"], z["pv"], z["op"], float(z["dt_s"])))
    summary("ISDB labelled loops", rows)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))

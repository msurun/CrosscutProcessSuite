"""Make the synthetic step-test CSV the Import e2e spec uploads.

Usage: python make_step_csv.py <out.csv>

A level (integrating) loop in manual mode as a historian would export it: semicolon
separated, decimal comma, ISO UTC times, 2 s samples for 80 min, columns timestamp;LIC1.PV;LIC1.OUT;LIC1.MODE.
OUT is 50 %, steps to 56 % at 30 min and back to 50 % at 50 min (a doublet). PV integrates
(OUT - 50) with slope SLOPE (PV per second per % OUT) after a dead time of THETA_S, plus a little
noise (sd 0.02). The spec compares the slope of the wizard dry run with SLOPE.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

SLOPE = 0.001
THETA_S = 20
DT_S = 2
DURATION_S = 80 * 60
STEP_UP_S = 30 * 60
STEP_DOWN_S = 50 * 60
START = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)


def signals() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Time (s), OUT (%) and PV (%) of the doublet record."""
    t = np.arange(0, DURATION_S + DT_S, DT_S, dtype=float)
    out = 50.0 + 6.0 * ((t >= STEP_UP_S) & (t < STEP_DOWN_S))
    lag = THETA_S // DT_S
    delayed = np.concatenate([np.full(lag, out[0]), out[:-lag]])
    pv = 40.0 + SLOPE * DT_S * np.cumsum(delayed - out[0])
    return t, out, pv + np.random.default_rng(7).normal(0.0, 0.02, len(t))


def main(path: Path) -> None:
    """Write the CSV: semicolon delimiter, decimal comma, MAN in the mode column."""
    t, out, pv = signals()
    lines = ["timestamp;LIC1.PV;LIC1.OUT;LIC1.MODE"]
    for seconds, o, p in zip(t, out, pv, strict=True):
        stamp = (START + timedelta(seconds=float(seconds))).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(f"{stamp};{p:.4f};{o:.2f};MAN".replace(".", ","))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

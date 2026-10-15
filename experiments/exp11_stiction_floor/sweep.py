"""Sweep samples per half-cycle against detection and false-alarm rate of the stiction index.

Design and decision rule were frozen in README.md. Writes results/sweep.md. Usage: python sweep.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from crosscut_loops import stiction_curvefit as cf

LENGTHS = (6, 8, 10, 12, 15, 20, 25, 30, 40, 60)
NOISES = (0.05, 0.15, 0.30)
TRIALS = 200
N_HALF = 40
THRESHOLD = 0.6
MIN_DETECTION = 0.80
MAX_FALSE_ALARM = 0.05
REQUIRED_NOISES = (0.05, 0.15)
REPORT = Path(__file__).resolve().parent / "results" / "sweep.md"


def half_cycle(rng: np.random.Generator, length: int, triangle: bool) -> np.ndarray:
    """One half-cycle: half-sine, or triangle with its apex at 0.4-0.6, scaled by 0.8-1.2."""
    x = np.linspace(0.0, 1.0, length)
    peak = rng.uniform(0.4, 0.6)
    shape = np.where(x < peak, x / peak, (1 - x) / (1 - peak)) if triangle else np.sin(np.pi * x)
    return rng.uniform(0.8, 1.2) * shape


def make_signal(seed: int, length: int, noise: float, triangle: bool) -> np.ndarray:
    """40 alternating half-cycles (lengths jittered by 0.9-1.1) plus white noise."""
    rng = np.random.default_rng(seed)
    parts = []
    for k in range(N_HALF):
        n = max(3, round(length * rng.uniform(0.9, 1.1)))
        parts.append((1 if k % 2 == 0 else -1) * half_cycle(rng, n, triangle))
    signal = np.concatenate(parts)
    return signal + rng.normal(0.0, noise, signal.size)


def rate(length: int, noise: float, triangle: bool) -> tuple[float, float]:
    """(share of trials with index >= THRESHOLD, share with no index at all)."""
    hits = refused = 0
    for seed in range(1, TRIALS + 1):
        result = cf.curve_fit_index(make_signal(seed, length, noise, triangle), 1.0)
        refused += result.index is None
        hits += result.index is not None and result.index >= THRESHOLD
    return hits / TRIALS, refused / TRIALS


def main() -> None:
    """Run the grid with the floor disabled, print the table and the smallest passing L."""
    cf.MIN_SAMPLES_PER_HALF_CYCLE = 1
    rows = [
        "| L | s | detection | refused (tri) | false alarm | refused (sine) |",
        "|---|---|---|---|---|---|",
    ]
    ok: dict[int, bool] = {length: True for length in LENGTHS}
    for length in LENGTHS:
        for noise in NOISES:
            det, ref_t = rate(length, noise, True)
            fa, ref_s = rate(length, noise, False)
            rows.append(
                f"| {length} | {noise} | {det:.0%} | {ref_t:.0%} | {fa:.0%} | {ref_s:.0%} |"
            )
            if noise in REQUIRED_NOISES and not (det >= MIN_DETECTION and fa <= MAX_FALSE_ALARM):
                ok[length] = False
    passing = [n for n in LENGTHS if all(ok[m] for m in LENGTHS if m >= n)]
    rows += ["", f"F (smallest L passing at and above): {passing[0] if passing else 'none'}"]
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("\n".join(rows))


if __name__ == "__main__":
    main()

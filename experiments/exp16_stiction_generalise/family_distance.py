"""Independence check: two-sample KS distance of each C6 feature between families (ranked rows).

Usage: python family_distance.py <table.npz>. Reports G3 vs G1 and G3 vs G2 next to G1 vs G2;
a G3 that only repeats G1/G2 would show distances no larger than G1 vs G2.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

NAMES = ("he_fold", "h3_out", "h3_pv", "odd", "log2_half", "ln_prom")


def ks(a: np.ndarray, b: np.ndarray) -> float:
    """Two-sample Kolmogorov-Smirnov statistic."""
    grid = np.sort(np.concatenate([a, b]))
    fa = np.searchsorted(np.sort(a), grid, side="right") / len(a)
    fb = np.searchsorted(np.sort(b), grid, side="right") / len(b)
    return float(np.max(np.abs(fa - fb)))


def main(path: Path) -> None:
    """Print the KS table per kind."""
    with np.load(path) as z:
        t = {k: z[k] for k in z.files}
    ok = ~np.isnan(t["x"]).any(axis=1)
    for kind in "FL":
        print(f"kind {kind}: feature  G1-G2  G1-G3  G2-G3")
        for i, name in enumerate(NAMES):
            v = {
                f: t["x"][ok & (t["kind"] == kind) & (t["family"] == f), i]
                for f in ("G1", "G2", "G3")
            }
            print(
                f"  {name:10s} {ks(v['G1'], v['G2']):.2f}  {ks(v['G1'], v['G3']):.2f}"
                f"  {ks(v['G2'], v['G3']):.2f}"
            )


if __name__ == "__main__":
    main(Path(sys.argv[1]))

"""Round 1: LOFO worst-family AUC of C7a (6 features) and C7b (+2 shape features), dev table.

Usage: python round1.py <table.npz> <shape.npz>. Stop rule: C7b must beat C7a by >= 0.02 worst-family.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from lofo import baseline, line, load, lofo


def main(table: Path, shape: Path) -> None:
    """Print baselines, C7a and C7b."""
    t = load(table)
    print(line("shipped", baseline(t, "shipped")))
    print(line("C7a (6 features)", lofo(t, list(range(6)))))
    with np.load(shape) as z:
        t["x"] = np.hstack([t["x"], z["shape"]])
    res = lofo(t, list(range(8)))
    print(line("C7b (+ area, squareness)", res))
    ok = ~np.isnan(t["x"]).any(axis=1)
    print(
        "ranked share C7b by family:",
        {f: round(float(ok[t["family"] == f].mean()), 2) for f in ("G1", "G2", "G3")},
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

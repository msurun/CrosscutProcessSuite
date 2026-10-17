"""Dev evaluation of the exp15 variants on cached exp01 records (seeds 1-20 only).

Usage: python eval_exp01.py <cache dir> <variant> [variant ...]
Prints, per class, how many of 20 seeds give test_valve / unlikely / not_ranked.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import cand15
import numpy as np

SEEDS = range(1, 21)


def cells(folder: Path) -> list[str]:
    """Class names found in the cache, in a stable order."""
    return sorted({p.name.split("__")[0] for p in folder.glob("*.npz")})


def advice(folder: Path, name: str, seed: int, variant: str) -> str:
    """Advice of one cached record under one variant (constant setpoint: not in the record)."""
    with np.load(folder / f"{name}__{seed}.npz") as z:
        pv, out, dt_s = z["pv"], z["out"], float(z["dt_s"])
    return cand15.suspicion15(np.zeros_like(pv), pv, out, dt_s, "F", variant).advice


def main(folder: Path, variants: list[str]) -> None:
    """Print one line per class and variant."""
    for name in cells(folder):
        row = []
        for v in variants:
            c = Counter(advice(folder, name, s, v) for s in SEEDS)
            row.append(f"{v}: {c['test_valve']:2d}/{c['unlikely']:2d}/{c['not_ranked']:2d}")
        print(f"{name:52s}", "  ".join(row))
    print("columns: test_valve / unlikely / not_ranked of 20 dev seeds")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])

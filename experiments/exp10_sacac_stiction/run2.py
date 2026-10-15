"""Round 2 of exp10: level (integrating) loops scored on PV, the rest on OP, floor 30 as shipped.

Targets are frozen in README.md ("Round 2"). Usage: python -I run2.py <folder with the unzipped SACAC data>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from run import LOOPS, STICTION_INDEX, index_for, read_op

LEVEL_LOOPS = ("horch-level", "eastman-LC2", "pisa-power-level")
PV_COLUMN = 2
MIN_LEVEL_HITS = 2
FLOOR = 30


def median_index(root: Path, stems: list[str], dt_s: float, column: int) -> float | None:
    """Median curve-fit index over a loop's files; None when no file yields one."""
    values = [index_for(read_op(root, s, column), dt_s, FLOOR).index for s in stems]
    found = [v for v in values if v is not None]
    return float(np.median(found)) if found else None


def main(root: Path) -> None:
    """Print one line per loop and the verdict on target L."""
    hits = 0
    for name, (dt_s, stems) in LOOPS.items():
        level = name in LEVEL_LOOPS
        idx = median_index(root, stems, dt_s, PV_COLUMN if level else 3)
        hits += int(level and idx is not None and idx >= STICTION_INDEX)
        print(f"{name:22s} {'PV' if level else 'OP'}  index {idx if idx is None else round(idx, 2)}")
    print(f"target L (>= {MIN_LEVEL_HITS} of 3 level loops >= {STICTION_INDEX}): {hits} ->",
          "met" if hits >= MIN_LEVEL_HITS else "MISSED")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

"""Round 3 of exp10: the shipped stiction index on SACAC loops that are NOT sticking.

Targets are frozen in README.md ("Round 3"). Usage: python run3.py <unzipped SACAC data folder>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from run import STICTION_INDEX, index_for, read_op

FLOOR = 30
SINGLE = "other-F-paper-horch-2003"
NEGATIVES = {  # loop -> (sampling period s, file stems)
    SINGLE: (1.0, [SINGLE]),
    "other-F-paper-horch-2003-2": (1.0, ["other-F-paper-horch-2003-2"]),
    "other-L-paper-horch-2003": (2.0, ["other-L-paper-horch-2003"]),
    "tuning-L-paper-horch-2003": (1.0, ["tuning-L-paper-horch-2003"]),
    "tuning-Q-paper-horch-2003": (1.0, ["tuning-Q-paper-horch-2003"]),
    "tuning-F-chemical-DB": (
        1.0,
        [f"tuning-F-chemical-DB-{n}-baccidicapaci-2018" for n in range(1, 13)],
    ),
}
LOWER_BAND = 0.4
WILSON_Z = 1.96


def wilson_upper(hits: int, n: int) -> float:
    """95 % Wilson upper bound of a proportion."""
    p = hits / n
    centre = p + WILSON_Z**2 / (2 * n)
    spread = WILSON_Z * np.sqrt(p * (1 - p) / n + WILSON_Z**2 / (4 * n**2))
    return float((centre + spread) / (1 + WILSON_Z**2 / n))


def main(root: Path) -> None:
    """Print one line per negative loop and the verdicts on N1 and N2."""
    medians = []
    for name, (dt_s, stems) in NEGATIVES.items():
        found = [index_for(read_op(root, s), dt_s, FLOOR).index for s in stems]
        found = [v for v in found if v is not None]
        medians.append(float(np.median(found)) if found else None)
        print(f"{name:30s} files with index {len(found)}/{len(stems)}  median {medians[-1]}")
    have = [m for m in medians if m is not None]
    flagged = sum(m >= STICTION_INDEX for m in have)
    middle = sum(LOWER_BAND <= m < STICTION_INDEX for m in have)
    bound = wilson_upper(flagged, len(medians))
    print(
        f"N1 (0 of 6 flagged): {flagged} flagged -> {'met' if flagged == 0 else 'MISSED'}, "
        f"95 % upper bound {bound:.0%}"
    )
    print(
        f"N2: {len(have)} of 6 with an index, {middle} in 0.4-0.6; "
        f"{'N1 not informative' if len(have) < 2 else 'N1 informative'}"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))

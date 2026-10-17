"""T7 sanity: share of noise-only records (OUT and PV independent noise) that get a window."""

from __future__ import annotations

import sys

import cand15
import numpy as np
from calib_prominence import noise

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 777  # dev; the final audit uses another seed
KINDS = ("white", "ar-0.5", "ar-0.9", "ar-0.98", "walk")


def rate(finder, n: int, count: int = 40) -> dict[str, float]:
    """Fraction of records with a window per noise kind."""
    rng = np.random.default_rng(SEED)
    out = {}
    for kind in KINDS:
        hits = 0
        for _ in range(count):
            pv, op = noise(rng, kind, n), noise(rng, kind, n)
            hits += finder(np.zeros(n), pv, op) is not None
        out[kind] = hits / count
    return out


if __name__ == "__main__":
    for name, finder in (("c2a", cand15.find_window_p),):
        for n in (6000, 14400):
            r = rate(finder, n)
            print(
                name,
                n,
                {k: f"{v:.0%}" for k, v in r.items()},
                f"mean {np.mean(list(r.values())):.1%}",
            )

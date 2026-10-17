"""G3 realism check without a detector: oscillation statistics of G3 versus the SACAC loops.

Usage: python realism.py <SACAC folder>. Per record the C5 oscillation window gives the period
(samples) and half-cycle; also std(PV)/std(OUT) in the window. Quantiles are printed per source.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for sub in ("exp15_stiction_robust", "exp13_stiction_suspicion", "exp12_stiction_scoreboard"):
    sys.path.insert(0, str(HERE.parent / sub))
import cand15  # noqa: E402
import run13  # noqa: E402
from g3 import CASES, NOISES, simulate_g3  # noqa: E402
from scoreboard import load_loops  # noqa: E402


def stats(sp, pv, op, kind: str) -> tuple[float, float] | None:
    """(period in samples, std PV / std OUT) of the oscillation window, or None."""
    sig = pv if kind == "L" else op
    seg = cand15.c5_segment(sp, pv, op, sig)
    if seg is None:
        return None
    sl, period = seg
    return period, float(np.std(pv[sl]) / max(np.std(op[sl]), 1e-9))


def summarise(label: str, rows: list, total: int) -> None:
    """Print coverage and quantiles of period, share below 18 samples per half-cycle, ratio."""
    if not rows:
        print(f"{label}: no oscillation window in {total}")
        return
    p, r = np.array([x[0] for x in rows]), np.array([x[1] for x in rows])
    q = lambda a: " ".join(f"{v:.2f}" for v in np.quantile(a, [0.1, 0.5, 0.9]))  # noqa: E731
    print(
        f"{label}: windows {len(rows)}/{total}; period q10/50/90 {q(p)}; "
        f"half<18 samples {np.mean(p / 2 < 18):.0%}; std(PV)/std(OUT) {q(r)}"
    )


def main(root: Path) -> None:
    """Compare G3 stick and healthy records with the SACAC counted loops."""
    rows = {"G3 stick": [], "G3 healthy": []}
    n = {"G3 stick": 0, "G3 healthy": 0}
    for kind in "FL":
        for ci, case in enumerate(CASES):
            for ni, noise in enumerate(NOISES):
                for seed in range(1, 21):
                    rng = np.random.default_rng([seed, "FL".index(kind), ci, ni])
                    r = simulate_g3(rng, kind, case, noise)
                    key = "G3 stick" if r.label else "G3 healthy"
                    n[key] += 1
                    s = stats(r.sp, r.pv, r.op, kind)
                    rows[key] += [s] if s else []
    for key in rows:
        summarise(key, rows[key], n[key])
    for label in ("stick", "other"):
        got, tot = [], 0
        for lp in (x for x in load_loops() if x.confidence != "low"):
            if (lp.label == "stick") != (label == "stick"):
                continue
            for stem in lp.stems:
                tot += 1
                s = stats(*run13.read_spo(root, stem), "L" if lp.kind == "L" else "F")
                got += [s] if s else []
        summarise(f"SACAC {label}", got, tot)


if __name__ == "__main__":
    main(Path(sys.argv[1]))

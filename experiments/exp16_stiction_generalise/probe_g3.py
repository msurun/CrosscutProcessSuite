"""Probe: shipped suspicion on G3 dev records (seeds 1-20): AUC and flag rate per healthy case.

Usage: python probe_g3.py. Dev use only; G3 final seeds come from the frozen salt later.
"""

from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

import numpy as np
from crosscut_loops.stiction_suspicion import stiction_suspicion
from g3 import CASES, NOISES, simulate_g3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exp15_stiction_robust"))
from eval_synth import auc  # noqa: E402


def job(args: tuple[str, str, str, int]) -> tuple:
    """Score one G3 record with the shipped module; abstain counts as 0."""
    kind, case, noise, seed = args
    rng = np.random.default_rng([seed, "FL".index(kind), CASES.index(case), NOISES.index(noise)])
    r = simulate_g3(rng, kind, case, noise)
    res = stiction_suspicion(r.sp, r.pv, r.op, r.dt_s, kind)
    score = 0.0 if res.score is None else res.score
    return kind, case, noise, r.label, score, res.score is not None, res.advice == "test_valve"


def main() -> None:
    """Run all combinations and print the table."""
    jobs = [(k, c, n, s) for k in "FL" for c in CASES for n in NOISES for s in range(1, 21)]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(job, jobs, chunksize=10))
    for kind in "FL":
        sub = [r for r in rows if r[0] == kind]
        pos = [r[4] for r in sub if r[3] == 1]
        neg = [r[4] for r in sub if r[3] == 0]
        print(f"kind {kind}: AUC {auc(pos, neg):.3f} (pos {len(pos)}, neg {len(neg)})")
    for case in CASES:
        sub = [r for r in rows if r[1] == case]
        print(
            f"{case:18s} ranked {np.mean([r[5] for r in sub]):.0%} "
            f"flagged {np.mean([r[6] for r in sub]):.0%} (n={len(sub)})"
        )


if __name__ == "__main__":
    main()

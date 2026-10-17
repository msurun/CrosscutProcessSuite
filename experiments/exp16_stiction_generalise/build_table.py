"""Build the dev feature table for leave-one-family-out: G1 (synth14), G2 (shifted), G3 (exp16).

Usage: python build_table.py <synth cache dir> <out.npz>. Dev seeds only: G1 100-399 and G2 1-300
from the exp15 cache, G3 seeds 1-60 generated here. Per record: family, kind, case, label, the
six C6 features (nan if not ranked), and the shipped and C4a scores (abstain -> nan).
"""

from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp15_stiction_robust"))
sys.path.insert(0, str(HERE.parent / "exp14_stiction_classifier"))
import cand15  # noqa: E402
from combiner import features_c6  # noqa: E402
from g3 import CASES as G3_CASES  # noqa: E402
from g3 import NOISES as G3_NOISES  # noqa: E402
from g3 import simulate_g3  # noqa: E402

G3_DEV_SEEDS = range(1, 61)


def row(family: str, kind: str, case: str, label: float, sp, pv, op, dt_s: float) -> tuple:
    """Features and scores of one record."""
    f = features_c6(sp, pv, op, kind)
    scores = []
    for variant in ("base", "c4a"):
        r = cand15.suspicion15(sp, pv, op, dt_s, kind, variant)
        scores.append(np.nan if r.score is None else r.score)
    return family, kind, case, label, np.full(6, np.nan) if f is None else f, *scores


def cached_job(path: str) -> tuple:
    """One cached G1/G2 record."""
    gen, kind, case, _noise, _seed = Path(path).stem.split("_")
    with np.load(path) as z:
        sp, pv, op, label = z["sp"], z["pv"], z["op"], float(z["label"])
    return row("G1" if gen == "s14" else "G2", kind, case, label, sp, pv, op, 1.0)


def g3_job(args: tuple[str, str, str, int]) -> tuple:
    """One freshly generated G3 dev record."""
    kind, case, noise, seed = args
    rng = np.random.default_rng(
        [seed, "FL".index(kind), G3_CASES.index(case), G3_NOISES.index(noise)]
    )
    r = simulate_g3(rng, kind, case, noise)
    return row("G3", kind, case, float(r.label), r.sp, r.pv, r.op, r.dt_s)


def main(cache: Path, out: Path) -> None:
    """Compute all rows in parallel and save the table."""
    files = [str(f) for f in sorted(cache.glob("*.npz"))]
    jobs = [(k, c, n, s) for k in "FL" for c in G3_CASES for n in G3_NOISES for s in G3_DEV_SEEDS]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(cached_job, files, chunksize=16))
        rows += list(pool.map(g3_job, jobs, chunksize=16))
    cols = list(zip(*rows, strict=True))
    np.savez(
        out,
        family=np.array(cols[0]),
        kind=np.array(cols[1]),
        case=np.array(cols[2]),
        label=np.array(cols[3]),
        x=np.array(cols[4]),
        shipped=np.array(cols[5]),
        c4a=np.array(cols[6]),
    )
    print(f"{len(rows)} records")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

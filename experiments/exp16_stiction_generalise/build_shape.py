"""Append the two C7b shape features to the dev table (same record order as build_table.py).

Usage: python build_shape.py <synth cache dir> <out.npz>. Writes ``shape`` (n x 2, nan if the
record is not ranked or cannot be folded).
"""

from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp15_stiction_robust"))
import build_table as bt  # noqa: E402
import cand15  # noqa: E402
from shape_features import loop_shape  # noqa: E402


def shape_of(sp, pv, op, kind: str) -> np.ndarray:
    """Shape features on the C5 segment, nan pair when unavailable."""
    sig = pv if kind == "L" else op
    seg = cand15.c5_segment(sp, pv, op, sig)
    res = None if seg is None else loop_shape(op[seg[0]], pv[seg[0]], seg[1])
    return np.full(2, np.nan) if res is None else np.array(res)


def cached_job(path: str) -> np.ndarray:
    """One cached G1/G2 record."""
    _gen, kind, _case, _noise, _seed = Path(path).stem.split("_")
    with np.load(path) as z:
        return shape_of(z["sp"], z["pv"], z["op"], kind)


def g3_job(args: tuple[str, str, str, int]) -> np.ndarray:
    """One G3 dev record (same seeding as build_table)."""
    kind, case, noise, seed = args
    rng = np.random.default_rng(
        [seed, "FL".index(kind), bt.G3_CASES.index(case), bt.G3_NOISES.index(noise)]
    )
    r = bt.simulate_g3(rng, kind, case, noise)
    return shape_of(r.sp, r.pv, r.op, kind)


def main(cache: Path, out: Path) -> None:
    """Compute in the same order as build_table and save."""
    files = [str(f) for f in sorted(cache.glob("*.npz"))]
    jobs = [
        (k, c, n, s)
        for k in "FL"
        for c in bt.G3_CASES
        for n in bt.G3_NOISES
        for s in bt.G3_DEV_SEEDS
    ]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(cached_job, files, chunksize=16))
        rows += list(pool.map(g3_job, jobs, chunksize=16))
    np.savez(out, shape=np.array(rows))
    print(len(rows))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

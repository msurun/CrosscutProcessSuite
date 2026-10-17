"""Cache the exp01 mill-simulation records (settled window) as npz for fast repeated evaluation.

Usage: python cache_exp01.py <cache dir> <first seed> <last seed>. Dev seeds are 1-20; the final
seeds 21-40 are generated only by the final run (final.py), never cached by hand.
"""

from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exp01_stiction_validation"))
import acceptance  # noqa: E402
import cases  # noqa: E402

MAX_WORKERS = 4


def one(args: tuple[str, cases.Case, int, str]) -> str:
    """Simulate one cell and seed, settle, and write cache/<name>__<seed>.npz."""
    name, case, seed, folder = args
    pv, out, dt_s = cases.simulate_case(case, seed)
    pv, out = acceptance.settle(pv, out, dt_s)
    np.savez(Path(folder) / f"{name}__{seed}.npz", pv=pv, out=out, dt_s=dt_s)
    return name


def main(folder: str, first: int, last: int) -> None:
    """Simulate every positive and negative class for seeds first..last."""
    Path(folder).mkdir(parents=True, exist_ok=True)
    named = {**acceptance.positive_cases(), **acceptance.negative_cases()}
    jobs = [(n, c, s, folder) for n, c in named.items() for s in range(first, last + 1)]
    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        list(pool.map(one, jobs))
    print(f"cached {len(jobs)} records in {folder}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))

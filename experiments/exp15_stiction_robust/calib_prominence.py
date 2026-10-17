"""Set PROMINENCE_MIN from noise-only synthetic records (white, AR(1), random walk, 1/f-like).

For each record the largest prominence over the 15 candidate segments (OUT and PV treated as two
independent noise series) is taken; the threshold is the 99th percentile over all records, so that
the multiple-testing over 15 segments x 2 signals is included. Synthetic only, no real data.
"""

from __future__ import annotations

import cand15
import numpy as np
from crosscut_loops import stiction_suspicion as ss
from crosscut_loops.stiction_curvefit import _detrend

N_RECORDS = 60
LENGTHS = (3000, 6000, 14400)


def noise(rng: np.random.Generator, kind: str, n: int) -> np.ndarray:
    """One noise-only series: white, AR(1) with phi 0.5 / 0.9 / 0.98, or a random walk."""
    e = rng.standard_normal(n)
    if kind == "white":
        return e
    if kind == "walk":
        return np.cumsum(e)
    phi = float(kind.split("-")[1])
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return x


def worst(rng: np.random.Generator, kind: str, n: int) -> float:
    """Largest prominence over the 15 segments of two independent noise series."""
    series = [noise(rng, kind, n) for _ in range(2)]
    best = 0.0
    for k in ss.SEGMENT_SPLITS:
        for i in range(k):
            for s in series:
                f = cand15.peak_prominence(_detrend(s[i * n // k : (i + 1) * n // k]))
                if f is not None and n / k / f[0] >= ss.MIN_CYCLES:
                    best = max(best, f[1])
    return best


def worst_pair(rng: np.random.Generator, kind: str, n: int) -> float:
    """Largest min(prominence OUT, prominence PV) over segments where periods agree (5 %)."""
    out, pv = noise(rng, kind, n), noise(rng, kind, n)
    best = 0.0
    for k in ss.SEGMENT_SPLITS:
        for i in range(k):
            sl = slice(i * n // k, (i + 1) * n // k)
            a, b = (
                cand15.peak_prominence(_detrend(out[sl])),
                cand15.peak_prominence(_detrend(pv[sl])),
            )
            if a is None or b is None or n / k / a[0] < ss.MIN_CYCLES:
                continue
            if abs(a[0] / b[0] - 1.0) <= cand15.PERIOD_AGREEMENT:
                best = max(best, min(a[1], b[1]))
    return best


def pair_main(rng: np.random.Generator, kinds: tuple[str, ...]) -> None:
    """Print the coincidence-prominence percentiles of noise-only record pairs."""
    pooled = []
    for kind in kinds:
        vals = [worst_pair(rng, kind, n) for n in LENGTHS for _ in range(N_RECORDS)]
        pooled += vals
        print(
            f"pair {kind:8s} p50 {np.percentile(vals, 50):5.1f} p99 {np.percentile(vals, 99):5.1f}"
        )
    print(
        f"pair pooled p97 = {np.percentile(pooled, 97):.1f}, p99 = {np.percentile(pooled, 99):.1f}"
    )


if __name__ == "__main__":
    pair_main(np.random.default_rng(31), ("white", "ar-0.5", "ar-0.9", "ar-0.98", "walk"))
    raise SystemExit(0)
    rng = np.random.default_rng(2024)
    kinds = ("white", "ar-0.5", "ar-0.9", "ar-0.98", "walk")
    allv = {}
    for kind in kinds:
        vals = [worst(rng, kind, n) for n in LENGTHS for _ in range(N_RECORDS)]
        allv[kind] = vals
        print(
            f"{kind:8s} max-prominence p50 {np.percentile(vals, 50):6.1f} "
            f"p99 {np.percentile(vals, 99):6.1f}"
        )
    pooled = np.concatenate(list(allv.values()))
    print(f"pooled p99 = {np.percentile(pooled, 99):.1f}, p97 = {np.percentile(pooled, 97):.1f}")

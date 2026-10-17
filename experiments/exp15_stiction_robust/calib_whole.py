"""Prominence gate for a single whole-record peak: 97th percentile over noise-only records (synthetic)."""

from __future__ import annotations

import cand15
import numpy as np
from calib_prominence import noise
from crosscut_loops.stiction_curvefit import _detrend

if __name__ == "__main__":
    rng = np.random.default_rng(55)
    vals = []
    for kind in ("white", "ar-0.5", "ar-0.9", "ar-0.98", "walk"):
        for n in (3000, 6000, 14400):
            for _ in range(60):
                f = cand15.peak_prominence(_detrend(noise(rng, kind, n)))
                vals.append(0.0 if f is None else f[1])
    print(
        f"whole-record noise prominence p95 {np.percentile(vals, 95):.1f} p97 {np.percentile(vals, 97):.1f} p99 {np.percentile(vals, 99):.1f}"
    )

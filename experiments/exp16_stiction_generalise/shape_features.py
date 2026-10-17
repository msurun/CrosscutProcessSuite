"""C7b features (fixed in README amendment 3): shape of the folded OUT-PV loop.

area_ratio = shoelace area of the phase-averaged loop / (range OUT * range PV): a sine/sine
ellipse gives 0.785, a degenerate loop 0. squareness = mean over the loop of max(|u|, |v|) with
u, v the centred values scaled by half ranges: an ellipse gives 0.90, a parallelogram or
rectangle more.
"""

from __future__ import annotations

import numpy as np

BINS = 64


def fold(x: np.ndarray, period: float) -> np.ndarray | None:
    """Phase-average ``x`` into BINS bins (None if a bin is empty)."""
    phase = ((np.arange(len(x)) % period) / period * BINS).astype(int)
    sums, counts = np.bincount(phase, x, BINS), np.bincount(phase, minlength=BINS)
    return None if (counts == 0).any() else sums / counts


def loop_shape(out: np.ndarray, pv: np.ndarray, period: float) -> tuple[float, float] | None:
    """(area_ratio, squareness) of the folded loop, or None when it cannot be folded."""
    a, b = fold(out - out.mean(), period), fold(pv - pv.mean(), period)
    if a is None or b is None:
        return None
    ra, rb = np.ptp(a), np.ptp(b)
    if ra < 1e-12 or rb < 1e-12:
        return None
    u, v = (a - a.mean()) / (ra / 2), (b - b.mean()) / (rb / 2)
    area = 0.5 * abs(np.sum(u * np.roll(v, -1) - np.roll(u, -1) * v)) / 4.0
    return float(area), float(np.mean(np.maximum(np.abs(u), np.abs(v))))

"""Oscillation window, Horch cross-correlation and the suspicion score of one loop record (exp13).

Horch's idea (H. Horch, Control Eng. Practice 7, 1999, recalled from the abstract): with a sticking
valve the cross-correlation of OP and PV is an odd function of the lag, with a disturbance it is
even. We measure the odd share of the cross-correlation energy of OP and raw PV. On synthetic loops
this separates kind F (AUC 0.83) but not integrating kind L (0.47; the first difference of PV
gave 0.18 for F and 0.52 for L), so Horch is not used for kind L. The curve-fit index is candidate A
of exp12. Scores are in [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from candidate_a import curve_fit_index_a, period_samples
from crosscut_loops import stiction_curvefit as cf

MIN_CYCLES = 6
MIN_REGULARITY = 0.5
SEGMENT_SPLITS = (1, 2, 4, 8)
MAX_SP_SWING = 0.3  # SP peak-to-peak allowed, relative to the PV oscillation peak-to-peak


@dataclass(frozen=True)
class Window:
    """A stretch [start, stop) of the record that holds a regular oscillation."""

    start: int
    stop: int
    period: float
    regularity: float


def regularity_at(x: np.ndarray, lag: int) -> float:
    """Normalised autocorrelation of ``x`` at ``lag`` (1 = perfectly periodic)."""
    spectrum = np.fft.rfft(x, 2 * x.size)
    acf = np.fft.irfft(spectrum * np.conj(spectrum))[: x.size]
    return float(acf[lag] / acf[0]) if acf[0] > 0 else 0.0


def try_segment(sp: np.ndarray, pv: np.ndarray, a: int, b: int) -> Window | None:
    """The segment as a Window if it has enough regular cycles and a quiet setpoint, else None."""
    x = cf._detrend(pv[a:b])
    period = period_samples(x)
    if period is None or (b - a) / period < MIN_CYCLES:
        return None
    reg = regularity_at(x, int(round(period)))
    quiet = np.ptp(sp[a:b]) <= MAX_SP_SWING * max(np.ptp(x), 1e-12)
    return Window(a, b, period, reg) if reg >= MIN_REGULARITY and quiet else None


def find_window(sp: np.ndarray, pv: np.ndarray) -> Window | None:
    """Best segment among the whole record, halves, quarters and eighths (longer wins near ties)."""
    n = pv.size
    found = []
    for k in SEGMENT_SPLITS:
        for i in range(k):
            w = try_segment(sp, pv, i * n // k, (i + 1) * n // k)
            if w is not None:
                found.append((w.regularity + 0.05 * np.log2(w.stop - w.start), w))
    return max(found, key=lambda f: f[0])[1] if found else None


def horch_oddness(op: np.ndarray, pv: np.ndarray, period: float) -> float:
    """Odd share of the OP-PV cross-correlation energy over lags of +-1 period (0..1)."""
    x, y = cf._detrend(op), cf._detrend(pv)
    m = int(period)
    full = np.correlate(x, y, "full") / (x.std() * y.std() * x.size + 1e-12)
    mid = x.size - 1
    pos, neg = full[mid + 1 : mid + m + 1], full[mid - m : mid][::-1]
    odd, even = (pos - neg) / 2.0, (pos + neg) / 2.0
    return float(np.sum(odd**2) / (np.sum(odd**2) + np.sum(even**2) + 1e-12))


def calibrated(raw: float, cal: tuple[float, float]) -> float:
    """Map a raw oddness to [0, 1].

    0 is the synthetic non-sticking median, 1 is the sticking one.
    """
    lo, hi = cal
    return float(np.clip((raw - lo) / (hi - lo), 0.0, 1.0))


def file_score(
    sp: np.ndarray, pv: np.ndarray, op: np.ndarray, dt_s: float, kind: str, cal: tuple[float, float]
) -> dict[str, float] | None:
    """Tests and mean score on the oscillation window, or None if the record has no regular one."""
    w = find_window(sp, pv)
    if w is None:
        return None
    sl = slice(w.start, w.stop)
    he = curve_fit_index_a((pv if kind == "L" else op)[sl], dt_s).index
    horch = (
        calibrated(horch_oddness(op[sl], pv[sl], w.period), cal) if kind != "L" else float("nan")
    )
    parts = [p for p in (horch, he) if p is not None and not np.isnan(p)]
    if not parts:
        return None
    return {
        "he": float("nan") if he is None else he,
        "horch": horch,
        "score": float(np.mean(parts)),
        "period": w.period,
        "op_ptp": float(np.ptp(op[sl])),
    }

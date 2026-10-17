"""Dev-only study: AUC of single candidate features, stiction vs each healthy class, per kind."""

from __future__ import annotations

import sys
from pathlib import Path

import cand15
import numpy as np
from crosscut_loops import stiction_suspicion as ss
from crosscut_loops.stiction_curvefit import _detrend


def harmonic_ratio(x: np.ndarray, period: float) -> float:
    """Amplitude of the 3rd harmonic over the fundamental of the folded waveform."""
    wave, _ = cand15.fold(x, period)
    spec = np.abs(np.fft.rfft(wave))
    return float(spec[3] / (spec[1] + 1e-12))


def features(sp, pv, op, kind) -> dict[str, float] | None:
    """Candidate features on the dominant spectral period of OUT (None if no period)."""
    xo, xp = _detrend(op), _detrend(pv)
    f = cand15.peak_prominence(xo) or cand15.peak_prominence(xp)
    if f is None:
        return None
    period = f[0]
    sig_he = xp if kind == "L" else xo
    wave_o, _ = cand15.fold(xo, period)
    wave_p, _ = cand15.fold(xp, period)
    he_fold = cand15.folded_index(sig_he, period)
    fo = np.fft.rfft(wave_o)[1]
    fp = np.fft.rfft(wave_p)[1]
    return {
        "he_fold": np.nan if he_fold is None else he_fold,
        "h3_out": harmonic_ratio(xo, period),
        "h3_pv": harmonic_ratio(xp, period),
        "odd": ss._horch_oddness(op, pv, period),
        "phase_op_pv": float(np.abs(np.angle(fp / fo))),
        "pv_over_op": float(np.abs(fp) / (np.abs(fo) + 1e-12)),
        "prom_out": f[1],
    }


def auc(p, n):
    """AUC ignoring NaNs; nan if a class is empty."""
    p, n = [x for x in p if not np.isnan(x)], [x for x in n if not np.isnan(x)]
    return (
        float(np.mean([(a > b) + 0.5 * (a == b) for a in p for b in n]))
        if p and n
        else float("nan")
    )


if __name__ == "__main__":
    rows = []
    for f in sorted(Path(sys.argv[1]).glob("*.npz")):
        gen, kind, case, noise, _ = f.stem.split("_")
        with np.load(f) as z:
            ft = features(z["sp"], z["pv"], z["op"], kind)
        if ft:
            rows.append((gen, kind, case, ft))
    names = list(rows[0][3])
    for kind in "FL":
        print(f"== kind {kind}   AUC of 'higher = stiction' (0.5 = no information)")
        print(f"{'feature':12s}" + "".join(f"{c:>9s}" for c in ("sine", "square", "tuning")))
        for name in names:
            line = f"{name:12s}"
            for neg in ("sine", "square", "tuning"):
                p = [r[3][name] for r in rows if r[1] == kind and r[2] == "stick"]
                n = [r[3][name] for r in rows if r[1] == kind and r[2] == neg]
                line += f"{auc(p, n):9.2f}"
            print(line)

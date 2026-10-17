"""Ablations of the shipped suspicion (C4a) on DEV data: without He, Horch, or the fallback.

Usage: python ablate_c4a.py <exp01 cache> <synth cache>. Final seeds are not read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cand15
import numpy as np
from crosscut_loops import stiction_suspicion as ss
from eval_synth import auc

VARIANTS = ("full", "no_he", "no_horch", "no_fallback")


def score(sp, pv, out, kind: str, variant: str) -> float | None:
    """Suspicion score of one variant (None = not ranked)."""
    w = cand15.find_window_p(sp, pv, out)
    sig = pv if kind == "L" else out
    if w is None:
        if variant in ("no_fallback", "no_he"):
            return None
        he, _ = ss._he_index(sig)
        return he
    sl = slice(w.start, w.stop)
    he = None if variant == "no_he" else ss._he_index(sig[sl])[0]
    horch = None
    if kind != "L" and variant != "no_horch":
        horch = ss._calibrated(ss._horch_oddness(out[sl], pv[sl], w.period))
    parts = [p for p in (horch, he) if p is not None]
    return float(np.mean(parts)) if parts else None


def exp01(folder: Path) -> None:
    """Flags of 20 dev seeds for the cells that matter."""
    cells = (
        "sticking band 8% (full noise)",
        "sticking band 6% (full noise)",
        "sticking band 8% (low noise)",
        "aggressive tuning (full noise)",
        "nominal wander (full noise)",
        "sine forcing (full noise)",
        "square forcing (adversarial) (full noise)",
    )
    print("exp01 dev flags of 20:", *VARIANTS, sep="  ")
    for name in cells:
        row = []
        for v in VARIANTS:
            n = 0
            for s in range(1, 21):
                with np.load(folder / f"{name}__{s}.npz") as z:
                    pv, out = z["pv"], z["out"]
                sc = score(np.zeros_like(pv), pv, out, "F", v)
                n += sc is not None and sc >= 0.5
            row.append(f"{n:2d}")
        print(f"  {name:45s}", "  ".join(row))


def synth(folder: Path) -> None:
    """AUC (abstain = 0) and healthy-class flags on synth14 dev 100-399 and shifted dev 1-100."""
    data = {v: [] for v in VARIANTS}
    for f in sorted(folder.glob("*.npz")):
        gen, kind, case, _lv, seed = f.stem.split("_")
        if (gen == "shift" and int(seed) > 100) or (gen == "s14" and int(seed) > 399):
            continue
        with np.load(f) as z:
            sp, pv, op, label = z["sp"], z["pv"], z["op"], float(z["label"])
        for v in VARIANTS:
            s = score(sp, pv, op, kind, v)
            data[v].append(
                (gen, kind, case, label, 0.0 if s is None else s, s is not None and s >= 0.5)
            )
    for v, rows in data.items():
        out = [f"{v:12s}"]
        for gen in ("s14", "shift"):
            g = [r for r in rows if r[0] == gen]
            a = auc([r[4] for r in g if r[3] == 1], [r[4] for r in g if r[3] == 0])
            fl = {c: np.mean([r[5] for r in g if r[2] == c]) for c in ("sine", "square", "tuning")}
            out.append(
                f"{gen}: AUC {a:.3f} flags " + " ".join(f"{k} {x:.0%}" for k, x in fl.items())
            )
        print("  ".join(out))


if __name__ == "__main__":
    exp01(Path(sys.argv[1]))
    synth(Path(sys.argv[2]))

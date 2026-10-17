"""Dev gate of amendment 1: C6 versus C4a on exp01 dev, shifted dev (read-only) and
noise-only (T7').

Usage: python dev_gate.py <exp01 cache> <synth cache>
"""

from __future__ import annotations

import sys
from pathlib import Path

import cand15
import numpy as np
from calib_prominence import noise
from combiner import load_models, score_c6
from eval_synth import auc

MODELS, THR = load_models()


def c6(sp: np.ndarray, pv: np.ndarray, out: np.ndarray, kind: str) -> tuple[float, bool, bool]:
    """(score with abstain = 0, ranked, flagged) of C6."""
    p = score_c6(sp, pv, out, kind, MODELS)
    return (0.0, False, False) if p is None else (p, True, p >= THR)


def c4a(sp: np.ndarray, pv: np.ndarray, out: np.ndarray, kind: str) -> tuple[float, bool, bool]:
    """(score with abstain = 0, ranked, flagged) of C4a."""
    r = cand15.suspicion15(sp, pv, out, 1.0, kind, "c4a")
    return (0.0, False, False) if r.score is None else (r.score, True, r.advice == "test_valve")


def exp01(folder: Path) -> None:
    """Flag counts per exp01 class for both candidates (dev seeds 1-20)."""
    for name in sorted({p.name.split("__")[0] for p in folder.glob("*.npz")}):
        row = []
        for tag, fn in (("c4a", c4a), ("c6", c6)):
            flags = 0
            for s in range(1, 21):
                with np.load(folder / f"{name}__{s}.npz") as z:
                    pv, out = z["pv"], z["out"]
                flags += fn(np.zeros_like(pv), pv, out, "F")[2]
            row.append(f"{tag} {flags:2d}/20")
        print(f"{name:52s}", "  ".join(row))


def shifted(folder: Path) -> None:
    """AUC and flags on shifted dev seeds 1-100 (read-only check)."""
    rows = {"c4a": [], "c6": []}
    for f in sorted(folder.glob("shift_*.npz")):
        _, kind, case, noise_lv, seed = f.stem.split("_")
        if int(seed) > 100:
            continue
        with np.load(f) as z:
            sp, pv, op, label = z["sp"], z["pv"], z["op"], float(z["label"])
        for tag, fn in (("c4a", c4a), ("c6", c6)):
            rows[tag].append((kind, case, noise_lv, label, *fn(sp, pv, op, kind)))
    for tag, rs in rows.items():
        pos = [r[4] for r in rs if r[3] == 1]
        neg = [r[4] for r in rs if r[3] == 0]
        rp = [r[4] for r in rs if r[3] == 1 and r[5]]
        rn = [r[4] for r in rs if r[3] == 0 and r[5]]
        fl = {
            c: np.mean([r[6] for r in rs if r[1] == c])
            for c in ("sine", "square", "tuning", "stick")
        }
        print(
            f"shifted {tag}: AUC {auc(pos, neg):.3f} (ranked only {auc(rp, rn):.3f}); flags",
            {k: f"{v:.0%}" for k, v in fl.items()},
        )
        for kind in "FL":
            p = [r[4] for r in rs if r[0] == kind and r[3] == 1]
            n = [r[4] for r in rs if r[0] == kind and r[3] == 0]
            print(f"   kind {kind} AUC {auc(p, n):.3f}")


def noise_only() -> None:
    """T7': share of noise-only records flagged by each candidate."""
    rng = np.random.default_rng(909)
    for tag, fn in (("c4a", c4a), ("c6", c6)):
        flagged = total = 0
        for kind in ("white", "ar-0.5", "ar-0.9", "ar-0.98", "walk"):
            for n in (3000, 6000, 14400):
                for _ in range(20):
                    pv, op = noise(rng, kind, n), noise(rng, kind, n)
                    flagged += fn(np.zeros(n), pv, op, "F")[2]
                    total += 1
        print(f"T7' {tag}: noise-only flagged {flagged}/{total} = {flagged / total:.1%}")


if __name__ == "__main__":
    exp01(Path(sys.argv[1]))
    shifted(Path(sys.argv[2]))
    noise_only()

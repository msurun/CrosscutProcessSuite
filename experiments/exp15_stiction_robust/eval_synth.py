"""Dev evaluation on cached synthetic records: AUC (abstain = 0) and false-alarm rates per variant.

Usage: python eval_synth.py <cache dir> <variant> [variant ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

import cand15
import numpy as np

SHORT_HALF = 18.0  # samples per half-cycle below which the He index is unavailable in the package


def auc(pos: list[float], neg: list[float]) -> float:
    """P(sticking scores above non-sticking), ties half; nan if a class is empty."""
    if not pos or not neg:
        return float("nan")
    return float(np.mean([(a > b) + 0.5 * (a == b) for a in pos for b in neg]))


def run_all(folder: Path, variant: str) -> list[dict]:
    """Score every cached record; one dict per record."""
    rows = []
    for f in sorted(folder.glob("*.npz")):
        gen, kind, case, noise, _seed = f.stem.split("_")
        with np.load(f) as z:
            sp, pv, op, label, half = z["sp"], z["pv"], z["op"], float(z["label"]), float(z["half"])
        r = cand15.suspicion15(sp, pv, op, 1.0, kind, variant)
        rows.append(
            dict(
                gen=gen,
                kind=kind,
                case=case,
                noise=noise,
                label=label,
                half=half,
                score=0.0 if r.score is None else r.score,
                ranked=r.score is not None,
                flagged=r.advice == "test_valve",
            )
        )
    return rows


def summarise(rows: list[dict], variant: str) -> None:
    """Print AUCs (abstain = 0 and ranked only) and false-alarm rates."""

    def pick(**kw):
        return [r for r in rows if all(r[k] == v for k, v in kw.items())]

    def a0(sub):
        return auc(
            [r["score"] for r in sub if r["label"] == 1],
            [r["score"] for r in sub if r["label"] == 0],
        )

    def ar(sub):
        s = [r for r in sub if r["ranked"]]
        return auc(
            [r["score"] for r in s if r["label"] == 1], [r["score"] for r in s if r["label"] == 0]
        )

    print(f"== {variant}")
    for gen in ("s14", "shift"):
        g = pick(gen=gen)
        parts = [f"all {a0(g):.2f} (ranked {ar(g):.2f})"]
        parts += [f"{k} {a0(pick(gen=gen, kind=k)):.2f}" for k in "FL"]
        short = [r for r in g if r["half"] < SHORT_HALF]
        parts.append(f"short<{SHORT_HALF:.0f} {a0(short):.2f} (n={len(short)})")
        if gen == "shift":
            parts += [f"noise {n} {a0(pick(gen=gen, noise=n)):.2f}" for n in ("low", "mid", "high")]
        print(f"  AUC {gen:5s}", "; ".join(parts))
    for case in ("sine", "square", "tuning"):
        neg = pick(case=case)
        print(f"  false alarm {case:7s} {np.mean([r['flagged'] for r in neg]):.1%} (n={len(neg)})")
    pos = pick(case="stick")
    print(
        f"  stick flagged {np.mean([r['flagged'] for r in pos]):.1%}, "
        f"ranked {np.mean([r['ranked'] for r in pos]):.1%}"
    )


if __name__ == "__main__":
    for v in sys.argv[2:]:
        summarise(run_all(Path(sys.argv[1]), v), v)

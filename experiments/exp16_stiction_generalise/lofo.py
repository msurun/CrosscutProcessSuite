"""Leave-one-family-out evaluation on the dev feature table (G1 synth14, G2 shifted, G3 exp16).

Usage: python lofo.py <table.npz>. A scorer is trained on two families and scored on the third;
the selection metric is the WORST family AUC (abstain = 0). Baselines: shipped module and C4a.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exp15_stiction_robust"))
from combiner import Combiner  # noqa: E402
from eval_synth import auc  # noqa: E402

FAMILIES = ("G1", "G2", "G3")


def load(path: Path) -> dict[str, np.ndarray]:
    """The table as a dict of arrays."""
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def fit_predict(t: dict, train: np.ndarray, test: np.ndarray, keep: list[int]) -> np.ndarray:
    """Per-kind combiner trained on ``train`` rows; probability per ``test`` row (0 if unranked)."""
    prob = np.zeros(len(t["label"]))
    ranked = ~np.isnan(t["x"]).any(axis=1)
    for kind in "FL":
        k = t["kind"] == kind
        tr, te = train & k & ranked, test & k & ranked
        model = Combiner(keep).fit(t["x"][tr], t["label"][tr])
        prob[te] = model.predict(t["x"][te])
    return prob


def family_auc(t: dict, rows: np.ndarray, score: np.ndarray) -> float:
    """AUC with abstain = 0 over ``rows`` (NaN scores count as 0)."""
    s = np.nan_to_num(score[rows], nan=0.0)
    y = t["label"][rows]
    return auc(list(s[y == 1]), list(s[y == 0]))


def lofo(t: dict, keep: list[int]) -> dict[str, float]:
    """Held-out AUC per family for a combiner using feature columns ``keep``."""
    out = {}
    for fam in FAMILIES:
        test = t["family"] == fam
        prob = fit_predict(t, ~test, test, keep)
        out[fam] = family_auc(t, test, prob)
    return out


def baseline(t: dict, name: str) -> dict[str, float]:
    """Per-family AUC of a fixed scorer stored in the table (``shipped`` or ``c4a``)."""
    return {fam: family_auc(t, t["family"] == fam, t[name]) for fam in FAMILIES}


def line(label: str, res: dict[str, float]) -> str:
    """One report line with the worst family."""
    cells = "  ".join(f"{f} {res[f]:.3f}" for f in FAMILIES)
    return f"{label:28s} {cells}  worst {min(res.values()):.3f}"


def main(path: Path) -> None:
    """Print baselines and LOFO combiners (all features and ablations)."""
    t = load(path)
    print(line("shipped", baseline(t, "shipped")))
    print(line("C4a", baseline(t, "c4a")))
    ranked = ~np.isnan(t["x"]).any(axis=1)
    print(
        "ranked share by family:",
        {f: round(float(ranked[t["family"] == f].mean()), 2) for f in FAMILIES},
    )
    n = t["x"].shape[1]
    print(line("C6 combiner, all features", lofo(t, list(range(n)))))
    for drop in range(n):
        keep = [i for i in range(n) if i != drop]
        print(line(f"  without feature {drop}", lofo(t, keep)))


if __name__ == "__main__":
    main(Path(sys.argv[1]))

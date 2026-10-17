"""Train C6 on synth14 dev records (seeds 100-399), grouped CV, threshold by the frozen rule.

Usage: python train_c6.py <synth cache dir>. Writes c6_model.json (models + threshold).
The shifted generator and the final seeds are never read here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from combiner import MODEL_PATH, NAMES, THRESHOLDS, Combiner, features_c6
from eval_synth import auc

FOLDS = 5
MAX_HEALTHY_FLAG = 0.10


def load(folder: Path) -> list[dict]:
    """Features of every synth14 dev record (None features kept as unranked)."""
    rows = []
    for f in sorted(folder.glob("s14_*.npz")):
        _, kind, case, _noise, seed = f.stem.split("_")
        with np.load(f) as z:
            feat = features_c6(z["sp"], z["pv"], z["op"], kind)
        rows.append(dict(kind=kind, case=case, seed=int(seed), x=feat, y=float(case == "stick")))
    return rows


def cv_probabilities(rows: list[dict], keep: list[int] | None = None) -> np.ndarray:
    """Out-of-fold probability per row (0 where the record is not ranked), folds grouped by seed."""
    prob = np.zeros(len(rows))
    for kind in "FL":
        for fold in range(FOLDS):
            tr = [
                i
                for i, r in enumerate(rows)
                if r["kind"] == kind and r["x"] is not None and r["seed"] % FOLDS != fold
            ]
            te = [
                i
                for i, r in enumerate(rows)
                if r["kind"] == kind and r["x"] is not None and r["seed"] % FOLDS == fold
            ]
            m = Combiner(keep).fit(
                np.array([rows[i]["x"] for i in tr]), np.array([rows[i]["y"] for i in tr])
            )
            prob[te] = m.predict(np.array([rows[i]["x"] for i in te]))
    return prob


def cv_auc(rows: list[dict], prob: np.ndarray) -> float:
    """AUC with abstain = 0 over all rows."""
    pos = [p for p, r in zip(prob, rows, strict=True) if r["y"] == 1]
    neg = [p for p, r in zip(prob, rows, strict=True) if r["y"] == 0]
    return auc(pos, neg)


def choose_threshold(rows: list[dict], prob: np.ndarray) -> float:
    """Smallest grid p with <= 10 % flags on the sine and the tuning class (pooled over kinds)."""
    for thr in THRESHOLDS:
        rates = [
            np.mean([p >= thr for p, r in zip(prob, rows, strict=True) if r["case"] == c])
            for c in ("sine", "tuning")
        ]
        if max(rates) <= MAX_HEALTHY_FLAG:
            return thr
    return THRESHOLDS[-1]


def main(folder: Path) -> None:
    """Run the CV, print the report, fit the final per-kind models and save them."""
    rows = load(folder)
    prob = cv_probabilities(rows)
    thr = choose_threshold(rows, prob)
    print(f"records {len(rows)}, ranked {sum(r['x'] is not None for r in rows)}")
    print(f"CV AUC (abstain = 0) {cv_auc(rows, prob):.3f}; threshold {thr}")
    for c in ("sine", "square", "tuning", "stick"):
        sub = [p >= thr for p, r in zip(prob, rows, strict=True) if r["case"] == c]
        print(f"  flagged {c:7s} {np.mean(sub):.1%} (n={len(sub)})")
    for kind in "FL":
        sub = [(p, r) for p, r in zip(prob, rows, strict=True) if r["kind"] == kind]
        print(
            f"  CV AUC kind {kind}: "
            f"{cv_auc([r for _, r in sub], np.array([p for p, _ in sub])):.3f}"
        )
    for label, keep in (("without h3", [0, 3, 4, 5]), ("without Horch", [0, 1, 2, 4, 5])):
        print(f"  ablation {label}: CV AUC {cv_auc(rows, cv_probabilities(rows, keep)):.3f}")
    models = {}
    for kind in "FL":
        ok = [r for r in rows if r["kind"] == kind and r["x"] is not None]
        models[kind] = Combiner().fit(
            np.array([r["x"] for r in ok]), np.array([r["y"] for r in ok])
        )
        print(
            f"  weights {kind}:",
            dict(zip(("bias", *NAMES), np.round(models[kind].w, 2), strict=True)),
        )
    MODEL_PATH.write_text(
        json.dumps({"threshold": thr, "models": {k: m.to_dict() for k, m in models.items()}})
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))

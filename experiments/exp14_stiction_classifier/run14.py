"""Run exp14: train on synthetic loops, check C1-C4 on synthetic held-out, then C3 on SACAC.

Usage: ../../.venv/Scripts/python run14.py <unzipped SACAC folder>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import synth14
from model14 import FEATURES, Logistic, features

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exp13_stiction_suspicion"))
import run13  # noqa: E402
import suspicion as su  # noqa: E402
from scoreboard import load_loops  # noqa: E402

CASES = ("stick", "sine", "square", "tuning")
N_PER = 60  # records per kind and case
SPLITS = {"train": 100, "test": 300}
ABLATE = {"no_horch": [0, 1, 4, 5, 6], "no_he": [2, 3, 4, 5, 6]}


def make_set(seed0: int) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Feature rows, labels and kinds for one synthetic split."""
    rng = np.random.default_rng(seed0)
    rows, labels, kinds = [], [], []
    for kind in "FL":
        for case in CASES:
            for _ in range(N_PER):
                sp, pv, op, label, k = synth14.simulate14(rng, kind, case)
                f = features(sp, pv, op, float(k), kind)
                if f is not None:
                    rows.append(f)
                    labels.append(label)
                    kinds.append(kind)
    return np.array(rows), np.array(labels), kinds


def hand_scores(x: np.ndarray, cal: tuple[float, float]) -> np.ndarray:
    """exp13 hand score recomputed from the features (mean of available calibrated tests)."""
    out = []
    for r in x:
        parts = [] if r[1] else [r[0]]
        if not r[3]:
            parts.append(su.calibrated(r[2], cal))
        out.append(np.mean(parts) if parts else 0.5)
    return np.array(out)


def synth_check() -> Logistic:
    """Train, print C1, C2, C4 on the synthetic held-out set, return the model."""
    xtr, ytr, _ = make_set(SPLITS["train"])
    xte, yte, _ = make_set(SPLITS["test"])
    cal = run13.calibrate()
    model = Logistic().fit(xtr, ytr)
    pos, neg = yte == 1, yte == 0
    a = run13.auc(list(model.predict(xte)[pos]), list(model.predict(xte)[neg]))
    h = hand_scores(xte, cal)
    ah = run13.auc(list(h[pos]), list(h[neg]))
    print(f"train n={len(ytr)} test n={len(yte)} (stick {pos.sum()}, other {neg.sum()})")
    print(f"C1 synthetic held-out AUC {a:.2f} -> {'met' if a >= 0.85 else 'MISSED'}")
    print(f"C2 hand score AUC {ah:.2f}; classifier {'beats' if a > ah else 'does NOT beat'} it")
    for name, keep in ABLATE.items():
        m = Logistic(keep).fit(xtr, ytr)
        p = m.predict(xte)
        print(f"C4 {name}: AUC {run13.auc(list(p[pos]), list(p[neg])):.2f}")
    print("weights:", dict(zip(("bias", *FEATURES), np.round(model.w, 2), strict=True)))
    return model


def sacac(model: Logistic, root: Path) -> None:
    """C3: the same R1/R2 report as exp13 with the classifier probability as score."""
    counted = [lp for lp in load_loops() if lp.confidence != "low"]
    n_stick = sum(lp.label == "stick" for lp in counted)
    ranked = []
    for lp in counted:
        probs = []
        for s in lp.stems:
            f = features(*run13.read_spo(root, s), lp.dt_s, lp.kind)
            if f is not None:
                probs.append(float(model.predict(f[None, :])[0]))
        if probs:
            p = float(np.median(probs))
            ranked.append((lp, {"score": p, "he": np.nan, "horch": np.nan}))
            print(f"{lp.name:26s} {lp.label:5s} {lp.split:5s} p {p:.2f}")
    print(f"ranked {len(ranked)}/{len(counted)}")
    run13.report(ranked, n_stick)


if __name__ == "__main__":
    sacac(synth_check(), Path(sys.argv[1]))

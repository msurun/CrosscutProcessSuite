"""Candidate C7a: the C6 combiner retrained on all three dev families (G1, G2, G3).

Usage: python train_c7.py <table.npz>. Threshold rule (fixed before looking): the smallest grid
value with <= 10 % flagged on EACH of the sine-forcing, tuning, quiet, staircase and multitone
healthy classes, using out-of-family predictions. Square forcing is excluded from the rule
(physically confusable). Writes c7_model.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp15_stiction_robust"))
from combiner import THRESHOLDS, Combiner  # noqa: E402
from lofo import FAMILIES, fit_predict, load  # noqa: E402

RULE_CLASSES = ("sine", "load_sine", "tuning", "tuning_aggressive", "tuning_sluggish")
RULE_CLASSES += ("quiet", "sp_steps", "load_multitone")
MAX_HEALTHY_FLAG = 0.10


def oof_probabilities(t: dict, keep: list[int]) -> np.ndarray:
    """Probability of every record from a model that never saw its family."""
    prob = np.zeros(len(t["label"]))
    for fam in FAMILIES:
        test = t["family"] == fam
        prob[test] = fit_predict(t, ~test, test, keep)[test]
    return prob


def class_flag_rates(t: dict, prob: np.ndarray, thr: float) -> dict[str, float]:
    """Flag rate per healthy class name (pooled over families and kinds)."""
    rates = {}
    for case in sorted(set(t["case"][t["label"] == 0])):
        sel = (t["case"] == case) & (t["label"] == 0)
        rates[case] = float(np.mean(prob[sel] >= thr))
    return rates


def choose_threshold(t: dict, prob: np.ndarray) -> float:
    """Smallest grid threshold meeting the rule on every rule class present in the table."""
    for thr in THRESHOLDS:
        rates = class_flag_rates(t, prob, thr)
        if max(rates[c] for c in RULE_CLASSES if c in rates) <= MAX_HEALTHY_FLAG:
            return thr
    return THRESHOLDS[-1]


def main(path: Path) -> None:
    """Choose the threshold out-of-family, fit final per-kind models on all rows, save them."""
    t = load(path)
    keep = list(range(t["x"].shape[1]))
    prob = oof_probabilities(t, keep)
    thr = choose_threshold(t, prob)
    print(f"threshold {thr}")
    for case, rate in class_flag_rates(t, prob, thr).items():
        print(f"  flagged {case:18s} {rate:.0%}")
    sticking = t["label"] == 1
    print(f"  flagged stick {np.mean(prob[sticking] >= thr):.0%}")
    ranked = ~np.isnan(t["x"]).any(axis=1)
    models = {}
    for kind in "FL":
        sel = ranked & (t["kind"] == kind)
        models[kind] = Combiner(keep).fit(t["x"][sel], t["label"][sel])
    out = {"threshold": thr, "models": {k: m.to_dict() for k, m in models.items()}}
    (HERE / "c7_model.json").write_text(json.dumps(out))


if __name__ == "__main__":
    main(Path(sys.argv[1]))

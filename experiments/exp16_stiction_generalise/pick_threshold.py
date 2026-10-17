"""Freeze the C7a flag threshold: smallest grid value with every exp01 healthy dev cell <= 2/20
flagged and noise-only (T7, dev seed 777) <= 5 % flagged. Uses c7_model.json (kind F model).

Usage: python pick_threshold.py <exp01 cache dir>. Prints the table and the chosen value.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp15_stiction_robust"))
from calib_prominence import noise  # noqa: E402
from combiner import THRESHOLDS, Combiner, features_c6  # noqa: E402

HEALTHY = ("aggressive", "nominal", "sine", "square")


def probs(folder: Path, model: Combiner) -> dict[str, list[float]]:
    """C7a probability per exp01 dev record by class (0 when not ranked)."""
    out: dict[str, list[float]] = {}
    for p in sorted(folder.glob("*__*.npz")):
        name, seed = p.stem.rsplit("__", 1)
        if int(seed) > 20:
            continue
        with np.load(p) as z:
            pv, op = z["pv"], z["out"]
        f = features_c6(np.zeros_like(pv), pv, op, "F")
        out.setdefault(name, []).append(0.0 if f is None else float(model.predict(f[None, :])[0]))
    return out


def noise_probs(model: Combiner) -> list[float]:
    """Probabilities of 100 noise-only records."""
    rng = np.random.default_rng(777)
    kinds = ("white", "ar-0.5", "ar-0.9", "ar-0.98", "walk")
    res = []
    for i in range(100):
        n = (3000, 6000, 14400)[i % 3]
        pv, op = noise(rng, kinds[i % 5], n), noise(rng, kinds[i % 5], n)
        f = features_c6(np.zeros(n), pv, op, "F")
        res.append(0.0 if f is None else float(model.predict(f[None, :])[0]))
    return res


def main(folder: Path) -> None:
    """Print the flag counts per threshold and the first threshold meeting the rule."""
    model = Combiner.from_dict(json.loads((HERE / "c7_model.json").read_text())["models"]["F"])
    cls, t7 = probs(folder, model), np.array(noise_probs(model))
    chosen = None
    for thr in THRESHOLDS:
        worst = max(sum(p >= thr for p in v) for k, v in cls.items() if k.startswith(HEALTHY))
        stick = {
            k: sum(p >= thr for p in v) for k, v in cls.items() if k.startswith("sticking band 8")
        }
        ok = worst <= 2 and np.mean(t7 >= thr) <= 0.05
        chosen = thr if ok and chosen is None else chosen
        print(f"thr {thr}: worst healthy cell {worst}/20, T7 {np.mean(t7 >= thr):.0%}, {stick}")
    print("chosen threshold:", chosen)


if __name__ == "__main__":
    main(Path(sys.argv[1]))

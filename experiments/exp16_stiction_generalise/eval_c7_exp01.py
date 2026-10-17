"""Dev check of a retrained C7 model on cached exp01 records (seeds 1-20, constant setpoint).

Usage: python eval_c7_exp01.py <exp01 cache dir> <model.json>. Prints flagged counts of 20 per
class for the shipped module and the model at its stored threshold.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exp15_stiction_robust"))
import cand15  # noqa: E402
from combiner import Combiner, features_c6  # noqa: E402

SEEDS = range(1, 21)


def main(folder: Path, model_path: Path) -> None:
    """One line per class: flagged by shipped and by the model."""
    d = json.loads(model_path.read_text())
    model, thr = Combiner.from_dict(d["models"]["F"]), float(d["threshold"])
    for name in sorted({p.name.split("__")[0] for p in folder.glob("*.npz")}):
        ship = new = 0
        for s in SEEDS:
            with np.load(folder / f"{name}__{s}.npz") as z:
                pv, out, dt_s = z["pv"], z["out"], float(z["dt_s"])
            sp = np.zeros_like(pv)
            ship += cand15.suspicion15(sp, pv, out, dt_s, "F", "base").advice == "test_valve"
            f = features_c6(sp, pv, out, "F")
            new += f is not None and model.predict(f[None, :])[0] >= thr
        print(f"{name:52s} shipped {ship:2d}/20  model {new:2d}/20")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

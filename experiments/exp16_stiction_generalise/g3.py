"""G3 generator: independent closed-loop records for stiction-suspicion validation (exp16).

Composes the clean simulation (g3_sim, g3_valve, g3_excite) with the measurement chain (g3_chain).
Written from G3_SPEC.md by a model that saw only the spec. `python g3.py` runs a self-test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from g3_chain import apply_chain
from g3_sim import count_cycles, simulate_clean

CASES = (
    "stick",
    "load_sine",
    "load_square",
    "load_multitone",
    "sp_square",
    "sp_steps",
    "tuning_aggressive",
    "tuning_sluggish",
    "quiet",
)
NOISES = ("low", "mid", "high")


@dataclass
class G3Record:
    """One record: percent-unit signals, label (1 = stiction) and drawn parameters."""

    sp: np.ndarray
    pv: np.ndarray
    op: np.ndarray
    label: int
    dt_s: float
    meta: dict = field(default_factory=dict)


def simulate_g3(rng: np.random.Generator, kind: str, case: str, noise: str) -> G3Record:
    """Simulate one loop and pass PV and OP through the measurement chain."""
    if kind not in ("F", "L") or case not in CASES or noise not in NOISES:
        raise ValueError(f"bad kind/case/noise: {kind}/{case}/{noise}")
    clean = simulate_clean(rng, kind, case)
    pv, op = apply_chain(rng, clean.pv, clean.op, noise, clean.swing)
    meta = dict(clean.meta, kind=kind, case=case, noise=noise)
    return G3Record(clean.sp, pv, op, int(case == "stick"), clean.dt_s, meta)


def _self_test() -> None:
    """Three records per kind/case/noise: finite, equal lengths, correct label, cycles."""
    rng = np.random.default_rng(0)
    print("kind case noise n dt cycles")
    for kind in "FL":
        for case in CASES:
            for noise in NOISES:
                r = simulate_g3(rng, kind, case, noise)
                ok = np.isfinite(r.pv).all() and np.isfinite(r.op).all()
                assert ok and len(r.sp) == len(r.pv) == len(r.op)
                assert r.label == int(case == "stick")
                print(kind, case, noise, len(r.pv), r.dt_s, count_cycles(r.pv))


if __name__ == "__main__":
    _self_test()

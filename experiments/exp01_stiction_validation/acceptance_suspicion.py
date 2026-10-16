"""Acceptance of crosscut_loops.stiction_suspicion on the exp01 grid (same seeds and report layout).

Reuses acceptance.py: only the classification function and the report path are replaced, and the
advice words are mapped to the verdict words so the existing tables apply unchanged.
"""

from __future__ import annotations

from pathlib import Path

import acceptance
import cases
import numpy as np
from crosscut_loops.stiction_suspicion import stiction_suspicion

ADVICE_AS_VERDICT = {
    "test_valve": "stiction",
    "unlikely": "no_stiction",
    "not_ranked": "inconclusive",
}
RESULTS_PATH = Path(__file__).resolve().parent / "results" / "acceptance_suspicion.md"


def classify_suspicion(case: cases.Case, seed: int) -> str:
    """Run one case and return the suspicion advice in verdict words (module level: picklable)."""
    pv, out, dt_s = cases.simulate_case(case, seed)
    pv_settled, out_settled = acceptance.settle(pv, out, dt_s)
    sp = np.zeros_like(pv_settled)  # no setpoint column in the record: constant
    advice = stiction_suspicion(sp, pv_settled, out_settled, dt_s, "F").advice
    return ADVICE_AS_VERDICT[advice]


if __name__ == "__main__":
    acceptance.classify = classify_suspicion
    acceptance.RESULTS_PATH = RESULTS_PATH
    acceptance.main()

"""Diagnosis of the exp07 gain miss: noise-free, 24 h records, weaker disturbance.

Reuses exp07's simulator and estimators, changes one module constant per condition
and prints signed gain/tau errors of the IV fit (mean shows bias, median-abs spread).
Frozen exp07 targets are not touched; this only explains the miss.
"""

from __future__ import annotations

import sys

import exp07
import numpy as np

CONDITIONS = {
    "baseline": {},
    "no_noise_no_disturbance": {"PV_NOISE_SD": 0.0, "DISTURBANCE_SD": 0.0},
    "noise_only_no_disturbance": {"DISTURBANCE_SD": 0.0},
    "disturbance_quarter": {"DISTURBANCE_SD": 0.125},
    "records_24h": {"SAMPLES_PER_RUN": 86400},
}
FIRST_SEED = 21
N_SEEDS = 20


def run_condition(overrides: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    """Signed IV gain and tau errors over the seeds, with ``overrides`` applied."""
    saved = {name: getattr(exp07, name) for name in overrides}
    for name, value in overrides.items():
        setattr(exp07, name, value)
    try:
        results = [exp07.fit_one_seed(s) for s in range(FIRST_SEED, FIRST_SEED + N_SEEDS)]
    finally:
        for name, value in saved.items():
            setattr(exp07, name, value)
    iv = [r.iv for r in results if r.iv is not None]
    return (
        np.array([m.relative_gain_error for m in iv]),
        np.array([m.relative_tau_error for m in iv]),
    )


def main() -> None:
    """Print one line per condition."""
    names = sys.argv[1:] or list(CONDITIONS)
    for name in names:
        gain, tau = run_condition(CONDITIONS[name])
        print(
            f"{name}: n={len(gain)} gain mean {gain.mean():+.3f} median|e| "
            f"{np.median(np.abs(gain)):.3f} | tau mean {tau.mean():+.3f} "
            f"median|e| {np.median(np.abs(tau)):.3f}",
            flush=True,
        )


if __name__ == "__main__":
    main()

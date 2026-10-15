"""Round 3 of exp12: harmonics kept and period floor of candidate A, from synthetic data only."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exp11_stiction_floor"))
import candidate_a as ca  # noqa: E402
from gate1 import MAX_FALSE_ALARM, MIN_DETECTION, rates  # noqa: E402

HARMONIC_CHOICES = (3, 5, 7)
LENGTHS = (10, 12, 15, 20, 25, 30, 40, 60)
NOISES = (0.05, 0.15)
SLACK = 0.9


def passes(length: int) -> bool:
    """True if both required noises meet the detection and false-alarm thresholds at ``length``."""
    for noise in NOISES:
        det, _ = rates(length, noise, True)
        fa, _ = rates(length, noise, False)
        print(
            f"  L={length:2d} s={noise:.2f} detection {det:4.0%} false alarm {fa:4.0%}", flush=True
        )
        if det < MIN_DETECTION or fa > MAX_FALSE_ALARM:
            return False
    return True


def smallest_passing(choice: int) -> int | None:
    """L_pass: smallest grid L from which all larger grid values pass, for ``choice`` harmonics."""
    ca.HARMONICS_KEPT = choice
    ca.MIN_HALF_CYCLE_SAMPLES = 1
    ok = {length: passes(length) for length in LENGTHS}
    good = [n for n in LENGTHS if all(ok[m] for m in LENGTHS if m >= n)]
    return good[0] if good else None


def main() -> None:
    """Print L_pass per H and the rule's choice."""
    found = {}
    for choice in HARMONIC_CHOICES:
        print(f"H = {choice}", flush=True)
        found[choice] = smallest_passing(choice)
        print(f"H = {choice}: L_pass = {found[choice]}", flush=True)
    valid = {h: n for h, n in found.items() if n is not None}
    if not valid:
        print("No setting passes: round 3 FAILED")
        return
    best = min(valid.values())
    h = max(h for h, n in valid.items() if n == best)
    print(f"Chosen H = {h}, L_pass = {best}, floor = {SLACK * best:.1f} samples per half-cycle")


if __name__ == "__main__":
    main()

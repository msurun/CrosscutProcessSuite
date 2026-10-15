"""Gate 1 of exp12 round 1: candidate A on the exp11 synthetic design (frozen in README.md)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exp11_stiction_floor"))
from candidate_a import curve_fit_index_a  # noqa: E402
from sweep import THRESHOLD, TRIALS, make_signal  # noqa: E402

REQUIRED_LENGTHS = (20, 30, 60)  # round 2 (Gate 1b); round 1 also required 10, 12, 15
EXTRA_LENGTHS = (10, 12, 15)
NOISES = (0.05, 0.15, 0.30)
REQUIRED_NOISES = (0.05, 0.15)
MIN_DETECTION = 0.80
MAX_FALSE_ALARM = 0.05


def rates(length: int, noise: float, triangle: bool) -> tuple[float, float]:
    """(share with index >= THRESHOLD, share without index) over TRIALS seeds."""
    hit = none = 0
    for seed in range(1, TRIALS + 1):
        index = curve_fit_index_a(make_signal(seed, length, noise, triangle), 1.0).index
        none += index is None
        hit += index is not None and index >= THRESHOLD
    return hit / TRIALS, none / TRIALS


def main() -> None:
    """Print the grid and whether the required cells pass."""
    failed = []
    for length in EXTRA_LENGTHS + REQUIRED_LENGTHS:
        for noise in NOISES:
            det, ref_t = rates(length, noise, True)
            fa, ref_s = rates(length, noise, False)
            print(
                f"L={length:2d} s={noise:.2f} detection {det:4.0%} (refused {ref_t:4.0%}) "
                f"false alarm {fa:4.0%} (refused {ref_s:4.0%})",
                flush=True,
            )
            required = length in REQUIRED_LENGTHS and noise in REQUIRED_NOISES
            if required and not (det >= MIN_DETECTION and fa <= MAX_FALSE_ALARM):
                failed.append((length, noise))
    print("Gate 1:", "PASSED" if not failed else f"FAILED at {failed}")


if __name__ == "__main__":
    main()

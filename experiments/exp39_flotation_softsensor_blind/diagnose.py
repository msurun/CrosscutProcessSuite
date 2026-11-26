"""Audit committed development lag scores without opening the flotation CSV.

This fallback quantifies the recorded lag comparison; it cannot identify physical causes.
"""

from __future__ import annotations

import re
from pathlib import Path

LAG_COUNT = 4  # Candidate sets contain zero through three hours of history.


def read_development_scores(report: str) -> tuple[float, ...]:
    """Extract the four recorded development RMSEs or reject an unexpected report."""
    match = re.search(r"validation RMSE.*?development ([\d., ]+) for", report)
    if match is None:
        raise ValueError("Expected development validation RMSE paragraph in results.md")
    scores = tuple(float(value.strip()) for value in match[1].split(","))
    if len(scores) != LAG_COUNT or any(value <= 0 for value in scores):
        raise ValueError("Expected four positive development RMSE values in results.md")
    return scores


def relative_penalties(scores: tuple[float, ...]) -> tuple[float, ...]:
    """Return fractional RMSE increases relative to the zero-lag candidate."""
    if len(scores) != LAG_COUNT or any(value <= 0 for value in scores):
        raise ValueError("Supply four positive development RMSE values")
    # Each scalar is RMSE in silica percentage points; ratios are dimensionless.
    # Penalty = RMSE(candidate) / RMSE(zero lag) - 1, not a significance test.
    return tuple(value / scores[0] - 1 for value in scores)


def main() -> None:
    """Print a development-only table from the committed aggregate results."""
    report = Path(__file__).with_name("results.md").read_text(encoding="utf-8")
    scores = read_development_scores(report)
    print("maximum lag (h), development RMSE (silica pp), increase (%)")
    for lag, (score, penalty) in enumerate(zip(scores, relative_penalties(scores), strict=True)):
        print(f"{lag}, {score:.3f}, {100 * penalty:.3f}")


if __name__ == "__main__":
    main()

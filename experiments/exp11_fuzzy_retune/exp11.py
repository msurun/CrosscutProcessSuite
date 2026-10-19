"""exp11: score the narrowed mill feed supervisor (v2) on fresh seeds 11-20.

Targets C1-C5 are frozen in README.md before the first run. Reuses the exp09 simulation and scoring;
only the rule base and the seeds differ. The original rule base is run too, as a reference.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from crosscut_fuzzy.model import FuzzySystem, system_from_dict

sys.path.insert(0, str(Path(__file__).parents[1] / "exp09_fuzzy_backtest"))
import exp09  # noqa: E402

SEEDS = range(11, 21)
RULE_BASE_V2 = Path(__file__).parents[2] / "fuzzy" / "examples" / "mill_feed_supervisor_v2.json"
RESULTS_PATH = Path(__file__).parent / "results" / "results.md"


def load_v2() -> FuzzySystem:
    """The narrowed rule base under test."""
    return system_from_dict(json.loads(RULE_BASE_V2.read_text(encoding="utf-8")))


def run(system: FuzzySystem) -> tuple[dict[str, float], dict[str, bool]]:
    """Summary medians and verdicts for one rule base over the fresh seeds."""
    rows = [exp09.score_seed(system, seed) for seed in SEEDS]
    summary = exp09.summarise(rows)
    return summary, exp09.verdicts(summary)


def table(title: str, summary: dict[str, float], met: dict[str, bool]) -> list[str]:
    """Markdown block for one rule base."""
    lines = [f"## {title}", "", "| metric | median |", "|---|---|"]
    lines += [f"| {name} | {value:.3f} |" for name, value in summary.items()]
    lines += ["", "| target | met |", "|---|---|"]
    lines += [f"| {name} | {'yes' if ok else 'NO'} |" for name, ok in met.items()]
    return lines + [""]


def main() -> None:
    """Run v2 and the original on seeds 11-20 and write the results table."""
    lines = ["# exp11 results (seeds 11-20; C1-C5 are exp09's B1-B5 rows)", ""]
    lines += table("v2 (narrowed terms)", *run(load_v2()))
    lines += table("original (reference)", *run(exp09.load_system()))
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

"""exp25 regression check after the review fixes (segmentation, NaN guard, resolution leg start).

Same cases, targets and harness as run25, on new seeds 100..119; a check that the fixes did not
break the analysis, not the frozen validation. Writes results25_recheck.md, never overwrites it.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run25  # noqa: E402

RESULTS = HERE / "results25_recheck.md"


def main() -> None:
    """Run the exp25 suites on seeds 100..119 and write the report."""
    if RESULTS.exists():
        raise SystemExit(f"refusing to overwrite {RESULTS}")
    run25.SEEDS = range(100, 120)
    report = run25.build_report(run25.run_main_suite(), run25.run_abort_suite())
    RESULTS.write_text(report.replace("Seeds 0..19", "Seeds 100..119 (recheck)"), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()

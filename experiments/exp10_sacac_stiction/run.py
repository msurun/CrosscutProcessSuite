"""Run the OUT-shape stiction index on the SACAC stiction loops, half-cycle floor 30 and 10.

Targets were frozen in README.md before this ran. Writes results/report.md (per-loop indices only,
no data). Usage: python -I run.py <folder with the unzipped SACAC repository>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from crosscut_loops import stiction_curvefit as cf

LOOPS = {  # loop -> (sampling period s, file stems)
    "horch-flow": (1.0, ["stiction-F-paper-horch-2003"]),
    "horch-level": (1.0, ["stiction-L-paper-horch-2003"]),
    "eastman-LC2": (20.0, ["stiction-L-chemicals-thornhill-2003"]),
    "pisa-power-level": (5.0, ["stiction-L-power-baccidicapaci-2018"]),
    "pisa-chem-pressure": (30.0, ["stiction-P-chemical-baccidicapaci-2018"]),
    "pisa-oilgas-pressure": (
        12.0,
        [f"stiction-P-oilgas-DB-{n}-baccidicapaci-2018" for n in range(1, 8)]
        + ["stiction-P-oilgas-baccidicapaci-2018"],
    ),
}
FLOORS = (30, 10)
STICTION_INDEX = 0.6
MIN_LOOPS_WITH_INDEX = 4
MIN_STICTION_SHARE = 0.5
REPORT = Path(__file__).resolve().parent / "results" / "report.md"


def read_op(root: Path, stem: str) -> np.ndarray:
    """OP column (4th, ';'-separated, CR or LF line ends) of one repository file."""
    hits = list(root.rglob(f"{stem}.csv"))
    lines = hits[0].read_text(encoding="latin-1").replace("\r", "\n").split("\n")[1:]
    return np.array([float(r.split(";")[3].replace(",", ".")) for r in lines if r.strip()])


def index_for(op: np.ndarray, dt_s: float, floor: int) -> cf.CurveFitResult:
    """Curve-fit index with the half-cycle floor temporarily set to ``floor`` samples."""
    saved = cf.MIN_SAMPLES_PER_HALF_CYCLE
    cf.MIN_SAMPLES_PER_HALF_CYCLE = floor
    try:
        return cf.curve_fit_index(op - op.mean(), dt_s)
    finally:
        cf.MIN_SAMPLES_PER_HALF_CYCLE = saved


def loop_line(
    name: str, root: Path, dt_s: float, stems: list[str], floor: int
) -> tuple[str, float | None]:
    """One report row and the loop's median index (None when no file gave one)."""
    results = [index_for(read_op(root, s), dt_s, floor) for s in stems]
    values = [r.index for r in results if r.index is not None]
    median = float(np.median(values)) if values else None
    reasons = sorted({r.reason for r in results if r.index is None})
    shown = "-" if median is None else f"{median:.2f}"
    return (
        f"| {name} | {floor} | {len(values)}/{len(stems)} | {shown} | {'; '.join(reasons)} |",
        median,
    )


def main(root: Path) -> None:
    """Write the report with both floors and the verdict on the frozen targets."""
    out = [
        "# exp10 report",
        "",
        "| loop | floor | files with index | median index | reasons otherwise |",
        "|---|---|---|---|---|",
    ]
    medians: dict[int, list[float | None]] = {f: [] for f in FLOORS}
    for floor in FLOORS:
        for name, (dt_s, stems) in LOOPS.items():
            row, median = loop_line(name, root, dt_s, stems, floor)
            out.append(row)
            medians[floor].append(median)
    got = [m for m in medians[10] if m is not None]
    share = sum(m >= STICTION_INDEX for m in got) / len(got) if got else 0.0
    out += [
        "",
        f"S2 target 1 (>= {MIN_LOOPS_WITH_INDEX} of 6 loops with an index): {len(got)} -> "
        f"{'met' if len(got) >= MIN_LOOPS_WITH_INDEX else 'MISSED'}",
        f"S2 target 2 (>= {MIN_STICTION_SHARE:.0%} of those >= {STICTION_INDEX}): {share:.0%} -> "
        f"{'met' if share >= MIN_STICTION_SHARE else 'MISSED'}",
    ]
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main(Path(sys.argv[1]))

"""Run the PV-only loop checks (oscillation, flatline) on the public flotation data.

Method and the limits of this data are in README.md; its thresholds were frozen before the run.
Writes results/report.md. Usage: python run.py <path to the flotation database CSV>
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from crosscut_connectors.flotation_public import LAB_COLUMNS, SAMPLE_PERIOD_S, load_flotation_csv
from crosscut_loops.metrics import flatline_fraction, hagglund_oscillation

MAX_GAP_S = 60.0  # a longer gap ends a segment
MIN_SEGMENT_SAMPLES = 1080  # 6 h at 20 s
AMPLITUDE_SPAN_SHARE = 0.05  # amplitude limit as a share of the 5-95 % span of the segment
ULTIMATE_PERIOD_S = 600.0  # assumed natural period of the loops, no identification possible
FLAT_RUN_SAMPLES = 30  # 10 min
LAB_FLAT_MIN = 0.99  # expected flat share of the hourly lab columns (loader sanity check)
REPORT_PATH = Path(__file__).resolve().parent / "results" / "report.md"


@dataclass(frozen=True)
class ColumnSummary:
    """Per-column result over its long gap-free segments."""

    name: str
    segments: int
    oscillating: int
    median_period_s: float | None
    median_flat: float


def segment_slices(t_s: np.ndarray) -> list[slice]:
    """Gap-free runs of at least MIN_SEGMENT_SAMPLES samples; a gap is a step above MAX_GAP_S."""
    breaks = np.flatnonzero(np.diff(t_s) > MAX_GAP_S) + 1
    edges = np.r_[0, breaks, len(t_s)]
    runs = [slice(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:], strict=True)]
    return [run for run in runs if run.stop - run.start >= MIN_SEGMENT_SAMPLES]


def check_segment(x: np.ndarray) -> tuple[bool, float | None, float]:
    """Oscillation flag, its period and the flat share of one segment (NaN samples are filled)."""
    filled = np.where(np.isnan(x), np.nanmedian(x), x)
    low, high = np.percentile(filled, [5, 95])
    error = filled - np.median(filled)
    result = hagglund_oscillation(
        error, SAMPLE_PERIOD_S, AMPLITUDE_SPAN_SHARE * (high - low), ULTIMATE_PERIOD_S
    )
    return result.detected, result.period_s, flatline_fraction(filled, FLAT_RUN_SAMPLES)


def summarise_column(name: str, x: np.ndarray, slices: list[slice]) -> ColumnSummary:
    """Run the checks on every segment of one column and condense them."""
    checks = [check_segment(x[run]) for run in slices]
    periods = [period for detected, period, _ in checks if detected and period is not None]
    flats = [flat for _, _, flat in checks]
    return ColumnSummary(
        name,
        len(checks),
        sum(1 for detected, _, _ in checks if detected),
        float(np.median(periods)) if periods else None,
        float(np.median(flats)),
    )


def render_report(rows: list[ColumnSummary], lab: list[ColumnSummary], n_samples: int) -> str:
    """Markdown report: the loader check first, then the per-column table."""
    title = f"# Public flotation data, PV-only checks ({n_samples} rows)"
    lines = [title, "", "## Loader check", ""]
    for row in lab:
        verdict = "ok" if row.median_flat > LAB_FLAT_MIN else "FAILED"
        lines.append(f"- {row.name}: flat share {row.median_flat:.3f} ({verdict})")
    header = "| column | segments | oscillating | median period s | flat share |"
    lines += ["", "## Columns", "", header]
    lines.append("|---|---|---|---|---|")
    for row in rows:
        period = f"{row.median_period_s:.0f}" if row.median_period_s else "-"
        cells = [row.name, row.segments, row.oscillating, period, f"{row.median_flat:.3f}"]
        lines.append("| " + " | ".join(str(cell) for cell in cells) + " |")
    return "\n".join(lines) + "\n"


def main(path: str) -> None:
    """Load the data, analyse every process column and lab column, write the report."""
    data = load_flotation_csv(path)
    slices = segment_slices(data.t_s)
    names = [name for name in data.columns if name not in LAB_COLUMNS]
    rows = [summarise_column(name, data.columns[name], slices) for name in names]
    lab = [summarise_column(name, data.columns[name], slices) for name in LAB_COLUMNS]
    report = render_report(rows, lab, len(data.t_s))
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main(sys.argv[1])

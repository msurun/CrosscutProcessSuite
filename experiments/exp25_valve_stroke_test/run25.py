"""exp25 one-shot harness: runs the frozen targets V1-V3 of the guided valve stroke test.

Every (case, seed) is simulated by g25_valve and analysed by crosscut_loops.valve_test, the
per-run numbers are kept in one row list and all tables are computed from that list alone.
Writes results25.md next to this file and refuses to overwrite an existing report.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import g25_valve  # noqa: E402
from crosscut_loops.valve_test import analyze_stroke_test, plan_stroke_test  # noqa: E402

SEEDS = range(0, 20)
OP_START = 50.0  # % of output span
TOLERANCE = 0.25  # % of output span, V1 and V2 deadband tolerance
V1_MIN = 0.90  # share of runs within TOLERANCE
V2_MIN = 0.95  # share of runs within TOLERANCE
V1_NOISE_LEVELS = (0.0, 0.05)  # noise_fraction pooled for V1
HEALTHY_NOISE_MAX = 0.05  # noise_fraction allowed for V2
REPORT_PATH = HERE / "results25.md"


@dataclass
class RunRow:
    """One analysed run: the case, the seed and what the analyzer returned."""

    case_name: str
    seed: int
    gain: float
    tau_s: float
    noise_fraction: float
    load: str
    true_deadband: float
    true_resolution: float
    deadband: float | None
    deadband_bracket: tuple[float, float] | None
    deadband_lower_bound: float | None
    resolution_le: float | None
    gain_estimate: float | None
    reason: str
    error: float | None

    def is_within_tolerance(self) -> bool:
        """True when the deadband estimate exists and is at most TOLERANCE off."""
        return self.error is not None and self.error <= TOLERANCE


def run_one(case, seed: int) -> RunRow:
    """Simulate one case at one seed and analyse it with the matching plan."""
    plan = plan_stroke_test(OP_START, g25_valve.dwell_for(case.tau_s))
    steps = [(step.op_target, step.dwell_s) for step in plan.steps]
    record = g25_valve.simulate_test(case, OP_START, steps, seed)
    result = analyze_stroke_test(record["t_s"], record["op"], record["pv"], plan)
    error = None
    if result.deadband is not None:
        error = abs(result.deadband - record["true_deadband"])
    return RunRow(
        case_name=case.name,
        seed=seed,
        gain=case.gain,
        tau_s=case.tau_s,
        noise_fraction=case.noise_fraction,
        load=case.load,
        true_deadband=record["true_deadband"],
        true_resolution=record["true_resolution"],
        deadband=result.deadband,
        deadband_bracket=result.deadband_bracket,
        deadband_lower_bound=result.deadband_lower_bound,
        resolution_le=result.resolution_le,
        gain_estimate=result.gain,
        reason=result.reason,
        error=error,
    )


def run_main_suite() -> list[RunRow]:
    """Run every main-suite case at every seed."""
    rows = []
    for case in g25_valve.all_cases():
        for seed in SEEDS:
            rows.append(run_one(case, seed))
    return rows


def run_abort_suite() -> list[RunRow]:
    """Run the abort cases; the band is half the PV deviation of the same record."""
    rows = []
    for case in g25_valve.abort_cases():
        for seed in SEEDS:
            rows.append(run_abort_one(case, seed))
    return rows


def run_abort_one(case, seed: int) -> RunRow:
    """Simulate once, size pv_band from that PV, then analyse the same record again."""
    dwell_s = g25_valve.dwell_for(case.tau_s)
    band_free_plan = plan_stroke_test(OP_START, dwell_s)
    steps = [(step.op_target, step.dwell_s) for step in band_free_plan.steps]
    record = g25_valve.simulate_test(case, OP_START, steps, seed)
    pv = np.asarray(record["pv"], dtype=float)
    deviation = float(np.max(np.abs(pv - pv[0])))
    banded_plan = plan_stroke_test(OP_START, dwell_s, pv_band=deviation / 2.0)
    result = analyze_stroke_test(record["t_s"], record["op"], pv, banded_plan)
    row = run_one_fields(case, seed, record, result)
    row.pv_left_band = bool(result.pv_left_band)
    return row


def run_one_fields(case, seed: int, record: dict, result) -> AbortRow:
    """Build an AbortRow from an already computed record and analysis result."""
    error = None
    if result.deadband is not None:
        error = abs(result.deadband - record["true_deadband"])
    return AbortRow(
        case_name=case.name,
        seed=seed,
        gain=case.gain,
        tau_s=case.tau_s,
        noise_fraction=case.noise_fraction,
        load=case.load,
        true_deadband=record["true_deadband"],
        true_resolution=record["true_resolution"],
        deadband=result.deadband,
        deadband_bracket=result.deadband_bracket,
        deadband_lower_bound=result.deadband_lower_bound,
        resolution_le=result.resolution_le,
        gain_estimate=result.gain,
        reason=result.reason,
        error=error,
        pv_left_band=False,
    )


@dataclass
class AbortRow(RunRow):
    """A RunRow that also carries the abort flag of the banded analysis."""

    pv_left_band: bool = False


def share_within_tolerance(rows: list[RunRow]) -> float:
    """Share of rows whose deadband estimate is within TOLERANCE."""
    if not rows:
        return float("nan")
    return sum(row.is_within_tolerance() for row in rows) / len(rows)


def v1_rows(rows: list[RunRow]) -> list[RunRow]:
    """The V1 population: no load step, low noise, a valve with real deadband."""
    return [
        row
        for row in rows
        if row.load == "none" and row.noise_fraction in V1_NOISE_LEVELS
        and row.true_deadband > 0
    ]


def v2_rows(rows: list[RunRow]) -> list[RunRow]:
    """The V2 population: a healthy valve (no deadband, no resolution), low noise."""
    return [
        row
        for row in rows
        if row.true_deadband == 0 and row.true_resolution == 0
        and row.load == "none" and row.noise_fraction <= HEALTHY_NOISE_MAX
    ]


def v3_share(rows: list[AbortRow]) -> float:
    """Share of abort-suite runs where pv_left_band came out True."""
    if not rows:
        return float("nan")
    return sum(row.pv_left_band for row in rows) / len(rows)


def verdict(share: float, target: float) -> str:
    """PASS or MISS for a share against its minimum."""
    return "PASS" if share >= target else "MISS"


def table_lines(header: str, rows: list[tuple[str, int, float]]) -> list[str]:
    """Markdown table with one row per key: label, run count, share."""
    lines = [f"### {header}", "", "| key | runs | share |", "|---|---|---|"]
    for label, count, share in rows:
        lines.append(f"| {label} | {count} | {share:.2f} |")
    lines.append("")
    return lines


def group_share(
    rows: list[RunRow], key_function
) -> list[tuple[str, int, float]]:
    """Group rows by key_function and give (label, count, share) per group, sorted."""
    groups: dict[str, list[RunRow]] = {}
    for row in rows:
        groups.setdefault(key_function(row), []).append(row)
    return [
        (label, len(group), share_within_tolerance(group))
        for label, group in sorted(groups.items())
    ]


def noise_load_label(row: RunRow) -> str:
    """Label of the (noise_fraction, load) cell of a row."""
    return f"noise {row.noise_fraction:.2f} / load {row.load}"


def deadband_label(row: RunRow) -> str:
    """Label of the true-deadband cell of a row."""
    return f"{row.true_deadband:.2f} %"


def tau_label(row: RunRow) -> str:
    """Label of the tau cell of a row."""
    return f"{row.tau_s:.0f} s"


def resolution_counts(rows: list[RunRow]) -> list[tuple[str, int, float]]:
    """Resolution table: per true resolution the share of runs with a finite resolution_le."""
    groups: dict[str, list[RunRow]] = {}
    for row in rows:
        label = f"true {row.true_resolution:.2f} %"
        groups.setdefault(label, []).append(row)
    entries = []
    for label, group in sorted(groups.items()):
        share = sum(row.resolution_le is not None for row in group) / len(group)
        entries.append((label, len(group), share))
    return entries


def reason_counts(rows: list[RunRow]) -> list[tuple[str, int, float]]:
    """Reason counts as a table: reason, run count, share of all runs."""
    groups: dict[str, int] = {}
    for row in rows:
        label = row.reason if row.reason else "(complete)"
        groups[label] = groups.get(label, 0) + 1
    total = max(len(rows), 1)
    return [(label, count, count / total) for label, count in sorted(groups.items())]


def build_report(main_rows: list[RunRow], abort_rows: list[AbortRow]) -> str:
    """Assemble the markdown report from the run rows; pure, no file access."""
    v1_share = share_within_tolerance(v1_rows(main_rows))
    v2_share = share_within_tolerance(v2_rows(main_rows))
    v3_value = v3_share(abort_rows)
    lines = [
        "# exp25 results - guided valve stroke test",
        "",
        f"Seeds {SEEDS.start}..{SEEDS.stop - 1}, OP start {OP_START:.0f} %, "
        f"tolerance {TOLERANCE:.2f} % of span.",
        "",
        "## Frozen targets",
        "",
        "| target | value | minimum | verdict |",
        "|---|---|---|---|",
        f"| V1 deadband within tolerance | {v1_share:.2f} | {V1_MIN:.2f} | "
        f"{verdict(v1_share, V1_MIN)} |",
        f"| V2 healthy valve | {v2_share:.2f} | {V2_MIN:.2f} | "
        f"{verdict(v2_share, V2_MIN)} |",
        f"| V3 abort detected | {v3_value:.2f} | 1.00 | "
        f"{verdict(v3_value, 1.0)} |",
        "",
        "## Report-only tables",
        "",
    ]
    lines += table_lines(
        "share within tolerance by noise and load",
        group_share(main_rows, noise_load_label),
    )
    lines += table_lines(
        "share within tolerance by true deadband",
        group_share(main_rows, deadband_label),
    )
    lines += table_lines(
        "share within tolerance by tau",
        group_share(main_rows, tau_label),
    )
    lines += table_lines(
        "resolution_le available per true resolution",
        resolution_counts(main_rows),
    )
    lines += table_lines("reason counts", reason_counts(main_rows))
    return "\n".join(lines)


def write_report(text: str, path: Path) -> None:
    """Write the report once; refuse to overwrite an earlier run's report."""
    if path.exists():
        raise SystemExit(
            f"{path} already exists: move it away before re-running the frozen targets"
        )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    """Run the main and abort suites, write results25.md and print it."""
    main_rows = run_main_suite()
    abort_rows = run_abort_suite()
    report = build_report(main_rows, abort_rows)
    write_report(report, REPORT_PATH)
    print(report)


if __name__ == "__main__":
    main()

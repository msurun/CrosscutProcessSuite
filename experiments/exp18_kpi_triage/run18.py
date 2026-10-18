"""Benchmark loop triage from crosscut_loops against SACAC and ISDB real-world data.

Evaluates sensitivity, specificity, and root-cause diagnostic accuracy against
frozen labels and triage thresholds defined across multi-run control loops.

Usage:
    python -I run18.py <SACAC folder> <ISDB npz folder> <exp12 labels.csv>
        <isdb_labels.csv> [--write]
"""

import csv
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Load sibling experiment modules
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp12_stiction_scoreboard"))
sys.path.insert(0, str(HERE.parent / "exp13_stiction_suspicion"))

import run13  # noqa: E402
from crosscut_loops.monitor import LoopSettings, analyze_loop  # noqa: E402
from crosscut_loops.overview import status_level  # noqa: E402
from scoreboard import load_loops, wilson  # noqa: E402

NEGATIVE_LOOPS = frozenset(
    {"other-F-horch-2", "other-L-horch", "buildings/loop1", "buildings/loop2", "buildings/loop8"}
)
UNKNOWN_STATUS_LOOPS = frozenset({"pulpPapers/loop6", "pulpPapers/loop9"})
ISDB_QUANTISATION_TRUTH = frozenset({"chemicals/loop3"})

FLAG_LEVELS = frozenset({"warning", "problem"})
QUANT_PREFIX = "quantisation:"
VALVE_PREFIX = "valve "


@dataclass(frozen=True)
class LoopRunResult:
    """Diagnostic outcome for a single continuous recording/stem."""

    is_flagged: bool
    has_quant_finding: bool
    is_saturated: bool
    sizing_hint: str | None
    first_status: str
    first_classification: str


@dataclass(frozen=True)
class ScoredLoop:
    """Aggregated triage outcome for a multi-run control loop."""

    name: str
    source: str
    category: str
    is_flagged: bool
    has_quant_finding: bool
    is_saturated: bool
    sizing_hint: str | None
    sample_status: str
    sample_classification: str


def build_loop_settings(pv: np.ndarray, dt_s: float, kind: str) -> LoopSettings:
    """Create standard triage settings for a loop based on sampling period and range."""
    finite_pv = pv[np.isfinite(pv)]
    pv_span = float(np.percentile(finite_pv, 99) - np.percentile(finite_pv, 1))
    amplitude_limit = 0.05 * pv_span if pv_span > 0.0 else 0.05
    process_kind = "integrating" if kind == "L" else "self_regulating"
    return LoopSettings(
        delay_s=5.0 * dt_s,
        ultimate_period_s=60.0 * dt_s,
        amplitude_limit=amplitude_limit,
        out_low=0.0,
        out_high=100.0,
        process_kind=process_kind,
    )


def build_active_mode_mask(sp: np.ndarray, pv: np.ndarray, op: np.ndarray) -> np.ndarray:
    """Return binary mode array: 1.0 where all channels are finite, 0.0 on missing values."""
    is_finite = np.isfinite(sp) & np.isfinite(pv) & np.isfinite(op)
    return is_finite.astype(float)


def check_is_run_flagged(level: str, findings: list[str]) -> bool:
    """Check if individual run status or diagnostics indicate loop issues."""
    if level in FLAG_LEVELS:
        return True
    return any(f.startswith(QUANT_PREFIX) or f.startswith(VALVE_PREFIX) for f in findings)


def evaluate_single_run(
    sp: np.ndarray, pv: np.ndarray, op: np.ndarray, dt_s: float, kind: str, loop_name: str
) -> LoopRunResult | None:
    """Execute analysis pipeline on a single run; catches and prints unexpected failures."""
    mode = build_active_mode_mask(sp, pv, op)
    t_s = np.arange(len(pv), dtype=float) * dt_s
    settings = build_loop_settings(pv, dt_s, kind)
    try:
        report = analyze_loop(t_s, pv, sp, op, mode, settings=settings)
    except Exception as exc:  # noqa: BLE001
        print(f"Error analyzing loop {loop_name}: {type(exc).__name__}: {exc}")
        return None
    level = status_level(report, settings)
    is_flagged = check_is_run_flagged(level, report.findings)
    has_quant = any(f.startswith(QUANT_PREFIX) for f in report.findings)
    return LoopRunResult(
        is_flagged=is_flagged,
        has_quant_finding=has_quant,
        is_saturated=report.classification == "saturated",
        sizing_hint=report.valve_sizing_hint,
        first_status=level,
        first_classification=report.classification,
    )


def aggregate_runs(
    name: str, source: str, category: str, run_results: list[LoopRunResult | None]
) -> ScoredLoop:
    """Aggregate per-stem run results into an overall loop classification."""
    valid_runs = [r for r in run_results if r is not None]
    total_runs = len(run_results)
    threshold = total_runs / 2.0
    flagged_count = sum(1 for r in valid_runs if r.is_flagged)
    quant_count = sum(1 for r in valid_runs if r.has_quant_finding)
    sat_count = sum(1 for r in valid_runs if r.is_saturated)
    first_valid = valid_runs[0] if valid_runs else None
    sample_status = first_valid.first_status if first_valid else "error"
    sample_cls = first_valid.first_classification if first_valid else "error"
    sizing_hint = first_valid.sizing_hint if first_valid else None
    return ScoredLoop(
        name=name,
        source=source,
        category=category,
        is_flagged=flagged_count > threshold,
        has_quant_finding=quant_count > threshold,
        is_saturated=sat_count > threshold,
        sizing_hint=sizing_hint,
        sample_status=sample_status,
        sample_classification=sample_cls,
    )


def load_isdb_rows(labels_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Load valid ISDB loops and collect names of low-confidence excluded loops."""
    rows = []
    excluded = []
    with labels_path.open(encoding="utf-8") as file_handle:
        for row in csv.DictReader(file_handle):
            if row["overlap"] != "independent":
                continue
            if row["confidence"] == "low":
                excluded.append(row["loop"])
            else:
                rows.append(row)
    return rows, excluded


def score_all_isdb_loops(isdb_dir: Path, isdb_rows: list[dict[str, str]]) -> list[ScoredLoop]:
    """Load arrays and compute triage scores across all independent ISDB loops."""
    scored = []
    for row in isdb_rows:
        loop_name = row["loop"]
        file_stem = loop_name.replace("/", "_")
        npz_path = isdb_dir / f"{file_stem}.npz"
        with np.load(npz_path) as data:
            dt_s = float(data["dt_s"])
            res = evaluate_single_run(
                data["sp"], data["pv"], data["op"], dt_s, row["kind"], loop_name
            )
        scored.append(aggregate_runs(loop_name, "ISDB", "", [res]))
    return scored


def score_sacac_loop(loop_obj, sacac_dir: Path) -> ScoredLoop:
    """Analyze all continuous recordings for a given SACAC control loop."""
    category = loop_obj.stems[0].split("-")[0]
    run_results = []
    for stem in loop_obj.stems:
        sp, pv, op = run13.read_spo(sacac_dir, stem)
        run_res = evaluate_single_run(sp, pv, op, loop_obj.dt_s, loop_obj.kind, loop_obj.name)
        run_results.append(run_res)
    return aggregate_runs(loop_obj.name, "SACAC", category, run_results)


def split_sacac_confidence(
    labels_path: Path,
) -> tuple[list[str], list[str]]:
    """Partition SACAC loop names by confidence from the master label metadata."""
    high_conf_loops = []
    low_conf_loops = []
    with labels_path.open(encoding="utf-8") as file_handle:
        for row in csv.DictReader(file_handle):
            if row["confidence"] == "low":
                low_conf_loops.append(row["loop"])
            else:
                high_conf_loops.append(row["loop"])
    return high_conf_loops, low_conf_loops


def format_rate(k: int, n: int) -> str:
    """Render count, total, percentage, and 95% Wilson confidence intervals."""
    if n == 0:
        return "0/0 (0.0%) [0.0%, 0.0%]"
    lo, hi = wilson(k, n)
    pct = 100.0 * k / n
    return f"{k}/{n} ({pct:.1f}%) [{100.0 * lo:.1f}%, {100.0 * hi:.1f}%]"


def generate_t1_markdown(scored_loops: list[ScoredLoop]) -> list[str]:
    """Generate Markdown evaluation for T1: Positive detection sensitivity."""
    positives = [
        lp
        for lp in scored_loops
        if lp.name not in NEGATIVE_LOOPS and lp.name not in UNKNOWN_STATUS_LOOPS
    ]
    sacac_pos = [lp for lp in positives if lp.source == "SACAC"]
    isdb_pos = [lp for lp in positives if lp.source == "ISDB"]
    k_all = sum(1 for lp in positives if lp.is_flagged)
    k_sac = sum(1 for lp in sacac_pos if lp.is_flagged)
    k_isdb = sum(1 for lp in isdb_pos if lp.is_flagged)
    verdict = "PASS" if (len(positives) > 0 and k_all / len(positives) >= 0.80) else "MISS"
    return [
        "## T1: Flagged Rate Among Positives",
        f"- Target >= 80% point estimate: **{verdict}**",
        f"- All Positives: {format_rate(k_all, len(positives))}",
        f"- SACAC Positives: {format_rate(k_sac, len(sacac_pos))}",
        f"- ISDB Positives: {format_rate(k_isdb, len(isdb_pos))}",
    ]


def generate_t2_markdown(scored_loops: list[ScoredLoop]) -> list[str]:
    """Generate Markdown evaluation for T2: Negative detection specificity."""
    negatives = [lp for lp in scored_loops if lp.name in NEGATIVE_LOOPS]
    k_neg = sum(1 for lp in negatives if lp.is_flagged)
    sac_neg = [lp for lp in negatives if lp.source == "SACAC"]
    isdb_neg = [lp for lp in negatives if lp.source == "ISDB"]
    k_sac_neg = sum(1 for lp in sac_neg if lp.is_flagged)
    k_isdb_neg = sum(1 for lp in isdb_neg if lp.is_flagged)
    return [
        "## T2: Flagged Rate Among Negatives",
        f"- Total Negatives Flagged: {k_neg}/{len(negatives)}",
        f"- SACAC Negatives Flagged: {k_sac_neg}/{len(sac_neg)}",
        f"- ISDB Negatives Flagged: {k_isdb_neg}/{len(isdb_neg)}",
    ]


def generate_t3_markdown(scored_loops: list[ScoredLoop]) -> list[str]:
    """Generate Markdown evaluation for T3: Root-cause identification accuracy."""
    quant_truth = [
        lp
        for lp in scored_loops
        if lp.category == "quantisation" or lp.name in ISDB_QUANTISATION_TRUTH
    ]
    k_quant = sum(1 for lp in quant_truth if lp.has_quant_finding)
    v_quant = "PASS" if k_quant >= 2 else "MISS"
    non_quant = [lp for lp in scored_loops if lp not in quant_truth]
    fp_quant = sum(1 for lp in non_quant if lp.has_quant_finding)

    sat_truth = [lp for lp in scored_loops if lp.category == "saturation"]
    k_sat = sum(1 for lp in sat_truth if lp.is_saturated)
    v_sat = "PASS" if k_sat >= 1 else "MISS"
    non_sat = [lp for lp in scored_loops if lp not in sat_truth]
    fp_sat = sum(1 for lp in non_sat if lp.is_saturated)

    return [
        "## T3: Diagnostic Specificity (Quantisation and Saturation)",
        f"- Quantisation Truth (Target >= 2/3): **{v_quant}** ({k_quant}/{len(quant_truth)})",
        f"- Quantisation Findings on Non-truth Loops: {fp_quant}",
        f"- Saturation Truth (Target >= 1/2): **{v_sat}** ({k_sat}/{len(sat_truth)})",
        f"- Saturated Classification on Non-truth Loops: {fp_sat}",
    ]


def generate_t4_t5_markdown(
    scored_loops: list[ScoredLoop], excluded_names: list[str]
) -> list[str]:
    """Generate Markdown evaluation for T4 (Sizing) and T5 (Audit counters)."""
    hints = Counter(lp.sizing_hint for lp in scored_loops)
    oversized = hints.get("oversized", 0)
    undersized = hints.get("undersized", 0)
    no_hint = len(scored_loops) - oversized - undersized
    error_count = sum(1 for lp in scored_loops if lp.sample_status == "error")

    sacac_table = [
        "### SACAC Detailed Results",
        "| Loop | Flagged | Status | Classification |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for lp in sorted(scored_loops, key=lambda x: x.name):
        if lp.source == "SACAC":
            is_flg = "yes" if lp.is_flagged else "no"
            sacac_table.append(
                f"| {lp.name} | {is_flg} | {lp.sample_status} | {lp.sample_classification} |"
            )

    return [
        "## T4: Valve Sizing Hints",
        f"- Oversized: {oversized}, Undersized: {undersized}, None: {no_hint}",
        "## T5: Scored and Excluded Summary",
        f"- Scored Loops Count: {len(scored_loops)}",
        f"- Excluded Loops ({len(excluded_names)}): {', '.join(sorted(excluded_names))}",
        f"- Errors Count: {error_count}",
        "",
        *sacac_table,
    ]


def build_markdown_report(scored_loops: list[ScoredLoop], excluded: list[str]) -> str:
    """Collate benchmark results across all 5 test segments into clean Markdown."""
    sections = [
        "# Loop Triage Benchmark Results (Exp 18)",
        "",
        *generate_t1_markdown(scored_loops),
        "",
        *generate_t2_markdown(scored_loops),
        "",
        *generate_t3_markdown(scored_loops),
        "",
        *generate_t4_t5_markdown(scored_loops, excluded),
    ]
    return "\n".join(sections)


def parse_arguments() -> tuple[Path, Path, Path, Path, bool]:
    """Validate and extract command line arguments."""
    if len(sys.argv) < 5:
        msg = "Usage: python -I run18.py <SACAC> <ISDB npz> <exp12 labels> <isdb labels> [--write]"
        raise ValueError(msg)
    sacac_dir = Path(sys.argv[1])
    isdb_dir = Path(sys.argv[2])
    exp12_labels = Path(sys.argv[3])
    isdb_labels = Path(sys.argv[4])
    write_file = len(sys.argv) > 5 and sys.argv[5] == "--write"
    return sacac_dir, isdb_dir, exp12_labels, isdb_labels, write_file


def main() -> None:
    """Execute evaluation protocol and optionally write Markdown report."""
    sacac_dir, isdb_dir, exp12_labels, isdb_labels, should_write = parse_arguments()
    sacac_high, sacac_low = split_sacac_confidence(exp12_labels)
    all_sacac_loops = load_loops()
    sacac_loops = [lp for lp in all_sacac_loops if lp.name in set(sacac_high)]
    scored_sacac = [score_sacac_loop(lp, sacac_dir) for lp in sacac_loops]

    isdb_rows, isdb_low = load_isdb_rows(isdb_labels)
    scored_isdb = score_all_isdb_loops(isdb_dir, isdb_rows)

    all_scored = scored_sacac + scored_isdb
    all_excluded = sacac_low + isdb_low
    report_md = build_markdown_report(all_scored, all_excluded)
    print(report_md)

    if should_write:
        output_path = HERE / "results18.md"
        output_path.write_text(report_md, encoding="utf-8")


if __name__ == "__main__":
    main()

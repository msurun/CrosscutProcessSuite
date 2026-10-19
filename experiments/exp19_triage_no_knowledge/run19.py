"""exp19: loop triage on SACAC and ISDB archives with no per-loop configuration.

Frozen exp19 protocol: settings never assume an OUT range (``known=frozenset()``), oscillation is
detected by the parameter-free ACF method. Output is one Markdown report; results19.md is written
only with --write and never overwritten (one run allowed).

Usage:
    python -I run19.py <SACAC folder> <ISDB npz folder> <exp12 labels.csv>
        <isdb_labels.csv> [--write]
"""

import csv
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp12_stiction_scoreboard"))
sys.path.insert(0, str(HERE.parent / "exp13_stiction_suspicion"))

import run13  # noqa: E402
from crosscut_loops.monitor import LoopSettings, analyze_loop  # noqa: E402
from crosscut_loops.overview import status_level  # noqa: E402
from scoreboard import load_loops, wilson  # noqa: E402

OUTPUT_PATH = HERE / "results19.md"

CALM = frozenset(
    {
        "buildings/loop1",
        "buildings/loop2",
        "buildings/loop8",
        "other-F-horch-2",
        "other-L-horch",
        "tuning-F-chemical",
        "other-F-chemicals",
    }
)
EXTRA_OSCILLATING = frozenset({"other-F-horch"})

FLAG_LEVELS = frozenset({"warning", "problem"})
QUANT_PREFIX = "quantisation:"
WITHHELD_WITHOUT_OP_RANGE = frozenset(
    {"saturation", "valve_kpis", "harris", "oscillation_amplitude"}
)
CAUGHT_ERRORS = (ValueError, FloatingPointError, IndexError)

O1_MIN_DETECTED = 16  # of 20 positives, the frozen 80 % target rounded up
O1_SHARE_TARGET = 0.80
O2_MAX_DETECTED = 1
O3_MAX_FLAGGED = 2
UNITY_SAMPLES = 1.0
TARGET_POSITIVE_COUNT = 20


@dataclass(frozen=True)
class RunResult:
    """Outcome of the analysis pipeline on one continuous recording."""

    detected: bool
    period_s: float | None
    period_samples: float | None
    status: str
    flagged: bool
    quant: bool
    classification: str
    not_assessed: tuple[str, ...]
    sizing_hint: str | None
    error: bool


@dataclass(frozen=True)
class LoopSpec:
    """A loop to score, with the label metadata the protocol attaches to it."""

    name: str
    source: str
    label: str  # "stick", or "no" (SACAC) / "other" (ISDB)
    category: str  # SACAC repository category (first stem up to "-"), "" for ISDB
    kind: str  # process kind letter from the label table; "L" is a level loop


@dataclass(frozen=True)
class RunContext:
    """What one recording is analysed with besides its signals."""

    dt_s: float
    kind: str
    loop_name: str


@dataclass(frozen=True)
class ScoredLoop:
    """Triage outcome and oscillation label for one loop, aggregated over its runs."""

    name: str
    source: str
    osc_label: str  # "pos", "neg" or "none"
    detected: bool
    period_s: float | None
    period_samples: float | None
    status: str
    classification: str
    flagged: bool
    quant: bool
    o4_ok: bool
    is_error: bool


def build_frozen_settings(dt_s: float, kind: str) -> LoopSettings:
    """Return the frozen no-knowledge settings; placeholders are never used with ``known`` empty."""
    return LoopSettings(
        delay_s=dt_s,
        ultimate_period_s=60.0 * dt_s,
        amplitude_limit=1.0,
        process_kind="integrating" if kind == "L" else "self_regulating",
        known=frozenset(),
    )


def build_active_mode_mask(sp: np.ndarray, pv: np.ndarray, op: np.ndarray) -> np.ndarray:
    """Return 1.0 where SP, PV and OP are all finite, 0.0 elsewhere (missing samples)."""
    return (np.isfinite(sp) & np.isfinite(pv) & np.isfinite(op)).astype(float)


def analyse_run(sp: np.ndarray, pv: np.ndarray, op: np.ndarray, ctx: RunContext) -> RunResult:
    """Run the frozen pipeline on one recording and pack its diagnostics into a RunResult."""
    mode = build_active_mode_mask(sp, pv, op)
    t_s = np.arange(len(pv), dtype=float) * ctx.dt_s
    settings = build_frozen_settings(ctx.dt_s, ctx.kind)
    try:
        report = analyze_loop(t_s, pv, sp, op, mode, settings=settings)
    except CAUGHT_ERRORS as exc:
        print(f"Error analyzing loop {ctx.loop_name}: {type(exc).__name__}: {exc}")
        return _error_result()
    return _result_from_report(report, settings, ctx.dt_s)


def _error_result() -> RunResult:
    """Return the placeholder RunResult used when analysis raised a caught error."""
    return RunResult(
        detected=False,
        period_s=None,
        period_samples=None,
        status="error",
        flagged=False,
        quant=False,
        classification="error",
        not_assessed=(),
        sizing_hint=None,
        error=True,
    )


def _result_from_report(report, settings: LoopSettings, dt_s: float) -> RunResult:
    """Convert a successful loop report into a RunResult (period samples = period / dt)."""
    period_s = report.oscillation_period_s
    period_samples = None if period_s is None else float(period_s / dt_s)
    status = status_level(report, settings)
    return RunResult(
        detected=period_s is not None,
        period_s=period_s,
        period_samples=period_samples,
        status=status,
        flagged=status in FLAG_LEVELS,
        quant=any(f.startswith(QUANT_PREFIX) for f in report.findings),
        classification=report.classification,
        not_assessed=tuple(report.not_assessed),
        sizing_hint=report.valve_sizing_hint,
        error=False,
    )


def is_run_o4_ok(run: RunResult) -> bool:
    """O4 check of one run: range-derived findings withheld, nothing assumed from an OP range."""
    has_all_withheld = WITHHELD_WITHOUT_OP_RANGE.issubset(run.not_assessed)
    return has_all_withheld and run.classification != "saturated" and run.sizing_hint is None


def majority_is_true(runs: list[RunResult | None], getter) -> bool:
    """A flag holds when ``getter`` is true in more than half of ALL runs (errors: false)."""
    return sum(1 for run in runs if run is not None and getter(run)) > len(runs) / 2.0


def first_valid_run(runs: list[RunResult | None]) -> RunResult | None:
    """Return the first run that did not error, or None when every run failed."""
    return next((run for run in runs if run is not None and not run.error), None)


def oscillation_label(name: str, label: str) -> str:
    """Map a loop to "pos", "neg" or "none" following the frozen label rules."""
    if label == "stick" or name in EXTRA_OSCILLATING:
        return "pos"
    if name in CALM:
        return "neg"
    return "none"


def aggregate_runs(spec: LoopSpec, runs: list[RunResult | None]) -> ScoredLoop:
    """Aggregate per-run outcomes into one ScoredLoop using the > half majority rule."""
    display = first_valid_run(runs)
    valid = [run for run in runs if run is not None and not run.error]
    return ScoredLoop(
        name=spec.name,
        source=spec.source,
        osc_label=oscillation_label(spec.name, spec.label),
        detected=majority_is_true(runs, lambda run: run.detected),
        period_s=display.period_s if display else None,
        period_samples=display.period_samples if display else None,
        status=display.status if display else "error",
        classification=display.classification if display else "error",
        flagged=majority_is_true(runs, lambda run: run.flagged),
        quant=majority_is_true(runs, lambda run: run.quant),
        o4_ok=all(is_run_o4_ok(run) for run in valid),
        is_error=display is None,
    )


def score_recordings(spec: LoopSpec, recordings: list[tuple], dt_s: float) -> ScoredLoop:
    """Analyse every (sp, pv, op) recording of one loop and aggregate them as one loop."""
    runs = [
        analyse_run(sp, pv, op, RunContext(dt_s, spec.kind, spec.name)) for sp, pv, op in recordings
    ]
    return aggregate_runs(spec, runs)


def load_sacac_specs(labels_path: Path) -> tuple[list[LoopSpec], list[str]]:
    """LoopSpecs of the SACAC label rows with confidence != low, plus the excluded names."""
    specs, excluded = [], []
    with labels_path.open(encoding="utf-8") as file_handle:
        for row in csv.DictReader(file_handle):
            if row["confidence"] == "low":
                excluded.append(row["loop"])
                continue
            category = row["stems"].split(";")[0].split("-")[0]
            specs.append(LoopSpec(row["loop"], "SACAC", row["label"], category, row["kind"]))
    return specs, excluded


def load_isdb_specs(labels_path: Path) -> tuple[list[LoopSpec], list[str]]:
    """LoopSpecs of the independent ISDB rows with confidence != low, plus the excluded names."""
    specs, excluded = [], []
    with labels_path.open(encoding="utf-8") as file_handle:
        for row in csv.DictReader(file_handle):
            if row["overlap"] != "independent":
                continue
            if row["confidence"] == "low":
                excluded.append(row["loop"])
                continue
            specs.append(LoopSpec(row["loop"], "ISDB", row["label"], "", row["kind"]))
    return specs, excluded


USAGE_TEXT = (
    "usage: python -I run19.py <SACAC folder> <ISDB npz folder> <exp12 labels.csv> "
    "<isdb_labels.csv> [--write]"
)
MIN_PATH_ARGUMENTS = 4
WILSON_CONFIDENCE = 0.95  # wilson() already applies this; kept here for the docstring
PERCENT = 100.0
NO_VALUE = "-"


def format_rate(k: int, n: int) -> str:
    """Format a count as "k/n (p%) [lo%, hi%]" with a Wilson 95 % interval; "0/0" when n is 0."""
    if n == 0:
        return "0/0"
    share = PERCENT * k / n
    lower, upper = wilson(k, n)
    return f"{k}/{n} ({share:.0f}%) [{PERCENT * lower:.0f}%, {PERCENT * upper:.0f}%]"


def score_sacac(specs: list[LoopSpec], sacac_dir: Path) -> list[ScoredLoop]:
    """Score every SACAC spec over all its stems; missing loops are skipped with a warning."""
    # load_loops() returns the exp12 loop objects; index them by loop name for O(1) lookups.
    loops_by_name = {loop.name: loop for loop in load_loops()}
    scored_loops = []
    for spec in specs:
        loop = loops_by_name.get(spec.name)
        if loop is None:
            print(f"Warning: SACAC loop {spec.name} not found in the exp12 loop table; skipped")
            continue
        recordings = [run13.read_spo(sacac_dir, stem) for stem in loop.stems]
        scored_loops.append(score_recordings(spec, recordings, loop.dt_s))
    return scored_loops


def score_isdb(specs: list[LoopSpec], isdb_dir: Path) -> list[ScoredLoop]:
    """Score every ISDB spec from its single npz recording (keys sp, pv, op, dt_s)."""
    scored_loops = []
    for spec in specs:
        npz_path = isdb_dir / (spec.name.replace("/", "_") + ".npz")
        if not npz_path.is_file():
            print(f"Warning: ISDB recording {npz_path} not found; skipped")
            continue
        with np.load(npz_path) as data:
            # Copy out: the arrays are needed after the file handle closes.
            recording = (data["sp"].copy(), data["pv"].copy(), data["op"].copy())
            dt_s = float(data["dt_s"])
        scored_loops.append(score_recordings(spec, [recording], dt_s))
    return scored_loops


def is_o1_pass(n: int, k: int) -> bool:
    """Decide O1: fixed count at the frozen n, otherwise the frozen share rule."""
    if n == TARGET_POSITIVE_COUNT:
        return k >= O1_MIN_DETECTED
    return n > 0 and k / n >= O1_SHARE_TARGET


def o1_lines(scored: list[ScoredLoop]) -> list[str]:
    """O1 sensitivity: detected share among the oscillating (positive) loops."""
    positives = [loop for loop in scored if loop.osc_label == "pos"]
    detected = sum(1 for loop in positives if loop.detected)
    verdict = "PASS" if is_o1_pass(len(positives), detected) else "MISS"
    missed = sorted(loop.name for loop in positives if not loop.detected)
    return [
        "## O1 sensitivity (positives)",
        "",
        f"- detected {format_rate(detected, len(positives))} of the positives "
        f"(n = {len(positives)}, target n = {TARGET_POSITIVE_COUNT}): **{verdict}**",
        f"- SACAC: {_source_rate(positives, 'SACAC')}",
        f"- ISDB: {_source_rate(positives, 'ISDB')}",
        f"- positives not detected: {', '.join(missed) if missed else 'none'}",
    ]


def _source_rate(loops: list[ScoredLoop], source: str) -> str:
    """Return format_rate for the detected share of one source within ``loops``."""
    subset = [loop for loop in loops if loop.source == source]
    return format_rate(sum(1 for loop in subset if loop.detected), len(subset))


def o2_lines(scored: list[ScoredLoop]) -> list[str]:
    """O2 false positives: detected share among the calm (negative) loops."""
    negatives = [loop for loop in scored if loop.osc_label == "neg"]
    detected = [loop.name for loop in negatives if loop.detected]
    verdict = "PASS" if len(detected) <= O2_MAX_DETECTED else "MISS"
    return [
        "## O2 calm loops (negatives)",
        "",
        f"- detected {format_rate(len(detected), len(negatives))} "
        f"(max {O2_MAX_DETECTED}): **{verdict}**",
        f"- detected negatives: {', '.join(sorted(detected)) if detected else 'none'}",
    ]


def o3_lines(scored: list[ScoredLoop]) -> list[str]:
    """O3 triage breadth: flagged share among negatives, overall share and status counts."""
    negatives = [loop for loop in scored if loop.osc_label == "neg"]
    flagged = [loop.name for loop in negatives if loop.flagged]
    verdict = "PASS" if len(flagged) <= O3_MAX_FLAGGED else "MISS"
    scored_without_error = [loop for loop in scored if not loop.is_error]
    all_flagged = sum(1 for loop in scored_without_error if loop.flagged)
    status_counts = Counter(loop.status for loop in scored)
    status_pairs = ", ".join(
        f"{status}: {count}" for status, count in sorted(status_counts.items())
    )
    return [
        "## O3 triage breadth",
        "",
        f"- flagged {format_rate(len(flagged), len(negatives))} of the negatives "
        f"(max {O3_MAX_FLAGGED}): **{verdict}**",
        f"- flagged negatives: {', '.join(sorted(flagged)) if flagged else 'none'}",
        f"- flagged over all scored loops: {format_rate(all_flagged, len(scored_without_error))}",
        f"- status counts: {status_pairs}",
    ]


def o4_lines(scored: list[ScoredLoop]) -> list[str]:
    """O4 rule check: the OP-range-derived findings must be withheld on every non-error loop."""
    violations = sorted(loop.name for loop in scored if not loop.is_error and not loop.o4_ok)
    verdict = "PASS" if not violations else "MISS"
    return [
        "## O4 OP-range rule",
        "",
        f"- loops violating the not-assessed rule: **{verdict}**",
        f"- violating loops: {', '.join(violations) if violations else 'none'}",
    ]


def _quantisation_truth(spec_name: str, categories: dict[str, str]):
    """Return True when a loop is a documented quantisation example, else False."""
    return categories.get(spec_name) == "quantisation" or spec_name == "chemicals/loop3"


def reported_lines(
    scored: list[ScoredLoop], excluded: list[str], categories: dict[str, str]
) -> list[str]:
    """Reported, untargeted figures: unlabelled detections, quantisation, errors, excluded loops."""
    unlabelled = [loop for loop in scored if loop.osc_label == "none"]
    detected = [loop.name for loop in unlabelled if loop.detected]
    quant_truth = [loop for loop in scored if _quantisation_truth(loop.name, categories)]
    quant_hit = sum(1 for loop in quant_truth if loop.quant)
    quant_other = sum(
        1 for loop in scored if loop.quant and not _quantisation_truth(loop.name, categories)
    )
    error_count = sum(1 for loop in scored if loop.is_error)
    return [
        "## Reported (no target)",
        "",
        f"- detected among unlabelled loops: {format_rate(len(detected), len(unlabelled))}",
        f"- detected unlabelled loops: {', '.join(sorted(detected)) if detected else 'none'}",
        f"- quantisation truth loops flagged quant: {format_rate(quant_hit, len(quant_truth))}",
        f"- quantisation flagged on other loops: {quant_other}",
        f"- loops with errors: {error_count}",
        f"- excluded (low confidence): {', '.join(sorted(excluded)) if excluded else 'none'}",
    ]


def _format_period(value: float | None) -> str:
    """Format a period for the table, rounded to one decimal, or a dash when missing."""
    return NO_VALUE if value is None else f"{value:.1f}"


def table_lines(scored: list[ScoredLoop]) -> list[str]:
    """Per-loop markdown table sorted by (source, name)."""
    header = (
        "| name | source | osc label | detected | period_s | period_samples | status "
        "| classification |"
    )
    separator = "|" + "---|" * 8
    rows = [header, separator]
    for loop in sorted(scored, key=lambda item: (item.source, item.name)):
        rows.append(
            f"| {loop.name} | {loop.source} | {loop.osc_label} | {loop.detected} "
            f"| {_format_period(loop.period_s)} | {_format_period(loop.period_samples)} "
            f"| {loop.status} | {loop.classification} |"
        )
    return ["## Per-loop table", ""] + rows


def build_report(scored: list[ScoredLoop], excluded: list[str], categories: dict[str, str]) -> str:
    """Assemble the full Markdown report, sections separated by one blank line."""
    sections = [
        [
            "# exp19 results",
            "",
            "Exploratory: SACAC and ISDB were seen in exp15-exp18 (see README).",
        ],
        o1_lines(scored),
        o2_lines(scored),
        o3_lines(scored),
        o4_lines(scored),
        reported_lines(scored, excluded, categories),
        table_lines(scored),
    ]
    return "\n\n".join("\n".join(lines) for lines in sections) + "\n"


def parse_arguments() -> tuple[Path, Path, Path, Path, bool]:
    """Parse CLI paths and the --write flag; exit with the usage text when paths are missing."""
    arguments = sys.argv[1:]
    write = "--write" in arguments
    paths = [argument for argument in arguments if argument != "--write"]
    if len(paths) < MIN_PATH_ARGUMENTS:
        raise SystemExit(USAGE_TEXT)
    sacac_dir, isdb_dir, exp12_labels, isdb_labels = (Path(path) for path in paths[:4])
    return sacac_dir, isdb_dir, exp12_labels, isdb_labels, write


def main() -> None:
    """Load specs, score both archives, print the report and optionally write results19.md."""
    sacac_dir, isdb_dir, exp12_labels, isdb_labels, write = parse_arguments()
    sacac_specs, sacac_excluded = load_sacac_specs(exp12_labels)
    isdb_specs, isdb_excluded = load_isdb_specs(isdb_labels)
    scored = score_sacac(sacac_specs, sacac_dir) + score_isdb(isdb_specs, isdb_dir)
    categories = {spec.name: spec.category for spec in sacac_specs}
    report = build_report(scored, sacac_excluded + isdb_excluded, categories)
    print(report)
    if not write:
        return
    if OUTPUT_PATH.exists():
        raise SystemExit("results19.md exists; the protocol allows one run")
    OUTPUT_PATH.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()

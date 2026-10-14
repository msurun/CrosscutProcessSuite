"""Timing faults experiment on the mill_feed control loop (exp05).

Evaluates the robustness of loop monitoring and readiness diagnostics against historian
timestamp jitter and manual operator mode flip disturbances across 5 simulation seeds.
Produces a structured markdown report validating targets J1-J3 and M1 against baselines.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import math
from pathlib import Path
from typing import NamedTuple

import numpy as np
from crosscut_loops.monitor import LoopReport, analyze_loop
from crosscut_loops.overview import LoopTags, default_settings
from crosscut_loops.readiness import check_readiness
from crosscut_sim.core import Scenario
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario
from crosscut_sim.timing_faults import ModeFlip, jitter_timestamps, mode_flip_events

# Simulation configuration
DURATION_S = 21600.0  # Total duration of nominal simulation: 6 hours
DT_S = 1.0  # Sampling step duration in seconds
FLIP_DURATION_S = 600.0  # 10 minutes duration for each manual mode flip
HALF_FLIP_DURATION_S = 300.0  # Half duration used for flip centering offset
SEEDS = tuple(range(1, 6))  # Random seeds 1 through 5
MAX_WORKERS = 4  # Concurrency limit for background simulation tasks
LOOP_NAME = "mill_feed"

# Tag conventions for the mill feed circuit
PV_TAG = f"sim.mc.{LOOP_NAME}"
SP_TAG = f"sim.mc.{LOOP_NAME}_sp"
OUT_TAG = f"sim.mc.{LOOP_NAME}_out"
MODE_TAG = f"sim.mc.{LOOP_NAME}_mode"

# Tolerance and target thresholds
JITTER_SIGMAS_S = (0.2, 1.0, 3.0)  # Standard deviation of jitter delays
MODE_FLIP_COUNTS = (1, 3, 6)  # Number of mode flips injected
HARRIS_REL_TOLERANCE = 0.20  # At most 20% relative variation permitted for J1
SERVICE_TOLERANCE = 0.02  # Maximum acceptable service factor error for M1
REQUIRED_PASSING_SEEDS = 4  # Frozen acceptance bar: at least 4 of 5 seeds
TOTAL_SEEDS = 5
NS_PER_S = 1e9  # Nanoseconds conversion factor

RESULTS_PATH = Path(__file__).parent / "results" / "results.md"


class SimulationSignals(NamedTuple):
    """Raw trajectory series extracted from the plant simulation."""

    pv: np.ndarray  # float64
    sp: np.ndarray  # float64
    out: np.ndarray  # float64
    mode: np.ndarray  # float64


class VariantOutcome(NamedTuple):
    """Analysis metrics and diagnostic check details for a run variant."""

    seed: int
    variant: str
    classification: str
    harris_index: float
    service_factor: float
    mode_changes: int
    non_ok_checks: tuple[str, ...]
    has_regularity_issue: bool
    longest_auto_stretch: int


class SeedBatchResult(NamedTuple):
    """Container holding baseline and fault metrics for an individual seed."""

    seed: int
    baseline: VariantOutcome
    jitter_results: dict[float, VariantOutcome]
    flip_results: dict[int, VariantOutcome]


def _simulate_loop(scenario: Scenario, seed: int) -> SimulationSignals:
    """Run mill circuit simulation and return PV, SP, OUT, and MODE arrays."""
    # Assumes tags: sim.mc.mill_feed, ..._sp, ..._out, ..._mode as float64
    plant = MillCircuitPlant()
    plant.reset(seed, scenario)
    n_steps = int(round(scenario.duration_s / scenario.dt_s))

    pv = np.empty(n_steps, dtype=np.float64)
    sp = np.empty(n_steps, dtype=np.float64)
    out = np.empty(n_steps, dtype=np.float64)
    mode = np.empty(n_steps, dtype=np.float64)

    for step in range(n_steps):
        pv[step] = float(plant.read(PV_TAG)[0])
        sp[step] = float(plant.read(SP_TAG)[0])
        out[step] = float(plant.read(OUT_TAG)[0])
        mode[step] = float(plant.read(MODE_TAG)[0])
        plant.step()

    return SimulationSignals(pv=pv, sp=sp, out=out, mode=mode)


def _longest_auto_stretch(mode: np.ndarray) -> int:
    """Compute the maximum consecutive sample count in automatic mode."""
    # AUTO mode convention code is 1.0
    auto_mask = mode == 1.0
    longest = current = 0
    for is_auto in auto_mask:
        if is_auto:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _build_nominal_timestamps(n_steps: int) -> np.ndarray:
    """Generate linearly spaced nanosecond integer timestamps."""
    return (np.arange(n_steps, dtype=np.float64) * NS_PER_S).astype(np.int64)


def _check_regularity_names(non_ok_checks: tuple[str, ...]) -> bool:
    """Return True if any non-ok check is sampled regularity-related."""
    keywords = ("regular", "period", "time")
    return any(any(kw in check.lower() for kw in keywords) for check in non_ok_checks)


def _run_diagnostics(
    t_s: np.ndarray,
    signals: SimulationSignals,
    seed: int,
    variant_label: str,
) -> VariantOutcome:
    """Run loop monitoring and readiness evaluations on the provided trajectory."""
    tags = LoopTags(
        name=LOOP_NAME,
        pv=PV_TAG,
        sp=SP_TAG,
        out=OUT_TAG,
        mode=MODE_TAG,
        unit="",
        eng_min=None,
        eng_max=None,
    )
    settings = default_settings(tags)
    report: LoopReport = analyze_loop(
        t_s, signals.pv, signals.sp, signals.out, signals.mode, settings=settings
    )
    columns = {
        PV_TAG: signals.pv,
        SP_TAG: signals.sp,
        OUT_TAG: signals.out,
        MODE_TAG: signals.mode,
    }
    readiness = check_readiness(t_s, columns, [tags])
    non_ok = tuple(chk.name for chk in readiness.checks if chk.status in ("warn", "fail"))

    return VariantOutcome(
        seed=seed,
        variant=variant_label,
        classification=report.classification,
        harris_index=float(report.harris_index),
        service_factor=float(report.service_factor),
        mode_changes=int(report.mode_changes),
        non_ok_checks=non_ok,
        has_regularity_issue=_check_regularity_names(non_ok),
        longest_auto_stretch=_longest_auto_stretch(signals.mode),
    )


def _build_flip_events(flip_count: int) -> tuple[ModeFlip, ...]:
    """Calculate evenly spaced mode flip events across the simulation window."""
    flips: list[ModeFlip] = []
    for i in range(flip_count):
        # Formula: flip i starts at (i + 1) * DURATION / (n + 1) - 300 s
        start_s = (i + 1) * DURATION_S / (flip_count + 1) - HALF_FLIP_DURATION_S
        flips.append(ModeFlip(start_s=start_s, duration_s=FLIP_DURATION_S))
    return tuple(flips)


def _evaluate_flips(seed: int, base_scenario: Scenario) -> dict[int, VariantOutcome]:
    """Simulate and evaluate all mode flip variants for one seed."""
    results: dict[int, VariantOutcome] = {}
    n_steps = int(round(DURATION_S / DT_S))
    nominal_t_s = np.arange(n_steps, dtype=np.float64) * DT_S

    for count in MODE_FLIP_COUNTS:
        flips = _build_flip_events(count)
        events = mode_flip_events(MODE_TAG, flips)
        flip_scenario = dataclasses.replace(base_scenario, events=events)
        signals = _simulate_loop(flip_scenario, seed)
        results[count] = _run_diagnostics(nominal_t_s, signals, seed, f"flip_{count}")
    return results


def _evaluate_jitters(
    seed: int, signals: SimulationSignals, nominal_ts_ns: np.ndarray
) -> dict[float, VariantOutcome]:
    """Apply timestamp jitter variations and evaluate monitoring diagnostics."""
    results: dict[float, VariantOutcome] = {}
    for sigma in JITTER_SIGMAS_S:
        jittered_ns = jitter_timestamps(nominal_ts_ns, sigma, seed)
        jittered_t_s = jittered_ns.astype(np.float64) / NS_PER_S
        results[sigma] = _run_diagnostics(jittered_t_s, signals, seed, f"jitter_{sigma}")
    return results


def run_seed_task(seed: int) -> SeedBatchResult:
    """Execute baseline and all fault variations for a single random seed."""
    base_scenario = build_scenario("mill_circuit", "nominal", duration_s=DURATION_S)
    nominal_signals = _simulate_loop(base_scenario, seed)
    nominal_ts_ns = _build_nominal_timestamps(nominal_signals.pv.size)
    nominal_t_s = nominal_ts_ns.astype(np.float64) / NS_PER_S

    baseline = _run_diagnostics(nominal_t_s, nominal_signals, seed, "baseline")
    jitter_map = _evaluate_jitters(seed, nominal_signals, nominal_ts_ns)
    flip_map = _evaluate_flips(seed, base_scenario)

    return SeedBatchResult(
        seed=seed,
        baseline=baseline,
        jitter_results=jitter_map,
        flip_results=flip_map,
    )


def _format_checks(checks: tuple[str, ...]) -> str:
    """Format non-ok check names as a clean comma-separated list or none indicator."""
    return ", ".join(checks) if checks else "none"


def _format_table_row(res: VariantOutcome) -> str:
    """Format an individual run outcome into a markdown table row."""
    harris_str = f"{res.harris_index:.4f}" if math.isfinite(res.harris_index) else "NaN"
    checks_str = _format_checks(res.non_ok_checks)
    return (
        f"| {res.seed} | {res.classification} | {harris_str} | "
        f"{res.service_factor:.4f} | {res.mode_changes} | {len(res.non_ok_checks)} | {checks_str} |"
    )


def _table_header() -> list[str]:
    """Return standard headers for metrics markdown tables."""
    return [
        "| Seed | Classification | Harris Index | Service Factor | Mode Changes | "
        "Non-OK Count | Non-OK Check Names |",
        "|---|---|---|---|---|---|---|",
    ]


def _build_variant_table(title: str, results: list[VariantOutcome]) -> list[str]:
    """Build a titled markdown table from a sequence of variant outcomes."""
    lines = [f"### {title}", "", *_table_header()]
    for res in sorted(results, key=lambda r: r.seed):
        lines.append(_format_table_row(res))
    lines.append("")
    return lines


def _eval_j1_seed(base: VariantOutcome, j_res: VariantOutcome) -> bool:
    """Check J1 acceptance for one seed: class equal and Harris change <= 20%."""
    if j_res.classification != base.classification:
        return False
    if not math.isfinite(base.harris_index) or base.harris_index == 0.0:
        return False
    if not math.isfinite(j_res.harris_index):
        return False
    relative_change = abs(j_res.harris_index - base.harris_index) / abs(base.harris_index)
    return relative_change <= HARRIS_REL_TOLERANCE


def _eval_m1_seed(base: VariantOutcome, f_res: VariantOutcome, flips: int) -> bool:
    """Check M1 target for one seed and flip count configuration."""
    if f_res.mode_changes != 2 * flips:
        return False
    expected_drop = flips * FLIP_DURATION_S / DURATION_S
    measured_drop = base.service_factor - f_res.service_factor
    if abs(measured_drop - expected_drop) > SERVICE_TOLERANCE:
        return False
    if flips in (1, 3) and f_res.classification != base.classification:
        return False
    # Harris index must be finite whenever AUTO stretch >= min_segment_samples (120)
    tags = LoopTags(
        name=LOOP_NAME,
        pv=PV_TAG,
        sp=SP_TAG,
        out=OUT_TAG,
        mode=MODE_TAG,
        unit="",
        eng_min=None,
        eng_max=None,
    )
    min_segment = default_settings(tags).min_segment_samples
    if f_res.longest_auto_stretch >= min_segment and not math.isfinite(f_res.harris_index):
        return False
    return True


def _compute_targets(batch: list[SeedBatchResult]) -> list[str]:
    """Evaluate acceptance targets J1, J2, J3, and M1 against frozen criteria."""
    # J1: sigma 0.2 s
    j1_passes = sum(
        1 for b in batch if _eval_j1_seed(b.baseline, b.jitter_results[0.2])
    )
    j1_status = "PASS" if j1_passes >= REQUIRED_PASSING_SEEDS else "FAIL"

    # J2: sigma 1.0 s and 3.0 s regularity check
    j2_passes = sum(
        1
        for b in batch
        if b.jitter_results[1.0].has_regularity_issue and b.jitter_results[3.0].has_regularity_issue
    )
    j2_status = "PASS" if j2_passes >= REQUIRED_PASSING_SEEDS else "FAIL"

    # J3: large jitter info count
    diff_class = sum(
        1 for b in batch if b.jitter_results[3.0].classification != b.baseline.classification
    )

    # M1: all seeds must satisfy flip constraints across 1, 3, and 6 flips
    m1_seeds_ok = sum(
        1 for b in batch if all(_eval_m1_seed(b.baseline, b.flip_results[n], n) for n in (1, 3, 6))
    )
    m1_status = "PASS" if m1_seeds_ok == TOTAL_SEEDS else "FAIL"

    return [
        "## Targets",
        "",
        f"- **J1 (small jitter, sigma 0.2 s)**: **{j1_status}** ({j1_passes}/{TOTAL_SEEDS} "
        f"seeds matched baseline classification and Harris index within 20%)",
        f"- **J2 (readiness)**: **{j2_status}** ({j2_passes}/{TOTAL_SEEDS} seeds raised "
        f"sampling regularity warnings at sigma 1.0 s and 3.0 s)",
        f"- **J3 (large jitter, sigma 3 s)**: **INFO** (No crashes; {diff_class}/{TOTAL_SEEDS} "
        f"seeds differed in classification from baseline)",
        f"- **M1 (mode flips)**: **{m1_status}** ({m1_seeds_ok}/{TOTAL_SEEDS} seeds satisfied "
        f"mode change counts, service drop within 0.02, finite Harris, and classification)",
        "",
    ]


def _build_markdown_report(batch: list[SeedBatchResult]) -> str:
    """Format complete experimental metrics into a structured markdown report."""
    lines = [
        "# Experiment 05: Timing Faults and Mode Flips Results",
        "",
        "Evaluation of timestamp jitter and manual mode flips on mill circuit feed loop.",
        "",
        "## Metrics Tables",
        "",
    ]
    lines.extend(_build_variant_table("Baseline (Nominal)", [b.baseline for b in batch]))
    for sigma in JITTER_SIGMAS_S:
        lines.extend(
            _build_variant_table(
                f"Jitter Sigma = {sigma} s", [b.jitter_results[sigma] for b in batch]
            )
        )
    for count in MODE_FLIP_COUNTS:
        lines.extend(
            _build_variant_table(
                f"Mode Flips n = {count} (10 min each)", [b.flip_results[count] for b in batch]
            )
        )
    lines.extend(_compute_targets(batch))
    return "\n".join(lines)


def main() -> None:
    """Coordinate multi-seed fault injection experiments and write markdown report."""
    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(run_seed_task, seed) for seed in SEEDS]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]

    results.sort(key=lambda b: b.seed)
    report_md = _build_markdown_report(results)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(report_md, encoding="utf-8")
    print(f"Results successfully written to: {RESULTS_PATH.resolve()}")


if __name__ == "__main__":
    main()

"""Experiment exp08: cascade tuning order and time-scale separation.

Runs the plan_cascade tuning on a simulated two-loop series cascade for several
separation ratios sigma = tau_c_outer / tau_c_inner, checks the acceptance targets
C1, C2, C3 frozen in the README, and writes the report to results/results.md.

The simulation helpers live in the sibling module exp08_sim; this file only
orchestrates them and turns their numbers into a readable report.
"""

from __future__ import annotations

import concurrent.futures
import statistics
from dataclasses import dataclass
from pathlib import Path

import exp08_sim as sim
from crosscut_loops.cascade import CascadePlan, plan_cascade
from crosscut_loops.tuning_rules import FopdtModel, PiSettings, simc_pi

# Seeds of the stochastic identification and simulation runs (README: 5 seeds).
SEEDS = (1, 2, 3, 4, 5)

# Separation ratios reported per seed: the README targets use 10 and 4, C3 also asks
# for 1 and 2 so the effect of too little separation becomes visible.
SIGMA_VALUES = (1.0, 2.0, 4.0, 10.0)

# Separation used in the README targets C1 and C2.
TARGET_SIGMA = 10.0
MIN_TARGET_SIGMA = 4.0

# C1: allowed overshoot of the outer setpoint response, in percent of the step.
MAX_OVERSHOOT_PCT = 20.0

# C2: cascade d2 IAE must be at most this fraction of the single-loop d2 IAE.
MAX_IAE_RATIO = 0.5

# The inner loop is tuned with SIMC tau_c = its own effective delay (cascade.py).
# The plan_cascade call below repeats that rule, so the numbers agree.
PLAN_SEPARATION = 10.0

# ProcessPoolExecutor worker count; the machine has four idle cores for this run.
MAX_WORKERS = 4

# Path constants for the report, relative to this script.
RESULTS_DIR = Path(__file__).parent / "results"
REPORT_PATH = RESULTS_DIR / "results.md"


@dataclass(frozen=True)
class SigmaResult:
    """One sigma value evaluated for one seed.

    Attributes:
        sigma: Requested ratio tau_c_outer / tau_c_inner.
        overshoot_pct: Overshoot of the cascade setpoint response, in percent.
        settled: Whether the cascade setpoint response settled within the tolerance.
        setpoint_iae: Integral absolute error of the setpoint step, in K*s.
        disturbance_iae: Integral absolute error of the d2 disturbance step, in K*s.
    """

    sigma: float
    overshoot_pct: float
    settled: bool
    setpoint_iae: float
    disturbance_iae: float


@dataclass(frozen=True)
class PlannedResult:
    """What ``plan_cascade`` produces for one requested separation, simulated as shipped.

    Attributes:
        requested: Separation passed to ``plan_cascade``.
        achieved: Separation the plan really has (the outer delay can raise tau_c_outer).
        overshoot_pct: Overshoot of the cascade setpoint response with the planned settings.
        settled: Whether that response settled.
        disturbance_iae: IAE of the d2 step with the planned settings, in K*s.
    """

    requested: float
    achieved: float
    overshoot_pct: float
    settled: bool
    disturbance_iae: float


@dataclass(frozen=True)
class SeedResult:
    """Everything one seed produced, or the reason it failed.

    Attributes:
        seed: Seed of the run.
        sigmas: One SigmaResult per requested sigma, empty when the seed failed.
        baseline_iae: Single-loop d2 IAE for the same seed, in K*s.
        plan: plan_cascade output for this seed, None when the seed failed.
        error: Message of the ValueError that aborted the seed, empty on success.
    """

    seed: int
    sigmas: tuple[SigmaResult, ...]
    baseline_iae: float
    plan: CascadePlan | None
    error: str
    planned: tuple[PlannedResult, ...] = ()

    @property
    def is_valid(self) -> bool:
        """Return True when the seed produced usable numbers."""
        return self.error == ""


def _tune_inner(seed: int) -> tuple[FopdtModel, PiSettings]:
    """Identify the inner process and tune the inner loop with SIMC.

    Returns:
        The identified inner model and its PI settings, with tau_c = inner delay.
    """
    inner_model = sim.identify_inner(seed)
    inner_settings = simc_pi(inner_model, tau_c_s=inner_model.delay_s)
    return inner_model, inner_settings


def _evaluate_sigma(
    sigma: float,
    inner_delay_s: float,
    outer_model: FopdtModel,
    inner_settings: PiSettings,
    seed: int,
) -> SigmaResult:
    """Tune the outer loop for one sigma and simulate both responses.

    Args:
        sigma: Requested ratio tau_c_outer / tau_c_inner.
        inner_delay_s: Inner effective delay, in seconds; sets tau_c_inner.
        outer_model: Outer process model identified with the inner loop closed.
        inner_settings: PI settings of the inner loop.
        seed: Seed of the simulation.

    Returns:
        The overshoot, settling flag and both IAEs of this sigma.
    """
    outer_settings = simc_pi(outer_model, tau_c_s=sigma * inner_delay_s)
    response = sim.cascade_setpoint_response(inner_settings, outer_settings, seed)
    disturbance_iae = sim.cascade_disturbance_iae(inner_settings, outer_settings, seed)
    return SigmaResult(
        sigma=sigma,
        overshoot_pct=response.overshoot_pct,
        settled=response.settled,
        setpoint_iae=response.iae,
        disturbance_iae=disturbance_iae,
    )


def _evaluate_plan(
    models: tuple[FopdtModel, FopdtModel],
    requested: float,
    seed: int,
) -> PlannedResult:
    """Simulate the settings ``plan_cascade`` itself chooses for a requested separation."""
    inner_model, outer_model = models
    plan = plan_cascade(inner_model, outer_model, separation=requested)
    response = sim.cascade_setpoint_response(plan.inner, plan.outer, seed)
    disturbance_iae = sim.cascade_disturbance_iae(plan.inner, plan.outer, seed)
    return PlannedResult(
        requested, plan.separation, response.overshoot_pct, response.settled, disturbance_iae
    )


def run_seed(seed: int) -> SeedResult:
    """Run the full cascade experiment for one seed.

    A ValueError from the identification or the tuning rules marks the seed as
    failed: the message is kept instead of being swallowed, so the report can
    count the loss.

    Args:
        seed: Seed for identification and simulation.

    Returns:
        A SeedResult, either with all sigma results or with the error message.
    """
    try:
        inner_model, inner_settings = _tune_inner(seed)
        outer_model = sim.identify_outer_with_inner_closed(inner_settings, seed)
        results = tuple(
            _evaluate_sigma(sigma, inner_model.delay_s, outer_model, inner_settings, seed)
            for sigma in SIGMA_VALUES
        )
        baseline_model = sim.identify_outer_open(seed)
        baseline_settings = simc_pi(baseline_model, tau_c_s=baseline_model.delay_s)
        baseline_iae = sim.single_loop_disturbance_iae(baseline_settings, seed)
        plan = plan_cascade(inner_model, outer_model, separation=PLAN_SEPARATION)
        planned = tuple(
            _evaluate_plan((inner_model, outer_model), sigma, seed) for sigma in SIGMA_VALUES
        )
    except ValueError as error:
        return SeedResult(seed, (), 0.0, None, str(error))
    return SeedResult(seed, results, baseline_iae, plan, "", planned)


def run_all_seeds() -> list[SeedResult]:
    """Run every seed in parallel and return the results ordered by seed.

    Returns:
        One SeedResult per seed in SEEDS, in seed order.
    """
    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(run_seed, SEEDS))
    return sorted(results, key=lambda result: result.seed)


def _valid_seeds(results: list[SeedResult]) -> list[SeedResult]:
    """Return only the seeds that finished without a ValueError."""
    return [result for result in results if result.is_valid]


def _sigma_values_of(results: list[SeedResult]) -> dict[float, list[SigmaResult]]:
    """Group the per-sigma results of all valid seeds by sigma value."""
    grouped: dict[float, list[SigmaResult]] = {sigma: [] for sigma in SIGMA_VALUES}
    for result in _valid_seeds(results):
        for sigma_result in result.sigmas:
            grouped[sigma_result.sigma].append(sigma_result)
    return grouped


def _median_background(values: list[float]) -> float:
    """Return the median, or nan for an empty list so the report stays readable."""
    return statistics.median(values) if values else float("nan")


def _seed_table(results: list[SeedResult]) -> list[str]:
    """Render the per-seed table (one row per seed and sigma)."""
    lines = [
        "| seed | sigma | overshoot % | settled | IAE setpoint | IAE disturbance |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        if not result.is_valid:
            lines.append(f"| {result.seed} | failed | | | | {result.error} |")
            continue
        for sigma_result in result.sigmas:
            lines.append(
                f"| {result.seed} | {sigma_result.sigma:g} | {sigma_result.overshoot_pct:.2f} "
                f"| {sigma_result.settled} | {sigma_result.setpoint_iae:.3f} "
                f"| {sigma_result.disturbance_iae:.3f} |"
            )
    return lines


def _sigma_summary_table(results: list[SeedResult]) -> list[str]:
    """Render the per-sigma summary table over all valid seeds."""
    grouped = _sigma_values_of(results)
    lines = [
        "| sigma | median overshoot % | median IAE setpoint | median IAE disturbance "
        "| settled (out of valid) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for sigma in SIGMA_VALUES:
        block = grouped[sigma]
        settled_count = sum(1 for item in block if item.settled)
        lines.append(
            f"| {sigma:g} | {_median_background([i.overshoot_pct for i in block]):.2f} "
            f"| {_median_background([i.setpoint_iae for i in block]):.3f} "
            f"| {_median_background([i.disturbance_iae for i in block]):.3f} "
            f"| {settled_count}/{len(block)} |"
        )
    return lines


def _target_c1(results: list[SeedResult]) -> str:
    """Judge target C1: overshoot and settling at sigma 10 and sigma 4."""
    grouped = _sigma_values_of(results)
    failures: list[str] = []
    for sigma in (TARGET_SIGMA, MIN_TARGET_SIGMA):
        block = grouped[sigma]
        overshoot_fail = [i for i in block if i.overshoot_pct > MAX_OVERSHOOT_PCT]
        unsettled = [i for i in block if not i.settled]
        if overshoot_fail or unsettled:
            failures.append(
                f"sigma={sigma:g}: {len(overshoot_fail)} overshoot, {len(unsettled)} unsettled"
            )
    if not _valid_seeds(results):
        return "- C1: NOT MET - no valid seed to judge."
    if failures:
        return "- C1: NOT MET - " + "; ".join(failures) + "."
    return "- C1: MET - overshoot <= 20 % and settled in all valid seeds for sigma 10 and 4."


def _target_c2(results: list[SeedResult]) -> str:
    """Judge target C2: cascade d2 IAE at sigma 10 against the single-loop baseline."""
    grouped = _sigma_values_of(results)[TARGET_SIGMA]
    cascade_iae = _median_background([i.disturbance_iae for i in grouped])
    baseline_iae = _median_background([r.baseline_iae for r in _valid_seeds(results)])
    if not grouped or not _valid_seeds(results):
        return "- C2: NOT MET - no valid seed to judge."
    limit = MAX_IAE_RATIO * baseline_iae
    if cascade_iae <= limit:
        return (
            f"- C2: MET - median cascade IAE {cascade_iae:.3f} <= "
            f"{MAX_IAE_RATIO:g} x baseline {baseline_iae:.3f} = {limit:.3f}."
        )
    return (
        f"- C2: NOT MET - median cascade IAE {cascade_iae:.3f} > "
        f"{MAX_IAE_RATIO:g} x baseline {baseline_iae:.3f} = {limit:.3f}."
    )


def _plan_lines(results: list[SeedResult]) -> list[str]:
    """Render the plan_cascade output of the first valid seed."""
    for result in _valid_seeds(results):
        if result.plan is not None:
            plan = result.plan
            warning_text = "; ".join(plan.warnings) if plan.warnings else "none"
            return [
                f"- seed: {result.seed}",
                f"- tau_c_inner = {plan.tau_c_inner_s:.3f} s, "
                f"tau_c_outer = {plan.tau_c_outer_s:.3f} s",
                f"- achieved separation sigma = {plan.separation:.3f}",
                f"- warnings: {warning_text}",
            ]
    return ["- no valid seed: plan_cascade produced no result."]


def _planned_table(results: list[SeedResult]) -> list[str]:
    """Per-sigma medians of the settings ``plan_cascade`` itself chooses."""
    lines = [
        "| requested sigma | achieved sigma (median) | median overshoot % | "
        "median IAE disturbance | settled |",
        "| --- | --- | --- | --- | --- |",
    ]
    valid = _valid_seeds(results)
    for index, sigma in enumerate(SIGMA_VALUES):
        rows = [result.planned[index] for result in valid if result.planned]
        if not rows:
            continue
        lines.append(
            f"| {sigma:g} | {_median_background([r.achieved for r in rows]):.2f} "
            f"| {_median_background([r.overshoot_pct for r in rows]):.2f} "
            f"| {_median_background([r.disturbance_iae for r in rows]):.3f} "
            f"| {sum(r.settled for r in rows)}/{len(rows)} |"
        )
    return lines


def _failed_seed_lines(results: list[SeedResult]) -> list[str]:
    """List the seeds that raised a ValueError and the message they carried."""
    failed = [result for result in results if not result.is_valid]
    if not failed:
        return ["- none, all seeds completed."]
    return [f"- seed {result.seed}: {result.error}" for result in failed]


def build_report(results: list[SeedResult]) -> str:
    """Assemble the full markdown report for the experiment.

    Args:
        results: The per-seed results returned by run_all_seeds.

    Returns:
        The report text, ready to be written to results/results.md.
    """
    valid_count = len(_valid_seeds(results))
    baseline_iae = _median_background([r.baseline_iae for r in _valid_seeds(results)])
    sections = [
        "# exp08: cascade tuning order and time-scale separation",
        "",
        f"Seeds run: {len(SEEDS)}, valid: {valid_count}, failed: {len(SEEDS) - valid_count}.",
        "",
        "## Per-seed results",
        "",
        *_seed_table(results),
        "",
        "## Per-sigma summary",
        "",
        *_sigma_summary_table(results),
        "",
        f"Baseline (single outer SIMC PI loop) median d2 IAE: {baseline_iae:.3f}.",
        "",
        "## plan_cascade (seed 1 when available)",
        "",
        *_plan_lines(results),
        "",
        "## plan_cascade as shipped (informational)",
        "",
        "The per-sigma table above tunes tau_c_outer = sigma x tau_c_inner directly. The planner",
        "never goes below the outer loop's own delay, so for a small requested sigma it gives a",
        "larger achieved sigma. Below: the planner's own settings, simulated.",
        "",
        *_planned_table(results),
        "",
        "## Failed seeds",
        "",
        *_failed_seed_lines(results),
        "",
        "## Targets",
        "",
        _target_c1(results),
        _target_c2(results),
        "- C3 (informational): see the per-sigma summary table for sigma = 1, 2, 4, 10.",
        "",
    ]
    return "\n".join(sections)


def write_report(report_text: str) -> Path:
    """Write the report next to this script and return the path."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    return REPORT_PATH


def main() -> None:
    """Run the experiment, write results/results.md and print its path."""
    results = run_all_seeds()
    report_path = write_report(build_report(results))
    print(report_path)


if __name__ == "__main__":
    main()

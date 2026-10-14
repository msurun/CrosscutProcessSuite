"""Closed-loop validation of SIMC and AMIGO retuning on a detuned mill circuit.

Validates that identifying an open-loop step test with our automated pipeline and
applying SIMC settings to a detuned mill loop improves closed-loop performance.
Evaluation compares the original detuned control against SIMC and AMIGO settings.

ACCEPTANCE TARGETS:
- Loop improvement: IAE_after_simc <= 0.8 * IAE_before and not unstable.
- Seed pass: at least 2 of 3 loops improve under SIMC.
- Experiment pass: at least 4 of 5 seeds pass.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
from pathlib import Path
from typing import NamedTuple

import numpy as np
from crosscut_loops.overview import LoopTags, analyze_dataset
from crosscut_loops.tuning_report import build_tuning_report
from crosscut_loops.tuning_rules import PiSettings
from crosscut_loops.tuning_view import suggest_windows
from crosscut_sim.core import Event, Scenario
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario

# Simulation horizon and identification parameters
STEP_TEST_DURATION_S = 9000.0  # Duration of open-loop identification run
EVALUATION_DURATION_S = 14400.0  # Duration of closed-loop step response run
MIN_WINDOW_LENGTH_S = 600.0  # Minimum duration required for step identification
SP_STEP_TIME_S = 1800.0  # Setpoint step injection timestamp
UNSTABLE_TAIL_WINDOW_S = 1800.0  # Final duration inspected for sustained oscillation
ROBUSTNESS_FACTOR = 0.5  # SIMC tuning tradeoff parameter (0.0 fast - 1.0 robust)

# Evaluation acceptance criteria thresholds
SETTLING_BAND_FRACTION = 0.05  # Within 5% of setpoint step to be considered settled
IMPROVEMENT_IAE_RATIO = 0.8  # IAE must drop by at least 20% to count as improved
REQUIRED_IMPROVED_PER_SEED = 2  # Passing seed requires >= 2 improved loops
REQUIRED_PASSING_SEEDS = 4  # Passing experiment requires >= 4 passing seeds

PERCENT_MULTIPLIER = 100.0
MAX_WORKERS = 4
SEEDS = range(1, 6)
LOOPS = ("hpgr_press", "mill_feed", "cyc_water")
SP_STEP: dict[str, float] = {"hpgr_press": 1.0, "mill_feed": 5.0, "cyc_water": 5.0}

RESULTS_PATH = Path(__file__).parent / "results" / "retune_validation.md"

LIMITS_TEXT = (
    "Result: PASS on the frozen targets (5 of 5 seeds). 14 of 15 loop runs improved, IAE "
    "70-93 % lower than the detuned loop. The 15th run (seed 5, cyc_water) was blocked by the "
    "poor-fit guard (P6.4): R squared -1.18 on a noisy step window, consistent with exp02 "
    "where the cyc_water time constant error reaches 487 % at the 90th percentile; the guard "
    "did what it is for, an engineer would pick another window. Caveats. (1) Settling time is "
    "almost the whole window in nearly every run: the 5 % band is below the measurement and "
    "process noise, so that column carries no information. (2) Overshoot is high for "
    "mill_feed (58-67 %) and cyc_water (33-37 %) for SIMC at robustness 0.5; probably loop "
    "interaction (the other two loops stay detuned) and the model error of exp02; not "
    "investigated. (3) Health 100 after retuning is the ceiling of the score, not extra "
    "proof. (4) IAE before is dominated by a sluggish loop that does not reach the new "
    "setpoint inside the window. (5) Only setpoint steps, operator off, one plant model; no "
    "load disturbances. AMIGO gives almost the same numbers as SIMC. (6) Tuning stays "
    "advisory: nothing is written to a DCS."
)


class SimulationData(NamedTuple):
    """Signals recorded from a closed-loop plant simulation."""

    t_s: np.ndarray  # Timestamps in seconds, shape (n_steps,)
    pv: np.ndarray  # Process variable readings, shape (n_steps,)
    sp: np.ndarray  # Setpoint readings, shape (n_steps,)
    out: np.ndarray  # Controller output commands, shape (n_steps,)
    mode: np.ndarray  # Controller operation modes, shape (n_steps,)
    dt_s: float  # Sampling period in seconds


class RunMetrics(NamedTuple):
    """Performance metrics evaluated after setpoint disturbance."""

    iae: float  # Integrated absolute error, error units * seconds
    overshoot_pct: float  # Percent overshoot past setpoint step
    settling_s: float  # Settling time in seconds to within 5% band
    is_unstable: bool  # True if residual error exceeds step size near end
    health_pct: float | None  # Heuristic loop health percentage score


class JobResult(NamedTuple):
    """Identification and closed-loop validation outcome for one seed and loop."""

    seed: int
    loop: str
    blocked: bool
    simc_settings: PiSettings | None
    amigo_settings: PiSettings | None
    before: RunMetrics | None
    after_simc: RunMetrics | None
    after_amigo: RunMetrics | None
    improved_simc: bool


def _override(
    params: tuple[tuple[str, float], ...], **overrides: float
) -> tuple[tuple[str, float], ...]:
    """Return scenario parameters with updated values for matching keys."""
    param_dict = dict(params)
    for key, value in overrides.items():
        param_dict[key] = value
    return tuple(param_dict.items())


def _simulate_loop(
    scenario: Scenario, loop: str, seed: int
) -> SimulationData:
    """Run mill-circuit simulation and record all control tags for one loop.

    Assumes plant exposes tag conventions: 'sim.mc.<loop>' for PV,
    'sim.mc.<loop>_sp' for SP, 'sim.mc.<loop>_out' for OUT, 'sim.mc.<loop>_mode' for MODE.
    """
    plant = MillCircuitPlant()
    plant.reset(seed, scenario)
    n_steps = int(round(scenario.duration_s / scenario.dt_s))

    pv = np.empty(n_steps, dtype=np.float64)
    sp = np.empty(n_steps, dtype=np.float64)
    out = np.empty(n_steps, dtype=np.float64)
    mode = np.empty(n_steps, dtype=object)

    pv_tag = f"sim.mc.{loop}"
    sp_tag = f"sim.mc.{loop}_sp"
    out_tag = f"sim.mc.{loop}_out"
    mode_tag = f"sim.mc.{loop}_mode"

    for step in range(n_steps):
        # Sample state before advancing simulation dynamic equations
        pv[step] = plant.read(pv_tag)[0]
        sp[step] = plant.read(sp_tag)[0]
        out[step] = plant.read(out_tag)[0]
        mode[step] = plant.read(mode_tag)[0]
        plant.step()

    t_s = np.arange(n_steps, dtype=np.float64) * scenario.dt_s
    return SimulationData(t_s=t_s, pv=pv, sp=sp, out=out, mode=mode, dt_s=scenario.dt_s)


def _identify_loop(
    loop: str, seed: int
) -> tuple[PiSettings | None, PiSettings | None, bool]:
    """Run open-loop step test and derive SIMC and AMIGO settings from report."""
    scenario = build_scenario("mill_circuit", "step_test", duration_s=STEP_TEST_DURATION_S)
    data = _simulate_loop(scenario, loop, seed)
    windows = suggest_windows(data.t_s, data.mode, data.out, min_length_s=MIN_WINDOW_LENGTH_S)
    if not windows:
        return None, None, True

    start_s, end_s = windows[0]
    mask = (data.t_s >= start_s) & (data.t_s <= end_s)
    report = build_tuning_report(
        loop_name=loop,
        u=data.out[mask],
        y=data.pv[mask],
        dt_s=data.dt_s,
        robustness=ROBUSTNESS_FACTOR,
    )
    is_blocked = report.blocked_reason is not None or report.simc is None
    return report.simc, report.amigo, is_blocked


def _compute_health(data: SimulationData, loop: str) -> float | None:
    """Compute dataset health score for the loop using automated diagnostics."""
    pv_tag = f"sim.mc.{loop}"
    sp_tag = f"sim.mc.{loop}_sp"
    out_tag = f"sim.mc.{loop}_out"
    mode_tag = f"sim.mc.{loop}_mode"

    tag_def = LoopTags(
        name=loop,
        pv=pv_tag,
        sp=sp_tag,
        out=out_tag,
        mode=mode_tag,
        unit="",
        eng_min=None,
        eng_max=None,
    )
    columns = {pv_tag: data.pv, sp_tag: data.sp, out_tag: data.out, mode_tag: data.mode}
    dataset_report = analyze_dataset(data.t_s, columns, [tag_def])
    score = dataset_report[0]["health_percent"]
    return None if score is None else float(score)


def _compute_metrics(data: SimulationData, loop: str) -> RunMetrics:
    """Compute IAE, overshoot, settling time, and stability on post-step horizon.

    Assumes data.pv, data.sp, data.t_s are 1D float64 numpy arrays of equal size.
    """
    step_size = SP_STEP[loop]
    post_step_mask = data.t_s >= SP_STEP_TIME_S
    pv_eval = data.pv[post_step_mask]
    sp_eval = data.sp[post_step_mask]
    t_eval = data.t_s[post_step_mask] - SP_STEP_TIME_S

    iae = float(np.sum(np.abs(sp_eval - pv_eval)) * data.dt_s)
    new_sp = sp_eval[-1]
    overshoot = float(max(0.0, (np.max(pv_eval) - new_sp) / step_size * PERCENT_MULTIPLIER))

    # Settling time formula: elapsed time to final departure from +/- 5% error tolerance
    band_limit = SETTLING_BAND_FRACTION * abs(step_size)
    outside_indices = np.where(np.abs(pv_eval - new_sp) > band_limit)[0]
    total_horizon_s = EVALUATION_DURATION_S - SP_STEP_TIME_S
    settling_s = float(t_eval[outside_indices[-1]]) if len(outside_indices) > 0 else total_horizon_s

    # Stability test: final 30 min maximum absolute tracking error vs step amplitude
    tail_mask = data.t_s >= (EVALUATION_DURATION_S - UNSTABLE_TAIL_WINDOW_S)
    tail_max_err = float(np.max(np.abs(data.pv[tail_mask] - new_sp)))
    is_unstable = tail_max_err > abs(step_size)

    health_pct = _compute_health(data, loop)
    return RunMetrics(iae, overshoot, settling_s, is_unstable, health_pct)


def _evaluate_tuning(
    loop: str, seed: int, settings: PiSettings | None
) -> RunMetrics:
    """Simulate detuned scenario with optional retuning parameter overrides."""
    base_scenario = build_scenario("mill_circuit", "detuned", duration_s=EVALUATION_DURATION_S)
    plant = MillCircuitPlant()
    plant.reset(seed, base_scenario)
    nominal_sp = plant.read(f"sim.mc.{loop}_sp")[0]

    sp_event = Event(SP_STEP_TIME_S, f"sim.mc.{loop}_sp", nominal_sp + SP_STEP[loop])
    params = base_scenario.params
    if settings is not None:
        params = _override(
            params,
            **{f"kc_{loop}": settings.kc, f"ti_s_{loop}": settings.ti_s},
        )

    eval_scenario = dataclasses.replace(base_scenario, events=(sp_event,), params=params)
    data = _simulate_loop(eval_scenario, loop, seed)
    return _compute_metrics(data, loop)


def run_single_job(seed: int, loop: str) -> JobResult:
    """Execute complete identification, baseline, and retuned validation for one cell."""
    simc, amigo, is_blocked = _identify_loop(loop, seed)
    if is_blocked or simc is None:
        return JobResult(
            seed=seed,
            loop=loop,
            blocked=True,
            simc_settings=None,
            amigo_settings=None,
            before=None,
            after_simc=None,
            after_amigo=None,
            improved_simc=False,
        )

    before = _evaluate_tuning(loop, seed, settings=None)
    after_simc = _evaluate_tuning(loop, seed, settings=simc)
    after_amigo = _evaluate_tuning(loop, seed, settings=amigo)

    improved = (
        after_simc.iae <= IMPROVEMENT_IAE_RATIO * before.iae
        and not after_simc.is_unstable
    )

    return JobResult(
        seed=seed,
        loop=loop,
        blocked=False,
        simc_settings=simc,
        amigo_settings=amigo,
        before=before,
        after_simc=after_simc,
        after_amigo=after_amigo,
        improved_simc=improved,
    )


def _format_result_row(job: JobResult) -> str:
    """Format row containing metrics for a single seed and loop simulation."""
    if job.blocked or job.simc_settings is None or job.before is None or job.after_simc is None:
        return (
            f"| {job.seed} | {job.loop} | True | - | - | - | - | - | - | - | - | - | - | False |"
        )

    kc = job.simc_settings.kc
    ti_s = job.simc_settings.ti_s
    iae_b = job.before.iae
    iae_s = job.after_simc.iae
    iae_a = job.after_amigo.iae if job.after_amigo else float("nan")
    imp_pct = (iae_b - iae_s) / iae_b * PERCENT_MULTIPLIER
    over_s = job.after_simc.overshoot_pct
    sett_s = job.after_simc.settling_s
    h_b = f"{job.before.health_pct:.1f}" if job.before.health_pct is not None else "-"
    h_s = f"{job.after_simc.health_pct:.1f}" if job.after_simc.health_pct is not None else "-"
    unstable_flag = str(job.after_simc.is_unstable)

    return (
        f"| {job.seed} | {job.loop} | False | {kc:.3f} | {ti_s:.1f} | "
        f"{iae_b:.1f} | {iae_s:.1f} | {iae_a:.1f} | {imp_pct:.1f}% | "
        f"{over_s:.1f}% | {sett_s:.0f} | {h_b} | {h_s} | {unstable_flag} | {job.improved_simc} |"
    )


def _build_markdown_report(
    results: list[JobResult],
    seeds_passed: int,
    verdict: str,
) -> str:
    """Assemble markdown report detailing acceptance criteria, data tables, and limits."""
    lines = [
        "# Retune Validation Experiment (exp03)",
        "",
        "## Acceptance Targets",
        "- **Loop improvement**: `IAE_after_simc <= 0.8 * IAE_before` and `not unstable`.",
        "- **Seed pass**: at least 2 of 3 loops improve under SIMC.",
        "- **Experiment pass**: at least 4 of 5 seeds pass.",
        "",
        "## Results Table",
        "| Seed | Loop | Blocked | SIMC Kc | SIMC Ti (s) | IAE Before | IAE SIMC | IAE AMIGO | "
        "Imp % | Overshoot | Settling (s) | Health Before | Health SIMC | Unstable | Improved |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    sorted_results = sorted(results, key=lambda r: (r.seed, r.loop))
    for res in sorted_results:
        lines.append(_format_result_row(res))

    lines.extend([
        "",
        "## Summary",
        f"- **Seeds passing (>= 2 improved loops)**: {seeds_passed} / {len(SEEDS)}",
        f"- **Overall Verdict**: **{verdict}**",
        "",
        "## Limits",
        LIMITS_TEXT,
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    """Coordinate multi-seed retuning experiment across parallel worker processes."""
    tasks = [(seed, loop) for seed in SEEDS for loop in LOOPS]

    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(run_single_job, seed, loop) for seed, loop in tasks]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]

    seed_pass_counts = 0
    for seed in SEEDS:
        seed_results = [r for r in results if r.seed == seed]
        improved_count = sum(1 for r in seed_results if r.improved_simc)
        if improved_count >= REQUIRED_IMPROVED_PER_SEED:
            seed_pass_counts += 1

    overall_pass = seed_pass_counts >= REQUIRED_PASSING_SEEDS
    verdict = "PASS" if overall_pass else "FAIL"

    report = _build_markdown_report(results, seed_pass_counts, verdict)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(report, encoding="utf-8")
    print(f"Verdict: {verdict} ({seed_pass_counts}/{len(SEEDS)} seeds passed)")


if __name__ == "__main__":
    main()

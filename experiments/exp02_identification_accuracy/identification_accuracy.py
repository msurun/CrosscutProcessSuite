"""Evaluate accuracy of identify_fopdt against noise-free mill-circuit step tests.

We identify First-Order Plus Dead Time (FOPDT) models on simulated open-loop steps
across three plant loops ("hpgr_press", "mill_feed", "cyc_water") under low and full
noise. Parameter errors are compared against an undisturbed reference run.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
from pathlib import Path
from typing import NamedTuple

import numpy as np
from crosscut_loops.identification import identify_fopdt
from crosscut_loops.tuning_rules import FopdtModel
from crosscut_loops.tuning_view import suggest_windows
from crosscut_sim.core import Scenario
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import (
    MILL_LOOP_NAMES,
    STEP_TEST_FIRST_STEP_S,
    STEP_TEST_HOLD_S,
    STEP_TEST_SIZE_PCT,
    build_scenario,
)

LIMITS_TEXT = (
    "Reading (10 seeds per row, step size 8 % OUT, open loop). With low noise the identified "
    "gain is exact and the time constant is within about 1.5 %. With full noise the median "
    "gain error is 5-7 % (90th percentile up to 21 %) and the time constant error is 8-49 % "
    "at the median; its 90th percentile reaches 130-490 %, so one run in ten is unusable. The "
    "reference delay is one sample (1 s), so a relative delay error is not meaningful: 6000 % "
    "means about 60 s of absolute error. Treat the gain as usable at full noise, the time "
    "constant and the delay only with the fit check (R squared) next to them; averaging "
    "several steps would help and is not done here. Closed-loop data with the operator on is "
    "out of scope (see exp00)."
)

DURATION_S = 9000.0  # length of each step-test simulation
MAX_DELAY_S = 600.0  # maximum transport delay scanned during identification
MIN_WINDOW_LENGTH_S = 600.0  # shortest valid open-loop step window
WINDOW_BASELINE_S = 300.0  # steady-state duration before and after step for reference gain
SEEDS = range(1, 11)  # 10 random seeds per test cell
NOISE_LEVELS = ("low", "full")
LOOPS = ("hpgr_press", "mill_feed", "cyc_water")
MAX_WORKERS = 4  # parallel worker processes

LOW_MEASUREMENT_NOISE = 0.1
ZERO_NOISE = 0.0
PERCENT_MULTIPLIER = 100.0
REFERENCE_SEED = 1

RESULTS_PATH = Path(__file__).parent / "results" / "identification_accuracy.md"


class SimulationTrace(NamedTuple):
    """Signals recorded from a mill-circuit simulation run."""

    t_s: np.ndarray  # timestamps in seconds, shape (n_samples,)
    pv: np.ndarray  # process variable samples, shape (n_samples,)
    out: np.ndarray  # controller output samples, shape (n_samples,)
    mode: np.ndarray  # loop control mode (e.g. MAN/AUTO), shape (n_samples,)
    dt_s: float  # sampling period in seconds


class RunResult(NamedTuple):
    """Outcome of identifying one loop run."""

    loop: str
    noise: str
    seed: int
    status: str  # "ok", "no_window", or "failed"
    gain: float | None
    time_constant_s: float | None
    delay_s: float | None


class ReferenceMetrics(NamedTuple):
    """Reference FOPDT model and empirical gain from a noise-free run."""

    model: FopdtModel
    steady_state_gain: float


def _override(
    params: tuple[tuple[str, float], ...], **overrides: float
) -> tuple[tuple[str, float], ...]:
    """Return scenario parameters with updated values for the given keys."""
    known = dict(params)
    for key, value in overrides.items():
        known[key] = value
    return tuple(known.items())


def _build_test_scenario(noise: str) -> Scenario:
    """Return the step-test scenario configured for low or full noise."""
    scenario = build_scenario("mill_circuit", "step_test", duration_s=DURATION_S)
    if noise == "full":
        return scenario
    if noise == "low":
        updated_params = _override(
            scenario.params, inner_noise=ZERO_NOISE, process_noise=ZERO_NOISE
        )
        return dataclasses.replace(
            scenario, params=updated_params, measurement_noise=LOW_MEASUREMENT_NOISE
        )
    raise ValueError(f"Unknown noise level {noise!r}; expected one of {NOISE_LEVELS}")


def _build_reference_scenario() -> Scenario:
    """Return the completely noise-free step-test scenario for baseline metrics."""
    scenario = build_scenario("mill_circuit", "step_test", duration_s=DURATION_S)
    updated_params = _override(
        scenario.params,
        operator=ZERO_NOISE,
        inner_noise=ZERO_NOISE,
        process_noise=ZERO_NOISE,
        hardness_sigma=ZERO_NOISE,
        moisture_sigma=ZERO_NOISE,
    )
    return dataclasses.replace(scenario, params=updated_params, measurement_noise=ZERO_NOISE)


def _simulate_loop(scenario: Scenario, loop: str, seed: int) -> SimulationTrace:
    """Run the mill-circuit scenario and collect PV, OUT, and MODE arrays for a loop."""
    plant = MillCircuitPlant()
    plant.reset(seed, scenario)
    n_steps = int(round(scenario.duration_s / scenario.dt_s))

    pv = np.empty(n_steps, dtype=np.float64)
    out = np.empty(n_steps, dtype=np.float64)
    mode = np.empty(n_steps, dtype=object)

    pv_tag = f"sim.mc.{loop}"
    out_tag = f"sim.mc.{loop}_out"
    mode_tag = f"sim.mc.{loop}_mode"

    for step in range(n_steps):
        # Sample plant state prior to advancing dynamics
        pv[step] = plant.read(pv_tag)[0]
        out[step] = plant.read(out_tag)[0]
        mode[step] = plant.read(mode_tag)[0]
        plant.step()

    t_s = np.arange(n_steps, dtype=np.float64) * scenario.dt_s
    return SimulationTrace(t_s=t_s, pv=pv, out=out, mode=mode, dt_s=scenario.dt_s)


def _extract_active_window(
    trace: SimulationTrace,
) -> tuple[np.ndarray, tuple[float, float]] | None:
    """Find the primary open-loop step window for the loop and return slice masks."""
    windows = suggest_windows(
        trace.t_s, trace.mode, trace.out, min_length_s=MIN_WINDOW_LENGTH_S
    )
    if not windows:
        return None
    start_s, end_s = windows[0]
    mask = (trace.t_s >= start_s) & (trace.t_s <= end_s)
    return mask, (start_s, end_s)


def _fit_trace(trace: SimulationTrace) -> tuple[str, FopdtModel | None]:
    """Identify FOPDT model on the first open-loop step window of a trace."""
    extracted = _extract_active_window(trace)
    if extracted is None:
        return "no_window", None
    mask, _ = extracted
    try:
        model = identify_fopdt(
            u=trace.out[mask],
            y=trace.pv[mask],
            dt_s=trace.dt_s,
            max_delay_s=MAX_DELAY_S,
        )
        return "ok", model
    except ValueError:
        # Fits fail if input lacks excitation or variance explained falls below threshold
        return "failed", None


def run_single_simulation(loop: str, noise: str, seed: int) -> RunResult:
    """Execute one simulation trial and identify the FOPDT parameters."""
    scenario = _build_test_scenario(noise)
    trace = _simulate_loop(scenario, loop, seed)
    status, model = _fit_trace(trace)
    if status != "ok" or model is None:
        return RunResult(loop, noise, seed, status, None, None, None)
    return RunResult(
        loop=loop,
        noise=noise,
        seed=seed,
        status="ok",
        gain=model.gain,
        time_constant_s=model.time_constant_s,
        delay_s=model.delay_s,
    )


def _calculate_empirical_gain(trace: SimulationTrace, loop: str) -> float:
    """Steady-state gain from the scripted up-step: delta(PV) / delta(OUT).

    The ``step_test`` scenario raises OUT by STEP_TEST_SIZE_PCT at a known time and restores it one
    hold later. The PV level just before the step and the PV level just before the restore are
    averaged over WINDOW_BASELINE_S, which gives the gain without any model.
    """
    step_s = STEP_TEST_FIRST_STEP_S + 2 * MILL_LOOP_NAMES.index(loop) * STEP_TEST_HOLD_S
    before = (trace.t_s >= step_s - WINDOW_BASELINE_S) & (trace.t_s < step_s)
    end_s = step_s + STEP_TEST_HOLD_S
    settled = (trace.t_s >= end_s - WINDOW_BASELINE_S) & (trace.t_s < end_s)
    delta_pv = float(np.mean(trace.pv[settled]) - np.mean(trace.pv[before]))
    return delta_pv / STEP_TEST_SIZE_PCT


def compute_reference(loop: str) -> ReferenceMetrics:
    """Derive ground-truth FOPDT model and steady-state gain from a noise-free run."""
    scenario = _build_reference_scenario()
    trace = _simulate_loop(scenario, loop, REFERENCE_SEED)
    extracted = _extract_active_window(trace)
    if extracted is None:
        raise RuntimeError(f"Noise-free reference run for loop {loop} produced no step window")
    mask, _ = extracted
    model = identify_fopdt(
        u=trace.out[mask],
        y=trace.pv[mask],
        dt_s=trace.dt_s,
        max_delay_s=MAX_DELAY_S,
    )
    ss_gain = _calculate_empirical_gain(trace, loop)
    return ReferenceMetrics(model=model, steady_state_gain=ss_gain)


def _compute_errors_percent(
    values: list[float], reference: float
) -> tuple[float, float]:
    """Compute median and 90th percentile of absolute relative error percentage."""
    if not values:
        return float("nan"), float("nan")
    # Relative error formula: |estimated - true| / true * 100
    errors = np.abs(np.array(values) - reference) / reference * PERCENT_MULTIPLIER
    return float(np.median(errors)), float(np.percentile(errors, 90))


def _format_cell_row(
    loop: str,
    noise: str,
    runs: list[RunResult],
    reference: ReferenceMetrics,
) -> str:
    """Format one Markdown table row for a (loop, noise) configuration."""
    successful = [r for r in runs if r.status == "ok"]
    failed_count = sum(1 for r in runs if r.status in ("failed", "no_window"))

    gains = [r.gain for r in successful if r.gain is not None]
    taus = [r.time_constant_s for r in successful if r.time_constant_s is not None]
    delays = [r.delay_s for r in successful if r.delay_s is not None]

    gain_med, gain_p90 = _compute_errors_percent(gains, reference.model.gain)
    tau_med, tau_p90 = _compute_errors_percent(taus, reference.model.time_constant_s)
    del_med, del_p90 = _compute_errors_percent(delays, reference.model.delay_s)

    return (
        f"| {loop} | {noise} | {failed_count} | "
        f"{gain_med:.1f} / {gain_p90:.1f} | "
        f"{tau_med:.1f} / {tau_p90:.1f} | "
        f"{del_med:.1f} / {del_p90:.1f} | "
        f"{reference.model.gain:.3f} | {reference.steady_state_gain:.3f} | "
        f"{reference.model.time_constant_s:.1f} | {reference.model.delay_s:.1f} |"
    )


def build_markdown_report(
    results: list[RunResult],
    references: dict[str, ReferenceMetrics],
) -> str:
    """Build summary report detailing errors against noise-free benchmarks."""
    header = [
        "# Identification Accuracy Validation",
        "",
        "Accuracy of FOPDT fits relative to noise-free step test baselines.",
        "",
        "| Loop | Noise | Failed/No-win | Gain Err % (Med/P90) | Tau Err % (Med/P90) "
        "| Delay Err % (Med/P90) | Ref Gain | Ref SS-Gain | Ref Tau (s) | Ref Delay (s) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines = list(header)
    for loop in LOOPS:
        for noise in NOISE_LEVELS:
            matching = [r for r in results if r.loop == loop and r.noise == noise]
            row = _format_cell_row(loop, noise, matching, references[loop])
            lines.append(row)

    lines.extend(["", "## Limits", "", LIMITS_TEXT, ""])
    return "\n".join(lines)


def main() -> None:
    """Run step-test accuracy sweeps in parallel and write results markdown."""
    references = {loop: compute_reference(loop) for loop in LOOPS}

    tasks = [
        (loop, noise, seed)
        for loop in LOOPS
        for noise in NOISE_LEVELS
        for seed in SEEDS
    ]

    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(run_single_simulation, *task) for task in tasks]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]

    report = build_markdown_report(results, references)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()

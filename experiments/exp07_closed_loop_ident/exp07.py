"""Experiment exp07: does an instrumental-variable fit remove closed-loop bias?

The controller in AUTO makes the manipulated variable correlated with the load
disturbance, so a direct ARX fit on (u, y) is biased. This script simulates 20
closed-loop runs, fits a FOPDT model with the direct and the setpoint-instrument
(IV) estimator on the same data, and writes the metric tables and the frozen
target verdicts (I1-I4) to results/results.md.
"""

from __future__ import annotations

import concurrent.futures
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from crosscut_loops.identification import identify_fopdt
from crosscut_loops.identification_cl import identify_fopdt_closed_loop
from crosscut_loops.tuning_rules import FopdtModel, simc_pi
from crosscut_sim.core import Fopdt

# True process, fixed for every run.
TRUE_GAIN = 2.0
TRUE_TAU_S = 50.0
TRUE_DELAY_S = 10.0

DT_S = 1.0
# SIMC tuning: tau_c equals the dead time (see the README setup).
TAU_C_S = 10.0

SAMPLES_PER_RUN = 14400  # 4 h at dt = 1 s
MAX_DELAY_S = 30.0
MIN_STEP_S = 1200  # shortest interval between two setpoint changes
MAX_STEP_S = 2400
MAX_ABS_SETPOINT = 2.0

# Ornstein-Uhlenbeck load disturbance, added to the controller output in input units.
DISTURBANCE_SD = 0.5
DISTURBANCE_TAU_S = 600.0

PV_NOISE_SD = 0.05

SEEDS = tuple(range(1, 21))
MAX_WORKERS = 4

# Frozen acceptance thresholds from the README (not to be changed after the run).
I1_MAX_GAIN_ERROR = 0.15
I2_IMPROVEMENT_FACTOR = 0.7
I3_MAX_DELAY_ERROR_SAMPLES = 3
I3_MAX_TAU_ERROR = 0.30
# I2 compares only when the direct fit is already outside this band.
I2_DIRECT_NOT_NEEDED_GAIN_ERROR = 0.15

RESULTS_PATH = Path(__file__).parent / "results" / "results.md"


@dataclass(frozen=True)
class Metrics:
    """Errors of one estimator against the true process for one seed.

    relative_gain_error and relative_tau_error are dimensionless fractions,
    delay_error_samples is a signed count of sampling periods.
    """

    relative_gain_error: float
    relative_tau_error: float
    delay_error_samples: float


@dataclass(frozen=True)
class SeedResult:
    """Metrics of both estimators for one seed, or 'fail' for each that raised."""

    seed: int
    direct: Metrics | None
    iv: Metrics | None


def simulate_run(seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Simulate one closed-loop run and return (u, y, sp) as equal-length arrays.

    u is the controller output in input units, y is the noisy measured process
    value, sp is the setpoint. The load disturbance is added to u before the
    process; the controller sees the setpoint, so it is an exogenous instrument.
    """
    rng = np.random.default_rng(seed)
    process = Fopdt(TRUE_GAIN, TRUE_TAU_S, TRUE_DELAY_S, DT_S)
    tuned = simc_pi(FopdtModel(TRUE_GAIN, TRUE_TAU_S, TRUE_DELAY_S), tau_c_s=TAU_C_S)
    gains = (tuned.kc, tuned.ti_s)

    setpoints = _build_setpoint_schedule(rng)
    disturbances = _build_disturbance(rng)
    return _close_the_loop(process, gains, setpoints, disturbances, rng)


def _build_setpoint_schedule(rng: np.random.Generator) -> np.ndarray:
    """Return the setpoint over time: start at 0, toggle by +-1 every 20-40 min.

    The sign is flipped back when the value would leave the +-2 band, so the
    setpoint stays inside it while still moving every interval.
    """
    schedule = np.zeros(SAMPLES_PER_RUN)
    current = 0.0
    change_at = _next_change_time(0, rng)
    for sample in range(SAMPLES_PER_RUN):
        if sample >= change_at:
            current = _next_setpoint_value(current, rng)
            change_at = _next_change_time(sample, rng)
        schedule[sample] = current
    return schedule


def _next_change_time(start_sample: int, rng: np.random.Generator) -> int:
    """Return the sample index of the next setpoint change, 20-40 min after start."""
    interval_s = rng.uniform(MIN_STEP_S, MAX_STEP_S)
    return start_sample + int(round(interval_s / DT_S))


def _next_setpoint_value(current: float, rng: np.random.Generator) -> float:
    """Return the toggled setpoint, flipping the sign to stay within +-2."""
    step = rng.choice((-1.0, 1.0))
    candidate = current + step
    if abs(candidate) > MAX_ABS_SETPOINT:
        candidate = current - step
    return candidate


def _build_disturbance(rng: np.random.Generator) -> np.ndarray:
    """Return the OU load disturbance in input units, exactly discretised.

    The Ornstein-Uhlenbeck process obeys dd = -d/tau * dt + sigma * sqrt(2/tau) * dW,
    so the exact update is d[k+1] = phi*d[k] + sd*sqrt(1-phi^2)*z with
    phi = exp(-dt/tau) the per-step correlation and z a standard normal draw.
    """
    phi = math.exp(-DT_S / DISTURBANCE_TAU_S)
    noise_scale = DISTURBANCE_SD * math.sqrt(1.0 - phi * phi)
    disturbance = np.zeros(SAMPLES_PER_RUN)
    for sample in range(1, SAMPLES_PER_RUN):
        disturbance[sample] = phi * disturbance[sample - 1] + noise_scale * rng.standard_normal()
    return disturbance


def _close_the_loop(
    process: Fopdt,
    gains: tuple[float, float],
    setpoints: np.ndarray,
    disturbances: np.ndarray,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Run the discrete PI controller against the process and record u, y, sp.

    The PI rule is u = Kc*e + I with I += Kc/Ti*e*dt, the integral accumulated
    from zero. The process sees u plus the disturbance; the controller sees the
    measured PV, y + noise, so those two signals differ.
    """
    proportional_gain, integral_time_s = gains
    controller_output = np.zeros(SAMPLES_PER_RUN)
    measured_output = np.zeros(SAMPLES_PER_RUN)
    integral = 0.0

    for sample in range(SAMPLES_PER_RUN):
        error = setpoints[sample] - measured_output[sample - 1] if sample else setpoints[sample]
        integral += proportional_gain / integral_time_s * error * DT_S
        controller_output[sample] = proportional_gain * error + integral
        process_input = controller_output[sample] + disturbances[sample]
        measured_output[sample] = (
            process.update(process_input) + PV_NOISE_SD * rng.standard_normal()
        )

    return controller_output, measured_output, setpoints


def compute_metrics(model: FopdtModel) -> Metrics:
    """Return the gain, time-constant and delay errors of a fitted model."""
    return Metrics(
        relative_gain_error=(model.gain - TRUE_GAIN) / TRUE_GAIN,
        relative_tau_error=(model.time_constant_s - TRUE_TAU_S) / TRUE_TAU_S,
        delay_error_samples=(model.delay_s - TRUE_DELAY_S) / DT_S,
    )


def fit_one_seed(seed: int) -> SeedResult:
    """Simulate one run and fit both estimators, recording 'fail' on ValueError.

    Module-level so it can be shipped to a ProcessPoolExecutor worker.
    """
    u, y, sp = simulate_run(seed)
    return SeedResult(
        seed=seed,
        direct=_fit_or_fail(identify_fopdt, seed, u, y, sp),
        iv=_fit_or_fail(identify_fopdt_closed_loop, seed, u, y, sp),
    )


def _fit_or_fail(
    estimator, seed: int, u: np.ndarray, y: np.ndarray, sp: np.ndarray
) -> Metrics | None:
    """Return the estimator's metrics, or None when it raises ValueError."""
    try:
        if estimator is identify_fopdt:
            model = estimator(u, y, DT_S, MAX_DELAY_S)
        else:
            model = estimator(u, y, sp, DT_S, MAX_DELAY_S)
    except ValueError:
        return None
    return compute_metrics(model)


def _check_i4() -> bool:
    """Return True when the IV fit raises ValueError on a constant setpoint."""
    u, y, _ = simulate_run(seed=1)
    try:
        identify_fopdt_closed_loop(u, y, np.zeros_like(u), DT_S, MAX_DELAY_S)
    except ValueError:
        return True
    return False


def _collect(direct_errors: np.ndarray, iv_errors: np.ndarray) -> dict[str, float]:
    """Return median and p90 of the absolute errors of both estimators."""
    return {
        "direct_median": float(np.median(direct_errors)),
        "direct_p90": float(np.percentile(direct_errors, 90)),
        "iv_median": float(np.median(iv_errors)),
        "iv_p90": float(np.percentile(iv_errors, 90)),
    }


def _abs_or_nan(results: list[SeedResult], field: str, attribute: str) -> np.ndarray:
    """Return the absolute error of one metric across seeds; nan for 'fail' seeds."""
    values = [
        abs(getattr(getattr(result, field), attribute))
        if getattr(result, field) is not None
        else np.nan
        for result in results
    ]
    return np.asarray(values, dtype=float)


def _summarise(results: list[SeedResult]) -> dict[str, dict[str, float]]:
    """Return per-metric summaries (median, p90) of the absolute errors."""
    return {
        "gain": _collect(
            _abs_or_nan(results, "direct", "relative_gain_error"),
            _abs_or_nan(results, "iv", "relative_gain_error"),
        ),
        "tau": _collect(
            _abs_or_nan(results, "direct", "relative_tau_error"),
            _abs_or_nan(results, "iv", "relative_tau_error"),
        ),
        "delay": _collect(
            _abs_or_nan(results, "direct", "delay_error_samples"),
            _abs_or_nan(results, "iv", "delay_error_samples"),
        ),
    }


def _verdict(passed: bool) -> str:
    """Return a PASS/FAIL string for the report."""
    return "PASS" if passed else "FAIL"


def _target_lines(summary: dict[str, dict[str, float]], i4_raised: bool) -> list[str]:
    """Return the markdown lines for the Targets section (I1-I4)."""
    gain = summary["gain"]
    iv_gain_ok = gain["iv_median"] <= I1_MAX_GAIN_ERROR
    direct_gain_ok = gain["direct_median"] <= I2_DIRECT_NOT_NEEDED_GAIN_ERROR
    improved = gain["iv_median"] <= I2_IMPROVEMENT_FACTOR * gain["direct_median"]

    if direct_gain_ok:
        i2 = "not needed (direct fit already within 15 %)"
    else:
        i2 = _verdict(improved)

    tau_ok = summary["tau"]["iv_median"] <= I3_MAX_TAU_ERROR
    delay_ok = summary["delay"]["iv_median"] <= I3_MAX_DELAY_ERROR_SAMPLES
    i3 = _verdict(tau_ok and delay_ok)

    return [
        f"- **I1** (IV median gain error <= 15 %): {_verdict(iv_gain_ok)} "
        f"(median {gain['iv_median']:.4f})",
        f"- **I2** (IV median gain error <= 0.7 x direct): {i2} "
        f"(direct {gain['direct_median']:.4f}, IV {gain['iv_median']:.4f})",
        f"- **I3** (IV median delay error <= 3 samples and tau error <= 30 %): {i3} "
        f"(delay {summary['delay']['iv_median']:.2f}, tau {summary['tau']['iv_median']:.4f})",
        f"- **I4** (flat setpoint raises ValueError): {_verdict(i4_raised)}",
    ]


def _format_metric(value: float | None, field: str) -> str:
    """Format one estimator's three metrics, or 'fail' when the fit raised."""
    if value is None:
        return "fail | fail | fail"
    values = (
        (value.relative_gain_error, value.relative_tau_error, value.delay_error_samples)
        if field == "direct"
        else (value.relative_gain_error, value.relative_tau_error, value.delay_error_samples)
    )
    return f"{values[0]:.4f} | {values[1]:.4f} | {values[2]:.2f}"


def _seed_table(results: list[SeedResult]) -> list[str]:
    """Return the markdown per-seed table lines."""
    lines = [
        "| seed | direct gain err | direct tau err | direct delay err | "
        "iv gain err | iv tau err | iv delay err |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            f"| {result.seed} | {_format_metric(result.direct, 'direct')} | "
            f"{_format_metric(result.iv, 'iv')} |"
        )
    return lines


def _summary_table(summary: dict[str, dict[str, float]]) -> list[str]:
    """Return the markdown summary table lines for median and p90 of abs errors."""
    headers = [
        "| metric | estimator | median abs err | p90 abs err |",
        "| --- | --- | --- | --- |",
    ]
    rows = []
    for metric_name, values in summary.items():
        rows.append(
            f"| {metric_name} | direct | {values['direct_median']:.4f} "
            f"| {values['direct_p90']:.4f} |"
        )
        rows.append(f"| {metric_name} | iv | {values['iv_median']:.4f} | {values['iv_p90']:.4f} |")
    return headers + rows


def write_report(
    results: list[SeedResult], summary: dict[str, dict[str, float]], i4_raised: bool
) -> Path:
    """Write the per-seed table, summary table and target verdicts; return the path."""
    lines = ["# exp07: closed-loop identification of a FOPDT model", ""]
    lines += ["## Per-seed errors", ""] + _seed_table(results)
    lines += ["", "## Summary of absolute errors", ""] + _summary_table(summary)
    lines += ["", "## Targets", ""] + _target_lines(summary, i4_raised)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return RESULTS_PATH


def main(argv: list[str] | None = None) -> None:
    """Run 20 seeds in parallel, write the results file and print its path.

    ``python exp07.py [FIRST_SEED]``: the default 1 gives seeds 1-20 and ``results.md``; another
    first seed gives the next 20 seeds and ``results_seeds_<first>_<last>.md`` (used to check a
    change of the method on seeds that were not used to diagnose it).
    """
    args = sys.argv[1:] if argv is None else argv
    first_seed = int(args[0]) if args else 1
    seeds = tuple(range(first_seed, first_seed + len(SEEDS)))
    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(fit_one_seed, seeds))
    summary = _summarise(results)
    i4_raised = _check_i4()
    path = write_report(results, summary, i4_raised)
    if first_seed != 1:
        path = path.replace(path.with_name(f"results_seeds_{seeds[0]}_{seeds[-1]}.md"))
    print(f"results written to {path}")


if __name__ == "__main__":
    main()

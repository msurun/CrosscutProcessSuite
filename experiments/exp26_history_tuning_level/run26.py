"""Harness for exp26: is a confident tuning recommendation from history safe on a level loop?

Runs every case x seed through `tune_from_history`, judges the recommended PI on a step
response, and writes results26.md with the frozen H1 target and the descriptive tables.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import g26_level  # noqa: E402
from crosscut_loops.history_tuning import tune_from_history  # noqa: E402

# Scenarios whose recommendation is graded "confident" and must be safe (H1).
CONFIDENT_LEVELS = frozenset({"high", "medium"})
# Fraction of the response window that counts as "settled".
SETTLE_WINDOW_FRACTION = 0.25
# Settled when residual error stays within this fraction of the step size.
SETTLE_TOLERANCE_FRACTION = 0.10
# Oscillation hysteresis: a sign change needs the error to clear this fraction of the step.
OSCILLATION_HYSTERESIS_FRACTION = 0.02
# More than this many error sign changes counts as oscillating.
MAX_OSCILLATION_SIGN_CHANGES = 4
SP_STEP_TIME_S = 50.0  # the generator steps SP at t = 50 s
# The history generator samples every second.
HISTORY_DT_S = 1.0
# Progress is printed to stderr every N cases.
PROGRESS_EVERY_CASES = 4
# Integrating SIMC with tau_c = delay: Ti = 4 (tau_c + delay) = 8 delay.
SIMC_TI_DELAY_FACTOR = 8.0
# Integrating SIMC Kc = 1 / (rate (tau_c + delay)) = 1 / (rate 2 delay).
SIMC_KC_DELAY_FACTOR = 2.0
# Baseline PV and OP used by the generator.
BASELINE_PV = 50.0


@dataclass(frozen=True)
class RunResult:
    """One tuning run on one simulated history, with the judgement of its recommendation."""

    case_name: str
    seed: int
    confidence: str
    model_gain: float | None
    model_tau_s: float | None
    model_delay_s: float | None
    recommended_kc: float | None
    recommended_ti_s: float | None
    is_recommendation_safe: bool | None
    overshoot: float | None


@dataclass(frozen=True)
class ReferenceResult:
    """Judgement of the running controller on the same step response, as a reference."""

    case_name: str
    seed: int
    tuning: str
    is_safe: bool


def load_cases() -> list:
    """Return every generator case (32 cells) in a stable order."""
    return list(g26_level.all_cases())


def measure_signed_error(response: dict) -> np.ndarray:
    """Return PV - SP after the setpoint step, in %PV, from t = history end onward.

    The generator steps SP from 50 to 50 + RESPONSE_STEP at t = 50 s; we judge only the
    transient after the step, so the first samples are dropped.
    """
    t_s = np.asarray(response["t_s"], dtype=float)
    sp = np.asarray(response["sp"], dtype=float)
    pv = np.asarray(response["pv"], dtype=float)
    after_step = t_s >= SP_STEP_TIME_S
    return (pv - sp)[after_step]


def is_settled(error: np.ndarray, step: float) -> bool:
    """Return True when |error| over the last quarter of the window stays within tolerance."""
    start = int(len(error) * (1.0 - SETTLE_WINDOW_FRACTION))
    tail = error[start:]
    return bool(np.max(np.abs(tail)) <= SETTLE_TOLERANCE_FRACTION * step)


def count_bounded_sign_changes(error: np.ndarray, step: float) -> int:
    """Count sign changes of error that clear the hysteresis band on both sides.

    A change counts only when the error goes from above +hysteresis to below -hysteresis
    (or the reverse), so measurement noise around zero does not inflate the count.
    """
    band = OSCILLATION_HYSTERESIS_FRACTION * step
    reached = np.flatnonzero(error >= 0.0)  # PV - SP starts at -step; count after it reaches SP
    error = error[reached[0]:] if len(reached) else error[:0]
    signs = np.zeros(len(error), dtype=int)
    signs[error > band] = 1
    signs[error < -band] = -1
    # Drop the "inside the band" samples: only decisive crossings separate opposite regimes.
    decisive = signs[signs != 0]
    if len(decisive) < 2:
        return 0
    return int(np.count_nonzero(np.diff(decisive) != 0))


def is_oscillating(error: np.ndarray, step: float) -> bool:
    """Return True when the error changes sign more than the allowed number of times."""
    return count_bounded_sign_changes(error, step) > MAX_OSCILLATION_SIGN_CHANGES


def measure_overshoot(response: dict, step: float) -> float:
    """Return (max PV - target) / step; positive means the PV exceeded the new setpoint."""
    pv = np.asarray(response["pv"], dtype=float)
    target = BASELINE_PV + step
    return float((np.max(pv) - target) / step)


def judge_response(response: dict, step: float) -> dict:
    """Return settled / oscillating / safe flags and the overshoot for one step response."""
    error = measure_signed_error(response)
    settled = is_settled(error, step)
    oscillating = is_oscillating(error, step)
    return {
        "settled": settled,
        "oscillating": oscillating,
        "safe": settled and not oscillating,
        "overshoot": measure_overshoot(response, step),
    }


def get_simc_settings(tuning) -> tuple[float, float] | None:
    """Return (Kc, Ti) from the tuning report, or None when no SIMC settings were produced."""
    if tuning.report is None or tuning.report.simc is None:
        return None
    return tuning.report.simc.kc, tuning.report.simc.ti_s


def tune_and_judge(case, seed: int) -> RunResult:
    """Tune one history, then judge the recommended PI on the step response if confident."""
    history = g26_level.simulate_history(case, seed)
    tuning = tune_from_history(
        "L", history["sp"], history["op"], history["pv"], dt_s=HISTORY_DT_S
    )
    simc = get_simc_settings(tuning)
    model = tuning.model
    base_kwargs = {
        "case_name": case.name,
        "seed": seed,
        "confidence": tuning.confidence,
        "model_gain": model.gain if model else None,
        "model_tau_s": model.time_constant_s if model else None,
        "model_delay_s": model.delay_s if model else None,
        "recommended_kc": simc[0] if simc else None,
        "recommended_ti_s": simc[1] if simc else None,
    }
    if tuning.confidence not in CONFIDENT_LEVELS or simc is None:
        return RunResult(**base_kwargs, is_recommendation_safe=None, overshoot=None)
    response = g26_level.step_response(_quiet(case), kc=simc[0], ti_s=simc[1], seed=seed)
    verdict = judge_response(response, g26_level.RESPONSE_STEP)
    return RunResult(
        **base_kwargs,
        is_recommendation_safe=verdict["safe"],
        overshoot=verdict["overshoot"],
    )


def _quiet(case):
    """The case without load and noise (amendment 1): stability is judged deterministically."""
    return replace(case, load_std=0.0, noise_std=0.0)


def judge_running_controller(case, seed: int) -> ReferenceResult:
    """Judge the running PI of one case on its step response, as a reference point."""
    kc, ti_s = g26_level.running_pi(case)
    response = g26_level.step_response(_quiet(case), kc=kc, ti_s=ti_s, seed=seed)
    verdict = judge_response(response, g26_level.RESPONSE_STEP)
    return ReferenceResult(
        case_name=case.name, seed=seed, tuning=case.tuning, is_safe=verdict["safe"]
    )


def run_all(cases: list, seeds: list[int]) -> tuple[list[RunResult], list[ReferenceResult]]:
    """Run every case x seed and print progress to stderr every few cases."""
    run_results: list[RunResult] = []
    reference_results: list[ReferenceResult] = []
    for case_index, case in enumerate(cases):
        if case_index % PROGRESS_EVERY_CASES == 0:
            print(
                f"[run26] case {case_index + 1}/{len(cases)}: {case.name}",
                file=sys.stderr,
            )
        for seed in seeds:
            run_results.append(tune_and_judge(case, seed))
            reference_results.append(judge_running_controller(case, seed))
    return run_results, reference_results


def build_case_lookup(cases: list) -> dict:
    """Return a dict from case name to the case object."""
    return {case.name: case for case in cases}


def summarize_h1(run_results: list[RunResult]) -> dict:
    """Return counts of confident recommendations and how many of them were judged safe."""
    confident = [r for r in run_results if r.confidence in CONFIDENT_LEVELS
                 and r.is_recommendation_safe is not None]
    safe = [r for r in confident if r.is_recommendation_safe]
    unsafe = [r for r in confident if not r.is_recommendation_safe]
    if not confident:
        verdict = "NOT EXERCISED"
    elif not unsafe:
        verdict = "PASS"
    else:
        verdict = "MISS"
    return {
        "count": len(confident),
        "safe": len(safe),
        "unsafe": unsafe,
        "verdict": verdict,
    }


def format_optional(value: float | None, digits: int = 3) -> str:
    """Format a float for a table cell, or a dash when the value is missing."""
    return "—" if value is None else f"{value:.{digits}f}"


def build_confidence_table(run_results: list[RunResult], cases: list) -> list[str]:
    """Return markdown lines of a per-case table of confidence counts (high/medium/low/none)."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for result in run_results:
        counts[result.case_name][result.confidence] += 1
    lines = ["| case | high | medium | low | none |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for case in cases:
        row = counts[case.name]
        lines.append(
            f"| {case.name} | {row['high']} | {row['medium']} | {row['low']} | {row['none']} |"
        )
    return lines


def build_model_table(run_results: list[RunResult], case_lookup: dict) -> list[str]:
    """Return markdown lines comparing the identified model with the true integrator.

    For an integrator the implied rate is gain / time_constant; the ratio to the true
    rate says how far the FOPDT fit is from the plant.
    """
    lines = [
        "| case | seed | confidence | implied rate / true rate | tau [s] | delay / true |",
        "| --- | ---: | --- | ---: | ---: | ---: |",
    ]
    for result in run_results:
        if result.confidence not in CONFIDENT_LEVELS or result.model_tau_s is None:
            continue
        case = case_lookup[result.case_name]
        if result.model_tau_s <= 0.0:
            continue
        implied_rate = result.model_gain / result.model_tau_s
        rate_ratio = implied_rate / case.rate
        delay_ratio = result.model_delay_s / case.delay_s
        lines.append(
            f"| {result.case_name} | {result.seed} | {result.confidence} | "
            f"{rate_ratio:.3f} | {result.model_tau_s:.1f} | {delay_ratio:.3f} |"
        )
    return lines


def build_recommendation_table(run_results: list[RunResult], case_lookup: dict) -> list[str]:
    """Return markdown lines comparing recommended Kc/Ti with integrating SIMC at tau_c = delay."""
    lines = [
        "| case | seed | Kc / SIMC Kc | Ti / SIMC Ti |",
        "| --- | ---: | ---: | ---: |",
    ]
    for result in run_results:
        if result.recommended_kc is None or result.recommended_ti_s is None:
            continue
        case = case_lookup[result.case_name]
        simc_kc = 1.0 / (case.rate * SIMC_KC_DELAY_FACTOR * case.delay_s)
        simc_ti = SIMC_TI_DELAY_FACTOR * case.delay_s
        lines.append(
            f"| {result.case_name} | {result.seed} | "
            f"{result.recommended_kc / simc_kc:.3f} | "
            f"{result.recommended_ti_s / simc_ti:.3f} |"
        )
    return lines


def build_running_controller_table(reference_results: list[ReferenceResult]) -> list[str]:
    """Return markdown lines with the running controller's safe share per tuning type."""
    totals: Counter = Counter()
    safe: Counter = Counter()
    for result in reference_results:
        totals[result.tuning] += 1
        if result.is_safe:
            safe[result.tuning] += 1
    lines = ["| running tuning | safe / runs | safe share |", "| --- | ---: | ---: |"]
    for tuning in sorted(totals):
        share = safe[tuning] / totals[tuning]
        lines.append(f"| {tuning} | {safe[tuning]} / {totals[tuning]} | {share:.3f} |")
    return lines


def build_unsafe_lines(unsafe_runs: list[RunResult]) -> list[str]:
    """Return markdown bullet lines, one per unsafe confident recommendation."""
    if not unsafe_runs:
        return ["None."]
    lines = []
    for result in unsafe_runs:
        lines.append(
            f"- {result.case_name} seed {result.seed} ({result.confidence}): "
            f"model gain {format_optional(result.model_gain)}, "
            f"tau {format_optional(result.model_tau_s)} s, "
            f"delay {format_optional(result.model_delay_s)} s; "
            f"recommended Kc {format_optional(result.recommended_kc)}, "
            f"Ti {format_optional(result.recommended_ti_s)} s; "
            f"overshoot {format_optional(result.overshoot)}"
        )
    return lines


def build_report(cases: list, run_results: list[RunResult],
                 reference_results: list[ReferenceResult]) -> str:
    """Return the markdown text of results26.md."""
    case_lookup = build_case_lookup(cases)
    h1 = summarize_h1(run_results)
    sections = [
        "# exp26: tuning from history on level loops (frozen 2026-10-19)\n",
        "## H1 (safety)\n",
        f"- Confident recommendations: {h1['count']}",
        f"- Judged safe: {h1['safe']}",
        f"- Verdict: **{h1['verdict']}**\n",
        "### Unsafe confident recommendations\n",
        *build_unsafe_lines(h1["unsafe"]),
        "\n## Confidence shares per case\n",
        *build_confidence_table(run_results, cases),
        "\n## Identified model vs true integrator (confident runs)\n",
        *build_model_table(run_results, case_lookup),
        "\n## Recommended PI vs integrating SIMC (tau_c = delay)\n",
        *build_recommendation_table(run_results, case_lookup),
        "\n## Running controller as reference\n",
        *build_running_controller_table(reference_results),
    ]
    return "\n".join(sections) + "\n"


def write_report(report_text: str, output_path: Path) -> None:
    """Write the report, refusing to overwrite an existing file."""
    if output_path.exists():
        raise SystemExit(f"refusing to overwrite existing report: {output_path}")
    output_path.write_text(report_text, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Return parsed command-line arguments (seeds default to the generator's list)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="*",
        default=None,
        help="override the generator seed list (default: g26_level.SEEDS)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the harness and write results26.md next to this file."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    seeds = list(g26_level.SEEDS) if args.seeds is None else args.seeds
    cases = load_cases()
    run_results, reference_results = run_all(cases, seeds)
    report_text = build_report(cases, run_results, reference_results)
    output_path = HERE / "results26.md"
    print(report_text)
    write_report(report_text, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

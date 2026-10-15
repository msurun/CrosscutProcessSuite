"""exp09: backtest the mill feed supervisor against the simulated operator's feed moves.

Targets B1-B5 are frozen in README.md before the first run. The rule base sees mill power and
P80; the operator (the simulator's `observational` scenario) moves the feed setpoint from a noisy
belief about the ore hardness. We replay the rule base over the record and score its advice just
before each operator move, separately on the first (tuning) and second (check) half of the run.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from crosscut_fuzzy.backtest import BacktestMetrics, BacktestSettings, backtest, split_halves
from crosscut_fuzzy.inference import evaluate
from crosscut_fuzzy.model import FuzzySystem, system_from_dict
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario

RUN_HOURS = 48.0
SEEDS = range(1, 11)
RECORD_EVERY_S = 10  # a record per 10 s is plenty: the operator acts every 1800 s
SCENARIO = "observational"
POWER_TAG = "sim.mc.mill_power"
P80_TAG = "sim.mc.p80"
FEED_SP_TAG = "sim.mc.mill_feed_sp"
RULE_BASE = Path(__file__).parents[2] / "fuzzy" / "examples" / "mill_feed_supervisor.json"
OUTPUT_ID = "feed_change"
RESULTS_PATH = Path(__file__).parent / "results" / "results.md"

TARGET_AGREEMENT = 0.65  # B1
TARGET_CORRELATION = 0.30  # B2
MAX_AGREEMENT_DROP = 0.10  # B3
MIN_EDGE_OVER_MAJORITY = 0.10  # B4
MAX_SILENT_SHARE = 0.30  # B5


def load_system() -> FuzzySystem:
    """The rule base under test."""
    return system_from_dict(json.loads(RULE_BASE.read_text(encoding="utf-8")))


def simulate(seed: int) -> dict[str, np.ndarray]:
    """Run the scenario and return power, P80 and the feed SP, one value per record."""
    scenario = build_scenario("mill_circuit", SCENARIO, duration_s=RUN_HOURS * 3600.0)
    plant = MillCircuitPlant()
    plant.reset(seed, scenario)
    n_steps = int(round(scenario.duration_s / scenario.dt_s))
    stride = int(round(RECORD_EVERY_S / scenario.dt_s))
    tags = {"power": POWER_TAG, "p80": P80_TAG, "sp": FEED_SP_TAG}
    series: dict[str, list[float]] = {name: [] for name in tags}
    for step in range(n_steps):
        if step % stride == 0:
            for name, tag in tags.items():
                series[name].append(plant.read(tag)[0])
        plant.step()
    return {name: np.asarray(values) for name, values in series.items()}


def fuzzy_advice(system: FuzzySystem, record: dict[str, np.ndarray]) -> np.ndarray:
    """Replay the rule base over the record; returns the crisp `feed_change` series."""
    result = evaluate(system, {"mill_power": record["power"], "p80": record["p80"]})
    return np.asarray(result.outputs[OUTPUT_ID].crisp, dtype=float)


def score_seed(system: FuzzySystem, seed: int) -> tuple[BacktestMetrics, BacktestMetrics]:
    """Metrics on the tuning half and on the check half for one seed."""
    record = simulate(seed)
    advice = fuzzy_advice(system, record)
    tuning, check = split_halves(len(advice))
    settings = BacktestSettings()
    return (
        backtest(advice, record["sp"], RECORD_EVERY_S, settings, tuning),
        backtest(advice, record["sp"], RECORD_EVERY_S, settings, check),
    )


def median_of(values: list[float]) -> float:
    """Median ignoring NaN; NaN when nothing is left."""
    finite = [value for value in values if not np.isnan(value)]
    return float(np.median(finite)) if finite else float("nan")


def summarise(rows: list[tuple[BacktestMetrics, BacktestMetrics]]) -> dict[str, float]:
    """Medians over seeds of the check-part metrics and the tuning-to-check drop."""
    tuning = [pair[0] for pair in rows]
    check = [pair[1] for pair in rows]
    drops = [t.sign_agreement - c.sign_agreement for t, c in zip(tuning, check, strict=True)]
    edges = [c.sign_agreement - c.majority_share for c in check]
    return {
        "B1_agreement": median_of([c.sign_agreement for c in check]),
        "B2_correlation": median_of([c.correlation for c in check]),
        "B3_drop": median_of(drops),
        "B4_edge": median_of(edges),
        "B5_silent": median_of([c.silent_share for c in check]),
        "moves_per_seed_check": median_of([float(c.n_moves) for c in check]),
    }


def verdicts(summary: dict[str, float]) -> dict[str, bool]:
    """Pass/fail of the frozen targets; a NaN metric fails."""
    return {
        "B1": summary["B1_agreement"] >= TARGET_AGREEMENT,
        "B2": summary["B2_correlation"] >= TARGET_CORRELATION,
        "B3": summary["B3_drop"] <= MAX_AGREEMENT_DROP,
        "B4": summary["B4_edge"] >= MIN_EDGE_OVER_MAJORITY,
        "B5": summary["B5_silent"] <= MAX_SILENT_SHARE,
    }


def main() -> None:
    """Run all seeds and write the results table."""
    system = load_system()
    rows = [score_seed(system, seed) for seed in SEEDS]
    summary = summarise(rows)
    lines = ["# exp09 results", "", "| metric | median |", "|---|---|"]
    lines += [f"| {name} | {value:.3f} |" for name, value in summary.items()]
    lines += ["", "| target | met |", "|---|---|"]
    lines += [f"| {name} | {'yes' if met else 'NO'} |" for name, met in verdicts(summary).items()]
    RESULTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

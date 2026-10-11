"""Experiment 0: identifying process gains from closed-loop data, setpoints versus actuator signals.

Question: when an operator moves the setpoints in response to ore hardness (a confounder), which
input signals recover the true causal gains of the grinding circuit?

Data: the synthetic mill circuit (`crosscut_sim`), recorded through the standard dataset pipeline.
Two scenarios: `observational` (operator on, confounded) and `excited` (operator off, random-binary
setpoint moves, unconfounded reference).
Estimator: least-squares FIR model of the cleaned output on lagged inputs; the steady-state gain
is the sum of the FIR coefficients of an input. Signal variants: setpoint (SP), measured actuator
state (PV), controller output (OUT), each raw or high-passed, and PV with the measured hardness
estimate as an extra regressor.

Usage (from the repository root):
    python experiments/exp00_sp_vs_mv/exp00.py --seeds 5 --hours 48
"""

from __future__ import annotations

import argparse
import csv
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
from crosscut_sim.dataset import read_dataset, record, to_wide
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario

DT_S = 5.0  # simulation step
SAMPLE_S = 30.0  # sampling period of the recorded data and of the FIR model
N_LAGS = 60  # FIR horizon: 60 samples = 30 min
HIGHPASS_SAMPLES = 20  # moving-average window removed by the high-pass: 10 min

DRIVERS = ("hpgr_press", "mill_feed", "cyc_water")
CV = "p80"
SP_TAGS = {driver: f"sim.mc.{driver}_sp" for driver in DRIVERS}
PV_TAGS = {driver: f"sim.mc.{driver}" for driver in DRIVERS}
OUT_TAGS = {driver: f"sim.mc.{driver}_out" for driver in DRIVERS}
CV_TAG = "sim.mc.p80"
HARDNESS_EST_TAG = "sim.mc.ore_hardness_est"

VARIANTS = (
    "SP raw",
    "SP high-pass",
    "PV raw",
    "PV high-pass",
    "OUT raw",
    "OUT high-pass",
    "PV raw + hardness",
)
SCENARIOS = ("observational", "excited")


def highpass(x: np.ndarray, window: int) -> np.ndarray:
    """Remove a centered moving average (window samples); the edges are not reliable."""
    kernel = np.ones(window) / window
    return x - np.convolve(x, kernel, mode="same")


def fir_gains(y: np.ndarray, inputs: Sequence[np.ndarray], n_lags: int) -> np.ndarray:
    """Least-squares FIR fit with an intercept; returns the sum of coefficients per input."""
    n_samples = len(y)
    rows = n_samples - n_lags + 1
    columns = [np.ones(rows)]
    for x in inputs:
        for lag in range(n_lags):
            columns.append(x[n_lags - 1 - lag : n_samples - lag])
    design = np.column_stack(columns)
    coefficients, *_ = np.linalg.lstsq(design, y[n_lags - 1 :], rcond=None)
    gains = []
    for k in range(len(inputs)):
        start = 1 + k * n_lags
        gains.append(float(coefficients[start : start + n_lags].sum()))
    return np.array(gains)


def with_simulation_step(scenario: Any) -> Any:
    """Return a copy of the scenario that runs at the experiment's simulation step DT_S."""
    return type(scenario)(
        name=scenario.name,
        duration_s=scenario.duration_s,
        dt_s=DT_S,
        measurement_noise=scenario.measurement_noise,
        disturbance_sigma=scenario.disturbance_sigma,
        disturbance_tau_s=scenario.disturbance_tau_s,
        events=scenario.events,
        params=scenario.params,
    )


def simulate(seed: int, scenario_name: str, hours: float, workdir: Path) -> dict[str, np.ndarray]:
    """Record a mill-circuit run through the dataset pipeline and read it back in wide format."""
    scenario = build_scenario("mill_circuit", scenario_name, duration_s=hours * 3600.0)
    scenario = with_simulation_step(scenario)
    out = workdir / f"{scenario_name}_seed{seed}"
    record(
        MillCircuitPlant(),
        scenario,
        out,
        seed=seed,
        dataset_id=out.name,
        plant_name="mill_circuit",
        scenario_name=scenario_name,
        sample_period_s=SAMPLE_S,
    )
    _, wide = to_wide(read_dataset(out))
    return wide


def estimate(wide: dict[str, np.ndarray], variant: str) -> np.ndarray:
    """Gains of the three drivers on p80 for one signal variant."""
    y = wide[CV_TAG]
    family = variant.split()[0]
    tags = {"SP": SP_TAGS, "PV": PV_TAGS, "OUT": OUT_TAGS}[family]
    inputs = [wide[tags[driver]] for driver in DRIVERS]
    extra: list[np.ndarray] = []
    if variant.endswith("hardness"):
        extra.append(wide[HARDNESS_EST_TAG])
    if variant.endswith("high-pass"):
        inputs = [highpass(x, HIGHPASS_SAMPLES) for x in inputs]
        y = highpass(y, HIGHPASS_SAMPLES)
    trim = HIGHPASS_SAMPLES  # drop unreliable edges (also for raw variants: same data window)
    inputs = [x[trim:-trim] for x in inputs]
    extra = [x[trim:-trim] for x in extra]
    y = y[trim:-trim]
    return fir_gains(y, [*inputs, *extra], N_LAGS)[: len(DRIVERS)]


def true_gains() -> dict[str, float]:
    """Ground-truth steady-state gains of the three drivers on p80 at ore hardness 14."""
    plant = MillCircuitPlant()
    return {driver: plant.true_gain(driver, CV, 14.0) for driver in DRIVERS}


def run(seeds: int, hours: float, out_dir: Path) -> list[dict[str, object]]:
    """Run all scenarios, seeds and variants; one result row per (scenario, variant, driver)."""
    estimates = collect_estimates(seeds, hours)
    rows = summarize(estimates, true_gains())
    out_dir.mkdir(parents=True, exist_ok=True)
    write_outputs(rows, out_dir, seeds, hours)
    return rows


def collect_estimates(seeds: int, hours: float) -> dict[tuple[str, str], list[np.ndarray]]:
    """Simulate every scenario and seed; group the gain estimates by (scenario, variant)."""
    estimates: dict[tuple[str, str], list[np.ndarray]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for scenario_name in SCENARIOS:
            for seed in range(1, seeds + 1):
                wide = simulate(seed, scenario_name, hours, Path(tmp))
                _add_variant_estimates(estimates, scenario_name, wide)
    return estimates


def _add_variant_estimates(
    estimates: dict[tuple[str, str], list[np.ndarray]],
    scenario_name: str,
    wide: dict[str, np.ndarray],
) -> None:
    """Append the gain estimate of every signal variant for one simulated run."""
    for variant in VARIANTS:
        estimates.setdefault((scenario_name, variant), []).append(estimate(wide, variant))


def summarize(
    estimates: dict[tuple[str, str], list[np.ndarray]], truth: dict[str, float]
) -> list[dict[str, object]]:
    """Turn the grouped estimates into one mean/std row per (scenario, variant, driver)."""
    rows: list[dict[str, object]] = []
    for (scenario_name, variant), runs in estimates.items():
        rows.extend(_summary_rows(scenario_name, variant, runs, truth))
    return rows


def _summary_rows(
    scenario_name: str, variant: str, runs: list[np.ndarray], truth: dict[str, float]
) -> list[dict[str, object]]:
    """Mean and sample standard deviation over the runs, for each driver of one variant."""
    stacked = np.vstack(runs)
    rows: list[dict[str, object]] = []
    for j, driver in enumerate(DRIVERS):
        rows.append(
            {
                "scenario": scenario_name,
                "variant": variant,
                "driver": driver,
                "true_gain": truth[driver],
                "mean": float(stacked[:, j].mean()),
                "std": float(stacked[:, j].std(ddof=1)) if len(runs) > 1 else float("nan"),
                "n_runs": len(runs),
            }
        )
    return rows


def write_outputs(rows: list[dict[str, object]], out_dir: Path, seeds: int, hours: float) -> None:
    """Write the run outputs (CSV, markdown report and plot) into out_dir."""
    write_results_csv(rows, out_dir)
    lines = build_results_markdown(rows, seeds, hours)
    (out_dir / "results.md").write_text("\n".join(lines), encoding="utf-8")
    plot(rows, out_dir)


def write_results_csv(rows: list[dict[str, object]], out_dir: Path) -> None:
    """Write the raw result rows to results.csv, using the first row as the header."""
    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_results_markdown(rows: list[dict[str, object]], seeds: int, hours: float) -> list[str]:
    """Return the markdown report lines: a header, then one section per driver."""
    lines = [
        f"# Experiment 0 results ({seeds} seeds x {hours:g} h, dt {DT_S:g} s,"
        f" sample {SAMPLE_S:g} s)",
        "",
        "Estimated steady-state gain on p80 (mean +/- std over seeds);",
        "the true gain is quoted at ore hardness 14.",
        "",
    ]
    for driver in DRIVERS:
        lines += build_driver_section(rows, driver)
    return lines


def build_driver_section(rows: list[dict[str, object]], driver: str) -> list[str]:
    """Return the markdown lines for one driver: its heading plus the variant/scenario table."""
    # The true gain is a per-driver constant, so any row for this driver carries it.
    true_gain = next(row["true_gain"] for row in rows if row["driver"] == driver)
    lines = [f"## {driver} -> p80 (true gain at h = 14: {true_gain:.3f})", ""]
    lines += ["| variant | " + " | ".join(SCENARIOS) + " |", "|---|" + "---|" * len(SCENARIOS)]
    for variant in VARIANTS:
        lines.append(build_variant_row(rows, driver, variant))
    lines.append("")
    return lines


def build_variant_row(rows: list[dict[str, object]], driver: str, variant: str) -> str:
    """Return one markdown table row: the variant name followed by a cell per scenario."""
    cells = [format_cell(rows, driver, variant, scenario_name) for scenario_name in SCENARIOS]
    return f"| {variant} | " + " | ".join(cells) + " |"


def format_cell(
    rows: list[dict[str, object]], driver: str, variant: str, scenario_name: str
) -> str:
    """Return the "mean +/- std" cell for one driver/variant/scenario combination."""
    measured_row = find_measurement_row(rows, driver, variant, scenario_name)
    return f"{measured_row['mean']:.3f} +/- {measured_row['std']:.3f}"


def find_measurement_row(
    rows: list[dict[str, object]], driver: str, variant: str, scenario_name: str
) -> dict[str, object]:
    """Return the single row matching driver, variant and scenario.

    Raises:
        StopIteration: when no row matches the given combination.
    """
    return next(
        row
        for row in rows
        if row["scenario"] == scenario_name
        and row["variant"] == variant
        and row["driver"] == driver
    )


def plot(rows: list[dict[str, object]], out_dir: Path) -> None:
    """Write a gains.png chart, one subplot per driver, into out_dir."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:  # plotting is optional
        return
    fig, axes = plt.subplots(1, len(DRIVERS), figsize=(15, 4.5), sharey=False)
    for ax, driver in zip(axes, DRIVERS, strict=True):
        _plot_driver(ax, rows, driver)
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "gains.png", dpi=130)
    plt.close(fig)


def _plot_driver(ax: Any, rows: list[dict[str, object]], driver: str) -> None:
    """Draw all scenario bars and the true-gain line for one driver on `ax`."""
    selected_rows = [row for row in rows if row["driver"] == driver]
    true_gain = cast(float, selected_rows[0]["true_gain"])
    for scenario_index, scenario_name in enumerate(SCENARIOS):
        _plot_scenario(ax, selected_rows, scenario_name, scenario_index)
    ax.axhline(true_gain, color="k", linestyle="--", linewidth=1, label="true gain (h = 14)")
    ax.set_title(f"{driver} -> p80")
    ax.set_xticks(np.arange(len(VARIANTS)))
    ax.set_xticklabels(VARIANTS, rotation=40, ha="right", fontsize=8)
    ax.axhline(0.0, color="grey", linewidth=0.5)


def _plot_scenario(
    ax: object,
    selected_rows: list[dict[str, object]],
    scenario_name: str,
    scenario_index: int,
) -> None:
    """Draw one grouped bar (one bar per variant) for a scenario on `ax`."""
    width = 0.38
    means = [_lookup_float(selected_rows, scenario_name, variant, "mean") for variant in VARIANTS]
    stds = [_lookup_float(selected_rows, scenario_name, variant, "std") for variant in VARIANTS]
    x = np.arange(len(VARIANTS)) + (scenario_index - 0.5) * width
    ax.bar(x, means, width, yerr=np.nan_to_num(stds), label=scenario_name, capsize=2)


def _lookup_float(
    selected_rows: list[dict[str, object]],
    scenario_name: str,
    variant: str,
    field: str,
) -> float:
    """Return the `field` value of the row matching scenario and variant; raise if missing."""
    for row in selected_rows:
        if row["scenario"] == scenario_name and row["variant"] == variant:
            return cast(float, row[field])
    raise KeyError(f"no row for scenario={scenario_name!r}, variant={variant!r}, field={field!r}")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line, run the gain identification experiment, and report how many rows
    were written."""
    parser = argparse.ArgumentParser(
        description="Experiment 0: SP-based versus MV-based gain identification."
    )
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--hours", type=float, default=48.0)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    args = parser.parse_args(argv)
    rows = run(args.seeds, args.hours, args.out)
    print(f"wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

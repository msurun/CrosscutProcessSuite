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
from typing import cast

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
SP_TAGS = {d: f"sim.mc.{d}_sp" for d in DRIVERS}
PV_TAGS = {d: f"sim.mc.{d}" for d in DRIVERS}
OUT_TAGS = {d: f"sim.mc.{d}_out" for d in DRIVERS}
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
    n = len(y)
    rows = n - n_lags + 1
    columns = [np.ones(rows)]
    for x in inputs:
        for lag in range(n_lags):
            columns.append(x[n_lags - 1 - lag : n - lag])
    design = np.column_stack(columns)
    coefficients, *_ = np.linalg.lstsq(design, y[n_lags - 1 :], rcond=None)
    gains = []
    for k in range(len(inputs)):
        start = 1 + k * n_lags
        gains.append(float(coefficients[start : start + n_lags].sum()))
    return np.array(gains)


def simulate(seed: int, scenario_name: str, hours: float, workdir: Path) -> dict[str, np.ndarray]:
    """Record a mill-circuit run through the dataset pipeline and read it back in wide format."""
    scenario = build_scenario("mill_circuit", scenario_name, duration_s=hours * 3600.0)
    scenario = type(scenario)(
        name=scenario.name,
        duration_s=scenario.duration_s,
        dt_s=DT_S,
        measurement_noise=scenario.measurement_noise,
        disturbance_sigma=scenario.disturbance_sigma,
        disturbance_tau_s=scenario.disturbance_tau_s,
        events=scenario.events,
        params=scenario.params,
    )
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
    inputs = [wide[tags[d]] for d in DRIVERS]
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
    plant = MillCircuitPlant()
    return {d: plant.true_gain(d, CV, 14.0) for d in DRIVERS}


def run(seeds: int, hours: float, out_dir: Path) -> list[dict[str, object]]:
    """Run all scenarios, seeds and variants; one result row per (scenario, variant, driver)."""
    estimates: dict[tuple[str, str], list[np.ndarray]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for scenario_name in SCENARIOS:
            for seed in range(1, seeds + 1):
                wide = simulate(seed, scenario_name, hours, Path(tmp))
                for variant in VARIANTS:
                    estimates.setdefault((scenario_name, variant), []).append(
                        estimate(wide, variant)
                    )
    truth = true_gains()
    rows: list[dict[str, object]] = []
    for (scenario_name, variant), runs in estimates.items():
        stacked = np.vstack(runs)
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
    out_dir.mkdir(parents=True, exist_ok=True)
    write_outputs(rows, out_dir, seeds, hours)
    return rows


def write_outputs(rows: list[dict[str, object]], out_dir: Path, seeds: int, hours: float) -> None:
    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        f"# Experiment 0 results ({seeds} seeds x {hours:g} h, dt {DT_S:g} s,"
        f" sample {SAMPLE_S:g} s)",
        "",
        "Estimated steady-state gain on p80 (mean +/- std over seeds);",
        "the true gain is quoted at ore hardness 14.",
        "",
    ]
    for driver in DRIVERS:
        truth = next(r["true_gain"] for r in rows if r["driver"] == driver)
        lines += [f"## {driver} -> p80 (true gain at h = 14: {truth:.3f})", ""]
        lines += ["| variant | " + " | ".join(SCENARIOS) + " |", "|---|" + "---|" * len(SCENARIOS)]
        for variant in VARIANTS:
            cells = []
            for scenario_name in SCENARIOS:
                r = next(
                    x
                    for x in rows
                    if x["scenario"] == scenario_name
                    and x["variant"] == variant
                    and x["driver"] == driver
                )
                cells.append(f"{r['mean']:.3f} +/- {r['std']:.3f}")
            lines.append(f"| {variant} | " + " | ".join(cells) + " |")
        lines.append("")
    (out_dir / "results.md").write_text("\n".join(lines), encoding="utf-8")
    plot(rows, out_dir)


def plot(rows: list[dict[str, object]], out_dir: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:  # plotting is optional
        return
    fig, axes = plt.subplots(1, len(DRIVERS), figsize=(15, 4.5), sharey=False)
    width = 0.38
    for ax, driver in zip(axes, DRIVERS, strict=True):
        sel = [r for r in rows if r["driver"] == driver]
        truth = cast(float, sel[0]["true_gain"])
        for i, scenario_name in enumerate(SCENARIOS):
            means = [
                cast(
                    float,
                    next(
                        r["mean"]
                        for r in sel
                        if r["scenario"] == scenario_name and r["variant"] == v
                    ),
                )
                for v in VARIANTS
            ]
            stds = [
                cast(
                    float,
                    next(
                        r["std"]
                        for r in sel
                        if r["scenario"] == scenario_name and r["variant"] == v
                    ),
                )
                for v in VARIANTS
            ]
            x = np.arange(len(VARIANTS)) + (i - 0.5) * width
            ax.bar(x, means, width, yerr=np.nan_to_num(stds), label=scenario_name, capsize=2)
        ax.axhline(truth, color="k", linestyle="--", linewidth=1, label="true gain (h = 14)")
        ax.set_title(f"{driver} -> p80")
        ax.set_xticks(np.arange(len(VARIANTS)))
        ax.set_xticklabels(VARIANTS, rotation=40, ha="right", fontsize=8)
        ax.axhline(0.0, color="grey", linewidth=0.5)
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "gains.png", dpi=130)
    plt.close(fig)


def main(argv: Sequence[str] | None = None) -> int:
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

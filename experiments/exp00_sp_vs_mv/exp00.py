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
    """Least-squares FIR fit with an intercept; returns the sum of coefficients per input.

    Model (a finite impulse response, FIR, linear model):

        y[t] = intercept + sum over inputs x of sum over lags j of b[x, j] * x[t - j]

    One "gain" per input is reported: the sum of that input's lag coefficients.
    Summing is a convention, not an optimisation: it describes the total steady-state
    effect (a unit step in x) if the input is held constant, and it keeps the
    reporting compact when the individual lag weights are not of interest.

    Correlated inputs make the individual coefficients unstable (multicollinearity),
    so only the summed gains are returned.

    Returns:
        (n_inputs,) array where entry ``k`` is the summed FIR gain, in y-units
        per x-units, for ``inputs[k]``. Raises ``np.linalg.LinAlgError`` if the
        fit fails to converge.
    """
    n_samples = len(y)
    # Each row of the design matrix is one timestep t of the fit. Only timesteps
    # with a full history of n_lags samples (so x[t], x[t-1], ..., x[t-n_lags+1]
    # all exist) can be used, leaving n_samples - n_lags + 1 rows.
    rows = n_samples - n_lags + 1
    # Column 0 is the intercept term: a constant 1 in every row.
    columns = [np.ones(rows)]
    # For each input, n_lags columns hold that input's history, one column per lag.
    # Rows span t = n_lags - 1 .. n_samples - 1. For row index r (t = r + n_lags - 1)
    # and lag j in 0..n_lags-1, the column holds x[t - j] = x[r + n_lags - 1 - j].
    # Hence, for lag j, the slice start is n_lags - 1 - j and the slice end is
    # n_samples - j: this shifts the sample window left as the lag grows.
    for x in inputs:
        for lag in range(n_lags):
            columns.append(x[n_lags - 1 - lag : n_samples - lag])
    # np.column_stack builds one 2-D array. Shape is (rows, 1 + n_inputs * n_lags):
    # column index 0 is the intercept; then n_lags contiguous columns per input.
    design = np.column_stack(columns)
    # Ordinary least squares: solve design @ beta ~= y at the fitted timesteps.
    # y[n_lags - 1 :] aligns the response with the first usable design row.
    # rcond=None uses numpy's default cutoff for small singular values.
    # lstsq returns (solution, residuals, rank, singular_values); only the first
    # element, the coefficient vector, is used here.
    coefficients, *_ = np.linalg.lstsq(design, y[n_lags - 1 :], rcond=None)
    gains = []
    for k in range(len(inputs)):
        # Column layout per input k starts after the intercept column (index 0)
        # and the k preceding inputs' n_lags columns.
        start = 1 + k * n_lags
        # Sum this input's n_lags coefficients into a single gain (as documented
        # in the docstring). float() converts the numpy scalar to a plain Python
        # float so the final array is a clean, 1-D numpy array.
        gains.append(float(coefficients[start : start + n_lags].sum()))
    return np.array(gains)


def with_simulation_step(scenario: Any) -> Any:
    """Return a copy of the scenario that runs at the experiment's simulation step DT_S.

    A simulation step is the fixed time interval, in seconds, at which the model advances its
    state: halving it doubles the number of integration steps and, usually, the accuracy and the
    run time. Every other setting of the scenario is copied unchanged, so only the time resolution
    of the run differs. The result is a new object; the input scenario is left untouched.
    """
    # Scenarios are usually created by callers with their own step size, but an experiment must
    # compare runs on a single, common time grid. Rather than mutating the caller's object, we
    # build a fresh scenario of the same class, passing every field through by name; the only
    # value we override is dt_s, the integration step in seconds.
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
    """Record a mill-circuit run through the dataset pipeline and read it back in wide format.

    The mill circuit is a closed-loop grinding circuit: ore is fed to a mill, the mill discharges
    into a sump, and a pump sends the sump slurry through a hydrocyclone that splits it into a
    fine overflow (product) and a coarse underflow recycled back to the mill. The scenario holds
    the starting state and the operating schedule; the plant holds the physics.

    A run is executed in two passes: `record` drives the plant over the scenario and writes the
    samples to disk, then `read_dataset`/`to_wide` load them back. The disk round-trip is not
    busywork — it guarantees the returned data is exactly what a consumer of the dataset would
    see, so a formatting bug cannot hide behind a live in-memory trajectory.

    Parameters:
        seed: Seed for the simulator's random number generator. Runs with the same seed and
            scenario reproduce bit-for-bit; different seeds give different disturbances.
        scenario_name: Name of the scenario variant to look up in the "mill_circuit" scenario set.
        hours: Run length in hours (converted to seconds below, since the simulator works in SI).
        workdir: Directory the run's output folder is created in.

    Returns:
        The dataset in wide format: one entry per recorded variable, each value an array whose
        first axis is time. The time axis is shared by every entry.

    Raises:
        Whatever `build_scenario`, `record` or `read_dataset` raises: an unknown scenario name,
        an unwritable output folder, or a corrupt dataset on disk.
    """
    scenario = build_scenario("mill_circuit", scenario_name, duration_s=hours * 3600.0)
    # Attach the plant's simulation step so the recorder knows how far to advance the plant
    # between two samples; without it the scenario only describes the operating schedule.
    scenario = with_simulation_step(scenario)
    # Each run gets its own folder named after the scenario and seed: same inputs -> same folder,
    # so re-running is idempotent and two seeds never overwrite each other's data.
    out = workdir / f"{scenario_name}_seed{seed}"
    record(
        MillCircuitPlant(),
        scenario,
        out,
        seed=seed,
        dataset_id=out.name,
        plant_name="mill_circuit",
        scenario_name=scenario_name,
        # Sampling period in seconds; the dataset resamples the plant's internal integration step
        # down to this coarser grid, which is what downstream models are trained on.
        sample_period_s=SAMPLE_S,
    )
    # `read_dataset` returns (metadata, long-format frames) — one row per (time, variable) pair.
    # `to_wide` pivots that into one column per variable, which is the layout we return.
    _, wide = to_wide(read_dataset(out))
    return wide


def estimate(wide: dict[str, np.ndarray], variant: str) -> np.ndarray:
    """Gains of the three drivers on p80 for one signal variant.

    Fits an FIR (finite impulse response) regression of the target signal on the driver signals
    and returns one gain per driver.

    Parameters
    ----------
    wide:
        Column-oriented table: tag -> 1-D signal array (one sample per time step).
    variant:
        Signal variant name, e.g. "<family> hardness" or "<family> high-pass". The family token
        (first word) selects which tag set the drivers are read from.

    Returns
    -------
    np.ndarray
        Gain (dimensionless, unit of target per unit of driver) for each of the DRIVERS, in order.
    """
    y = wide[CV_TAG]
    # The variant name is "<family> [modifier]"; the family token picks the tag dictionary that
    # says which signal tag belongs to each driver.
    family = variant.split()[0]
    tags = {"SP": SP_TAGS, "PV": PV_TAGS, "OUT": OUT_TAGS}[family]
    inputs = [wide[tags[driver]] for driver in DRIVERS]
    # Regressors that are not driver signals, e.g. a hardness estimate. Empty unless the variant
    # asks for them.
    extra: list[np.ndarray] = []
    if variant.endswith("hardness"):
        extra.append(wide[HARDNESS_EST_TAG])
    if variant.endswith("high-pass"):
        # high-pass variants remove the slow drift; run the same filter on target and drivers so
        # that the fitted gains are not biased by the filter.
        inputs = [highpass(x, HIGHPASS_SAMPLES) for x in inputs]
        y = highpass(y, HIGHPASS_SAMPLES)
    # The filter has a transient at both ends where its output is not valid; cut the same window
    # from every signal (raw variants too) so all arrays stay sample-aligned with each other.
    trim = HIGHPASS_SAMPLES  # number of samples dropped at each end
    inputs = [x[trim:-trim] for x in inputs]
    extra = [x[trim:-trim] for x in extra]
    y = y[trim:-trim]
    # fir_gains returns one gain per regressor (drivers first, then extra terms); keep only the
    # driver gains, dropping the regressors appended by the "hardness" variant.
    return fir_gains(y, [*inputs, *extra], N_LAGS)[: len(DRIVERS)]


def true_gains() -> dict[str, float]:
    """Ground-truth steady-state gains of the three drivers on p80 at ore hardness 14."""
    plant = MillCircuitPlant()
    return {driver: plant.true_gain(driver, CV, 14.0) for driver in DRIVERS}


def run(seeds: int, hours: float, out_dir: Path) -> list[dict[str, object]]:
    """Run all scenarios, seeds and variants; one result row per (scenario, variant, driver).

    A "scenario" is one data-collection setting to evaluate, a "variant" one way of estimating
    gains inside it, a "seed" one independent random repetition, and a "driver" one processed
    unit of work. `hours` is the simulated window in hours. Results are written under `out_dir`
    and also returned, so callers can use them without re-reading the files.

    Returns the list of result rows, one dict per (scenario, variant, driver).
    """
    # Measure every (scenario, variant, seed) combination. `estimates` holds the measured
    # gain values; `true_gains` below is the ground truth they will be compared against.
    estimates = collect_estimates(seeds, hours)
    # Compare each estimate with the true gain it tries to recover, giving one row per
    # (scenario, variant, driver) with the error metrics for that combination.
    rows = summarize(estimates, true_gains())
    # Create the report directory (and any missing parents); harmless if it already exists.
    out_dir.mkdir(parents=True, exist_ok=True)
    # Persist the rows as files (tables and/or plots) inside `out_dir`, for later reading.
    write_outputs(rows, out_dir, seeds, hours)
    return rows


def collect_estimates(seeds: int, hours: float) -> dict[tuple[str, str], list[np.ndarray]]:
    """Simulate every scenario and seed; group the gain estimates by (scenario, variant).

    Runs the whole simulation grid: each scenario in SCENARIOS is simulated once per
    seed in 1..seeds, and each run contributes one gain estimate per variant.

    Arguments:
        seeds: number of independent replications per scenario, one per seed; more
            seeds give a tighter Monte-Carlo confidence band on the mean gain.
        hours: simulated time span of a single run, in hours.

    Returns:
        ``{(scenario_name, variant_name): [gain arrays, one per seed]}``. The lists
        are ordered by increasing seed, so index 0 is seed 1.
    """

    # Accumulator filled in place by _add_variant_estimates: keys are
    # (scenario name, variant name) pairs, values are the per-seed gain arrays
    # appended in seed order.
    estimates: dict[tuple[str, str], list[np.ndarray]] = {}

    # A TemporaryDirectory cleans up its contents on exit; simulate() writes its
    # intermediate files there so the grid leaves nothing behind on disk.
    with tempfile.TemporaryDirectory() as tmp:
        for scenario_name in SCENARIOS:

            # Seeds start at 1 (not 0) so every run is reproducible and seed 0 is
            # never mistaken for "no seed given".
            for seed in range(1, seeds + 1):
                # "wide" is the long-format result of one run: one row per
                # (variant, time step) with the simulated gain.
                wide = simulate(seed, scenario_name, hours, Path(tmp))
                _add_variant_estimates(estimates, scenario_name, wide)

    return estimates


def _add_variant_estimates(
    estimates: dict[tuple[str, str], list[np.ndarray]],
    scenario_name: str,
    wide: dict[str, np.ndarray],
) -> None:
    """Append the gain estimate of every signal variant for one simulated run.

    A "variant" is one way of processing the raw signals of a run (for example raw, filtered, or
    normalised); each variant yields one gain estimate. This function is called once per simulated
    run, so calling it repeatedly accumulates one estimate per run in the list of each variant.

    Parameters
    ----------
    estimates
        Accumulator, keyed by (scenario name, variant name). The list in each entry holds one
        gain estimate per simulated run, in call order; its length is the number of runs seen so
        far. The key is created on first use, so the dict may start empty.
    scenario_name
        Name of the simulated scenario this run belongs to.
    wide
        Signals of this run in wide format: one array per column name, all sharing the same time
        axis.
    """
    # One accumulator entry per (scenario, variant) pair; setdefault creates the list the first
    # time a pair shows up and the loop over runs keeps appending to it afterwards.
    for variant in VARIANTS:
        estimates.setdefault((scenario_name, variant), []).append(estimate(wide, variant))


def summarize(
    estimates: dict[tuple[str, str], list[np.ndarray]], truth: dict[str, float]
) -> list[dict[str, object]]:
    """Turn the grouped estimates into one mean/std row per (scenario, variant, driver).

    Each key of `estimates` is a (scenario, variant) pair and its value is the list of
    per-run estimates for that pair, one array per driver. `truth` maps a driver name to
    its known true value, used to score the estimates. Returns one flat list of rows,
    each row a dict describing a single (scenario, variant, driver) combination, so the
    caller can hand it straight to a table or CSV writer.
    """
    # Flat list of result rows. We build it here and let the per-group helper return
    # its own rows, then extend (not append) so the nesting of the two dicts disappears:
    # the final structure is a plain list of independent records, an invariant the
    # downstream writer relies on.
    rows: list[dict[str, object]] = []
    # One iteration per (scenario, variant) group. `runs` is the list of arrays for
    # that group, and the helper expands it into one row per driver.
    for (scenario_name, variant), runs in estimates.items():
        rows.extend(_summary_rows(scenario_name, variant, runs, truth))
    return rows


def _summary_rows(
    scenario_name: str, variant: str, runs: list[np.ndarray], truth: dict[str, float]
) -> list[dict[str, object]]:
    """Mean and sample standard deviation over the runs, for each driver of one variant.

    What it computes: for every estimated "gain" (a scalar the model fits for one driver),
    the average and the spread across repeated runs of the same scenario/variant.

    Returns a list of one flat dict per driver, ready to become a row of a results table.
    """
    # `runs` is one array per repetition of the experiment; each array holds one estimated
    # gain per driver, in the fixed order given by DRIVERS. Stacking turns the per-run 1-D
    # arrays into a 2-D array of shape (n_runs, n_drivers), so column j is the whole sample
    # of the j-th driver across runs -- one column per driver, one row per run.
    stacked = np.vstack(runs)
    rows: list[dict[str, object]] = []
    for j, driver in enumerate(DRIVERS):
        rows.append(
            {
                # Which experiment this row belongs to, so rows from several scenarios and
                # variants can be concatenated into a single table.
                "scenario": scenario_name,
                "variant": variant,
                # DRIVERS[j] is the name of the driver whose column we are summarising.
                "driver": driver,
                # The reference value the estimate is trying to recover (same unit as the
                # estimate, here a gain ratio, dimensionless). Used later to score accuracy.
                "true_gain": truth[driver],
                # Sample mean of that driver over the runs, in the driver's own unit.
                "mean": float(stacked[:, j].mean()),
                # Sample standard deviation with Bessel's correction (ddof=1 divides by n-1,
                # the unbiased estimator). With a single run there is no spread to estimate,
                # so we report nan instead of the 0.0 that ddof=1 would silently produce.
                "std": float(stacked[:, j].std(ddof=1)) if len(runs) > 1 else float("nan"),
                # How many runs went into `mean` and `std`; kept in the row so downstream
                # analysis knows how much weight the summary deserves.
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
    """Return the markdown report lines: a header, then one section per driver.

    The report describes a simulation ensemble: each *driver* is the manipulated
    input, and `rows` holds one entry per (driver, seed) run. All rows were
    produced with the same physical configuration, so they can be averaged.

    Args:
        rows: one dict per simulated run, in the schema produced by the runner.
        seeds: number of random seeds per driver (UNIT: runs, dimensionless count).
        hours: simulated duration of every run (UNIT: hours).

    Returns:
        The report as a list of markdown lines, blank lines included.
    """
    # Provenance header: state the ensemble size and the two sampling intervals so a
    # reader can tell how the numbers below were produced. DT_S is the simulation step
    # (UNIT: seconds), SAMPLE_S the interval at which outputs were recorded (UNIT:
    # seconds); both are module-level constants of the experiment.
    lines = [
        f"# Experiment 0 results ({seeds} seeds x {hours:g} h, dt {DT_S:g} s,"
        f" sample {SAMPLE_S:g} s)",
        "",
        "Estimated steady-state gain on p80 (mean +/- std over seeds);",
        "the true gain is quoted at ore hardness 14.",
        "",
    ]
    # DRIVERS fixes the section order, so two reports of the same experiment are
    # diff-friendly. Each call appends that driver's subsection (title, table, notes).
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

    A "row" is one measurement record loaded from the results table: a dict
    keyed by column name ("scenario", "variant", "driver", ...). The triple
    (scenario, variant, driver) is the unique key of the table, so at most
    one row can match.

    Raises:
        StopIteration: when no row matches the given combination. Callers
            normally wrap this call in try/except StopIteration.
    """
    # all() of the three equalities, short-circuiting on the first mismatch.
    # next() pulls the first (and, by the unique-key invariant, only) match,
    # or raises StopIteration if the generator is exhausted.
    return next(
        row
        for row in rows
        if row["scenario"] == scenario_name
        and row["variant"] == variant
        and row["driver"] == driver
    )


def plot(rows: list[dict[str, object]], out_dir: Path) -> None:
    """Write a gains.png chart, one subplot per driver, into out_dir.

    One subplot is drawn per driver in DRIVERS. A "gain" is the percentage of the initial
    input recovered at the output, in percent (100 % means no loss). The chart lets the
    reader compare how each driver responds as the input varies.

    Args:
        rows: Experiment results, each a dict with an "input" key (the value fed in) and
            one gain key per driver holding the percentage recovered, e.g. 87.5 for 87.5 %.
        out_dir: Directory where gains.png is written; must already exist.

    Returns:
        None. If matplotlib is not installed the function returns quietly: charting is an
        optional extra, and its absence must not fail the caller.

    Raises:
        KeyError: If rows lack a driver key needed for a curve.
        OSError: If out_dir is missing or not writable.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:  # plotting is optional
        return
    # "Agg" above selects a backend that draws straight to a raster file, so this works
    # on a headless machine with no display. One row of len(DRIVERS) subplots lays the
    # drivers side by side for comparison; sharey=False keeps each driver's own y-scale.
    fig, axes = plt.subplots(1, len(DRIVERS), figsize=(15, 4.5), sharey=False)
    # strict=True asserts axes and DRIVERS have equal length: a mismatch means these two
    # lists have drifted apart, and silently dropping a driver would hide that bug.
    for ax, driver in zip(axes, DRIVERS, strict=True):
        _plot_driver(ax, rows, driver)
    # Only the first subplot gets a legend; all subplots share the same series labels, so
    # repeating it on every panel would be visual noise.
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    # 130 dpi is a compromise between legible text and a file small enough to attach.
    fig.savefig(out_dir / "gains.png", dpi=130)
    plt.close(fig)


def _plot_driver(ax: Any, rows: list[dict[str, object]], driver: str) -> None:
    """Draw all scenario bars and the true-gain line for one driver on `ax`.

    A "driver" is an input feature the forecast is attributed to; a "scenario" is a way of
    measuring that attribution (e.g. shuffle, retrain). Attributes are expressed as gains in
    some target metric over a no-driver baseline, so 0 means "no contribution".

    Args:
        ax: Matplotlib axes to draw on, already created and laid out by the caller.
        rows: One dict per (driver, scenario, variant) measurement. Each dict holds at least
            the keys "driver", "true_gain" and whatever `_plot_scenario` reads.
        driver: The driver to filter `rows` down to; one figure per driver.

    Raises:
        IndexError: If `rows` contains nothing for `driver`.
    """
    selected_rows = [row for row in rows if row["driver"] == driver]
    # Every measurement of this driver carries the same reference value, so taking it from the
    # first row is enough; "true_gain" is the gain [target metric units, typically USD] that a
    # horizon-14 forecast of the real (non-permuted) data achieves.
    true_gain = cast(float, selected_rows[0]["true_gain"])
    for scenario_index, scenario_name in enumerate(SCENARIOS):
        _plot_scenario(ax, selected_rows, scenario_name, scenario_index)
    # Horizontal reference line at the honest-model gain, so bars can be read as a fraction of it.
    # Dashed black, deliberately distinct from the grey zero line drawn below.
    ax.axhline(true_gain, color="k", linestyle="--", linewidth=1, label="true gain (h = 14)")
    # p80 = the 80th percentile: the y values are quantile statistics, not means.
    ax.set_title(f"{driver} -> p80")
    # X axis is categorical: place one tick at each integer bar position (0..len(VARIANTS)-1),
    # then replace the numbers by the variant names. Rotating 40 deg avoids label overlap.
    ax.set_xticks(np.arange(len(VARIANTS)))
    ax.set_xticklabels(VARIANTS, rotation=40, ha="right", fontsize=8)
    # Baseline line at gain 0: anything above it is a positive attribution.
    ax.axhline(0.0, color="grey", linewidth=0.5)


def _plot_scenario(
    ax: object,
    selected_rows: list[dict[str, object]],
    scenario_name: str,
    scenario_index: int,
) -> None:
    """Draw one grouped bar (one bar per variant) for a scenario on `ax`.

    Each variant's bar is plotted at its own x position so that several
    scenarios can share one axis side by side (a "grouped" bar chart).
    Error bars are drawn from the per-variant standard deviation.
    """
    # Fraction of a variant's x slot that one scenario bar occupies; the rest
    # of the slot is left blank so neighbouring scenario bars do not touch.
    width = 0.38
    # Mean metric value for this scenario, one entry per variant. `means` and
    # `stds` are aligned with VARIANTS: index i refers to VARIANTS[i].
    means = [_lookup_float(selected_rows, scenario_name, variant, "mean") for variant in VARIANTS]
    # Same alignment, but each entry is the standard deviation of that mean.
    # `np.nan_to_num` turns a missing (NaN) std into 0 so the error bar is
    # simply not drawn rather than making the whole bar disappear.
    stds = [_lookup_float(selected_rows, scenario_name, variant, "std") for variant in VARIANTS]
    # `scenario_index` is the 0-based position of this scenario among the
    # scenarios drawn on this axis. The `- 0.5 * width` term centres the group
    # of scenario bars on each variant's integer x slot, and shifting by
    # `scenario_index * width` spaces the scenarios within that slot.
    x = np.arange(len(VARIANTS)) + (scenario_index - 0.5) * width
    # `label=scenario_name` makes matplotlib list this scenario in the legend.
    # `capsize=2` adds the small horizontal ticks at the ends of the error bars.
    ax.bar(x, means, width, yerr=np.nan_to_num(stds), label=scenario_name, capsize=2)


def _lookup_float(
    selected_rows: list[dict[str, object]],
    scenario_name: str,
    variant: str,
    field: str,
) -> float:
    """Return the `field` value of the row matching scenario and variant; raise if missing.

    The table is modelled as a list of row dicts, where each dict has the keys
    "scenario", "variant" and any number of numeric fields (e.g. "capex_usd").
    The (scenario, variant) pair is the composite key that uniquely identifies a
    row; the invariant is that it appears at most once.

    The per-row match below is what makes another scenario's or variant's row
    unavailable, which is why a missing key raises instead of returning a
    sentinel like 0.0 or None: a silent zero would flow into later arithmetic
    and be indistinguishable from a genuine zero value.
    """
    # Linear scan over the rows. Rows are few (one per scenario/variant combo),
    # so O(n) per lookup is fine and no index by composite key is built.
    for row in selected_rows:
        # Compare both halves of the composite key; equality is exact, so a
        # scenario name differing only by case or whitespace does not match.
        if row["scenario"] == scenario_name and row["variant"] == variant:
            # row[field] is typed `object` (the dict's value type), so cast()
            # tells the type checker it is a float, as documented for every
            # numeric field in this table. cast() is a no-op at runtime and
            # adds no error checking; the caller relies on the data contract.
            return cast(float, row[field])
    # No matching row was found: surface the three lookup inputs so the caller
    # can see whether the scenario, the variant or the field name was wrong.
    raise KeyError(f"no row for scenario={scenario_name!r}, variant={variant!r}, field={field!r}")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line, run the gain identification experiment, and report how many rows
    were written.

    Returns the process exit code: 0 when the experiment completed.
    """
    # argparse turns the raw command-line tokens (`argv`, or sys.argv[1:] when None) into an
    # `args` object. `--seeds` is the number of independent runs (Monte-Carlo replicates of the
    # same scenario, each with its own random noise); `--hours` is the simulated duration in
    # hours; `--out` is the directory the result CSV/table is written to, defaulting next to
    # this file so the experiment works no matter the current working directory.
    parser = argparse.ArgumentParser(
        description="Experiment 0: SP-based versus MV-based gain identification."
    )
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--hours", type=float, default=48.0)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results")

    # This is the only place command-line text becomes typed Python values.
    args = parser.parse_args(argv)

    # `run` performs the actual simulation and identification (the side effects: sim, files on
    # disk). It returns one row per (seed, method) comparison, so `len(rows)` is the number of
    # SP-versus-MV pairings written, not the number of seeds.
    rows = run(args.seeds, args.hours, args.out)
    print(f"wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

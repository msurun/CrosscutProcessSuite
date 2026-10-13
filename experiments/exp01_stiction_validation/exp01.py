"""Validate crosscut_loops.stiction.detect_stiction against the mill-circuit simulator.

Ground truth: the "stiction" scenario lets us set a valve stiction band and jump (in percent of
the actuator span) and switch the operator off. A band of 0 % means a healthy valve, so the
detector should answer "no_stiction"; a band above 0 % should give "stiction". We sweep band,
measurement noise and seeds, and tabulate the verdict counts.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
from crosscut_loops.stiction import detect_stiction
from crosscut_sim.core import Event
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario

RUN_HOURS = 6.0  # simulated length of one run
SEEDS = range(1, 6)  # repetition seeds, one independent run each
BANDS_PERCENT = (0.0, 2.0, 4.0, 8.0)  # valve stiction band, percent of actuator span
JUMP_RATIO = 0.5  # stiction jump as a fraction of the band (jump <= band is required)
NOISE_LEVELS = ("full", "low")  # "low" overrides measurement and inner noise
LOW_MEASUREMENT_NOISE = 0.1  # measurement-noise std, engineering units
LOW_INNER_NOISE = 0.0  # controller inner-loop noise, engineering units
SETPOINT_TAG = "sim.mc.hpgr_press_sp"
SETPOINT_STEP = 1.0  # persistent offset that makes a sticking valve hunt, engineering units
STEP_TIME_S = 1800.0  # the setpoint moves once, 30 min into the run
ANALYSIS_START_S = 7200.0  # the detector sees only the settled part, after the first 2 h
OPERATOR_OFF = 0.0  # operator gain; 0 keeps the loop unexcited by hand moves

PV_TAG = "sim.mc.hpgr_press"
OUT_TAG = "sim.mc.hpgr_press_out"
BAND_TAG = "stiction_band_hpgr_press"
JUMP_TAG = "stiction_jump_hpgr_press"
OPERATOR_TAG = "operator"
INNER_NOISE_TAG = "inner_noise"
MEASUREMENT_NOISE_KEY = "measurement_noise"

VERDICTS = ("stiction", "no_stiction", "inconclusive")
RESULTS_PATH = Path(__file__).parent / "results" / "summary.md"


def _override(
    params: tuple[tuple[str, float], ...], **overrides: float
) -> tuple[tuple[str, float], ...]:
    """Return `params` with the named keys replaced by the given values.
    """
    known = dict(params)
    for key, value in overrides.items():
        known[key] = value
    return tuple(known.items())


def _configure_scenario(band_percent: float, noise: str):
    """Return the "stiction" scenario configured for one band and noise level.

    `band_percent` is the stiction band in percent of the actuator span; 0 means a
    healthy valve. `noise` selects the default ("full") or the reduced ("low")
    measurement and inner-loop noise.
    """
    scenario = build_scenario("mill_circuit", "stiction", duration_s=RUN_HOURS * 3600.0)
    params = _override(
        scenario.params,
        **{
            BAND_TAG: band_percent,
            JUMP_TAG: band_percent * JUMP_RATIO,
            OPERATOR_TAG: OPERATOR_OFF,
        },
    )
    if noise == "low":
        params = _override(params, **{INNER_NOISE_TAG: LOW_INNER_NOISE})
        scenario = dataclasses.replace(
            scenario, params=params, measurement_noise=LOW_MEASUREMENT_NOISE
        )
    elif noise == "full":
        scenario = dataclasses.replace(scenario, params=params)
    else:
        raise ValueError(f"unknown noise level {noise!r}; expected one of {NOISE_LEVELS}")
    return scenario


def simulate_loop(
    seed: int, band_percent: float, noise: str
) -> tuple[np.ndarray, np.ndarray, float]:
    """Run the stiction scenario and return the recorded (pv, out, dt_s) traces.

    The plant advances one step of `dt_s` seconds per sample:

        state[t + 1] = f(state[t], inputs[t]),  t = 0 .. n_steps - 1

    so the number of samples is the run duration divided by `dt_s`. Both signals
    are stored every step, because stiction detection needs the full resolution
    of the oscillation, not a decimated record.

    Returns:
        pv: HPGR press pressure samples (process variable), engineering units.
        out: controller output (OUT) samples, engineering units.
        dt_s: sampling period in seconds, shared by both arrays.
    """
    scenario = _configure_scenario(band_percent, noise)
    plant = MillCircuitPlant()
    plant.reset(seed, scenario)
    # A loop already at its setpoint never leaves the valve deadband, so no limit cycle starts.
    nominal_setpoint = plant.read(SETPOINT_TAG)[0]
    step_event = Event(t_s=STEP_TIME_S, tag_id=SETPOINT_TAG, value=nominal_setpoint + SETPOINT_STEP)
    scenario = dataclasses.replace(scenario, events=(step_event,))
    plant.reset(seed, scenario)
    n_steps = int(round(scenario.duration_s / scenario.dt_s))
    pv = np.empty(n_steps, dtype=np.float64)
    out = np.empty(n_steps, dtype=np.float64)
    for step in range(n_steps):
        pv[step] = plant.read(PV_TAG)[0]
        out[step] = plant.read(OUT_TAG)[0]
        plant.step()
    return pv, out, scenario.dt_s


def _verdict_for(seed: int, band_percent: float, noise: str) -> str:
    """Run one simulation and return the detector verdict as a string."""
    pv, out, dt_s = simulate_loop(seed, band_percent, noise)
    first = int(ANALYSIS_START_S / dt_s)
    return detect_stiction(pv[first:], out[first:], dt_s).verdict


def summarise(rows: list[tuple[float, str, str]]) -> dict[tuple[float, str], dict[str, int]]:
    """Count detector verdicts per (band, noise) cell.

    Each row is (band_percent, noise, verdict); the counters start at zero for every
    cell so a missing verdict shows up as a count of 0 rather than a missing key.
    """
    summary: dict[tuple[float, str], dict[str, int]] = {}
    for band_percent, noise, verdict in rows:
        counters = summary.setdefault((band_percent, noise), dict.fromkeys(VERDICTS, 0))
        counters[verdict] += 1
    return summary


def format_table(summary: dict[tuple[float, str], dict[str, int]]) -> str:
    """Render the verdict counts as a markdown table, one row per (band, noise) cell."""
    header = "| band % | noise | " + " | ".join(VERDICTS) + " |"
    separator = "|---|---|" + "---|" * len(VERDICTS)
    lines = [header, separator]
    for (band_percent, noise), counters in sorted(summary.items()):
        counts = " | ".join(str(counters[verdict]) for verdict in VERDICTS)
        lines.append(f"| {band_percent:g} | {noise} | {counts} |")
    return "\n".join(lines) + "\n"


def collect_rows() -> list[tuple[float, str, str]]:
    """Simulate every (band, noise, seed) combination and return (band, noise, verdict) rows."""
    return [
        (band_percent, noise, _verdict_for(seed, band_percent, noise))
        for band_percent in BANDS_PERCENT
        for noise in NOISE_LEVELS
        for seed in SEEDS
    ]


def main() -> None:
    """Run the validation sweep, print the summary table and write it to summary.md."""
    summary = summarise(collect_rows())
    table = format_table(summary)
    print(table)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(table, encoding="utf-8")


if __name__ == "__main__":
    main()

"""Response of chosen output tags to the steps of one driver tag (e.g. a pump speed), per step.

Interim tool; to be absorbed into model identification for MPC in Phase 7 of docs/PRODUCT.md.

Analysis only (no plant access): finds the driver's steps with step_events (the driver is treated
like a manual OUT) and fits each output with step_fit (FOPDT or IPDT, standard errors), then prints
the median and spread per output. Used for the feed-disturbance identification of a future MPC.
Usage: python tools/driver_response.py [--pre-s S] [--post-s S] [--min-step X]
       <data root> <dataset> <driver tag> <out tag>:<fopdt|ipdt> ...
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from crosscut_api.app import DatasetStore
from crosscut_loops.step_events import find_step_events
from crosscut_loops.step_fit import StepFitError, fit_step

DEFAULT_PRE_S = 300.0  # baseline before a driver step
DEFAULT_POST_S = 1200.0  # response window after it
DEFAULT_MIN_STEP = 0.4  # smallest driver step kept (driver units)
MAD_SCALE = 1.4826  # MAD to standard deviation for normal data


def driver_events(
    t_s: np.ndarray,
    driver: np.ndarray,
    dt_s: float,
    pre_s: float = DEFAULT_PRE_S,
    post_s: float = DEFAULT_POST_S,
    min_step: float = DEFAULT_MIN_STEP,
) -> list:
    """Steps of the driver tag, windows clipped by the neighbouring steps."""
    filler = np.zeros_like(t_s)
    events, _ = find_step_events(t_s, filler, filler, driver, filler, dt_s, pre_s, post_s)
    return [event for event in events if abs(event.size) >= min_step]


def fit_rows(t_s: np.ndarray, driver: np.ndarray, output: np.ndarray, model: str, events: list):
    """One (size, parameter, se, theta, tau, r2) tuple per driver step; None if the fit failed."""
    rows = []
    for event in events:
        window = slice(event.i0, event.i1)
        try:
            fit = fit_step(t_s[window], output[window], driver[window], event.pre, model)
        except StepFitError:
            rows.append(None)
            continue
        param = fit.gain if model == "fopdt" else fit.slope
        tau = fit.tau_s.value if fit.tau_s else float("nan")
        rows.append((event.size, param.value, param.se, fit.theta_s.value, tau, fit.r2))
    return rows


def summary(rows: list) -> str:
    """Median and robust spread of parameter, dead time and time constant over the good fits."""
    good = np.array([row for row in rows if row is not None and row[5] >= 0.5], dtype=float)
    if good.shape[0] == 0:
        return "no fit with R2 >= 0.5"
    med = np.median(good, axis=0)
    mad = MAD_SCALE * np.median(np.abs(good - med), axis=0)
    head = f"n={good.shape[0]} param {med[1]:.4g} +- {mad[1]:.2g}"
    return f"{head}  theta {med[3]:.0f} s +- {mad[3]:.0f}  tau {med[4]:.0f} s +- {mad[4]:.0f}"


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    """Command-line arguments: positional data location and tags, windows as options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-s", type=float, default=DEFAULT_PRE_S, metavar="SECONDS")
    parser.add_argument("--post-s", type=float, default=DEFAULT_POST_S, metavar="SECONDS")
    parser.add_argument("--min-step", type=float, default=DEFAULT_MIN_STEP, metavar="FLOAT")
    parser.add_argument("root")
    parser.add_argument("dataset")
    parser.add_argument("driver_tag")
    parser.add_argument("outputs", nargs="+", metavar="TAG:MODEL")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> None:
    """Print the per-step table and the summary of every requested output."""
    args = _parse(argv)
    root, dataset, driver_tag, outputs = args.root, args.dataset, args.driver_tag, args.outputs
    t_s, values = DatasetStore(Path(root)).load_seconds(dataset)
    driver = np.asarray(values[driver_tag], dtype=float)
    dt_s = float(np.median(np.diff(t_s)))
    events = driver_events(t_s, driver, dt_s, args.pre_s, args.post_s, args.min_step)
    print(f"{len(events)} driver steps: {[round(e.size, 2) for e in events]}")
    for spec in outputs:
        tag, model = spec.rsplit(":", 1)
        rows = fit_rows(t_s, driver, np.asarray(values[tag], dtype=float), model, events)
        print(f"{tag} [{model}]: {summary(rows)}")


if __name__ == "__main__":
    main(sys.argv[1:])

"""Make the synthetic lab CSV the soft sensor e2e spec uploads.

Usage: python make_lab_csv.py <data_root> <out.csv>

Reads the demo dataset `mill_circuit_observational_seed42` (parquet) and writes one lab result
every 5 minutes: a known linear function of the 60 s bin means of four process tags plus a little
noise (sd 2 % of the signal). Times are ISO strings (UTC) so the spec also
exercises the origin field.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pyarrow.dataset as ds

DATASET_ID = "mill_circuit_observational_seed42"
START = datetime(2026, 1, 1, tzinfo=UTC)
SAMPLE_PERIOD_S = 10
BIN_SAMPLES = 6
LAB_EVERY_BINS = 5
WEIGHTS = {
    "sim.mc.mill_power": 3.0,
    "sim.mc.mill_feed": 0.5,
    "sim.mc.cyc_water": -2.0,
    "sim.mc.hpgr_press": 1.0,
}


def _series(root: Path, tag: str) -> np.ndarray:
    """Values of one tag in time order."""
    table = ds.dataset(root / DATASET_ID / "data").to_table(filter=ds.field("tag_id") == tag)
    order = np.argsort(table["ts"].to_numpy())
    return table["value"].to_numpy()[order]


def _truth(root: Path) -> np.ndarray:
    """The hidden quality per 60 s bin: weighted sum of the bin means."""
    total = None
    for tag, weight in WEIGHTS.items():
        values = _series(root, tag)
        usable = len(values) // BIN_SAMPLES * BIN_SAMPLES
        bins = values[:usable].reshape(-1, BIN_SAMPLES).mean(axis=1)
        total = weight * bins if total is None else total + weight * bins
    return total


def main(root: Path, out: Path) -> None:
    """Write `sample_time,value` rows (ISO UTC time, value) every five minutes."""
    truth = _truth(root)
    noise = np.random.default_rng(1).normal(0.0, 0.02 * truth.std(), len(truth))
    lines = ["sample_time,value"]
    for k in range(0, len(truth), LAB_EVERY_BINS):
        when = START + timedelta(seconds=k * BIN_SAMPLES * SAMPLE_PERIOD_S)
        lines.append(f"{when.strftime('%Y-%m-%dT%H:%M:%SZ')},{float(truth[k] + noise[k])!r}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

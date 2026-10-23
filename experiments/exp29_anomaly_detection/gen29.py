"""Generator G29: mill-circuit records with one injected sensor fault (exp29, frozen README.md).

Training (48 h) and quiet (72 h) records are fault-free runs of the `observational` scenario; the
fault record (24 h) wraps the plant in `crosscut_sim.faults.FaultyPlant`. One raw sample every 10 s,
averaged to 60 s rows. Independent of `crosscut_anomaly`; every record is a function of its seed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from crosscut_sim.faults import Fault, FaultyPlant
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario

SCENARIO = "observational"
TAG_NAMES = (
    "hpgr_press",
    "mill_feed",
    "cyc_water",
    "feed_moisture",
    "p80",
    "mill_power",
    "hpgr_power",
    "ore_hardness_est",
)
TAGS = tuple(f"sim.mc.{name}" for name in TAG_NAMES)  # PV tags only, protocol order
FAULT_KINDS = ("drift", "freeze", "spike", "bad_quality", "dropout")  # protocol cycle order
RAW_PERIOD_S = 10.0  # raw sample period, s
ROW_PERIOD_S = 60.0  # averaged row period, s
RAW_PER_ROW = int(ROW_PERIOD_S / RAW_PERIOD_S)
HOUR_S = 3600.0
QUIET_SEED_OFFSET = 1000  # protocol: quiet record = plant seed + 1000
FAULT_SEED_OFFSET = (
    2000  # harness reading: fault record = plant seed + 2000 (distinct from training)
)
ONSET_STREAM = 29  # second word of the onset RNG seed [seed, 29]
# Fault window length (h) per kind, frozen by the protocol.
FAULT_HOURS = {"drift": 6.0, "freeze": 2.0, "spike": 1.0, "bad_quality": 1.0, "dropout": 1.0}
DRIFT_SD_PER_H = 1.0  # drift rate, training standard deviations per hour
SPIKE_SD = 6.0  # spike size, training standard deviations
SPIKE_PROBABILITY = 0.02  # per raw (10 s) sample: the fault RNG draws once per plant step


@dataclass(frozen=True)
class Durations:
    """Record lengths and the onset window (h); the defaults are the frozen protocol values."""

    train_h: float = 48.0
    quiet_h: float = 72.0
    fault_h: float = 24.0
    onset_low_h: float = 6.0
    onset_high_h: float = 16.0


PROTOCOL = Durations()


@dataclass(frozen=True)
class Record:
    """One 60 s record: rows by the TAGS columns, one quality code per row (max over tags).

    ``t_s`` stamps each row at its last raw sample (window start + 50 s), so a row never
    carries a time earlier than the data averaged into it.
    """

    t_s: np.ndarray
    x: np.ndarray  # rows by tags, engineering units, NaN where a raw sample was missing
    quality: (
        np.ndarray
    )  # per row: max raw quality code over the window and the tags (0 good, 2 bad)
    meta: dict


def _scenario_plant(seed: int, hours: float, faults: list[Fault] | None) -> object:
    """A reset mill-circuit plant (wrapped in FaultyPlant when ``faults`` is given)."""
    scenario = build_scenario("mill_circuit", SCENARIO, duration_s=hours * HOUR_S)
    plant: object = MillCircuitPlant()
    if faults is not None:
        plant = FaultyPlant(plant, faults)
    plant.reset(seed, scenario)
    return plant


def _raw_samples(plant: object, hours: float) -> tuple[np.ndarray, np.ndarray]:
    """Values and quality codes of the TAGS every 10 s over ``hours`` (plant dt = 1 s)."""
    n_raw = int(round(hours * HOUR_S / RAW_PERIOD_S))
    stride = int(RAW_PERIOD_S)  # plant steps per raw sample (dt_s = 1 s)
    values = np.empty((n_raw, len(TAGS)))
    quality = np.empty((n_raw, len(TAGS)), dtype=np.int64)
    for i in range(n_raw):
        snap = plant.snapshot()
        for j, tag in enumerate(TAGS):
            values[i, j], quality[i, j] = snap[tag]
        for _ in range(stride):
            plant.step()
    return values, quality


def average_rows(
    values: np.ndarray, quality: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Block means of 6 raw samples: (t_s, x, row quality).

    A missing raw sample (NaN) makes the row value NaN (no imputation); the row quality is the
    worst raw quality code of the window over all tags.
    """
    n_rows = len(values) // RAW_PER_ROW
    shape = (n_rows, RAW_PER_ROW, values.shape[1])
    x = values[: n_rows * RAW_PER_ROW].reshape(shape).mean(axis=1)  # NaN propagates
    q = quality[: n_rows * RAW_PER_ROW].reshape(shape).max(axis=(1, 2))
    t_s = np.arange(n_rows) * ROW_PERIOD_S + (RAW_PER_ROW - 1) * RAW_PERIOD_S
    return t_s, x, q


def _record(plant: object, hours: float, meta: dict) -> Record:
    """Sample a reset plant for ``hours`` and average to 60 s rows."""
    t_s, x, q = average_rows(*_raw_samples(plant, hours))
    return Record(t_s, x, q, meta)


def training_record(seed: int, durations: Durations = PROTOCOL) -> Record:
    """Fault-free training record, plant seed = seed."""
    plant = _scenario_plant(seed, durations.train_h, None)
    return _record(plant, durations.train_h, {"role": "training", "plant_seed": seed})


def quiet_record(seed: int, durations: Durations = PROTOCOL) -> Record:
    """Fault-free quiet test record, plant seed = seed + 1000."""
    plant_seed = seed + QUIET_SEED_OFFSET
    plant = _scenario_plant(plant_seed, durations.quiet_h, None)
    return _record(plant, durations.quiet_h, {"role": "quiet", "plant_seed": plant_seed})


def fault_spec(
    seed: int, index: int, train_sd: np.ndarray, durations: Durations = PROTOCOL
) -> dict:
    """Kind, tag, onset (whole s), window and magnitude of the one fault of a fault record.

    ``index`` is the position of the seed in its fault family: kinds cycle with period 5,
    tags with period 8. Magnitudes are in units of the target tag's training standard deviation.
    """
    kind, column = FAULT_KINDS[index % len(FAULT_KINDS)], index % len(TAGS)
    rng = np.random.default_rng([seed, ONSET_STREAM])
    onset = float(np.round(rng.uniform(durations.onset_low_h, durations.onset_high_h) * HOUR_S))
    sd = float(train_sd[column])
    magnitude = {"drift": DRIFT_SD_PER_H * sd, "spike": SPIKE_SD * sd}.get(kind, 0.0)
    return {
        "kind": kind,
        "tag": TAGS[column],
        "column": column,
        "onset_s": onset,
        "end_s": onset + FAULT_HOURS[kind] * HOUR_S,
        "magnitude": magnitude,
        "train_sd": sd,
        "probability": SPIKE_PROBABILITY if kind == "spike" else 1.0,
    }


def fault_record(seed: int, spec: dict, durations: Durations = PROTOCOL) -> Record:
    """24 h record with the one fault of ``spec``, plant seed = seed + 2000."""
    fault = Fault(
        kind=spec["kind"],
        tag_id=spec["tag"],
        start_s=spec["onset_s"],
        end_s=spec["end_s"],
        magnitude=spec["magnitude"],
        probability=spec["probability"],
    )
    plant_seed = seed + FAULT_SEED_OFFSET
    plant = _scenario_plant(plant_seed, durations.fault_h, [fault])
    meta = {"role": "fault", "plant_seed": plant_seed, "fault": spec}
    return _record(plant, durations.fault_h, meta)


def training_sd(record: Record) -> np.ndarray:
    """Per-tag standard deviation (ddof 1) of the 60 s training rows: the fault magnitude unit."""
    return np.nanstd(record.x, axis=0, ddof=1)

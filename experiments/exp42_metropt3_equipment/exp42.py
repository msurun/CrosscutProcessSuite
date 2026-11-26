"""Load MetroPT-3 and evaluate the frozen equipment protocol.

Only an explicit CLI invocation learns and scans; imports never access real data.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from crosscut_anomaly.equipment_learning import learn_equipment
from crosscut_connectors.base import LiveValue
from crosscut_runtime.jobs.equipment_scan import EquipmentScanJob

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "frozen_config.json").read_text(encoding="utf-8-sig"))
MEASUREMENTS = CONFIG["measurements"]
STATE_COLUMNS = CONFIG["state_columns"]
SECONDS_PER_DAY = 86400  # Seconds in a nominal elapsed day, without timezone conversion.
NANOSECONDS_PER_SECOND = 1_000_000_000


def load_metropt3(path: str | Path) -> tuple[pd.DatetimeIndex, np.ndarray, pd.DataFrame]:
    """Return naive source timestamps, float measurement matrix and aligned state frame."""
    frame = pd.read_csv(path)
    required = ["timestamp", *MEASUREMENTS, *STATE_COLUMNS]
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing MetroPT-3 columns: {sorted(missing)}")
    times = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], format="ISO8601", errors="raise"))
    if times.empty or times.hasnans or not times.is_monotonic_increasing or times.has_duplicates:
        raise ValueError("Provide nonempty, unique, increasing MetroPT-3 timestamps")
    if times.tz is not None:
        raise ValueError("Use the dataset's naive source timestamps without timezone conversion")
    # Shape: n rows x 7 analogue channels (A, bar, degrees C); states are n x 8 numeric keys.
    numeric = frame[MEASUREMENTS + STATE_COLUMNS].apply(pd.to_numeric, errors="raise")
    return times, numeric[MEASUREMENTS].to_numpy(float), numeric[STATE_COLUMNS].copy()


def failure_windows() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return inclusive early-warning windows in the dataset's source clock."""
    lead = pd.Timedelta(hours=CONFIG["lead_hours"])
    return [(pd.Timestamp(start) - lead, pd.Timestamp(end)) for start, end in CONFIG["failures"]]


def match_events(openings: pd.DatetimeIndex) -> list[bool]:
    """Credit each failure once when at least one alarm opens inside its warning window."""
    return [bool(((openings >= start) & (openings <= end)).any())
            for start, end in failure_windows()]


def normal_rows(times: pd.DatetimeIndex) -> np.ndarray:
    """Return rows outside the union of all inclusive early-warning windows."""
    normal = np.ones(len(times), dtype=bool)
    for start, end in failure_windows():
        normal &= ~((times >= start) & (times <= end))
    return normal


def count_false_alarms(openings: pd.DatetimeIndex) -> int:
    """Count distinct alarm openings outside every early-warning window."""
    return int(normal_rows(openings.unique()).sum())


def coverage(scored: np.ndarray) -> float:
    """Return scored rows / all held-out rows, including unavailable and warmup rows."""
    values = np.asarray(scored)
    if values.ndim != 1 or values.dtype != np.dtype(bool) or not len(values):
        raise ValueError("Provide a nonempty one-dimensional boolean scored-row mask")
    return float(values.mean())


def equipment_document() -> dict:
    """Describe one compressor with condition, pressure and digital context variables."""
    kinds = {"Motor_current": "current", "Oil_temperature": "temperature"}
    signals = [{"tag": name, "kind": kinds.get(name, "pressure")}
               for name in MEASUREMENTS]
    signals.extend({"tag": name, "kind": "state"} for name in STATE_COLUMNS)
    return {"id": CONFIG["equipment_id"], "loops": [], "signals": signals}


class ReplayConnector:
    """Expose one synthetic or recorded row through the public live connector interface."""

    def __init__(self) -> None:
        """Start with no available measurement values."""
        self.row: dict[str, float] = {}

    def capabilities(self) -> set[str]:
        """Disable historian backfill because the runner already replays every row."""
        return set()

    def read_live(self, tag_ids: list[str]) -> dict[str, LiveValue]:
        """Mark finite channels GOOD and leave missing channels unavailable."""
        return {name: LiveValue(self.row[name], 0, "") for name in tag_ids
                if name in self.row and np.isfinite(self.row[name])}


def train_model(times: pd.DatetimeIndex, data: dict, equipment: dict):
    """Fit exclusively on February, without label, running or state exclusions."""
    training = (times >= CONFIG["train_start"]) & (times < CONFIG["score_start"])
    if not training.any():
        raise ValueError("Provide February 2020 training rows")
    seconds = times.asi8 / NANOSECONDS_PER_SECOND
    selected = {name: values[training] for name, values in data.items()}
    model = learn_equipment(seconds[training], selected, equipment, [])
    if model.pca is None:
        raise ValueError("February cannot fit equipment PCA; report insufficient training data")
    return model


def replay_rows(job: EquipmentScanJob, connector: ReplayConnector, record: tuple) -> np.ndarray:
    """Scan chronologically, resetting lag and persistence across archive gaps."""
    times, data = record
    scored = np.zeros(len(times), dtype=bool)
    previous = None
    for index, stamp in enumerate(times):
        seconds = stamp.value / NANOSECONDS_PER_SECOND
        if previous is not None and seconds - previous > 1.5 * CONFIG["sample_period_s"]:
            job.states.clear()
        connector.row = {name: values[index] for name, values in data.items()}
        job.clock = lambda value=seconds: value
        result = job.run()["equipment"][CONFIG["equipment_id"]]
        scored[index] = result.get("t2") is not None and result.get("spe") is not None
        previous = seconds
    return scored


def scan_model(model, equipment: dict, record: tuple) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Use the public runtime job and retain only deduplicated opening identities."""
    with tempfile.TemporaryDirectory(dir=HERE) as directory:
        root = Path(directory)
        destination = root / "_anomaly" / "equipment" / f"{equipment['id']}.model.json"
        destination.parent.mkdir(parents=True)
        destination.write_text(json.dumps(model.to_dict()), encoding="utf-8")
        connector = ReplayConnector()
        job_document = {**CONFIG, "equipment": [equipment["id"]]}
        site = {"equipment": [equipment], "loops": []}
        job = EquipmentScanJob(job_document, site, connector, root)
        scored = replay_rows(job, connector, record)
        revisions = job.events_path.read_text().splitlines() if job.events_path.exists() else []
        openings = pd.DatetimeIndex([pd.Timestamp(json.loads(line)["opened_utc"])
                                     .tz_localize(None) for line in revisions]).unique()
    return openings, scored


def summarize(times: pd.DatetimeIndex, openings: pd.DatetimeIndex, scored: np.ndarray) -> dict:
    """Compute event recall, observed normal exposure and scored-row coverage."""
    # Exposure = normal observed rows * 10 s / 86400 s/day; gaps never add normal hours.
    normal_days = float(normal_rows(times).sum() * CONFIG["sample_period_s"] / SECONDS_PER_DAY)
    if normal_days == 0:
        raise ValueError("No normal scoring exposure; false-alarm rate is undefined")
    return {"false_alarms": count_false_alarms(openings), "normal_days": normal_days,
            "false_alarms_per_normal_day": count_false_alarms(openings) / normal_days,
            "events_detected": match_events(openings),
            "event_detection": float(np.mean(match_events(openings))),
            "coverage": coverage(scored), "scoring_rows": len(times)}


def run(path: Path, output: Path) -> None:
    """Learn February and scan the remainder only when explicitly invoked."""
    times, matrix, states = load_metropt3(path)
    data = dict(zip(MEASUREMENTS, matrix.T, strict=True))
    data.update({name: states[name].to_numpy(float) for name in STATE_COLUMNS})
    equipment = equipment_document()
    model = train_model(times, data, equipment)
    testing = times >= CONFIG["score_start"]
    record = (times[testing], {name: values[testing] for name, values in data.items()})
    openings, scored = scan_model(model, equipment, record)
    metrics = summarize(record[0], openings, scored)
    write_results(output, metrics)


def write_results(output: Path, metrics: dict) -> None:
    """Write aggregate outcomes and the three frozen target decisions."""
    targets = CONFIG["targets"]
    metrics["targets_passed"] = {
        "false_alarms": metrics["false_alarms_per_normal_day"]
        <= targets["false_alarms_per_normal_day"],
        "event_detection": metrics["event_detection"] >= CONFIG["targets"]["event_detection"],
        "coverage": metrics["coverage"] >= CONFIG["targets"]["coverage"]}
    output.write_text("# exp42 results\n\n```json\n" + json.dumps(metrics, indent=2)
                      + "\n```\n", encoding="utf-8")


def main() -> None:
    """Require an explicit dataset path before starting the frozen scoring run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "results.md")
    arguments = parser.parse_args()
    run(arguments.data, arguments.out)


if __name__ == "__main__":
    main()



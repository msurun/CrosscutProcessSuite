"""Make the `tuning_live_demo` dataset the tuning-live e2e proposes from.

Usage: python make_tuning_dataset.py <data_root>

One closed-loop record of the simulated process (tuning_plant_sim.py) with the controller at its
initial tuning, 40 min at 1 s, written as a CSV and imported with the CSV connector, plus a
project.json that names the loop TUNE1 (the id of the loop in the site document of the live stack).
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crosscut_connectors.csv_import import import_csv
from tuning_plant_sim import INITIAL_KP, INITIAL_TI_S, record

DATASET_ID = "tuning_live_demo"
LOOP_ID = "TUNE1"
DURATION_S = 2400
SAMPLE_S = 1.0
START = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)
CLOSED_LOOP_MODE = 1


def _write_csv(path: Path) -> None:
    """Wide CSV: timestamp, PV [%], SP, OUT [%] and MODE (1 = AUTO) of the loop."""
    data = record(DURATION_S, SAMPLE_S, (INITIAL_KP, INITIAL_TI_S))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        header = [
            "timestamp",
            f"{LOOP_ID} [%]",
            f"{LOOP_ID}_sp [%]",
            f"{LOOP_ID}_out [%]",
            f"{LOOP_ID}_mode",
        ]
        writer.writerow(header)
        for t_s, pv, sp, out in zip(data["t"], data["pv"], data["sp"], data["out"], strict=True):
            stamp = (START + timedelta(seconds=float(t_s))).isoformat()
            writer.writerow([stamp, f"{pv:.4f}", f"{sp:.4f}", f"{out:.4f}", CLOSED_LOOP_MODE])


def _project() -> dict[str, object]:
    """project.json: the loop explicit, self-regulating, unit %."""
    loop = {
        "id": LOOP_ID, "name": LOOP_ID, "pv": LOOP_ID, "sp": f"{LOOP_ID}_sp",
        "out": f"{LOOP_ID}_out", "mode": f"{LOOP_ID}_mode", "unit": "%",
    }  # fmt: skip
    return {"loops": [loop]}


def main(data_root: Path) -> None:
    """Create ``<data_root>/tuning_live_demo`` (refuses to overwrite an existing one)."""
    target = data_root / DATASET_ID
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "tuning.csv"
        _write_csv(csv_path)
        import_csv(csv_path, target, dataset_id=DATASET_ID)
    (target / "project.json").write_text(json.dumps(_project(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

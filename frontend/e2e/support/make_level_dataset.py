"""Make the `level_integrating_demo` dataset the integrating-loop e2e spec needs.

Usage: python make_level_dataset.py <data_root>

Two level loops in manual mode, 2 h at 10 s, written as a CSV and imported with the CSV connector,
plus a project.json that marks both loops integrating:
  LIC1  a true integrator: PV ramps after an OUT pulse (slope 0.002 %/s per % OUT, dead time 30 s).
  LIC2  a first-order process (gain 1.5, tau 200 s) driven by OUT steps, so the ramp is refused.
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from crosscut_connectors.csv_import import import_csv

DATASET_ID = "level_integrating_demo"
DT_S = 10
N = 720
SLOPE = 0.002
THETA_S = 30
TAU_S = 200.0
GAIN = 1.5
START = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)
LOOPS = ("LIC1", "LIC2")


def _out_pulse() -> np.ndarray:
    """OUT of LIC1: 50 %, +5 % at 40 min, back at 70 min."""
    t = np.arange(N) * DT_S
    return 50.0 + 5.0 * ((t >= 2400) & (t < 4200))


def _out_steps() -> np.ndarray:
    """OUT of LIC2: +5 % on and off every 10 min from minute 20."""
    t = np.arange(N) * DT_S
    on = (t >= 1200) & (((t - 1200) // 600) % 2 == 0)
    return 50.0 + 5.0 * on


def _integrator(u: np.ndarray) -> np.ndarray:
    """PV of LIC1: starts at 40 %, integrates the delayed OUT deviation with a little noise."""
    delayed = np.concatenate([np.full(THETA_S // DT_S, u[0]), u[: N - THETA_S // DT_S]])
    pv = 40.0 + SLOPE * DT_S * np.cumsum(delayed - u[0])
    return pv + np.random.default_rng(1).normal(0.0, 0.02, N)


def _first_order(u: np.ndarray) -> np.ndarray:
    """PV of LIC2: first order with gain and tau, 30 % start, a little noise."""
    pv = np.zeros(N)
    for i in range(1, N):
        pv[i] = pv[i - 1] + (GAIN * (u[i - 1] - u[0]) - pv[i - 1]) * DT_S / TAU_S
    return 30.0 + pv + np.random.default_rng(2).normal(0.0, 0.02, N)


def _write_csv(path: Path) -> None:
    """Wide CSV: timestamp, then PV [%], SP, OUT [%] and MODE (0 = manual) per loop."""
    u1, u2 = _out_pulse(), _out_steps()
    pv1, pv2 = _integrator(u1), _first_order(u2)
    header = ["timestamp"]
    for name in LOOPS:
        header += [f"{name} [%]", f"{name}_sp [%]", f"{name}_out [%]", f"{name}_mode"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for i in range(N):
            stamp = (START + timedelta(seconds=i * DT_S)).isoformat()
            row = [stamp]
            for pv, u in ((pv1, u1), (pv2, u2)):
                row += [f"{pv[i]:.4f}", f"{pv[0]:.4f}", f"{u[i]:.3f}", "0"]
            writer.writerow(row)


def _project() -> dict[str, object]:
    """project.json: both loops explicit, marked integrating, unit %."""
    loops = [
        {"id": n, "name": n, "pv": n, "sp": f"{n}_sp", "out": f"{n}_out", "mode": f"{n}_mode",
         "unit": "%", "process_kind": "integrating"}
        for n in LOOPS
    ]  # fmt: skip
    return {"loops": loops}


def main(data_root: Path) -> None:
    """Create ``<data_root>/level_integrating_demo`` (refuses to overwrite an existing one)."""
    target = data_root / DATASET_ID
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "level.csv"
        _write_csv(csv_path)
        import_csv(csv_path, target, dataset_id=DATASET_ID)
    (target / "project.json").write_text(json.dumps(_project(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

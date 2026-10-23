"""Write a recorded step test as a Crosscut dataset directory plus a project.json (integrating).

The record is resampled to a uniform grid (OUT, SP and MODE hold the last value; PV is linearly
interpolated) and written with the same dataset writer the CSV connector uses, so the web app
lists it and the tuning wizard opens it. Refuses to overwrite an existing dataset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from crosscut_sim.dataset import DatasetInfo, Samples, write_dataset

from crosscut_loops.step_test_check import resample_uniform
from crosscut_loops.step_test_io import Record

GOOD_QUALITY = 0
NS_PER_S = 1_000_000_000
MAX_SAMPLES = 200_000
ROLES = ("PV", "SP", "OUT", "MODE")


@dataclass(frozen=True)
class DatasetSpec:
    """Names and units of the dataset to write."""

    loop_name: str = "LIC1"
    process_kind: str = "integrating"
    pv_unit: str = "%"
    out_unit: str = "%"
    step_s: float | None = None  # None: median sampling period, at least 1 s


def choose_step(t: np.ndarray, step_s: float | None) -> float:
    """The resampling period: given, else the median period (min 1 s); widened to cap the size."""
    step = step_s if step_s else max(1.0, float(round(float(np.median(np.diff(t))))))
    return max(step, float(t[-1] - t[0]) / MAX_SAMPLES)


def _tag(tag_id: str, role: str, unit: str) -> dict[str, object]:
    """One tags.json row."""
    return {
        "id": tag_id, "name": tag_id, "description": "", "unit": unit, "type": "float",
        "role": role, "source": {"driver": "csv", "address": tag_id},
    }  # fmt: skip


def _signals(rec: Record, step: float) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Uniform grid and the four signals; SP and MODE are filled when the record lacks them."""
    sp = rec.sp if rec.sp is not None else np.full(len(rec.t_s), rec.pv[0])
    mode = rec.mode if rec.mode is not None else np.zeros(len(rec.t_s))
    cols = {"pv": rec.pv, "out": rec.out, "sp": sp, "mode": mode}
    return resample_uniform(rec.t_s, cols, step)


def assumptions(rec: Record, spec: DatasetSpec, step: float) -> list[str]:
    """Plain-language list of what make-dataset assumed."""
    base = [
        *rec.assumptions,
        f"time zone: UTC (naive timestamps are read as UTC); start {rec.origin_utc.isoformat()}",
        f"units: PV '{spec.pv_unit}', OUT '{spec.out_unit}' (from the options)",
        f"resampling: uniform {step:g} s grid; OUT, SP, MODE hold the last value; PV linear",
    ]
    if not rec.absolute:
        base.append("times were relative seconds: anchored at 2026-01-01T00:00:00Z")
    if rec.sp is None:
        base.append("no SP column: SP is held at the first PV value")
    if rec.mode is None:
        base.append("no MODE column: MODE is set to 0 (manual) for the whole record")
    return base


def _samples(rec: Record, spec: DatasetSpec, step: float) -> tuple[Samples, list[str]]:
    """Resampled Samples (PV, SP, OUT, MODE tags) and their tag ids."""
    grid, sig = _signals(rec, step)
    n = spec.loop_name
    ids = [n, f"{n}_sp", f"{n}_out", f"{n}_mode"]
    values = np.column_stack([sig["pv"], sig["sp"], sig["out"], sig["mode"]])
    origin_ns = int(round(rec.origin_utc.timestamp() * NS_PER_S))
    ts_ns = np.round((grid - grid[0]) * NS_PER_S).astype(np.int64) + origin_ns
    quality = np.full(values.shape, GOOD_QUALITY, np.uint8)
    return Samples(ts_ns, ids, values, quality), ids


def write_step_test_dataset(rec: Record, out_dir: Path, spec: DatasetSpec) -> list[str]:
    """Write ``out_dir`` (dataset + project.json) and return the list of assumptions made.

    Raises FileExistsError if ``out_dir`` already exists and is not empty.
    """
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"{out_dir} already exists; choose a new dataset directory")
    step = choose_step(rec.t_s, spec.step_s)
    samples, ids = _samples(rec, spec, step)
    units = (spec.pv_unit, spec.pv_unit, spec.out_unit, "")
    rows = [_tag(i, r, u) for i, r, u in zip(ids, ROLES, units, strict=True)]
    tags = {"schema_version": "0.1.0", "tags": rows}
    start = rec.origin_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    write_dataset(out_dir, samples, DatasetInfo(out_dir.name, {"kind": "file"}, start, tags))
    project = json.dumps(_project(spec, ids), indent=2)
    (out_dir / "project.json").write_text(project, encoding="utf-8")
    return assumptions(rec, spec, step)


def _project(spec: DatasetSpec, ids: list[str]) -> dict[str, object]:
    """project.json: one explicit loop marked with the process kind."""
    pv, sp, out, mode = ids
    entry = {
        "id": spec.loop_name, "name": spec.loop_name, "pv": pv, "sp": sp, "out": out,
        "mode": mode, "unit": spec.pv_unit, "process_kind": spec.process_kind,
    }  # fmt: skip
    return {"loops": [entry]}

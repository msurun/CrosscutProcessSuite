"""Record plant runs into Parquet datasets and read them back."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from crosscut_sim.core import SCHEMA_VERSION, Plant, Scenario

DEFAULT_START_UTC = "2026-01-01T00:00:00Z"


def compute_data_sha256(table: pa.Table) -> str:
    """SHA-256 hex digest over the logical content, independent of Parquet encoding."""
    hasher = hashlib.sha256()
    ts = table["ts"].cast(pa.int64()).to_numpy()
    tag_ids = "\n".join(table["tag_id"].to_pylist()).encode("utf-8")
    values = table["value"].to_numpy().tobytes()
    qualities = table["quality"].to_numpy().tobytes()
    hasher.update(ts.tobytes())
    hasher.update(tag_ids)
    hasher.update(values)
    hasher.update(qualities)
    return hasher.hexdigest()


def read_dataset(path: str | Path) -> pa.Table:
    """Read every data/date=*/part-*.parquet under path, sorted by file path, concatenate."""
    path = Path(path)
    parts = sorted(path.glob("data/date=*/part-*.parquet"))
    if not parts:
        raise FileNotFoundError("No partition files found")
    tables = [pq.read_table(part) for part in parts]
    return pa.concat_tables(tables)


def to_wide(table: pa.Table) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Convert a long-format table (same tags in the same order at every timestamp) to wide.

    Returns the sample timestamps (datetime64[ns]) and a dict tag_id -> float64 array.
    """
    tag_ids = table["tag_id"].to_pylist()
    unique_tags = list(dict.fromkeys(tag_ids))
    n_tags = len(unique_tags)
    if n_tags == 0 or len(tag_ids) % n_tags != 0:
        raise ValueError("Row count is not a multiple of the number of distinct tags")
    ts = table["ts"].cast(pa.int64()).to_numpy()[::n_tags].astype("datetime64[ns]")
    values = table["value"].to_numpy().reshape(-1, n_tags)
    return ts, {tag_id: values[:, j].copy() for j, tag_id in enumerate(unique_tags)}


def record(
    plant: Plant,
    scenario: Scenario,
    out_dir: str | Path,
    *,
    seed: int,
    dataset_id: str,
    plant_name: str,
    scenario_name: str | None = None,
    start_utc: str = DEFAULT_START_UTC,
    sample_period_s: float | None = None,
    git_commit: str | None = None,
    created_utc: str | None = None,
) -> dict[str, Any]:
    """Record a plant run into a Parquet dataset."""
    out_dir = Path(out_dir)
    if (out_dir / "dataset.json").exists():
        raise FileExistsError(f"{out_dir / 'dataset.json'} already exists")

    sample_period_s = scenario.dt_s if sample_period_s is None else sample_period_s
    ratio = sample_period_s / scenario.dt_s
    if not np.isclose(ratio, round(ratio), atol=1e-9) or ratio < 1:
        raise ValueError("sample_period_s must be an integer multiple of scenario.dt_s")

    plant.reset(seed, scenario)
    n_steps = round(scenario.duration_s / scenario.dt_s)
    every = round(sample_period_s / scenario.dt_s)
    n_samples = -(-n_steps // every)  # ceil: step 0 is always sampled

    start_dt = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    start_ns = int(start_dt.timestamp()) * 10**9
    ts = np.array(
        [start_ns + round(i * scenario.dt_s * 1e9) for i in range(n_steps) if i % every == 0],
        dtype=np.int64,
    )
    tag_ids = plant.tags.ids()
    values = np.zeros((n_samples, len(tag_ids)), dtype=np.float64)
    qualities = np.zeros((n_samples, len(tag_ids)), dtype=np.uint8)

    for i in range(n_steps):
        if i % every == 0:
            sample_idx = i // every
            snapshot = plant.snapshot()
            for j, tag_id in enumerate(tag_ids):
                values[sample_idx, j], qualities[sample_idx, j] = snapshot[tag_id]
        plant.step()

    ts_col = pa.array(np.repeat(ts, len(tag_ids)), type=pa.int64()).cast(
        pa.timestamp("ns", tz="UTC")
    )
    tag_id_col = pa.array(tag_ids * n_samples, type=pa.string())
    value_col = pa.array(values.flatten(), type=pa.float64())
    quality_col = pa.array(qualities.flatten(), type=pa.uint8())

    table = pa.Table.from_arrays(
        [ts_col, tag_id_col, value_col, quality_col], names=["ts", "tag_id", "value", "quality"]
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tags.json").write_text(
        json.dumps(plant.tags.to_document(), indent=2) + "\n", encoding="utf-8"
    )

    # One Parquet file per UTC calendar day; rows are already ordered by time.
    row_ts = table["ts"].cast(pa.int64()).to_numpy()
    day_index = row_ts // (86_400 * 10**9)
    boundaries = np.flatnonzero(np.diff(day_index)) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [len(row_ts)]))
    for first, last in zip(starts, ends, strict=True):
        day = datetime.fromtimestamp(int(row_ts[first]) // 10**9, tz=UTC)
        date_dir = out_dir / "data" / f"date={day:%Y-%m-%d}"
        date_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            table.slice(int(first), int(last - first)),
            date_dir / "part-0.parquet",
            compression="zstd",
        )

    last_s = int(ts[-1]) // 10**9
    end_utc = datetime.fromtimestamp(last_s, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "created_utc": created_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "kind": "sim",
            "plant": plant_name,
            "seed": seed,
        },
        "time_range": {
            "start_utc": start_utc,
            "end_utc": end_utc,
        },
        "tags": tag_ids,
        "row_count": table.num_rows,
        "storage": {
            "format": "parquet",
            "layout": "long",
            "partitioning": "daily",
            "path": "data",
        },
        "data_sha256": compute_data_sha256(table),
    }

    if scenario_name is not None:
        doc["source"]["scenario"] = scenario_name
    if git_commit is not None:
        doc["code"] = {"git_commit": git_commit}

    (out_dir / "dataset.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    return doc

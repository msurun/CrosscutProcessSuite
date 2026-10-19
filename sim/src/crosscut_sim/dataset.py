"""Record plant runs into Parquet datasets and read them back.

On disk a dataset is ``dataset.json`` + ``tags.json`` + daily long-format Parquet files
(columns ts, tag_id, value, quality). In memory the samples are wide: one row per instant.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from crosscut_sim.core import SCHEMA_VERSION, Plant, Scenario

DEFAULT_START_UTC = "2026-01-01T00:00:00Z"
# The ``storage`` block of dataset.json: long-form Parquet, one file per UTC day under data/.
STORAGE_BLOCK = {"format": "parquet", "layout": "long", "partitioning": "daily", "path": "data"}


def compute_data_sha256(table: pa.Table) -> str:
    """Return the SHA-256 hex digest of the table's logical content.

    Two tables holding the same rows hash to the same digest even if they were read from
    Parquet files with different compression or encodings, because the row values are
    converted to raw bytes first and hashed in a fixed order.

    The table is expected to have exactly the columns "ts", "tag_id", "value" and "quality".
    """
    # Incremental hash: each update() feeds the next chunk of bytes, and hexdigest() at the
    # end returns the digest of the whole concatenation. The chunk order is part of the
    # contract, so callers of this function rely on it: change the order and every stored
    # digest becomes stale.
    hasher = hashlib.sha256()

    ts = table["ts"].cast(pa.int64()).to_numpy()

    # "tag_id" is a string identifier for the sensor or channel. Python strings are not
    # bytes, so encode them as UTF-8. The "\n" separator keeps the fields unambiguous:
    # without it, ["ab", "c"] and ["a", "bc"] would produce the same bytes.
    tag_ids = "\n".join(table["tag_id"].to_pylist()).encode("utf-8")

    # "value" is the numeric reading and "quality" the code 0 good / 1 uncertain / 2 bad.
    # to_numpy() gives the array in the column's own dtype (float64 and uint8 as written by
    # this module) and tobytes() writes that array's raw, native-endian buffer, so on a
    # machine with the opposite byte order the digest of the same data would differ.
    values = table["value"].to_numpy().tobytes()
    qualities = table["quality"].to_numpy().tobytes()

    hasher.update(ts.tobytes())
    hasher.update(tag_ids)
    hasher.update(values)
    hasher.update(qualities)
    return hasher.hexdigest()


def read_dataset(path: str | Path) -> pa.Table:
    """Read every data/date=*/part-*.parquet under path, sorted by file path, concatenate.

    The dataset is Hive-partitioned by date: each day lives in its own directory
    named `date=<value>` and holds one or more `part-*.parquet` files. Reading the
    partitions in sorted path order keeps the rows in chronological order, because
    the date is part of the directory name and the lexicographic order of those
    names is also the chronological order (dates use a sortable format such as
    ISO YYYY-MM-DD).

    Returns a single Arrow table with the rows of all partitions stacked. Raises
    FileNotFoundError if no partition file matches.
    """
    path = Path(path)

    # Glob returns paths in arbitrary order from the filesystem. Sorting them makes
    # the concatenation deterministic and puts the days in order: the `date=` segment
    # is compared first, then the `part-` name inside the day.
    parts = sorted(path.glob("data/date=*/part-*.parquet"))

    if not parts:
        raise FileNotFoundError("No partition files found")

    # One table per partition file, then concatenated by schema: `concat_tables` keeps
    # every column, in the order of the first table, and requires the other tables to
    # carry the same column types.
    tables = [pq.read_table(part) for part in parts]
    return pa.concat_tables(tables)


def to_wide(table: pa.Table) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Convert a long-format table (same tags in the same order at every timestamp) to wide.

    Long format: one row per (timestamp, tag). Wide format: one row per timestamp, one column
    per tag. The caller guarantees that every timestamp carries exactly the same tags in the
    same order, so the rows repeat in blocks of the same tag sequence.

    Returns the sample timestamps (datetime64[ns]) and a dict tag_id -> float64 array.
    Raises ValueError if the row count is not a multiple of the number of distinct tags.
    """
    # Distinct tag ids, keeping first-seen order: dict.fromkeys deduplicates and preserves it.
    # This order defines the column order of the wide array built below.
    tag_ids = table["tag_id"].to_pylist()
    unique_tags = list(dict.fromkeys(tag_ids))
    n_tags = len(unique_tags)
    # Every block of rows must hold one row per tag: otherwise the reshape further down
    # would silently fold rows from different timestamps together.
    if n_tags == 0 or len(tag_ids) % n_tags != 0:
        raise ValueError("Row count is not a multiple of the number of distinct tags")
    # The timestamp column repeats once per row within a block, so keep the first row of each
    # block ([::n_tags]) to get one timestamp per sample.
    ts = table["ts"].cast(pa.int64()).to_numpy()[::n_tags].astype("datetime64[ns]")
    # One row per timestamp, n_tags columns: row i, column j holds tag unique_tags[j] at ts[i].
    values = table["value"].to_numpy().reshape(-1, n_tags)
    # Copy each column out of the C-contiguous view, so the per-tag arrays are independent
    # and callers cannot be confused by the shared underlying buffer.
    return ts, {tag_id: values[:, j].copy() for j, tag_id in enumerate(unique_tags)}


@dataclass(frozen=True)
class RunInfo:
    """Describes one simulated run: what to record and the metadata stored with it.

    ``sample_period_s`` defaults to the scenario step. ``scenario_name`` is omitted from the
    dataset's ``source`` block when ``None``.
    """

    seed: int
    dataset_id: str
    plant_name: str
    scenario_name: str | None = None
    start_utc: str = DEFAULT_START_UTC
    sample_period_s: float | None = None
    git_commit: str | None = None
    created_utc: str | None = None


@dataclass(frozen=True)
class Samples:
    """Samples in "wide" form: one row per timestamp, one column per tag.

    ``ts_ns`` holds int64 nanoseconds since the Unix epoch, one per sample. ``values`` is a
    float64 array and ``qualities`` a uint8 array (0 Good, 1 Uncertain, 2 Bad), both of
    shape ``(n_samples, len(tag_ids))`` with the columns in ``tag_ids`` order.
    """

    ts_ns: np.ndarray
    tag_ids: list[str]
    values: np.ndarray
    qualities: np.ndarray


@dataclass(frozen=True)
class DatasetInfo:
    """Metadata of a dataset document (``dataset.json``) and its ``tags.json``.

    ``source`` is the ``source`` block (``kind`` plus origin details); ``tags_document`` must
    validate against ``tags.schema.json``; ``git_commit`` is recorded under ``code`` when
    given; ``created_utc`` defaults to "now" in UTC.
    """

    dataset_id: str
    source: dict[str, Any]
    start_utc: str
    tags_document: dict[str, Any]
    git_commit: str | None = None
    created_utc: str | None = None


def _steps_between_samples(scenario: Scenario, sample_period_s: float) -> int:
    """Return how many simulation steps separate two samples.

    A sample must fall exactly on a simulation step, so the ratio of the sample period to the
    step must be a whole number >= 1. ``atol=1e-9`` absorbs float rounding from the division.
    """
    ratio = sample_period_s / scenario.dt_s
    if not np.isclose(ratio, round(ratio), atol=1e-9) or ratio < 1:
        raise ValueError("sample_period_s must be an integer multiple of scenario.dt_s")
    return round(ratio)


def _sample_timestamps(scenario: Scenario, start_utc: str, every: int) -> np.ndarray:
    """Return one int64 timestamp (ns since the Unix epoch) per kept sample.

    ``start_utc`` is ISO-8601 "YYYY-MM-DDTHH:MM:SSZ"; ``tzinfo=UTC`` makes it timezone-aware
    so the Unix conversion is well defined. Step ``i`` happens ``i * dt_s`` seconds after the
    start; ``round`` avoids float noise such as 999999999 ns.
    """
    n_steps = round(scenario.duration_s / scenario.dt_s)
    start_dt = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    start_ns = int(start_dt.timestamp()) * 10**9
    return np.array(
        [start_ns + round(i * scenario.dt_s * 1e9) for i in range(0, n_steps, every)],
        dtype=np.int64,
    )


def _simulate_samples(
    plant: Plant, scenario: Scenario, every: int, tag_ids: list[str]
) -> tuple[np.ndarray, np.ndarray]:
    """Run the plant and return ``(values, qualities)``, one row per kept sample.

    ``values[sample, column]`` is the tag value (float64, in the tag's own unit);
    ``qualities[sample, column]`` is the quality code (uint8; 0 good, 1 uncertain, 2 bad).
    Step 0 is always
    sampled, so the sample count is ``ceil(n_steps / every)`` (``-(-a // b)`` is integer ceil).
    """
    n_steps = round(scenario.duration_s / scenario.dt_s)
    n_samples = -(-n_steps // every)
    values = np.zeros((n_samples, len(tag_ids)), dtype=np.float64)
    qualities = np.zeros((n_samples, len(tag_ids)), dtype=np.uint8)
    for step in range(n_steps):
        if step % every == 0:
            snapshot = plant.snapshot()
            row = step // every
            for column, tag_id in enumerate(tag_ids):
                values[row, column], qualities[row, column] = snapshot[tag_id]
        plant.step()
    return values, qualities


def _refuse_existing_dataset(out_dir: Path) -> None:
    """Raise ``FileExistsError`` if ``out_dir`` already holds a dataset."""
    if (out_dir / "dataset.json").exists():
        raise FileExistsError(f"{out_dir / 'dataset.json'} already exists")


def _run_source(run: RunInfo, plant: Plant) -> dict[str, Any]:
    """Return the ``source`` block of a simulated run.

    Only defined keys are written: a run without a named scenario omits the scenario key, and
    ``ground_truth`` appears only when the plant reports injected faults.
    """
    source: dict[str, Any] = {"kind": "sim", "plant": run.plant_name, "seed": run.seed}
    if run.scenario_name is not None:
        source["scenario"] = run.scenario_name
    ground_truth: dict[str, dict[str, float]] = getattr(plant, "ground_truth", dict)()
    if ground_truth:
        source["ground_truth"] = ground_truth
    return source


def record(plant: Plant, scenario: Scenario, out_dir: str | Path, run: RunInfo) -> dict[str, Any]:
    """Record a plant run into a Parquet dataset.

    Simulates ``plant`` over ``scenario``, samples every tag at a fixed period and
    writes the samples, their timestamps and their quality flags as a dataset.

    Sampling is decoupled from simulation: the plant advances in steps of
    ``scenario.dt_s`` seconds, but only every ``run.sample_period_s``-th step is kept.
    ``run.sample_period_s`` must be an integer multiple of ``scenario.dt_s`` so that a
    tag value is always read exactly on a simulation step, never interpolated.

    Returns the write summary produced by :func:`write_dataset`.
    Raises ``FileExistsError`` if the target dataset already exists, and
    ``ValueError`` if ``run.sample_period_s`` is not a valid multiple of ``scenario.dt_s``.
    """
    out_dir = Path(out_dir)
    _refuse_existing_dataset(out_dir)
    sample_period_s = scenario.dt_s if run.sample_period_s is None else run.sample_period_s
    every = _steps_between_samples(scenario, sample_period_s)

    plant.reset(run.seed, scenario)
    ts = _sample_timestamps(scenario, run.start_utc, every)
    # tag_ids fixes the column order of the dataset; values and qualities share it.
    tag_ids = plant.tags.ids()
    values, qualities = _simulate_samples(plant, scenario, every, tag_ids)

    info = DatasetInfo(
        dataset_id=run.dataset_id,
        source=_run_source(run, plant),
        start_utc=run.start_utc,
        tags_document=plant.tags.to_document(),
        git_commit=run.git_commit,
        created_utc=run.created_utc,
    )
    return write_dataset(out_dir, Samples(ts, tag_ids, values, qualities), info)


def _samples_to_table(samples: Samples) -> pa.Table:
    """Convert wide samples to the long table with columns ts, tag_id, value, quality.

    Every sample is repeated once per tag, and inside one sample the tag ids keep the column
    order of the wide arrays. ``np.repeat(ts, n_tags)`` therefore lines up with
    ``tag_ids * n_samples`` element-wise, and the flattened wide arrays follow the same
    row-major order, which is what makes the four columns a table.
    """
    ts = np.asarray(samples.ts_ns, dtype=np.int64)
    ts_col = pa.array(np.repeat(ts, len(samples.tag_ids)), type=pa.int64()).cast(
        pa.timestamp("ns", tz="UTC")
    )
    tag_id_col = pa.array(list(samples.tag_ids) * len(ts), type=pa.string())
    value_col = pa.array(np.asarray(samples.values, dtype=np.float64).flatten(), type=pa.float64())
    quality_col = pa.array(np.asarray(samples.qualities, dtype=np.uint8).flatten(), type=pa.uint8())
    return pa.Table.from_arrays(
        [ts_col, tag_id_col, value_col, quality_col], names=["ts", "tag_id", "value", "quality"]
    )


def _write_daily_partitions(table: pa.Table, out_dir: Path) -> None:
    """Write one Parquet file per UTC calendar day; rows are already ordered by time.

    A row's day number is its timestamp divided by the nanoseconds in 24 h
    (``86_400 * 10**9``), so rows sharing a day number share a file. ``np.diff(day_index)``
    is non-zero only where the day changes; adding 1 to the ``flatnonzero`` result gives the
    first row of each new day. Putting 0 in front and ``len(row_ts)`` at the back turns those
    indices into ``[start, end)`` pairs, one per day.
    """
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


def _dataset_document(
    info: DatasetInfo, tag_ids: list[str], last_ts_ns: int, table: pa.Table
) -> dict[str, Any]:
    """Build the ``dataset.json`` document for a table that has been written."""
    end_utc = datetime.fromtimestamp(last_ts_ns // 10**9, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": info.dataset_id,
        "created_utc": info.created_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": info.source,
        "time_range": {"start_utc": info.start_utc, "end_utc": end_utc},
        "tags": list(tag_ids),
        "row_count": table.num_rows,
        "storage": dict(STORAGE_BLOCK),
        "data_sha256": compute_data_sha256(table),
    }
    if info.git_commit is not None:
        doc["code"] = {"git_commit": info.git_commit}
    return doc


def write_dataset(out_dir: str | Path, samples: Samples, info: DatasetInfo) -> dict[str, Any]:
    """Write samples as a Parquet dataset (tags.json, daily partitions, dataset.json).

    The samples arrive in "wide" form -- one row per timestamp, one column per tag -- and are
    written in "long" form, one row per (timestamp, tag) pair, which is what Parquet and the
    query layer expect. ``out_dir`` is created if missing and must not already contain
    ``dataset.json``.

    Returns the dataset document that was written to ``dataset.json``.
    Raises ``FileExistsError`` if ``dataset.json`` already exists in ``out_dir``.
    """
    out_dir = Path(out_dir)
    _refuse_existing_dataset(out_dir)
    table = _samples_to_table(samples)

    out_dir.mkdir(parents=True, exist_ok=True)
    tags_text = json.dumps(info.tags_document, indent=2) + "\n"
    (out_dir / "tags.json").write_text(tags_text, encoding="utf-8")
    _write_daily_partitions(table, out_dir)

    last_ts_ns = int(np.asarray(samples.ts_ns, dtype=np.int64)[-1])
    doc = _dataset_document(info, samples.tag_ids, last_ts_ns, table)
    (out_dir / "dataset.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc

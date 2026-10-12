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

    # "ts" is a timestamp in nanoseconds since the Unix epoch (UTC). The cast to int64
    # makes the byte layout independent of the timestamp's own resolution: a table
    # declared in microseconds and one declared in nanoseconds hash alike if they
    # represent the same instants.
    ts = table["ts"].cast(pa.int64()).to_numpy()

    # "tag_id" is a string identifier for the sensor or channel. Python strings are not
    # bytes, so encode them as UTF-8. The "\n" separator keeps the fields unambiguous:
    # without it, ["ab", "c"] and ["a", "bc"] would produce the same bytes.
    tag_ids = "\n".join(table["tag_id"].to_pylist()).encode("utf-8")

    # "value" is the numeric reading and "quality" is a status code (for example a bit
    # mask or a severity level, not a unit). to_numpy() gives the array in the column's
    # own dtype – float32, float64, int16, ... – and tobytes() writes that array's raw,
    # native-endian buffer, so the digest can differ across machines with opposite byte
    # order. That is accepted here: digests are compared only between files read on the
    # same machine.
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
    # block ([::n_tags]) to get one timestamp per sample. Cast to int64 (ns since the epoch)
    # because pyarrow durations do not convert to numpy datetime64 directly.
    ts = table["ts"].cast(pa.int64()).to_numpy()[::n_tags].astype("datetime64[ns]")
    # One row per timestamp, n_tags columns: row i, column j holds tag unique_tags[j] at ts[i].
    values = table["value"].to_numpy().reshape(-1, n_tags)
    # Copy each column out of the C-contiguous view, so the per-tag arrays are independent
    # and callers cannot be confused by the shared underlying buffer.
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
    """Record a plant run into a Parquet dataset.

    Simulates ``plant`` over ``scenario``, samples every tag at a fixed period and
    writes the samples, their timestamps and their quality flags as a dataset.

    Sampling is decoupled from simulation: the plant advances in steps of
    ``scenario.dt_s`` seconds, but only every ``sample_period_s``-th step is kept.
    ``sample_period_s`` must be an integer multiple of ``scenario.dt_s`` so that a
    tag value is always read exactly on a simulation step, never interpolated.

    Returns the write summary produced by :func:`write_dataset`.
    Raises ``FileExistsError`` if the target dataset already exists, and
    ``ValueError`` if ``sample_period_s`` is not a valid multiple of ``scenario.dt_s``.
    """
    out_dir = Path(out_dir)
    if (out_dir / "dataset.json").exists():
        raise FileExistsError(f"{out_dir / 'dataset.json'} already exists")

    # Default sampling period: keep every simulation step.
    sample_period_s = scenario.dt_s if sample_period_s is None else sample_period_s

    # ratio = how many simulation steps fit in one sampling period (unitless, >= 1).
    ratio = sample_period_s / scenario.dt_s
    # Reject a period that is not a whole number of steps: otherwise a sample would
    # have to be read between two steps, which the plant cannot provide.
    # atol=1e-9 absorbs the rounding error of dividing two floats.
    if not np.isclose(ratio, round(ratio), atol=1e-9) or ratio < 1:
        raise ValueError("sample_period_s must be an integer multiple of scenario.dt_s")

    plant.reset(seed, scenario)

    # n_steps = total number of simulation steps in the run (unitless).
    n_steps = round(scenario.duration_s / scenario.dt_s)
    # every = number of simulation steps between two consecutive samples (unitless).
    every = round(sample_period_s / scenario.dt_s)
    # Number of samples kept. Integer ceiling division: -(-a // b) == ceil(a / b).
    # Step 0 is always sampled, so n_steps == 0 still yields no samples while
    # n_steps > 0 yields at least one.
    n_samples = -(-n_steps // every)  # ceil: step 0 is always sampled

    # start_dt parses the ISO-8601 "YYYY-MM-DDTHH:MM:SSZ" start timestamp;
    # tzinfo=UTC makes it timezone-aware so Unix conversion below is well defined.
    start_dt = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    # start_ns is the run start expressed in nanoseconds since the Unix epoch
    # (the unit used by the Arrow/Parquet timestamp column).
    start_ns = int(start_dt.timestamp()) * 10**9
    # One timestamp per kept sample, in nanoseconds: start plus the simulated
    # elapsed time i * dt_s seconds. round() avoids float noise such as 999999999.
    ts = np.array(
        [start_ns + round(i * scenario.dt_s * 1e9) for i in range(n_steps) if i % every == 0],
        dtype=np.int64,
    )

    # tag_ids fixes the column order of the dataset; both arrays below share it.
    tag_ids = plant.tags.ids()
    # values[sample, column] is the tag value (float64, in the tag's own unit).
    values = np.zeros((n_samples, len(tag_ids)), dtype=np.float64)
    # qualities[sample, column] is the tag quality flag (uint8, OPC-UA style code:
    # 0 = GOOD, any other value = not trustworthy).
    qualities = np.zeros((n_samples, len(tag_ids)), dtype=np.uint8)

    # Advance the plant one step at a time; on sampling steps, take a snapshot of
    # all tags at once (a consistent picture of the run at that instant) and store
    # each tag's (value, quality) pair in the row of that sample.
    for i in range(n_steps):
        if i % every == 0:
            sample_idx = i // every
            snapshot = plant.snapshot()
            for j, tag_id in enumerate(tag_ids):
                values[sample_idx, j], qualities[sample_idx, j] = snapshot[tag_id]
        plant.step()

    # Provenance for the dataset header: how the data was produced. Only defined
    # keys are written, so a run without a named scenario has no "scenario" key.
    source: dict[str, Any] = {"kind": "sim", "plant": plant_name, "seed": seed}
    if scenario_name is not None:
        source["scenario"] = scenario_name

    return write_dataset(
        out_dir,
        ts,
        tag_ids,
        values,
        qualities,
        dataset_id=dataset_id,
        source=source,
        start_utc=start_utc,
        tags_document=plant.tags.to_document(),
        git_commit=git_commit,
        created_utc=created_utc,
    )


def write_dataset(
    out_dir: str | Path,
    ts_ns: np.ndarray,
    tag_ids: list[str],
    values: np.ndarray,
    qualities: np.ndarray,
    *,
    dataset_id: str,
    source: dict[str, Any],
    start_utc: str,
    tags_document: dict[str, Any],
    git_commit: str | None = None,
    created_utc: str | None = None,
) -> dict[str, Any]:
    """Write samples as a Parquet dataset (tags.json, daily partitions, dataset.json).

    The samples arrive in "wide" form -- one row per timestamp, one column per tag -- and are
    written in "long" form, one row per (timestamp, tag) pair, which is what Parquet and the
    query layer expect.

    Parameters
    ----------
    out_dir:
        Dataset directory; created if missing. Must not already contain ``dataset.json``.
    ts_ns:
        Sample timestamps as int64 nanoseconds since the Unix epoch, one per sample.
    tag_ids:
        Tag identifiers, one per column of ``values`` and ``qualities``.
    values:
        Float64 array of shape ``(n_samples, len(tag_ids))``.
    qualities:
        Uint8 array of shape ``(n_samples, len(tag_ids))``; 0 Good, 1 Uncertain, 2 Bad.
    source:
        The ``source`` block of the dataset document (``kind`` plus origin details).
    tags_document:
        Document written to ``tags.json``; must validate against ``tags.schema.json``.
    git_commit:
        Commit that produced the data, recorded under ``code`` when given.
    created_utc:
        Timestamp for the ``created_utc`` field; defaults to "now" in UTC.

    Returns
    -------
    dict[str, Any]
        The dataset document that was written to ``dataset.json``.

    Raises
    ------
    FileExistsError
        If ``dataset.json`` already exists in ``out_dir``.
    """
    out_dir = Path(out_dir)
    if (out_dir / "dataset.json").exists():
        raise FileExistsError(f"{out_dir / 'dataset.json'} already exists")

    ts = np.asarray(ts_ns, dtype=np.int64)
    n_samples = len(ts)
    n_tags = len(tag_ids)
    tag_id_list = list(tag_ids)

    # Long form: every sample is repeated once per tag, and inside one sample the tag ids keep
    # the column order of the wide arrays. Repeating a timestamp n_tags times and cycling the
    # tag ids therefore line up element-wise, which is what makes the four columns a table.
    ts_col = pa.array(np.repeat(ts, n_tags), type=pa.int64()).cast(pa.timestamp("ns", tz="UTC"))
    tag_id_col = pa.array(tag_id_list * n_samples, type=pa.string())
    value_col = pa.array(np.asarray(values, dtype=np.float64).flatten(), type=pa.float64())
    quality_col = pa.array(np.asarray(qualities, dtype=np.uint8).flatten(), type=pa.uint8())

    table = pa.Table.from_arrays(
        [ts_col, tag_id_col, value_col, quality_col], names=["ts", "tag_id", "value", "quality"]
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tags.json").write_text(json.dumps(tags_document, indent=2) + "\n", encoding="utf-8")

    # One Parquet file per UTC calendar day; rows are already ordered by time.
    # A row's day is its timestamp floored to a whole day: integer division by 86_400 * 10**9 ns
    # (the number of nanoseconds in 24 h) yields the day number since the epoch, so rows sharing
    # a day number share a file. diff() is non-zero only where the day changes, giving the first
    # row index of each new day; concatenating 0 at the front and len(rows) at the back turns
    # those indices into [start, end) pairs, one per day.
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

    # The input is time-ordered, so the last sample carries the latest timestamp; truncate from
    # nanoseconds to seconds before formatting it as the ISO-8601 end of the covered range.
    last_s = int(ts[-1]) // 10**9
    end_utc = datetime.fromtimestamp(last_s, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Manifest describing what was written; ``row_count`` counts long-form rows, i.e. samples
    # times tags, and ``data_sha256`` hashes the table contents so a reader can detect tampering.
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "created_utc": created_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "time_range": {
            "start_utc": start_utc,
            "end_utc": end_utc,
        },
        "tags": tag_id_list,
        "row_count": table.num_rows,
        "storage": {
            "format": "parquet",
            "layout": "long",
            "partitioning": "daily",
            "path": "data",
        },
        "data_sha256": compute_data_sha256(table),
    }

    if git_commit is not None:
        doc["code"] = {"git_commit": git_commit}

    (out_dir / "dataset.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    return doc

# connectors/src/crosscut_connectors/sql_import.py
"""Import a dataset from a sqlite database using a query.

The importer reads a sqlite database and imports the result of a query into a
dataset. The query must be a single SELECT statement that returns at least three
columns: ts, tag, and value. The ts column can be either a string (ISO-8601) or a
numeric value (epoch seconds). The tag column is sanitized to ensure it is a valid
identifier. The value column is converted to a float. An optional quality column
can be provided to specify the quality of the data.

The importer writes the dataset to the specified output directory and returns an
SqlImportReport that summarizes the import operation.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from crosscut_sim.core import BAD, GOOD
from crosscut_sim.dataset import write_dataset

from crosscut_connectors.csv_import import (
    _parse_iso8601,
    _sanitize_tag_name,
    _to_utc_nanoseconds,
)

NS_PER_S = 1_000_000_000


@dataclass(frozen=True)
class SqlImportReport:
    """Summary of the import operation.

    Attributes
    ----------
    n_rows: int
        Number of rows in the dataset.
    n_tags: int
        Number of tags in the dataset.
    n_duplicates_dropped: int
        Number of duplicate rows dropped.
    n_bad_values: int
        Number of bad values in the dataset.
    """

    n_rows: int
    n_tags: int
    n_duplicates_dropped: int
    n_bad_values: int


def _parse_timestamp(ts: Any, tz: str) -> int:
    """Parse a timestamp into nanoseconds since the Unix epoch (UTC)."""
    if isinstance(ts, str):
        dt = _parse_iso8601(ts)
        if dt is None:
            raise ValueError("unparseable timestamp")
        return _to_utc_nanoseconds(dt, tz)
    if isinstance(ts, (int, float)):
        return int(ts * NS_PER_S)
    raise ValueError("timestamp must be a string or a numeric value")


def _pivot_rows(
    rows: list[tuple[Any, ...]],
    tz: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Pivot rows into timestamps, tag_ids, values, and qualities.

    Parameters
    ----------
    rows: list[tuple[Any, ...]]
        List of rows from the query result.
    tz: str
        Timezone name used for naive timestamps.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]
        Unique timestamps, unique tag ids, the wide value and quality grids, and the
        number of duplicate (timestamp, tag) rows dropped.
    """
    ts_ns, tag_ids, values, qualities = _collect_samples(rows, tz)
    ts_ns, tag_ids, values, qualities = _sort_by_time(ts_ns, tag_ids, values, qualities)
    n_duplicates_dropped = _count_duplicates(ts_ns, tag_ids)
    unique_ts, unique_tags, wide_values, wide_qualities = _widen(
        ts_ns, tag_ids, values, qualities
    )
    return unique_ts, unique_tags, wide_values, wide_qualities, n_duplicates_dropped


def _clean_value(raw: Any) -> float:
    """Convert a raw cell to float; NULL, non-numeric or non-finite cells become NaN."""
    if raw is None:
        return float("nan")
    try:
        value = float(raw)
    except ValueError:
        return float("nan")
    return value if np.isfinite(value) else float("nan")


def _parse_row(row: tuple[Any, ...], tz: str) -> tuple[int, str, float, Any]:
    """Return (timestamp ns, sanitized tag, value, quality) for one query row.

    A missing or invalid value is always BAD, whatever the quality column says.
    """
    value = _clean_value(row[2])
    quality = BAD if np.isnan(value) else (row[3] if len(row) > 3 else GOOD)
    return _parse_timestamp(row[0], tz), _sanitize_tag_name(row[1]), value, quality


def _check_identifier(raw_by_tag: dict[str, Any], tag: str, raw_tag: Any) -> None:
    """Reject two different raw tag names that sanitise to the same identifier."""
    known_raw_tag = raw_by_tag.setdefault(tag, raw_tag)
    if known_raw_tag != raw_tag:
        raise ValueError("duplicate tag identifiers after sanitisation")


def _collect_samples(
    rows: list[tuple[Any, ...]], tz: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Parse every row into parallel arrays of timestamps, tags, values and qualities."""
    ts_ns: list[int] = []
    tags: list[str] = []
    values: list[float] = []
    qualities: list[Any] = []
    raw_by_tag: dict[str, Any] = {}
    for row in rows:
        ts, tag, value, quality = _parse_row(row, tz)
        _check_identifier(raw_by_tag, tag, row[1])
        ts_ns.append(ts)
        tags.append(tag)
        values.append(value)
        qualities.append(quality)
    return (
        np.array(ts_ns, dtype=np.int64),
        np.array(tags),
        np.array(values, dtype=np.float64),
        np.array(qualities, dtype=np.uint8),
    )


def _sort_by_time(
    ts_ns: np.ndarray, tag_ids: np.ndarray, values: np.ndarray, qualities: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Reorder samples by timestamp, keeping query order among equal timestamps."""
    order = np.argsort(ts_ns, kind="stable")
    return ts_ns[order], tag_ids[order], values[order], qualities[order]


def _count_duplicates(ts_ns: np.ndarray, tag_ids: np.ndarray) -> int:
    """Count samples that repeat an earlier (timestamp, tag) pair."""
    unique_pairs = np.unique(np.column_stack((ts_ns, tag_ids)), axis=0)
    return len(ts_ns) - len(unique_pairs)


def _widen(
    ts_ns: np.ndarray, tag_ids: np.ndarray, values: np.ndarray, qualities: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Lay samples out as a timestamp-by-tag grid; a later sample overwrites an earlier one.

    Cells without a sample keep NaN values and BAD quality.
    """
    unique_ts = np.unique(ts_ns)
    unique_tags = np.unique(tag_ids)
    ts_idx = np.searchsorted(unique_ts, ts_ns)
    tag_idx = np.searchsorted(unique_tags, tag_ids)
    shape = (len(unique_ts), len(unique_tags))
    wide_values = np.full(shape, np.nan, dtype=np.float64)
    wide_qualities = np.full(shape, BAD, dtype=np.uint8)
    for row_idx, col_idx, value, quality in zip(ts_idx, tag_idx, values, qualities, strict=True):
        wide_values[row_idx, col_idx] = value
        wide_qualities[row_idx, col_idx] = quality
    return unique_ts, unique_tags, wide_values, wide_qualities


def _read_rows(database: Path, query: str) -> list[tuple[Any, ...]]:
    """Read rows from the sqlite database using the provided query."""
    if not query.strip().upper().startswith("SELECT"):
        raise ValueError("query must be a single SELECT statement")
    if ";" in query:
        raise ValueError("query must be a single statement")

    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        with closing(connection.cursor()) as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            if not rows:
                raise ValueError("no rows returned by the query")
            if len(rows[0]) < 3:
                raise ValueError("query must return at least three columns")
            return rows


def import_sql(
    database: Path,
    query: str,
    out_dir: Path,
    *,
    dataset_id: str,
    tz: str = "UTC",
) -> SqlImportReport:
    """Import a dataset from a sqlite database using a query.

    Parameters
    ----------
    database: Path
        Path to the sqlite database.
    query: str
        Query to execute on the database.
    out_dir: Path
        Destination directory for the created dataset.
    dataset_id: str
        Identifier used inside the dataset metadata.
    tz: str
        Timezone name used for naive timestamps.

    Returns
    -------
    SqlImportReport
        Summary of the import operation.
    """
    rows = _read_rows(database, query)
    ts_ns, tag_ids, values, qualities, n_duplicates_dropped = _pivot_rows(rows, tz)

    write_dataset(
        out_dir,
        ts_ns,
        tag_ids.tolist(),
        values,
        qualities,
        dataset_id=dataset_id,
        source={"kind": "sql"},
        start_utc=_start_iso(ts_ns),
        tags_document=_tags_document(tag_ids),
    )

    return _make_report(ts_ns, tag_ids, values, n_duplicates_dropped)


def _start_iso(ts_ns: np.ndarray) -> str:
    """Return the first timestamp as an ISO-8601 string with a trailing Z, whole seconds."""
    return datetime.fromtimestamp(int(ts_ns[0]) // NS_PER_S, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tags_document(tag_ids: np.ndarray) -> dict[str, Any]:
    """Build the tags.json document: one float tag per identifier, sourced from SQL."""
    return {
        "schema_version": "0.1.0",
        "tags": [
            {
                "id": tag_id,
                "name": tag_id,
                "description": "",
                "unit": "",
                "type": "float",
                "role": "other",
                "source": {"driver": "sql", "address": tag_id},
            }
            for tag_id in tag_ids
        ],
    }


def _make_report(
    ts_ns: np.ndarray, tag_ids: np.ndarray, values: np.ndarray, n_duplicates_dropped: int
) -> SqlImportReport:
    """Summarise the pivoted grid as an SqlImportReport."""
    return SqlImportReport(
        n_rows=ts_ns.shape[0],
        n_tags=tag_ids.shape[0],
        n_duplicates_dropped=n_duplicates_dropped,
        n_bad_values=int(np.isnan(values).sum()),
    )

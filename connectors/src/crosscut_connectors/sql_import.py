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
from crosscut_sim.dataset import DatasetInfo, Samples, write_dataset

from crosscut_connectors.csv_import import (
    _parse_iso8601,
    _sanitize_tag_name,
    _to_utc_nanoseconds,
)
from crosscut_connectors.import_target import ImportTarget

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
    """Parse a timestamp into nanoseconds since the Unix epoch (UTC).

    Accepts either an ISO-8601 string (interpreted in the caller's local time
    zone `tz` when the string carries no offset) or a numeric epoch value in
    seconds. Returns an integer count of nanoseconds since 1970-01-01T00:00:00Z,
    which is the internal time unit used everywhere in this module because it
    keeps sub-microsecond precision and sorts as a plain integer.

    Raises:
        ValueError: if `ts` is neither a string nor a number, or if the string
            cannot be parsed as an ISO-8601 timestamp.
    """
    # Strings go through the full ISO-8601 parser so that offsets, fractional
    # seconds and date-only forms all end up on the same UTC timeline.
    if isinstance(ts, str):
        dt = _parse_iso8601(ts)
        if dt is None:
            raise ValueError("unparseable timestamp")
        return _to_utc_nanoseconds(dt, tz)
    # Numbers are already epoch-relative, so they are simply scaled from
    # seconds to nanoseconds; int() truncates any sub-nanosecond float noise.
    # bool is a subclass of int but is rejected above: True would silently
    # become 1e9 ns, which is never a real timestamp.
    if isinstance(ts, (int, float)):
        return int(ts * NS_PER_S)
    raise ValueError("timestamp must be a string or a numeric value")


def _pivot_rows(
    rows: list[tuple[Any, ...]],
    tz: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Pivot long-format query rows into wide (time x tag) grids.

    "Long" means one row per observation: a timestamp, a tag, a value. "Wide" means
    one row per timestamp and one column per tag, which is the layout charts and
    numeric routines expect.

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
    # Only four values per row are needed (time, tag, value, quality), so the raw
    # database rows are reduced here to four parallel flat arrays of equal length.
    ts_ns, tag_ids, values, qualities = _collect_samples(rows, tz)
    # Sorting by time first means every later step can assume time increases, which
    # allows _count_duplicates and _widen to use sorted data directly.
    ts_ns, tag_ids, values, qualities = _sort_by_time(ts_ns, tag_ids, values, qualities)
    n_duplicates_dropped = _count_duplicates(ts_ns, tag_ids)
    # _widen returns one row per distinct timestamp and one column per distinct tag,
    # with the value and quality grids sharing that shape.
    unique_ts, unique_tags, wide_values, wide_qualities = _widen(ts_ns, tag_ids, values, qualities)
    return unique_ts, unique_tags, wide_values, wide_qualities, n_duplicates_dropped


def _clean_value(raw: Any) -> float:
    """Convert a raw cell to float; NULL, non-numeric or non-finite cells become NaN.

    This is the standardisation step before any numeric work (e.g. an AHP pairwise
    matrix, where every cell must be a comparable number). "Dirty" cells are not an
    error here: they are silently mapped to NaN so the caller can decide how to
    handle missing data instead of crashing on one bad spreadsheet cell.

    Returns:
        The cell as a float, or NaN when the cell is missing, not numeric, or
        infinite. NaN is used as the single "no usable value" marker so that the
        caller only has to test one condition with np.isnan().

    Raises:
        TypeError: if `raw` is a type float() cannot convert at all (e.g. a list);
            a ValueError from a malformed string is handled, but a TypeError is
            not, because a container in a numeric cell signals a caller bug.
    """
    # None has no numeric meaning at all, whereas the string "nan" and the float
    # nan do; short-circuit so NULL never reaches float().
    if raw is None:
        return float("nan")
    try:
        # float() accepts int, float, numeric strings ("3.14", "1e-3") and also
        # strings such as "nan" or "inf", so the finiteness check below is still needed.
        value = float(raw)
    except ValueError:
        # Cell held text that is not a number (e.g. "n/a", "abc"): treat it as missing
        # rather than aborting the whole import.
        return float("nan")
    # np.isfinite() is False for NaN and for +/-inf. Infinities would poison later
    # arithmetic and comparisons, so they are folded into NaN as well: NaN is the one
    # and only missing sentinel this function returns.
    return value if np.isfinite(value) else float("nan")


def _parse_row(row: tuple[Any, ...], tz: str) -> tuple[int, str, float, Any]:
    """Return (timestamp ns, sanitized tag, value, quality) for one query row.

    A "row" is one raw record coming back from the historian database, laid out
    positionally as (timestamp, tag name, value, quality):

    * index 0 -- the sample instant, in a timezone-aware form that
      ``_parse_timestamp`` normalises to nanoseconds since the Unix epoch (int).
    * index 1 -- the raw tag name, normalised by ``_sanitize_tag_name``.
    * index 2 -- the measured value; may be NaN when the historian stored no
      number for that instant.
    * index 3 -- the historian's own quality flag, present only on some queries;
      GOOD means the historian believes the sample is usable.

    A missing or invalid value is always BAD, whatever the quality column says:
    a GOOD label on a NaN sample would otherwise leak a hole into downstream
    maths. Rows shorter than four fields are treated as GOOD when the value is
    finite, which is the convention of the legacy "value only" query shape.

    :param row: one database row, positionally laid out as described above.
    :param tz: IANA timezone name (for example "Europe/Paris") the stored
        timestamp is expressed in.
    :return: a tuple of (timestamp in nanoseconds since the Unix epoch,
        sanitized tag name, value as a float, quality flag).
    :raises ValueError: if the row has fewer than three fields, so there is no
        value to read.
    """
    # _clean_value returns a float or NaN, so np.isnan needs a float; NULL or
    # non-numeric cells become NaN here rather than raising.
    value = _clean_value(row[2])
    # The quality column is optional. Trust it only when we have a finite number:
    # NaN outranks the historian's own opinion and forces BAD.
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
    """Parse every row into parallel arrays of timestamps, tags, values and qualities.

    Returns four equal-length arrays; element i of each describes the same sample.

    The four values are also the input format of the timeseries model (a set of
    measurements of the same quantity taken at successive instants, here one
    column per measurement rather than one row per measurement).

    Raises:
        Whatever ``_parse_row`` raises for a malformed row, and
        ``_check_identifier`` for a tag that maps to two different raw identifiers.
    """
    # One Python list per output column; they are built in lockstep below so that
    # index i always refers to the same sample in all four, then handed to numpy.
    ts_ns: list[int] = []  # sample time as an integer number of nanoseconds since the epoch
    tags: list[str] = []  # name of the signal the sample belongs to, e.g. "pump_1.flow"
    values: list[float] = []  # the measured quantity, in the unit of its tag
    qualities: list[Any] = []  # data-quality flag reported by the historian; 0 means "good"

    # Maps each tag to the raw identifier (row[1]) it was first seen with. The
    # invariant kept is that a tag is a single signal: the same tag must always
    # come from the same raw identifier, otherwise two signals would be silently
    # merged into one series.
    raw_by_tag: dict[str, Any] = {}
    for row in rows:
        ts, tag, value, quality = _parse_row(row, tz)
        _check_identifier(raw_by_tag, tag, row[1])
        ts_ns.append(ts)
        tags.append(tag)
        values.append(value)
        qualities.append(quality)
    # Conversion to numpy lives in a separate helper so that the loop above stays
    # pure data gathering and this function stays short.
    return _build_sample_arrays(ts_ns, tags, values, qualities)


def _build_sample_arrays(
    ts_ns: list[int],
    tags: list[str],
    values: list[float],
    qualities: list[Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert the parsed columns into typed numpy arrays.

    The four lists are parallel: index i in each one describes the same sample.

    Returns one array per column, in the order (timestamps, tags, values, qualities):
    - timestamps: int64, nanoseconds since the Unix epoch (UTC)
    - tags: unicode strings, the signal name the sample belongs to
    - values: float64, the measurement in the signal's own unit
    - qualities: uint8, the OPC-UA status code, 0 meaning "good"
    """
    # numpy needs one homogeneous dtype per array, so each column is converted
    # separately; dtype is given explicitly to fix the width and signedness
    # rather than let numpy infer them from the Python values.
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
    """Read rows from the sqlite database using the provided query.

    The query is expected to be a single SELECT statement returning at least
    three columns: the first three columns of each row are assumed (by the
    callers of this helper) to carry the values the caller needs, in order.

    Args:
        database: Path to the sqlite file, opened read-only so that running a
            report cannot modify the data.
        query: One SELECT statement, without a trailing semicolon.

    Returns:
        The rows exactly as the sqlite driver produced them, one tuple per row.

    Raises:
        ValueError: If the query is not a single SELECT statement, if it
            returns no rows, or if it returns fewer than three columns.
    """
    # Guard clause: the query must be a SELECT. `strip()` removes surrounding
    # whitespace, `upper()` makes the keyword check case-insensitive
    # ("select" and "Select" are both valid sqlite).
    if not query.strip().upper().startswith("SELECT"):
        raise ValueError("query must be a single SELECT statement")
    # A semicolon would allow chaining a second statement (e.g. "SELECT ...; DROP ..."),
    # so we reject any query containing one. The read-only connection below is a
    # second line of defence, not a replacement for this check.
    if ";" in query:
        raise ValueError("query must be a single statement")

    # The URI form "file:///path/to.db?mode=ro" with uri=True tells sqlite to open
    # the database read-only at the file level, so an accidental write fails loudly.
    # `closing(...)` guarantees the connection and the cursor are released even if
    # the body raises.
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        with closing(connection.cursor()) as cursor:
            cursor.execute(query)
            # fetchall() returns a list of tuples, one tuple per result row,
            # each tuple holding the selected columns in query order.
            rows = cursor.fetchall()
            if not rows:
                raise ValueError("no rows returned by the query")
            # Callers index rows[i][0..2], so a narrower result set would fail
            # later with an opaque IndexError. We check it here to fail clearly.
            if len(rows[0]) < 3:
                raise ValueError("query must return at least three columns")
            return rows


def import_sql(database: Path, query: str, target: ImportTarget) -> SqlImportReport:
    """Import a dataset from a sqlite database using a query.

    The query is expected to return one long-format row per (timestamp, tag) pair; this
    function turns that table into the wide "one column per tag" layout the dataset
    writer expects.

    Parameters
    ----------
    database: Path
        Path to the sqlite database.
    query: str
        Query to execute on the database.
    target: ImportTarget
        Output directory, dataset id and the timezone applied to timestamps
        without a UTC offset.

    Returns
    -------
    SqlImportReport
        Summary of the import operation.
    """
    rows = _read_rows(database, query)
    # Pivot from long to wide. The arrays share the row axis (one entry per timestamp)
    # and the column axis (one entry per tag_id); a repeated (timestamp, tag) pair is
    # dropped and only counted, so the arrays stay rectangular.
    #   ts_ns      int64[num_rows]               nanoseconds since the Unix epoch (UTC)
    #   tag_ids    str[num_tags]                 one per column of `values`
    #   values     float64[num_rows, num_tags]   NaN = no sample or invalid
    #   qualities  uint8[num_rows, num_tags]     quality flag per cell
    ts_ns, tag_ids, values, qualities, n_duplicates_dropped = _pivot_rows(rows, target.tz)

    write_dataset(
        target.out_dir,
        Samples(ts_ns, tag_ids.tolist(), values, qualities),
        DatasetInfo(
            dataset_id=target.dataset_id,
            source={"kind": "sql"},
            # start_utc is the dataset's first instant in ISO-8601 form; derived from ts_ns
            # rather than from `rows` so it matches the stored timestamps exactly.
            start_utc=_start_iso(ts_ns),
            tags_document=_tags_document(tag_ids),
        ),
    )

    return _make_report(ts_ns, tag_ids, values, n_duplicates_dropped)


def _start_iso(ts_ns: np.ndarray) -> str:
    """Return the first timestamp as an ISO-8601 string with a trailing Z, whole seconds."""
    return datetime.fromtimestamp(int(ts_ns[0]) // NS_PER_S, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tags_document(tag_ids: np.ndarray) -> dict[str, Any]:
    """Build the tags.json document: one float tag per identifier, sourced from SQL.

    A "tag" is the simulator's name for a single signal it can read or write, roughly
    like a PLC variable: it has an id (the address), a name, a unit and a data type.
    Each identifier in `tag_ids` becomes exactly one tag whose SQL address is the
    identifier itself (this database exposes every signal by its own id).

    Returns a dict with two keys: "schema_version" (the version of the tags.json
    format this document follows) and "tags" (one dict per identifier, in the order
    the identifiers appear in the input array).
    """
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
                # The driver tells the reader how to fetch the value: "sql" means the tag is
                # read by querying the database, and "address" is the key to look it up with.
                "source": {"driver": "sql", "address": tag_id},
            }
            for tag_id in tag_ids
        ],
    }


def _make_report(
    ts_ns: np.ndarray, tag_ids: np.ndarray, values: np.ndarray, n_duplicates_dropped: int
) -> SqlImportReport:
    """Summarise the pivoted grid as an SqlImportReport.

    A "pivot" reshapes long rows (one per timestamp/tag reading) into a matrix whose
    axes are time and tag. That matrix has one column per tag and one row per distinct
    timestamp, so its shape already tells us how many rows and tags we kept.

    Args:
        ts_ns: Distinct timestamps kept, in nanoseconds since the Unix epoch.
        tag_ids: Tag identifiers kept, in the same order as the columns of `values`.
        values: The pivoted readings, shape (n_timestamps, n_tags). Missing readings
            are stored as NaN rather than 0, since 0 is a valid measurement.
        n_duplicates_dropped: Count of input rows discarded because the same
            (timestamp, tag) pair appeared more than once. Already tallied by the
            caller, so it is passed in rather than recomputed here.

    Returns:
        An SqlImportReport whose counts describe the grid that will be written.
    """
    return SqlImportReport(
        n_rows=ts_ns.shape[0],
        n_tags=tag_ids.shape[0],
        n_duplicates_dropped=n_duplicates_dropped,
        n_bad_values=int(np.isnan(values).sum()),
    )

"""Read a whole PI wide CSV file and describe it for the import preview.

Owns the file-reading path for the plant import: it turns the wide CSV (one time column, an
optional `test` label column, hundreds of numeric tag columns) into arrays in UTC plus the
notes, loops and gaps that a user needs to trust the import before it is written.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.csv as pa_csv

from crosscut_loops.plant_import_loops import (
    DetectedLoop,
    DictRow,
    detect_loops,
    read_dictionary,
)
from crosscut_loops.plant_import_time import TimeZoneSpec, to_utc_ns
from crosscut_loops.step_test_io import Note

# Data shapes used in this module
# ------------------------------
# The source file is a wide table: row = one timestamp, column = one tag.
#   * time column: naive LOCAL wall-clock text, e.g. '2026-10-23 08:00:10'
#   * 'test' column: window label text, empty outside test windows
#   * every other column: a numeric tag; an empty or non-numeric cell means missing
# PlantTable keeps the same rows in UTC, with missing values as NaN (float64).

# Column names accepted as the time column when the first column is not named 'timestamp'.
TIME_COLUMN_NAMES = frozenset({"timestamp", "time", "datetime"})
TEST_COLUMN_NAME = "test"

# A step larger than this multiple of the median sampling period is reported as a gap.
GAP_FACTOR = 5.0
MAX_LISTED_GAPS = 20

# pyarrow reads every value as text first so a cell like 'Bad' cannot break the read;
# the strings are then converted to numbers with a null on failure (missing value).
READ_OPTIONS = pa_csv.ReadOptions(block_size=1 << 20)
PARSE_OPTIONS = pa_csv.ParseOptions(delimiter=",")

NS_PER_SECOND = 1_000_000_000


def _text_options(path: Path) -> pa_csv.ConvertOptions:
    """Convert options that read every column as text (the header names come from line 1)."""
    with open(path, encoding="utf-8-sig") as handle:
        names = handle.readline().rstrip("\r\n").split(",")
    return pa_csv.ConvertOptions(column_types={n.strip().strip('"'): pa.string() for n in names})

# Leading date part of a time cell: 'YYYY-MM-DD' or 'YYYY/MM/DD' separated by space or 'T'.
_TIME_TEXT_PATTERN = re.compile(
    r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?"
)


@dataclass(frozen=True)
class PlantTable:
    """A whole PI wide file after reading: UTC times, numeric tags, test labels, notes.

    ts_ns: int64 nanoseconds since Unix epoch in UTC, strictly increasing (a repeated
        timestamp keeps the last row); n rows.
    columns: tag name -> float64 array of length n, NaN where the cell is empty or not a
        number, in the order the file lists them.
    test: object array of length n of label strings, '' outside test windows.
    notes: human-readable notes produced while reading, including the time zone ones.
    first_local, last_local: ISO text of the first and last naive local time as read.
    """

    ts_ns: np.ndarray
    columns: dict[str, np.ndarray]
    test: np.ndarray
    notes: list[Note]
    first_local: str
    last_local: str


def iso_utc(ns: int) -> str:
    """Format int64 UTC nanoseconds as 'YYYY-MM-DDTHH:MM:SSZ'."""
    moment = datetime.fromtimestamp(int(ns) // NS_PER_SECOND, tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _time_column_name(header: list[str]) -> str:
    """Return the name of the time column: the first column or a known time name.

    Raises:
        ValueError: when no column can serve as the time column.
    """
    if not header:
        raise ValueError("data file has no columns; export it with a 'timestamp' column")
    first = header[0]
    if first.strip().lower() in TIME_COLUMN_NAMES:
        return first
    for name in header:
        if name.strip().lower() in TIME_COLUMN_NAMES:
            return name
    raise ValueError(
        "data file has no time column; name it 'timestamp' (or 'time'/'datetime'), "
        f"or put it first (first column is '{first}')"
    )


def _is_text_column(name: str) -> bool:
    """Return True for the test label column (matched case-insensitively)."""
    return name.strip().lower() == TEST_COLUMN_NAME


def _text_cell(value: Any) -> str:
    """Return a text cell as a stripped string, '' when the cell is empty."""
    if value is None:
        return ""
    return str(value).strip()


def _parse_local_times(texts: np.ndarray | pa.Array) -> np.ndarray:
    """Parse time cells to a datetime64[ns] array of naive local times.

    A pure numeric cell is read as epoch seconds (some exporters write PI timestamps that
    way). A malformed cell raises instead of silently dropping a row.
    """
    values = texts.to_pylist()
    parsed = np.empty(len(values), dtype="datetime64[ns]")
    for position, cell in enumerate(values):
        parsed[position] = _parse_one_local_time(_text_cell(cell), position)
    return parsed


def _parse_one_local_time(text: str, row: int) -> np.datetime64:
    """Parse one time cell, raising a friendly error naming the row."""
    try:
        numeric = float(text)
        return np.datetime64(int(round(numeric * NS_PER_SECOND)), "ns")
    except ValueError:
        pass
    match = _TIME_TEXT_PATTERN.match(text)
    if match is None:
        raise ValueError(
            f"row {row + 1}: cannot read time '{text}'; use 'YYYY-MM-DD hh:mm:ss'"
        )
    year, month, day, hour, minute, second = _time_parts(match)
    wall_time = datetime(year, month, day, hour, minute, second)
    return np.datetime64(wall_time, "ns")


def _time_parts(match: re.Match[str]) -> tuple[int, int, int, int, int, int]:
    """Split a matched time pattern into integer date and time fields."""
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4)),
        int(match.group(5)),
        int(match.group(6) or 0),
    )


def _numeric_values(texts: np.ndarray | pa.Array) -> np.ndarray:
    """Convert a text column to float64, NaN where the cell is empty or not a number."""
    values = texts.to_pylist()
    return np.array([_to_float(cell) for cell in values], dtype=np.float64)


def _to_float(value: Any) -> float:
    """Parse one cell as a number, or NaN when it is empty or non-numeric."""
    if value is None:
        return float("nan")
    try:
        return float(str(value).strip())
    except ValueError:
        return float("nan")


def _drop_repeated_times(
    ts_ns: np.ndarray, columns: dict[str, np.ndarray], test: np.ndarray
) -> tuple[np.ndarray, dict[str, np.ndarray], np.ndarray]:
    """Keep only the last row of every repeated timestamp, preserving row order.

    The dataset needs strictly increasing times; scanning backwards keeps the last row of
    each repeated group and drops everything already seen.
    """
    keep = np.ones(ts_ns.size, dtype=bool)
    last_seen: dict[int, int] = {}
    for position in range(ts_ns.size - 1, -1, -1):
        ns = int(ts_ns[position])
        if ns in last_seen:
            keep[position] = False
        else:
            last_seen[ns] = position
    return ts_ns[keep], {tag: col[keep] for tag, col in columns.items()}, test[keep]


def _sorted_ascending(
    ts_ns: np.ndarray, columns: dict[str, np.ndarray], test: np.ndarray
) -> tuple[np.ndarray, dict[str, np.ndarray], np.ndarray, list[Note]]:
    """Drop repeated times and sort rows by time, reporting what changed in the notes."""
    n_before = ts_ns.size
    ts_ns, columns, test = _drop_repeated_times(ts_ns, columns, test)
    order = np.argsort(ts_ns, kind="stable")
    notes: list[Note] = []
    if ts_ns.size != n_before:
        dropped = n_before - ts_ns.size
        notes.append(
            Note(
                "duplicate_times",
                f"{dropped} row(s) with a repeated time were dropped, the last kept",
                {"rows": dropped},
            )
        )
    if not np.all(np.diff(ts_ns) > 0):
        notes.append(Note("unsorted", "rows were sorted by time", {}))
    sorted_ns = ts_ns[order]
    return sorted_ns, {tag: col[order] for tag, col in columns.items()}, test[order], notes


def read_plant_table(path: Path, tz: TimeZoneSpec) -> PlantTable:
    """Read a wide PI CSV into UTC times, numeric tag columns and test labels.

    Args:
        path: the CSV file to read.
        tz: how to read the naive local times in the file.

    Returns:
        A PlantTable with strictly increasing UTC times, one float64 column per tag, the
        `test` label per row and the reading notes.

    Raises:
        ValueError: when the file is empty, has no time column or no readable rows.
    """
    table = pa_csv.read_csv(path, read_options=READ_OPTIONS, parse_options=PARSE_OPTIONS,
                            convert_options=_text_options(path))
    if table.num_rows == 0:
        raise ValueError("data file has no rows; export at least one timed record")
    time_name = _time_column_name(table.column_names)
    local_times = _parse_local_times(table.column(time_name))
    ts_ns, time_notes = to_utc_ns(local_times, tz)
    columns, test = _split_tag_columns(table, time_name)
    notes = [*time_notes, _read_note(table, len(columns))]
    sorted_ns, sorted_columns, sorted_test, change_notes = _sorted_ascending(
        ts_ns, columns, test
    )
    return PlantTable(
        ts_ns=sorted_ns,
        columns=sorted_columns,
        test=sorted_test,
        notes=notes + change_notes,
        first_local=str(local_times[0]),
        last_local=str(local_times[-1]),
    )


def _split_tag_columns(
    table: pa.Table, time_name: str
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Return the numeric tag columns and the test labels of a text table."""
    columns: dict[str, np.ndarray] = {}
    test = np.array([""] * table.num_rows, dtype=object)
    for name in table.column_names:
        if name == time_name:
            continue
        if _is_text_column(name):
            test = np.array([_text_cell(cell) for cell in table.column(name).to_pylist()],
                            dtype=object)
        else:
            columns[name] = _numeric_values(table.column(name))
    return columns, test


def _read_note(table: pa.Table, n_tags: int) -> Note:
    """Note recording how many rows and tag columns were read."""
    text = f"read {table.num_rows} row(s) and {n_tags} tag column(s)"
    return Note("read_plant", text, {"rows": table.num_rows, "columns": n_tags})


def _median_period(ts_ns: np.ndarray) -> float:
    """Median sampling period in seconds; 0.0 when there are fewer than two rows."""
    if ts_ns.size < 2:
        return 0.0
    steps_ns = np.diff(ts_ns)
    return float(np.median(steps_ns)) / NS_PER_SECOND


def find_gaps(
    ts_ns: np.ndarray, factor: float = GAP_FACTOR, limit: int = MAX_LISTED_GAPS
) -> tuple[float, int, list[dict]]:
    """Find time gaps in the UTC times: a step longer than `factor` times the median period.

    Returns:
        (median period in seconds, total number of gaps, up to `limit` gaps as dicts with
        'start_utc', 'end_utc' (ISO text, Z) and 'seconds').
    """
    if ts_ns.size < 2:
        return 0.0, 0, []
    period_s = _median_period(ts_ns)
    steps_ns = np.diff(ts_ns)
    gap_positions = np.flatnonzero(steps_ns > factor * period_s * NS_PER_SECOND)
    gaps = [_gap_dict(ts_ns, position, steps_ns[position])
            for position in gap_positions[:limit]]
    return period_s, int(gap_positions.size), gaps


def _gap_dict(ts_ns: np.ndarray, position: int, step_ns: int) -> dict:
    """Describe the gap that starts after row `position`."""
    return {
        "start_utc": iso_utc(ts_ns[position]),
        "end_utc": iso_utc(ts_ns[position + 1]),
        "seconds": float(step_ns) / NS_PER_SECOND,
    }


def _run_starts(test: np.ndarray) -> np.ndarray:
    """Positions where a run of equal labels (empty ones included) starts."""
    starts = np.ones(test.size, dtype=bool)
    if test.size > 1:
        changed = test[1:] != test[:-1]
        starts[1:] = changed
    return starts


def test_windows(ts_ns: np.ndarray, test: np.ndarray) -> list[dict]:
    """Group contiguous runs of the same non-empty test label into windows.

    Returns:
        One dict per run: 'label', 'start_utc', 'end_utc' (ISO text, Z) and 'rows'.
    """
    starts = np.flatnonzero(_run_starts(test))
    windows: list[dict] = []
    for run_number, start in enumerate(starts):
        end = starts[run_number + 1] if run_number + 1 < starts.size else test.size
        if str(test[start]):  # an empty label is the gap between windows, not a window
            windows.append(_window_dict(ts_ns, test, int(start), int(end)))
    return windows


def _window_dict(ts_ns: np.ndarray, test: np.ndarray, start: int, end: int) -> dict:
    """Describe the test window that covers rows [start, end)."""
    return {
        "label": str(test[start]),
        "start_utc": iso_utc(ts_ns[start]),
        "end_utc": iso_utc(ts_ns[end - 1]),
        "rows": end - start,
    }


def _loop_as_dict(loop: DetectedLoop) -> dict:
    """Return a detected loop as a JSON-safe dict (tuples become lists)."""
    return {key: list(value) if isinstance(value, tuple) else value
            for key, value in dataclasses.asdict(loop).items()}


def _skipped_tags(columns: dict[str, np.ndarray]) -> dict:
    """Describe tags that carry no data at all: every value is NaN."""
    all_nan = sum(1 for values in columns.values() if bool(np.all(np.isnan(values))))
    reason = "tags with no numeric value" if all_nan else ""
    return {"count": all_nan, "reason": reason}


def _note_as_dict(note: Note) -> dict:
    """Return a note as a JSON-safe dict."""
    return {"code": note.code, "text": note.text, "params": dict(note.params)}


def _dictionary_or_none(dictionary_text: str | None) -> list[DictRow] | None:
    """Parse the optional dictionary text; None stays None (roles from tag names)."""
    if dictionary_text is None:
        return None
    return read_dictionary(dictionary_text)


def preview_plant(
    path: Path, dictionary_text: str | None, tz: TimeZoneSpec
) -> dict[str, Any]:
    """Read a wide PI CSV and return a JSON-safe preview of its import.

    Reads the file once, converts times to UTC with `tz`, finds gaps and test windows, and
    detects loops from the tag columns using the dictionary when one is given.

    Returns:
        A dict with the keys n_rows, n_columns, start_local, end_local, start_utc, end_utc,
        period_s, n_gaps, gaps, loops, skipped, test_windows and notes.
    """
    table = read_plant_table(path, tz)
    period_s, n_gaps, gaps = find_gaps(table.ts_ns)
    loops = detect_loops(list(table.columns), _dictionary_or_none(dictionary_text))
    return {
        "n_rows": int(table.ts_ns.size),
        "n_columns": len(table.columns),
        "start_local": table.first_local,
        "end_local": table.last_local,
        "start_utc": iso_utc(int(table.ts_ns[0])),
        "end_utc": iso_utc(int(table.ts_ns[-1])),
        "period_s": period_s,
        "n_gaps": n_gaps,
        "gaps": gaps,
        "loops": [_loop_as_dict(loop) for loop in loops],
        "skipped": _skipped_tags(table.columns),
        "test_windows": test_windows(table.ts_ns, table.test),
        "notes": [_note_as_dict(note) for note in table.notes],
    }

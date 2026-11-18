"""Filter CSV history without changing value or quality cells.

The row-oriented adapter retains source cells and samples the last observed row,
so a bad value keeps the quality and timestamp that explain it.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TIME_COLUMNS = ("timestamp", "timestamp_utc", "time")


@dataclass(frozen=True)
class HistoryWindow:
    """UTC query bounds and an optional sampling period measured in seconds."""

    start: datetime
    end: datetime
    period_s: float | None


def parse_window(start_utc: str, end_utc: str, period_s: float | None) -> HistoryWindow:
    """Validate UTC bounds and a finite, positive sampling period."""
    start, end = _utc_timestamp(start_utc), _utc_timestamp(end_utc)
    if end < start:
        raise ValueError("history end_utc must be at or after start_utc")
    if period_s is not None and (not math.isfinite(period_s) or period_s <= 0):
        raise ValueError("history period_s must be finite and greater than zero seconds")
    return HistoryWindow(start, end, period_s)


def _utc_timestamp(value: str) -> datetime:
    """Interpret an ISO timestamp in UTC; a timestamp without an offset means UTC."""
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        message = f"invalid history timestamp {value!r}; use an ISO 8601 timestamp"
        raise ValueError(message) from error
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def read_history(
    folder: Path, tag_ids: Sequence[str], window: HistoryWindow, options: Mapping[str, Any]
) -> list[dict[str, str]]:
    """Read each requested file once and apply bounds before sampling."""
    selections: dict[str, list[str]] = {}
    for tag_id in tag_ids:
        if "/" in tag_id:
            filename, column = tag_id.split("/", 1)
            selections.setdefault(filename, []).append(column)
    result: list[dict[str, str]] = []
    for filename, columns in selections.items():
        path = folder / filename
        if path.is_file() and path.suffix.lower() == ".csv":
            rows = _read_rows(path, options)
            result.extend(_select_rows(rows, columns, window, options))
    return result


def _read_rows(path: Path, options: Mapping[str, Any]) -> list[dict[str, str]]:
    """Read named CSV cells using the configured delimiter and encoding."""
    with path.open(encoding=options.get("encoding", "utf-8-sig"), newline="") as source:
        return list(csv.DictReader(source, delimiter=options.get("delimiter", ",")))


def _time_column(row: dict[str, str], options: Mapping[str, Any]) -> str:
    """Find the configured timestamp column or a conventional timestamp header."""
    configured = options.get("timestamp_column")
    if configured is not None:
        if configured not in row:
            raise ValueError(f"CSV history timestamp column {configured!r} is missing")
        return str(configured)
    for column in TIME_COLUMNS:
        if column in row:
            return column
    raise ValueError("CSV history needs a timestamp column; set timestamp_column in options")


def _select_rows(
    rows: list[dict[str, str]], columns: list[str], window: HistoryWindow,
    options: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Keep requested long tags or wide columns, ordered by their UTC timestamps."""
    if not rows:
        return []
    time_column = _time_column(rows[0], options)
    tag_column = str(options.get("tag_column", "tag"))
    value_column = str(options.get("value_column", "value"))
    layout = options.get("layout")
    is_long = layout == "long" or (layout is None and {tag_column, value_column} <= rows[0].keys())
    selected = _project_rows(rows, columns, time_column, tag_column if is_long else None)
    # Each entry is one observed row; sorting is stable so the last duplicate wins.
    observations = sorted(
        ((_utc_timestamp(row[time_column]), row) for row in selected),
        key=lambda observation: observation[0],
    )
    bounded = [(stamp, row) for stamp, row in observations if window.start <= stamp < window.end]
    return _sample_rows(bounded, window, tag_column if is_long else None)


def _project_rows(
    rows: list[dict[str, str]], columns: list[str], time_column: str, tag_column: str | None,
) -> list[dict[str, str]]:
    """Preserve long row quality fields or restrict wide rows to requested columns."""
    if tag_column is not None:
        return [row for row in rows if row.get(tag_column) in columns]
    missing = set(columns) - rows[0].keys()
    if missing:
        raise ValueError(f"CSV history columns are missing: {', '.join(sorted(missing))}")
    included = {time_column, *columns}
    return [{name: value for name, value in row.items() if name in included} for row in rows]


def _sample_rows(
    observations: list[tuple[datetime, dict[str, str]]], window: HistoryWindow,
    tag_column: str | None,
) -> list[dict[str, str]]:
    """Take the last observed row per period, separately for each long-format tag."""
    if window.period_s is None:
        return [row for _, row in observations]
    latest: dict[tuple[int, str], tuple[datetime, dict[str, str]]] = {}
    # Bucket k spans [start + k * period_s, start + (k + 1) * period_s), in seconds.
    # Keep actual observation times and omit empty buckets; never invent carried values.
    for timestamp, row in observations:
        bucket = math.floor((timestamp - window.start).total_seconds() / window.period_s)
        tag = row[tag_column] if tag_column is not None else ""
        latest[bucket, tag] = timestamp, row
    return [row for _, row in sorted(latest.values(), key=lambda observation: observation[0])]

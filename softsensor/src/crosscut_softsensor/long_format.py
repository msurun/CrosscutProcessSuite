"""Load long-format lab and online-analyser results from a plant historian export.

The historian exports one row per result (timestamp, tag, value, raw_value); the soft sensor
needs each tag as its own series with its own sample times, so we parse the CSV into
`TagSeries` keyed by tag and expose helpers to feed the model (grid resampling, lab delays).
"""

from __future__ import annotations

import csv
import os
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import numpy as np

from crosscut_softsensor.runner import LabResults

# Named constants keep the meaning of each string and number in one place.
REQUIRED_COLUMNS: Final = ("timestamp", "tag", "value")
TIMESTAMP_FORMAT: Final = "YYYY-MM-DD HH:MM:SS[.fff]"
SECONDS_PER_HOUR: Final = 3600.0
NAN: Final = float("nan")


class LongFormatError(ValueError):
    """Raised when the CSV cannot be read as long-format historian output."""


@dataclass(frozen=True, eq=False)
class TagSeries:
    """Time series for a single tag: sample times in seconds and matching float values."""

    tag: str
    t_s: np.ndarray
    values: np.ndarray


def load_long_csv(
    path: str | os.PathLike[str],
    *,
    tags: Collection[str] | None = None,
    utc_offset_h: float = 0.0,
) -> dict[str, TagSeries]:
    """Read a long-format CSV into a mapping of tag name to `TagSeries`.

    Rows with an empty or non-numeric value are skipped. Duplicate stamps within a tag keep
    the last row and each tag is sorted ascending. If `tags` is given, only those exact tag
    names are kept. `utc_offset_h` is the local offset east of UTC, so true UTC is
    local minus that offset.

    Returns:
        Mapping from tag name to its sorted `TagSeries`.

    Raises:
        LongFormatError: If a required column is missing.
    """
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader: csv.DictReader[str] = csv.DictReader(handle)
        _require_columns(reader.fieldnames, file_path)
        return _collect_by_tag(reader, tags, utc_offset_h)


def to_lab_results(
    series: TagSeries,
    *,
    lab_delay_s: float,
    shift_s: float = 0.0,
) -> LabResults:
    """Convert a `TagSeries` into `LabResults`, shifting stamps by a composite end offset.

    `shift_s` moves each stamp from a period end to its sample (mid-period) time; the lab
    delay is then applied by `LabResults.with_delay`.
    """
    return LabResults.with_delay(series.t_s + shift_s, series.values, lab_delay_s)


def resample_to_grid(
    series: TagSeries,
    t_grid_s: np.ndarray,
    *,
    max_age_s: float,
) -> np.ndarray:
    """Zero-order-hold `series` onto `t_grid_s`, NaN where the held value is too old.

    For each grid time we take the latest sample at or before it (last-value-held). A grid
    point whose latest earlier sample is older than `max_age_s`, or which has no earlier
    sample at all, becomes NaN.
    """
    grid = np.asarray(t_grid_s, dtype=float)
    if len(series.t_s) == 0:
        return np.full(grid.shape, NAN)
    # For each grid point, find the index of the last sample with t_s <= grid point.
    sample_index = np.searchsorted(series.t_s, grid, side="right") - 1
    is_missing = sample_index < 0
    safe_index = np.clip(sample_index, 0, len(series.t_s) - 1)
    held_values = series.values[safe_index]
    held_age_s = grid - series.t_s[safe_index]
    is_stale = held_age_s > max_age_s
    return np.where(is_missing | is_stale, NAN, held_values)


def _require_columns(fieldnames: Sequence[str] | None, file_path: Path) -> None:
    """Raise `LongFormatError` if any required column is missing from the header row."""
    present = set(fieldnames or [])
    for column in REQUIRED_COLUMNS:
        if column not in present:
            raise LongFormatError(
                f"{file_path}: missing required column '{column}'. "
                f"Expected columns: {', '.join(REQUIRED_COLUMNS)}."
            )


def _collect_by_tag(
    reader: csv.DictReader[str],
    tags: Collection[str] | None,
    utc_offset_h: float,
) -> dict[str, TagSeries]:
    """Group parsed rows by tag and build one sorted `TagSeries` per tag."""
    stamp_by_tag: dict[str, dict[float, float]] = {}
    for row in reader:
        parsed = _parse_row(row, tags, utc_offset_h)
        if parsed is None:
            continue
        tag, t_s, value = parsed
        # Later rows win: assigning overwrites an earlier duplicate stamp.
        stamp_by_tag.setdefault(tag, {})[t_s] = value
    return {tag: _build_series(tag, stamps) for tag, stamps in stamp_by_tag.items()}


def _parse_row(
    row: dict[str, str],
    tags: Collection[str] | None,
    utc_offset_h: float,
) -> tuple[str, float, float] | None:
    """Return (tag, t_s, value) for a usable row, or None when the row should be skipped."""
    tag = (row.get("tag") or "").strip()
    if tags is not None and tag not in tags:
        return None
    value = _parse_float(row.get("value"))
    if value is None:
        return None
    t_s = _parse_timestamp(row.get("timestamp"), utc_offset_h)
    return tag, t_s, value


def _parse_float(text: str | None) -> float | None:
    """Parse a float, returning None for empty or non-numeric text."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def _parse_timestamp(text: str | None, utc_offset_h: float) -> float:
    """Parse a stamp as if it were UTC wall clock, then subtract the local offset."""
    stripped = (text or "").strip().replace("T", " ")
    try:
        parsed = datetime.fromisoformat(stripped)
    except ValueError as error:
        raise LongFormatError(
            f"Unparseable timestamp '{stripped}'; expected '{TIMESTAMP_FORMAT}' or ISO 'T'."
        ) from error
    # Treat the wall-clock value as if it were UTC, then correct by the local offset.
    wall_clock_s = parsed.replace(tzinfo=UTC).timestamp()
    return wall_clock_s - utc_offset_h * SECONDS_PER_HOUR


def _build_series(tag: str, stamps: dict[float, float]) -> TagSeries:
    """Turn a deduplicated {t_s: value} mapping into a sorted `TagSeries`."""
    times = np.array(sorted(stamps), dtype=float)
    values = np.array([stamps[t] for t in times], dtype=float)
    return TagSeries(tag=tag, t_s=times, values=values)

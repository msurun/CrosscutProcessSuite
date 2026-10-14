"""Import a LONG-format CSV (one row per timestamp, tag, value) as a dataset.

Historian exports often come as rows of ``time, tag, value[, quality]`` instead of one column per
tag. This reads such a file with the same tolerance as the wide importer (delimiter, decimal
comma, header) and reuses the SQL importer's pivot, so both long-format sources behave alike.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

from crosscut_sim.core import BAD, GOOD, UNCERTAIN

from crosscut_connectors.csv_import import (
    _detect_decimal_separator,
    _detect_delimiter,
    _parse_cell,
    _read_text,
    _sanitize_tag_name,
    _split_lines,
)
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.sql_import import SqlImportReport, _import_rows

MIN_COLUMNS = 3  # timestamp, tag, value
HEADER_ROWS = 1  # the first line names the columns
UNIT_COLUMN_NAMES = ("unit", "units", "eu", "engineering unit")  # header words for the unit column
QUALITY_COLUMN_NAMES = ("quality", "q", "status")  # header words for the quality column
QUALITY_WORDS = {"": GOOD, "good": GOOD, "ok": GOOD, "uncertain": UNCERTAIN, "bad": BAD}


class LongFile(NamedTuple):
    """A parsed long-format file: its rows and the engineering unit of each tag."""

    rows: list[tuple[Any, ...]]
    units: dict[str, str]  # sanitised tag id -> unit text; only tags that have a unit


def read_long_rows(path: Path) -> list[tuple[Any, ...]]:
    """Parse the file into ``(timestamp text, tag, value[, quality])`` rows, header dropped.

    See :func:`read_long_file` for the rules; this returns the rows only.
    """
    return read_long_file(path).rows


def read_long_file(path: Path) -> LongFile:
    """Parse the file into rows and per-tag units.

    Cells that are not numbers become NaN (the importer marks them BAD). The optional columns are
    found by their header word: ``quality`` / ``q`` / ``status`` (a number 0 good, 1 uncertain,
    2 bad, or the words good / ok / uncertain / bad, or empty = good) and ``unit`` / ``units`` /
    ``eu``. Without a recognised header word the fourth column is the quality, as before.

    Raises:
        ValueError: if the file has fewer than three columns, a quality cell is none of these, or
            one tag is given two different units.
    """
    lines = _split_lines(_read_text(path))
    delimiter = _detect_delimiter(lines)
    cells = [line.split(delimiter) for line in lines[HEADER_ROWS:]]
    if not cells or min(len(row) for row in cells) < MIN_COLUMNS:
        raise ValueError("a long-format CSV needs at least timestamp, tag and value columns")
    quality_at, unit_at = _optional_columns(lines[0].split(delimiter))
    decimal = _detect_decimal_separator([[row[0], row[2]] for row in cells], delimiter)
    rows = [
        (
            row[0].strip(),
            row[1].strip(),
            _parse_cell(row[2], decimal),
            *_quality_of(row[quality_at : quality_at + 1] if quality_at is not None else []),
        )
        for row in cells
    ]
    return LongFile(rows, _units_by_tag(cells, unit_at))


def _optional_columns(header: list[str]) -> tuple[int | None, int | None]:
    """Column index of the quality and of the unit, from the header words (None when absent)."""
    names = [cell.strip().lower() for cell in header]
    unit_at = next((i for i, name in enumerate(names) if name in UNIT_COLUMN_NAMES), None)
    quality_at = next((i for i, name in enumerate(names) if name in QUALITY_COLUMN_NAMES), None)
    if quality_at is None and unit_at != MIN_COLUMNS:
        quality_at = MIN_COLUMNS  # legacy layout: the fourth column is the quality
    return quality_at, unit_at


def _units_by_tag(cells: list[list[str]], unit_at: int | None) -> dict[str, str]:
    """First non-empty unit of every tag; two different units for one tag are an error."""
    units: dict[str, str] = {}
    if unit_at is None:
        return units
    for row in cells:
        unit = row[unit_at].strip() if len(row) > unit_at else ""
        tag = _sanitize_tag_name(row[1].strip())
        if unit and units.setdefault(tag, unit) != unit:
            raise ValueError(f"tag {tag!r} has two units: {units[tag]!r} and {unit!r}")
    return units


def _quality_of(cell: list[str]) -> list[int]:
    """The quality flag of a row as a one-element list, or [] when the file has no such column."""
    if not cell:
        return []
    text = cell[0].strip()
    if text.lower() in QUALITY_WORDS:
        return [QUALITY_WORDS[text.lower()]]
    try:
        return [int(text)]
    except ValueError:
        raise ValueError(f"unknown quality {text!r}; use 0/1/2 or good, uncertain, bad") from None


def import_csv_long(path: Path, target: ImportTarget) -> SqlImportReport:
    """Import a long-format CSV; ``target.tz`` applies to timestamps without a UTC offset."""
    parsed = read_long_file(path)
    return _import_rows(parsed.rows, target, parsed.units)

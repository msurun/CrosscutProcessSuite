"""Import a LONG-format CSV (one row per timestamp, tag, value) as a dataset.

Historian exports often come as rows of ``time, tag, value[, quality]`` instead of one column per
tag. This reads such a file with the same tolerance as the wide importer (delimiter, decimal
comma, header) and reuses the SQL importer's pivot, so both long-format sources behave alike.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from crosscut_sim.core import BAD, GOOD, UNCERTAIN

from crosscut_connectors.csv_import import (
    _detect_decimal_separator,
    _detect_delimiter,
    _parse_cell,
    _read_text,
    _split_lines,
)
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.sql_import import SqlImportReport, _import_rows

MIN_COLUMNS = 3  # timestamp, tag, value
HEADER_ROWS = 1  # the first line names the columns
QUALITY_WORDS = {"": GOOD, "good": GOOD, "ok": GOOD, "uncertain": UNCERTAIN, "bad": BAD}


def read_long_rows(path: Path) -> list[tuple[Any, ...]]:
    """Parse the file into ``(timestamp text, tag, value[, quality])`` rows, header dropped.

    Cells that are not numbers become NaN (the importer marks them BAD). The optional fourth column
    is the quality flag: a number (0 good, 1 uncertain, 2 bad), or the words good / ok / uncertain
    / bad, or empty (= good).

    Raises:
        ValueError: if the file has fewer than three columns or a quality cell is none of these.
    """
    lines = _split_lines(_read_text(path))
    delimiter = _detect_delimiter(lines)
    cells = [line.split(delimiter) for line in lines[HEADER_ROWS:]]
    if not cells or min(len(row) for row in cells) < MIN_COLUMNS:
        raise ValueError("a long-format CSV needs at least timestamp, tag and value columns")
    decimal = _detect_decimal_separator([[row[0], row[2]] for row in cells], delimiter)
    return [
        (row[0].strip(), row[1].strip(), _parse_cell(row[2], decimal), *_quality_of(row[3:4]))
        for row in cells
    ]


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
    return _import_rows(read_long_rows(path), target)

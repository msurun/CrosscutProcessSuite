"""Import a LONG-format CSV (one row per timestamp, tag, value) as a dataset.

Historian exports often come as rows of ``time, tag, value[, quality]`` instead of one column per
tag. This reads such a file with the same tolerance as the wide importer (delimiter, decimal
comma, header) and reuses the SQL importer's pivot, so both long-format sources behave alike.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


def read_long_rows(path: Path) -> list[tuple[Any, ...]]:
    """Parse the file into ``(timestamp text, tag, value[, quality])`` rows, header dropped.

    Cells that are not numbers become NaN (the importer marks them BAD); the optional fourth
    column is passed on untouched as the quality flag.
    """
    lines = _split_lines(_read_text(path))
    delimiter = _detect_delimiter(lines)
    cells = [line.split(delimiter) for line in lines[HEADER_ROWS:]]
    if not cells or min(len(row) for row in cells) < MIN_COLUMNS:
        raise ValueError("a long-format CSV needs at least timestamp, tag and value columns")
    decimal = _detect_decimal_separator([[row[0], row[2]] for row in cells], delimiter)
    return [
        (row[0].strip(), row[1].strip(), _parse_cell(row[2], decimal), *row[3:4]) for row in cells
    ]


def import_csv_long(path: Path, target: ImportTarget) -> SqlImportReport:
    """Import a long-format CSV; ``target.tz`` applies to timestamps without a UTC offset."""
    return _import_rows(read_long_rows(path), target)

"""CSV round trip of the tag section of the site catalogue (issue #144).

The site's tags are exported as a flat CSV for editing in a spreadsheet and
imported back again. The header carries every tag field of the schema (id
first, the rest sorted); a list or dict is JSON-encoded in its cell; an
empty cell means the optional field is not stated, so an empty string does
not survive a round trip.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from crosscut_connectors.site import SCHEMA_PATH, validate_site

IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")  # the schema's identifier pattern
IDENTIFIER_LENGTH = 128  # schema maxLength of an identifier, in characters
DTYPE_VALUES = ("float", "int", "bool", "string")  # the schema's dtype enum
QUALITY_WORDS = ("good", "bad", "uncertain")  # values of one quality_map cell
DEADBAND_UNITS = ("engineering", "percent_of_span")  # the schema's deadband_unit enum
LIMIT_KEYS = ("min", "max")  # the only keys a limits object may hold
SAMPLE_KEYS = ("period_s", "on_change")  # the only keys a sampling object may hold
COMPRESSION_KEYS = ("deadband", "deadband_unit")  # the only keys a compression object may hold


@dataclass(frozen=True)
class RowError:
    """One problem found while reading a tag CSV.

    ``row`` is the 1-based data row; row 0 names the header line, and the
    empty column name names the whole row (no single column at fault).
    """

    row: int
    column: str
    message: str


@dataclass(frozen=True)
class CsvImport:
    """The parsed tag file: either the tags or the reasons the file was refused.

    ``tags`` is empty whenever ``errors`` is not (all-or-nothing import).
    """

    tags: list[dict]
    errors: list[RowError]


_TAG_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]["tag"]
TAG_FIELDS = ("id",) + tuple(
    name for name in sorted(_TAG_SCHEMA["properties"]) if name != "id"
)
REQUIRED_FIELDS = tuple(_TAG_SCHEMA.get("required", ()))


def _is_number(value: Any) -> bool:
    """True for an int or a float, but not a bool (a JSON boolean, not a number)."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _check_text(cell: str) -> str:
    """Plain text fields (name, description, unit, area, address): any text is fine."""
    return cell


def _check_identifier(cell: str) -> str:
    if len(cell) > IDENTIFIER_LENGTH or not IDENTIFIER.match(cell):
        raise ValueError("must be 1-128 characters of letters, digits, '_', '.', ':' or '-'")
    return cell


def _check_dtype(cell: str) -> str:
    if cell not in DTYPE_VALUES:
        raise ValueError(f"must be one of {'/'.join(DTYPE_VALUES)}")
    return cell


def _load_json(cell: str, what: str) -> Any:
    try:
        return json.loads(cell)
    except json.JSONDecodeError as problem:
        raise ValueError(f"{what} must be JSON: {problem.msg}") from None


def _check_object_keys(value: Any, allowed: tuple[str, ...]) -> None:
    if not isinstance(value, dict):
        raise ValueError("must be a JSON object")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ValueError(f"unknown key {unknown[0]!r}; the schema allows {', '.join(allowed)}")


def _check_limits(cell: str) -> dict:
    value = _load_json(cell, "a limits cell")
    _check_object_keys(value, LIMIT_KEYS)
    if not value or not all(_is_number(item) for item in value.values()):
        raise ValueError("must state min and/or max as numbers")
    return value


def _check_sampling(cell: str) -> dict:
    value = _load_json(cell, "a sampling cell")
    _check_object_keys(value, SAMPLE_KEYS)
    if "period_s" in value and not (_is_number(value["period_s"]) and value["period_s"] > 0):
        raise ValueError("period_s must be a number above 0")
    if "on_change" in value and not isinstance(value["on_change"], bool):
        raise ValueError("on_change must be true or false")
    return value


def _check_compression(cell: str) -> dict:
    value = _load_json(cell, "a compression cell")
    _check_object_keys(value, COMPRESSION_KEYS)
    deadband = value.get("deadband")
    if deadband is not None and not (_is_number(deadband) and deadband >= 0):
        raise ValueError("deadband must be a number of 0 or more")
    if "deadband_unit" in value and value["deadband_unit"] not in DEADBAND_UNITS:
        raise ValueError(f"deadband_unit must be one of {'/'.join(DEADBAND_UNITS)}")
    return value


def _check_number_list(cell: str) -> list:
    value = _load_json(cell, "a missing_codes cell")
    if not isinstance(value, list) or not all(_is_number(item) for item in value):
        raise ValueError("must be a JSON list of numbers")
    if len(set(value)) != len(value):
        raise ValueError("must not repeat a value")
    return value


def _check_text_list(cell: str) -> list:
    value = _load_json(cell, "a missing_text_codes cell")
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError("must be a JSON list of non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError("must not repeat a value")
    return value


def _check_quality_map(cell: str) -> dict:
    value = _load_json(cell, "a quality_map cell")
    if not isinstance(value, dict) or any(word not in QUALITY_WORDS for word in value.values()):
        raise ValueError(f"must map codes to one of {'/'.join(QUALITY_WORDS)}")
    return value


CELL_CHECKS: dict[str, Callable[[str], Any]] = {
    "id": _check_identifier,
    "source": _check_identifier,
    "dtype": _check_dtype,
    "range": _check_limits,
    "eng_limits": _check_limits,
    "sampling": _check_sampling,
    "compression": _check_compression,
    "missing_codes": _check_number_list,
    "missing_text_codes": _check_text_list,
    "quality_map": _check_quality_map,
}


def export_tags_csv(site: dict) -> str:
    """The site's tags as CSV text: a header row, then one row per tag.

    The header carries every tag field of the schema, id first and the rest
    sorted; lists and dicts are JSON-encoded in their cell, and a field the
    tag does not state becomes an empty cell.
    """
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(TAG_FIELDS)
    for tag in site.get("tags", ()):
        writer.writerow([_export_cell(tag.get(name)) for name in TAG_FIELDS])
    return stream.getvalue()


def _export_cell(value: Any) -> str:
    """The CSV cell of one tag value; lists and dicts go out as JSON text."""
    if value is None:
        return ""
    if isinstance(value, list | dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def parse_tags_csv(text: str, site: dict) -> CsvImport:
    """Parse a tag CSV into a CsvImport, reporting every problem it finds.

    ``site`` is the catalogue the import will later be applied to; it is kept
    in the signature so reference checks against it can be added without
    changing callers. Row 0 reports problems of the header line; a blank
    line is not a data row.
    """
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0] if rows else []
    columns = {name: index for index, name in enumerate(header)}
    errors = _header_errors(header)
    tags: list[dict] = []
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows[1:], start=1):
        if not row:
            continue
        errors += _row_length_errors(row_number, header, row)
        tag, row_errors = _import_row(row_number, row, columns)
        errors += row_errors
        if tag is not None:
            tag_id = tag["id"]
            if tag_id in seen_ids:
                errors.append(RowError(row_number, "id", f"duplicate id {tag_id!r}"))
            seen_ids.add(tag_id)
            tags.append(tag)
    if errors:
        return CsvImport(tags=[], errors=errors)
    return CsvImport(tags=tags, errors=[])


def _header_errors(header: list[str]) -> list[RowError]:
    """Problems of the header line: unknown columns and missing required ones."""
    unknown = [
        RowError(0, name, "column is not a tag field of the schema")
        for name in header
        if name not in TAG_FIELDS
    ]
    missing = [
        RowError(0, name, "required column is missing")
        for name in REQUIRED_FIELDS
        if name not in header
    ]
    return unknown + missing


def _row_length_errors(row_number: int, header: list[str], row: list[str]) -> list[RowError]:
    """A data row with more cells than the header names is malformed."""
    extra = len(row) - len(header)
    if extra <= 0:
        return []
    return [RowError(row_number, "", f"{extra} more cells than the header names")]


def _import_row(
    row_number: int, row: list[str], columns: dict[str, int]
) -> tuple[dict[str, Any] | None, list[RowError]]:
    """One data row as a tag dict, or (None, the errors) when the row is no tag."""
    tag: dict[str, Any] = {}
    errors: list[RowError] = []
    for name in TAG_FIELDS:
        if name not in columns:
            continue
        cell = row[columns[name]] if columns[name] < len(row) else ""
        if cell == "":
            if name in REQUIRED_FIELDS:
                errors.append(RowError(row_number, name, "required value is missing"))
            continue
        check = CELL_CHECKS.get(name, _check_text)
        try:
            tag[name] = check(cell)
        except ValueError as problem:
            errors.append(RowError(row_number, name, str(problem)))
    if "id" not in tag:
        return None, errors
    return tag, errors


def apply_tags_import(site: dict, result: CsvImport) -> dict:
    """A new site document whose tags are replaced by the import, validated.

    Existing ids are updated in place and new ids are appended in file
    order. Raises ValueError when the import was refused or the resulting
    document fails validation.
    """
    if result.errors:
        raise ValueError(_rejection_message(result))
    document = copy.deepcopy(site)
    imported = {tag["id"]: tag for tag in result.tags}
    existing = document.get("tags", [])
    merged = [imported.get(tag["id"], tag) for tag in existing]
    fresh = [tag for tag in result.tags if tag["id"] not in {t["id"] for t in existing}]
    document["tags"] = merged + fresh
    problems = validate_site(document)
    if problems:
        raise ValueError("imported site is not acceptable: " + "; ".join(problems))
    return document


def _rejection_message(result: CsvImport) -> str:
    """What to fix before the import can be applied, with up to three examples."""
    shown = "; ".join(
        f"row {error.row} {error.column}: {error.message}" for error in result.errors[:3]
    )
    if len(result.errors) > 3:
        shown += f" ({len(result.errors) - 3} more)"
    return f"cannot apply a refused import: {shown}"

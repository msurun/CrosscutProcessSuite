"""Read and edit the per-loop knowledge of a project file.

The analysis tunes itself from a few numbers per loop (transport delay, ultimate period,
amplitude limit, process kind). This module validates edits to those numbers, applies them
to a deep copy of the project and writes the result atomically, so a crash never leaves a
half-written project file behind.
"""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from crosscut_loops.overview import LoopTags
from crosscut_loops.project_loops import (
    AMPLITUDE_LIMIT_KEY,
    DEFAULT_PROCESS_KIND,
    DELAY_KEY,
    ENG_MAX_KEY,
    ENG_MIN_KEY,
    ID_KEY,
    LOOPS_KEY,
    MODE_KEY,
    NAME_KEY,
    OUT_ENG_MAX_KEY,
    OUT_ENG_MIN_KEY,
    OUT_KEY,
    PROCESS_KIND_KEY,
    PV_ENG_MAX_KEY,
    PV_ENG_MIN_KEY,
    PV_KEY,
    SP_KEY,
    ULTIMATE_PERIOD_KEY,
    VENDOR_KEY,
)
from crosscut_loops.vendor_forms import VENDOR_FORMS

# The per-loop keys that carry the user's tuning knowledge.
# The four engineering-range overrides (PV and OUT, min and max) are knowledge keys too.
ENG_OVERRIDE_KEYS = (PV_ENG_MIN_KEY, PV_ENG_MAX_KEY, OUT_ENG_MIN_KEY, OUT_ENG_MAX_KEY)
KNOWLEDGE_KEYS = (
    DELAY_KEY,
    ULTIMATE_PERIOD_KEY,
    AMPLITUDE_LIMIT_KEY,
    PROCESS_KIND_KEY,
    VENDOR_KEY,
    *ENG_OVERRIDE_KEYS,
)
# Per signal: (loop-entry role key, override min key, override max key).
_SIGNAL_RANGES = (
    ("pv", PV_KEY, PV_ENG_MIN_KEY, PV_ENG_MAX_KEY),
    ("out", OUT_KEY, OUT_ENG_MIN_KEY, OUT_ENG_MAX_KEY),
)
# Numeric knowledge keys must be strictly positive; the value is in the key's own unit
# (seconds for the two time keys, engineering units for the amplitude limit).
NUMERIC_KNOWLEDGE_KEYS = (DELAY_KEY, ULTIMATE_PERIOD_KEY, AMPLITUDE_LIMIT_KEY)
PROCESS_KINDS = (DEFAULT_PROCESS_KIND, "integrating")
# JSON files are human files: two-space indent and UTF-8 keep diffs readable.
JSON_INDENT = 2
JSON_ENSURE_ASCII = False


class KnowledgeError(ValueError):
    """Raised when a knowledge update names an unknown key or carries an invalid value."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def validate_knowledge(update: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a knowledge update and return a cleaned copy with floats as float.

    ``update`` may contain only keys of ``KNOWLEDGE_KEYS``; a value of None means "clear this
    key". Numeric keys must be real numbers (not bool), finite and strictly positive;
    ``process_kind`` must be one of ``PROCESS_KINDS``. The four engineering-range overrides
    (``ENG_OVERRIDE_KEYS``) must be finite real numbers of any sign.

    Returns:
        A new dict with the validated values (None kept as None to signal "clear").

    Raises:
        KnowledgeError: for an unknown key, a non-numeric value, a non-finite or
            non-positive number, or a process kind outside ``PROCESS_KINDS``.
    """
    unknown_key = _first_unknown_key(update)
    if unknown_key is not None:
        raise KnowledgeError(f"unknown knowledge key {unknown_key!r}")
    return {key: _clean_value(key, value) for key, value in update.items()}


def find_entry(project: Mapping[str, Any], loop_name: str) -> dict[str, Any]:
    """The loop entry of the project whose display name equals ``loop_name``.

    The display name is the entry's ``name`` when present, its ``id`` otherwise. The real
    dict inside ``project[LOOPS_KEY]`` is returned, so callers can build a deep copy of it.

    Raises:
        KeyError: when no loop has that display name.
    """
    for entry in project.get(LOOPS_KEY, []):
        if _display_name(entry) == loop_name:
            found: dict[str, Any] = entry
            return found
    raise KeyError(f"no loop named {loop_name!r} in the project")


def loop_knowledge(project: Mapping[str, Any], loop_name: str) -> dict[str, Any]:
    """The knowledge of one loop, None for every key it does not define.

    ``process_kind`` falls back to ``"self_regulating"`` when absent, matching the analysis
    default, so a fresh loop always reports a concrete kind.

    Raises:
        KeyError: when no loop has that display name.
    """
    entry = find_entry(project, loop_name)
    knowledge = {key: entry.get(key) for key in KNOWLEDGE_KEYS}
    # The analysis treats a missing process kind as self-regulating; report it the same way.
    if knowledge[PROCESS_KIND_KEY] is None:
        knowledge[PROCESS_KIND_KEY] = DEFAULT_PROCESS_KIND
    return knowledge


def apply_knowledge(
    project: Mapping[str, Any],
    loop_name: str,
    update: Mapping[str, Any],
    tags: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return a deep copy of ``project`` with ``update`` applied to one loop.

    A None value in the validated update removes that key from the entry. Afterwards each
    signal's effective range (entry override, else tag row from ``tags``) must have min < max
    when both ends are known.

    Raises:
        KnowledgeError: when ``update`` is invalid (see ``validate_knowledge``) or leaves an
            effective range with min >= max.
        KeyError: when no loop has that display name.
    """
    cleaned = validate_knowledge(update)
    edited_project: dict[str, Any] = copy.deepcopy(dict(project))
    entry = find_entry(edited_project, loop_name)
    for key, value in cleaned.items():
        _set_or_remove(entry, key, value)
    _check_effective_ranges(entry, tags)
    return edited_project


def tag_range_defaults(
    project: Mapping[str, Any], loop_name: str, tags: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, float | None]]:
    """The tag rows' own ranges of one loop: ``pv_eng_default`` and ``out_eng_default``.

    Each value is ``{"min": ..., "max": ...}`` from the tag row (None where it has none), i.e.
    what applies when the loop entry carries no override.

    Raises:
        KeyError: when no loop has that display name.
    """
    entry = find_entry(project, loop_name)
    rows = _rows_by_id(tags)
    return {
        f"{signal}_eng_default": _row_range(rows.get(str(entry.get(role_key))))
        for signal, role_key, _, _ in _SIGNAL_RANGES
    }


def project_from_loops(loops: Sequence[LoopTags]) -> dict[str, Any]:
    """Build a minimal project mapping from a sequence of loops, in the given order.

    Each loop becomes an entry identified by its name. Only knowledge that differs from the
    defaults (a defined value, or a non-default process kind) is written, so the file stays
    short and readable.
    """
    return {LOOPS_KEY: [_entry_from_loop(loop) for loop in loops]}


def write_project_atomic(path: Path, project: Mapping[str, Any]) -> None:
    """Write ``project`` as UTF-8 JSON to ``path`` via a temp file in the same directory.

    Writing to a sibling temp file and then ``os.replace``-ing it makes the rename atomic on
    POSIX and Windows, so a crash leaves either the old file or the new one, never a partial
    file. The JSON uses two-space indentation, keeps non-ASCII text readable and ends with a
    newline.
    """
    directory = path.parent
    # same-dir temp file: os.replace is only atomic within one filesystem.
    handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temp_file:
            json.dump(project, temp_file, indent=JSON_INDENT, ensure_ascii=JSON_ENSURE_ASCII)
            temp_file.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        # Clean the temp file up on any failure and re-raise: never swallow the error.
        _remove_quietly(temp_name)
        raise


def _first_unknown_key(update: Mapping[str, Any]) -> str | None:
    """The first update key that is not in KNOWLEDGE_KEYS, or None when all are known."""
    for key in update:
        if key not in KNOWLEDGE_KEYS:
            return key
    return None


def _clean_value(key: str, value: Any) -> Any:
    """The validated value for one key; None is kept to signal "clear this key"."""
    if value is None:
        return None
    if key == PROCESS_KIND_KEY:
        return _clean_process_kind(value)
    if key == VENDOR_KEY:
        return _clean_vendor(value)
    if key in ENG_OVERRIDE_KEYS:
        return _clean_finite_number(key, value)
    return _clean_positive_number(key, value)


def _clean_process_kind(value: Any) -> str:
    """The process kind as text, checked against PROCESS_KINDS."""
    if not isinstance(value, str) or value not in PROCESS_KINDS:
        raise KnowledgeError(f"process_kind must be one of {PROCESS_KINDS}, got {value!r}")
    return value


def _clean_vendor(value: Any) -> str:
    """The vendor form key as text, checked against the keys of VENDOR_FORMS."""
    if not isinstance(value, str) or value not in VENDOR_FORMS:
        raise KnowledgeError(f"vendor must be one of {tuple(VENDOR_FORMS)}, got {value!r}")
    return value


def _clean_finite_number(key: str, value: Any) -> float:
    """The value as a finite float of any sign.

    ``bool`` is rejected explicitly: in Python ``True`` is an int and would pass silently.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KnowledgeError(f"{key} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise KnowledgeError(f"{key} must be finite, got {value!r}")
    return number


def _rows_by_id(tags: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """The tag rows indexed by tag id."""
    return {str(row[ID_KEY]): row for row in tags}


def _row_range(row: Mapping[str, Any] | None) -> dict[str, float | None]:
    """``{"min", "max"}`` of a tag row; both None when the row is missing."""
    source: Mapping[str, Any] = row or {}
    return {"min": source.get(ENG_MIN_KEY), "max": source.get(ENG_MAX_KEY)}


def _check_effective_ranges(entry: Mapping[str, Any], tags: Sequence[Mapping[str, Any]]) -> None:
    """Raise KnowledgeError when a signal's effective range has min >= max."""
    rows = _rows_by_id(tags)
    for signal, role_key, min_key, max_key in _SIGNAL_RANGES:
        default = _row_range(rows.get(str(entry.get(role_key))))
        low = entry.get(min_key, default["min"])
        high = entry.get(max_key, default["max"])
        if low is not None and high is not None and low >= high:
            raise KnowledgeError(f"{signal} range needs min < max, got {low!r} and {high!r}")


def _clean_positive_number(key: str, value: Any) -> float:
    """The value as a finite float strictly greater than zero."""
    number = _clean_finite_number(key, value)
    if number <= 0.0:
        raise KnowledgeError(f"{key} must be finite and greater than 0, got {value!r}")
    return number


def _display_name(entry: Mapping[str, Any]) -> str:
    """The entry's display name: its name, or its id when the name is missing or empty.

    This is the same rule as ``project_loops._loop_name``, so a loop is found here under the
    name the analysis reports it by.
    """
    name = "" if entry.get(NAME_KEY) is None else str(entry[NAME_KEY])
    return name or ("" if entry.get(ID_KEY) is None else str(entry[ID_KEY]))


def _set_or_remove(entry: dict[str, Any], key: str, value: Any) -> None:
    """Set the key to value, or delete it when the value is None."""
    if value is None:
        entry.pop(key, None)
    else:
        entry[key] = value


def _entry_from_loop(loop: LoopTags) -> dict[str, Any]:
    """The project entry of one loop: identity tags plus its non-default knowledge."""
    entry: dict[str, Any] = {
        ID_KEY: loop.name,
        NAME_KEY: loop.name,
        PV_KEY: loop.pv,
        SP_KEY: loop.sp,
        OUT_KEY: loop.out,
        MODE_KEY: loop.mode,
    }
    _add_defined_knowledge(entry, loop)
    return entry


def _add_defined_knowledge(entry: dict[str, Any], loop: LoopTags) -> None:
    """Copy the loop's non-default knowledge into the entry in place."""
    # A None field means "not configured": leave the key out so the default applies.
    field_by_key = {
        DELAY_KEY: loop.delay_s,
        ULTIMATE_PERIOD_KEY: loop.ultimate_period_s,
        AMPLITUDE_LIMIT_KEY: loop.amplitude_limit,
    }
    for key, value in field_by_key.items():
        if value is not None:
            entry[key] = value
    # Only a non-default process kind is written; the default would just add noise.
    if loop.process_kind != DEFAULT_PROCESS_KIND:
        entry[PROCESS_KIND_KEY] = loop.process_kind
    if loop.vendor is not None:
        entry[VENDOR_KEY] = loop.vendor


def _remove_quietly(path_name: str) -> None:
    """Delete ``path_name`` ignoring a missing file; other errors are raised."""
    try:
        os.unlink(path_name)
    except FileNotFoundError:
        return

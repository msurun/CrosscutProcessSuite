# loops/src/crosscut_loops/project_loops.py
"""Build the LoopTags of a project from its ``loops`` entries and its tag list.

The project file names the tags of every loop explicitly (unlike ``overview.discover_loops``, which
guesses them from the ``_sp``/``_out``/``_mode`` naming convention), so this module is the bridge
between a hand-written project description and the analysis in ``overview``.

An entry that points at a tag the project does not define cannot be analysed: it is skipped and the
remaining loops are kept, so one typo in a project file does not hide the whole plant.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from crosscut_loops.overview import LoopTags

# --- Project file keys ------------------------------------------------------

LOOPS_KEY = "loops"
ID_KEY = "id"
NAME_KEY = "name"
PV_KEY = "pv"
SP_KEY = "sp"
OUT_KEY = "out"
MODE_KEY = "mode"
UNIT_KEY = "unit"
ENG_MIN_KEY = "eng_min"
ENG_MAX_KEY = "eng_max"
DELAY_KEY = "delay_s"
ULTIMATE_PERIOD_KEY = "ultimate_period_s"
AMPLITUDE_LIMIT_KEY = "amplitude_limit"

# The four tag ids a loop must reference to be analysable.
REQUIRED_TAG_KEYS = (PV_KEY, SP_KEY, OUT_KEY, MODE_KEY)


def loops_from_project(
    project: Mapping[str, Any], tags: Sequence[Mapping[str, Any]]
) -> list[LoopTags]:
    """Build one LoopTags per analysable loop entry of the project.

    A "loop" is a control loop (PID): it reads a process variable (pv), compares it with a
    setpoint (sp), and drives an output (out) between manual and automatic (mode).  A "tag" is
    the plant's definition of one signal: its id, unit of measure and engineering range.

    Entries whose ``pv``, ``sp``, ``out`` or ``mode`` is absent, or names a tag that ``tags`` does
    not define, are skipped; the order of the project file is preserved.

    Args:
        project: the project mapping; its ``loops`` key holds the loop entries.
        tags: raw tag rows, each with an ``id`` and optionally ``unit``, ``eng_min``, ``eng_max``.

    Returns:
        The loops that can be analysed, in project order.
    """
    # Resolve every tag id once, up front, so the per-entry work below is a dict lookup instead
    # of a scan over the whole tag list.  tag_rows maps tag id (str) -> tag row (mapping).
    tag_rows = _index_tags_by_id(tags)
    # _analysable_entries yields the loop entries that pass the checks (in project order) and
    # _build_loop turns each entry plus the tag index into a LoopTags.  Splitting the two steps
    # keeps the filtering decision free of the construction side effect.
    return [_build_loop(entry, tag_rows) for entry in _analysable_entries(project, tag_rows)]


def _analysable_entries(
    project: Mapping[str, Any], tag_rows: Mapping[str, Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """The project's loop entries whose four tags all exist, in project order.

    A "loop" is one control loop of the plant (a level loop, a flow loop, ...).
    Each entry in `project[LOOPS_KEY]` is a mapping of tag roles to tag names, so the
    builder downstream needs every tag of the entry to be resolvable.

    `tag_rows` maps a tag name to that tag's row from the tag list; it acts as the
    lookup table of the tags that exist.

    An entry that names an unknown tag is dropped here, so the loop builder can trust
    its input. Entries keep their original order, and `project` is not modified.

    Returns a list of the surviving entries (shallow references to the originals),
    empty if the project has no `LOOPS_KEY` key at all.
    """
    # A list comprehension, not a loop with append: order is preserved by definition, and
    # `_is_analysable` holds the whole decision (pure predicate), so this function stays
    # free of any side effect.
    return [entry for entry in project.get(LOOPS_KEY, []) if _is_analysable(entry, tag_rows)]


def _index_tags_by_id(tags: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """The tag rows indexed by tag id, for fast lookup while building loops."""
    return {str(row[ID_KEY]): row for row in tags}


def _is_analysable(entry: Mapping[str, Any], tag_rows: Mapping[str, Mapping[str, Any]]) -> bool:
    """True when the entry names all four of its tags and every one of them exists."""
    tag_ids = (_text_or_none(entry.get(key)) for key in REQUIRED_TAG_KEYS)
    return all(tag_id is not None and tag_id in tag_rows for tag_id in tag_ids)


def _text_or_none(value: Any) -> str | None:
    """The value as a string, or None when it is missing or empty."""
    return None if value is None or value == "" else str(value)


def _build_loop(entry: Mapping[str, Any], tag_rows: Mapping[str, Mapping[str, Any]]) -> LoopTags:
    """Build the LoopTags of one entry; the caller has already checked its tags exist.

    A "loop" is a control loop of the plant: one measured value (the PV, process variable)
    is compared to its setpoint (SP) by the controller, whose output (OUT) drives the field
    device. `tag_rows` maps a tag name to that tag's own entry, and is used to look up the
    engineering range of the PV tag. Returns the immutable LoopTags record used downstream.
    """
    # A loop is identified by four tag names plus the PV tag's engineering details
    # (measurement unit and the raw-to-engineering conversion range).
    unit, eng_min, eng_max = _pv_engineering_details(entry, tag_rows)
    out_low, out_high = _out_engineering_range(entry, tag_rows)
    # Optional keys (delay, period, amplitude limit) are absent when the loop is not a
    # cycling/oscillating one, so they are read with .get() and stay None in that case.
    return LoopTags(
        name=_loop_name(entry),
        pv=str(entry[PV_KEY]),
        sp=str(entry[SP_KEY]),
        out=str(entry[OUT_KEY]),
        mode=str(entry[MODE_KEY]),
        unit=unit,
        eng_min=eng_min,
        eng_max=eng_max,
        delay_s=entry.get(DELAY_KEY),
        ultimate_period_s=entry.get(ULTIMATE_PERIOD_KEY),
        amplitude_limit=entry.get(AMPLITUDE_LIMIT_KEY),
        out_low=out_low,
        out_high=out_high,
    )


def _out_engineering_range(
    entry: Mapping[str, Any], tag_rows: Mapping[str, Mapping[str, Any]]
) -> tuple[float | None, float | None]:
    """Engineering minimum and maximum of the entry's OUT tag, None where not configured.

    The OUT tag is the controller output (the signal sent to the valve or drive). Its range is
    the actuator span that saturation is measured against: a 4-20 mA output needs 4.0 and 20.0,
    not the 0-100 % that the analysis assumes when no range is given.
    """
    out_row = tag_rows[str(entry[OUT_KEY])]
    return out_row.get(ENG_MIN_KEY), out_row.get(ENG_MAX_KEY)


def _pv_engineering_details(
    entry: Mapping[str, Any], tag_rows: Mapping[str, Mapping[str, Any]]
) -> tuple[str, float | None, float | None]:
    """Unit, engineering minimum and maximum of the entry's PV tag.

    A PV tag recorded without unit or range leaves the loop without scaling information; the
    analysis then falls back to its own defaults (``overview.default_settings``).

    In control-engineering terms a "PV" (process variable) is the tag whose measured value the
    controller reads and compares to its setpoint. ``tag_rows`` is the tag dictionary keyed by
    tag name; every row is a mapping of tag attributes. The unit is returned as text (``""``
    when the row carries none), and the engineering range as two floats or ``None`` each:
    ``ENG_MIN_KEY``/``ENG_MAX_KEY`` are the low and high ends of the sensor's calibrated span,
    in the tag's own engineering unit (e.g. 0.0 and 100.0 for a 0-100 degC transmitter), and
    are what the loop uses to turn a raw percentage into a physical value.

    Returns:
        A 3-tuple ``(unit, engineering_minimum, engineering_maximum)``; the two bounds are
        ``None`` when the tag row does not define them.

    Raises:
        KeyError: if ``entry[PV_KEY]`` names a PV tag that is absent from ``tag_rows``; that
            means the entry and the tag dictionary disagree and the caller must fix its input.
    """
    # Look the PV up by name. This raises KeyError rather than returning None on purpose:
    # a missing tag is a broken input, not a tag that merely lacks a range.
    pv_row = tag_rows[str(entry[PV_KEY])]
    return (
        # Unit as plain text; _text_or_empty maps a missing/None attribute to "" so callers
        # can treat "no unit" and "empty unit" alike.
        _text_or_empty(pv_row.get(UNIT_KEY)),
        # Both bounds are passed through as-is: None means "not configured", which the
        # caller distinguishes from a legitimate 0.0 bound.
        pv_row.get(ENG_MIN_KEY),
        pv_row.get(ENG_MAX_KEY),
    )


def _text_or_empty(value: Any) -> str:
    """The value as a string, or an empty string when it is missing."""
    return "" if value is None else str(value)


def _loop_name(entry: Mapping[str, Any]) -> str:
    """The display name of the entry, falling back to the loop id when none was given."""
    return _text_or_empty(entry.get(NAME_KEY)) or _text_or_empty(entry.get(ID_KEY))

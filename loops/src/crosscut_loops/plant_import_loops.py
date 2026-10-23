"""Loop detection for whole PI wide-file imports.

Reads an optional tag dictionary and groups plant tags into control loops so the
dataset writer can decide which PV/SP/OUT/MODE signals belong together.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

# Data shapes used throughout this module
# ---------------------------------------
# DictRow: one dictionary line, all fields are strings, never None.
# DetectedLoop: one control loop; the four main signals are tag names or None.
# columns: the header of the wide CSV; the numeric column names are the tags.

# Signals as they appear in the dictionary's `signal` column (exact strings).
SIGNAL_PV = "PV (measured)"
SIGNAL_OUT = "OUT (controller output)"
SIGNAL_SP = "SP"
SIGNAL_MODE = "mode flag"
SIGNAL_FEEDBACK = "feedback (actuator position)"
VALVE_SIGNALS = frozenset({"valve position (AI)", "valve reference (AO)"})

DICTIONARY_FIELDS = ("tag", "description", "unit", "signal", "loop", "cell")

# Controller prefixes that make the process integrating (level control).
INTEGRATING_PREFIXES = frozenset({"lic", "lc"})

# Suffix of the controller mode flag; the valve's own setauto flag is not the loop's mode.
MODE_SUFFIX = ".auto#state"
VALVE_MODE_MARKER = ":io.setauto#state"

# Matches 'demo.1000-lic-20103.out': prefix before '-', loop number after it.
CONTROLLER_TAG_PATTERN = re.compile(
    r"(?P<prefix>[a-z]+)-(?P<number>\d+)\.(?:mv|out|sp|feedback)$",
    re.IGNORECASE,
)
MODE_TAG_PATTERN = re.compile(
    r"(?P<prefix>[a-z]+)-(?P<number>\d+)" + re.escape(MODE_SUFFIX),
    re.IGNORECASE,
)
# Matches 'demo.1000-lv-20103-a-ao': valve tag, with an actuator letter after the number.
VALVE_TAG_PATTERN = re.compile(r"lv-(?P<number>\d+)-[a-z]-(?:ai|ao)$", re.IGNORECASE)


@dataclass(frozen=True)
class DictRow:
    """One line of the tag dictionary."""

    tag: str
    description: str
    unit: str
    signal: str
    loop: str
    cell: str


@dataclass(frozen=True)
class DetectedLoop:
    """One control loop and the tags that carry its signals.

    `complete` is True when pv, sp, out and mode are all present. `missing`
    lists the absent role names, always among 'pv', 'sp', 'out', 'mode'.
    """

    id: str
    name: str
    process_kind: str
    pv: str | None
    sp: str | None
    out: str | None
    mode: str | None
    feedback: str | None
    valves: tuple[str, ...]
    unit: str
    cell: str
    complete: bool
    missing: tuple[str, ...]


@dataclass
class _RawRoles:
    """Tags of one loop before the completeness decision is made (mutable)."""

    number: str
    prefix: str = ""
    unit: str = ""
    cell: str = ""
    pv: str | None = None
    sp: str | None = None
    out: str | None = None
    mode: str | None = None
    feedback: str | None = None
    valves: list[str] = field(default_factory=list)


def read_dictionary(text: str) -> list[DictRow]:
    """Parse the tag dictionary CSV into rows.

    The header must contain a `tag` column; other columns are optional and
    default to an empty string. A UTF-8 BOM at the start is stripped.

    Raises:
        ValueError: when there is no `tag` column in the header.
    """
    csv_text = text.lstrip("\ufeff")
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    if "tag" not in _field_names_of(csv_text):
        raise ValueError("dictionary CSV has no 'tag' column; add a header row 'tag,...'")
    return [_dict_row_from(raw_row) for raw_row in rows]


def _field_names_of(csv_text: str) -> list[str]:
    """Return the header field names of a CSV text."""
    return next(csv.reader(io.StringIO(csv_text)), [])


def _dict_row_from(raw_row: dict[str, str | None]) -> DictRow:
    """Build a DictRow from a CSV row, filling missing columns with ''."""
    values = {key: (raw_row.get(key) or "") for key in DICTIONARY_FIELDS}
    return DictRow(**values)


def detect_loops(columns: list[str], dictionary: list[DictRow] | None) -> list[DetectedLoop]:
    """Detect control loops in the CSV columns using the dictionary or tag names.

    Only tags that appear in `columns` count. With a dictionary the roles come
    from its `signal` column; without one they are derived from the tag names.

    Returns:
        Loops sorted by id. A group without an OUT tag is not a controller and
        is omitted.
    """
    present_tags = set(columns)
    if dictionary is None:
        grouped = _roles_from_tag_names(present_tags)
    else:
        grouped = _roles_from_dictionary(dictionary, present_tags)
    controller_loops = [raw for raw in grouped.values() if raw.out is not None]
    return sorted((_loop_from_raw(raw) for raw in controller_loops), key=lambda loop: loop.id)


def _roles_from_dictionary(
    dictionary: list[DictRow], present_tags: set[str]
) -> dict[str, _RawRoles]:
    """Group dictionary rows by loop number and assign each tag a role."""
    grouped: dict[str, _RawRoles] = {}
    for row in dictionary:
        if row.loop and row.tag in present_tags:
            _assign_dictionary_role(grouped.setdefault(row.loop, _RawRoles(row.loop)), row)
    return grouped


def _assign_dictionary_role(grouped_loop: _RawRoles, row: DictRow) -> None:
    """Assign one dictionary row to a role of its loop (mutates the loop)."""
    if row.signal == SIGNAL_OUT:
        grouped_loop.out = row.tag
        identity = _split_controller_tag(row.tag)
        if identity is not None:
            grouped_loop.prefix, grouped_loop.number = identity
    elif row.signal == SIGNAL_PV:
        grouped_loop.pv = row.tag
        grouped_loop.unit = row.unit
        grouped_loop.cell = row.cell
    elif row.signal == SIGNAL_SP:
        grouped_loop.sp = row.tag
    elif row.signal == SIGNAL_FEEDBACK:
        grouped_loop.feedback = row.tag
    elif row.signal in VALVE_SIGNALS:
        _add_valve(grouped_loop, row.tag)
    elif row.signal == SIGNAL_MODE and _is_controller_mode_flag(row.tag):
        grouped_loop.mode = row.tag


def _add_valve(grouped_loop: _RawRoles, tag: str) -> None:
    """Add a valve tag to the loop if it is not already there."""
    if tag not in grouped_loop.valves:
        grouped_loop.valves.append(tag)


def _is_controller_mode_flag(tag: str) -> bool:
    """Return True for a controller mode flag, not for a valve setauto flag."""
    if not tag.endswith(MODE_SUFFIX) or VALVE_MODE_MARKER in tag:
        return False
    return MODE_TAG_PATTERN.search(tag) is not None


def _split_controller_tag(tag: str) -> tuple[str, str] | None:
    """Return (prefix, number) of a controller signal tag, or None.

    Example: 'demo.1000-lic-20103.out' -> ('lic', '20103').
    """
    match = CONTROLLER_TAG_PATTERN.search(tag)
    if match is None:
        return None
    return match.group("prefix").lower(), match.group("number")


def _roles_from_tag_names(present_tags: set[str]) -> dict[str, _RawRoles]:
    """Derive loop roles from tag names when no dictionary is given."""
    grouped: dict[str, _RawRoles] = {}
    for tag in sorted(present_tags):
        _assign_named_role(grouped, tag)
    return grouped


def _assign_named_role(grouped: dict[str, _RawRoles], tag: str) -> None:
    """Assign one tag to a loop by its name (mutates the grouping)."""
    identity = _split_controller_tag(tag)
    if identity is not None:
        prefix, number = identity
        _assign_named_controller_role(grouped.setdefault(number, _RawRoles(number)), tag, prefix)
        return
    _assign_named_mode_role(grouped, tag)


def _assign_named_controller_role(grouped_loop: _RawRoles, tag: str, prefix: str) -> None:
    """Fill a controller role slot from the tag's suffix."""
    grouped_loop.prefix = grouped_loop.prefix or prefix
    if tag.endswith(".out"):
        grouped_loop.out = tag
    elif tag.endswith(".mv"):
        # '.mv' is the measured value (the PV) of the controller.
        grouped_loop.pv = tag
    elif tag.endswith(".sp"):
        grouped_loop.sp = tag
    elif tag.endswith(".feedback"):
        grouped_loop.feedback = tag


def _assign_named_mode_role(grouped: dict[str, _RawRoles], tag: str) -> None:
    """Attach a mode flag, else a valve tag, to its loop number by name."""
    mode_match = MODE_TAG_PATTERN.search(tag)
    if mode_match is not None and VALVE_MODE_MARKER not in tag:
        grouped_loop = grouped.setdefault(
            mode_match.group("number"), _RawRoles(mode_match.group("number"))
        )
        grouped_loop.prefix = grouped_loop.prefix or mode_match.group("prefix").lower()
        grouped_loop.mode = tag
        return
    valve_match = VALVE_TAG_PATTERN.search(tag)
    if valve_match is not None:
        number = valve_match.group("number")
        _add_valve(grouped.setdefault(number, _RawRoles(number)), tag)


def _loop_from_raw(raw_loop: _RawRoles) -> DetectedLoop:
    """Build a DetectedLoop from collected roles, computing completeness."""
    loop_id = _loop_id(raw_loop)
    missing = _missing_roles(raw_loop)
    return DetectedLoop(
        id=loop_id,
        name=loop_id,
        process_kind=_process_kind(raw_loop.prefix),
        pv=raw_loop.pv,
        sp=raw_loop.sp,
        out=raw_loop.out,
        mode=raw_loop.mode,
        feedback=raw_loop.feedback,
        valves=tuple(sorted(raw_loop.valves)),
        unit=raw_loop.unit,
        cell=raw_loop.cell,
        complete=not missing,
        missing=missing,
    )


def _loop_id(raw_loop: _RawRoles) -> str:
    """Return the loop id like 'LIC-20103'; use 'LOOP' when no prefix is known."""
    prefix = raw_loop.prefix.upper() if raw_loop.prefix else "LOOP"
    return f"{prefix}-{raw_loop.number}"


def _process_kind(prefix: str) -> str:
    """Level controllers (lic, lc) integrate, all others self-regulate."""
    return "integrating" if prefix.lower() in INTEGRATING_PREFIXES else "self_regulating"


def _missing_roles(raw_loop: _RawRoles) -> tuple[str, ...]:
    """Return the absent roles among pv, sp, out, mode, in a fixed order."""
    roles = {"pv": raw_loop.pv, "sp": raw_loop.sp, "out": raw_loop.out, "mode": raw_loop.mode}
    return tuple(role for role, tag in roles.items() if tag is None)

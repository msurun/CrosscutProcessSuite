"""Tag role mapping and legacy vocabulary reconciliation (Phase 1, #37).

Provides pure functions to infer signal roles (pv, sp, out, mode, fb, input, target, lab, dv)
from tag names and site naming conventions, reconcile legacy role vocabularies, and assemble
control loop definitions for the site catalogue.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# Canonical signal roles defined in schemas/site.schema.json
ROLE_PV = "pv"
ROLE_SP = "sp"
ROLE_OUT = "out"
ROLE_MODE = "mode"
ROLE_FB = "fb"
ROLE_INPUT = "input"
ROLE_TARGET = "target"
ROLE_LAB = "lab"
ROLE_DV = "dv"

LOOP_ROLES = (ROLE_PV, ROLE_SP, ROLE_OUT, ROLE_MODE, ROLE_FB)

# Reconciliation map from legacy vocabularies (plant_import_loops, intake, provisional site)
LEGACY_TO_CANONICAL: dict[str, str] = {
    # Dictionary signals from plant_import_loops
    "PV (measured)": ROLE_PV,
    "SP": ROLE_SP,
    "OUT (controller output)": ROLE_OUT,
    "mode flag": ROLE_MODE,
    "feedback (actuator position)": ROLE_FB,
    "valve position (AI)": ROLE_FB,
    "valve reference (AO)": ROLE_FB,
    # Provisional site schema roles (PV, SP, OUT, MODE, MEAS)
    "PV": ROLE_PV,
    "OUT": ROLE_OUT,
    "MODE": ROLE_MODE,
    "MEAS": ROLE_INPUT,
    # Intake categories
    "pv": ROLE_PV,
    "sp": ROLE_SP,
    "out": ROLE_OUT,
    "mode": ROLE_MODE,
}

# Suffix to canonical role mapping for structured controller tag names
SUFFIX_TO_ROLE: dict[str, str] = {
    "pv": ROLE_PV,
    "mv": ROLE_PV,
    "sp": ROLE_SP,
    "setp": ROLE_SP,
    "setpoint": ROLE_SP,
    "out": ROLE_OUT,
    "op": ROLE_OUT,
    "valve": ROLE_OUT,
    "cv": ROLE_OUT,
    "mode": ROLE_MODE,
    "fb": ROLE_FB,
    "feedback": ROLE_FB,
    "dv": ROLE_DV,
    "dist": ROLE_DV,
}


def canonical_role_from_legacy(legacy_signal: str) -> str | None:
    """Return the canonical signal role for a legacy string, or None if unknown."""
    return LEGACY_TO_CANONICAL.get(legacy_signal)


def suggest_roles(
    tag_names: Sequence[str],
    naming: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Infer canonical signals for a list of tag names using site conventions.

    # In plain words:
    Analyzes each tag name to decide whether it belongs to a PID control loop
    (such as a process variable or setpoint) or serves as an unlooped measurement,
    prediction target, or laboratory value.
    """
    naming_dict = dict(naming or {})
    return [_suggest_one_signal(tag, naming_dict) for tag in tag_names]


def _suggest_one_signal(tag: str, naming: dict[str, Any]) -> dict[str, Any]:
    """Determine role and optional loop ID for a single tag name."""
    from_naming = _match_custom_naming(tag, naming)
    if from_naming is not None:
        return from_naming

    from_suffix = _match_delimited_suffix(tag)
    if from_suffix is not None:
        return from_suffix

    return _classify_non_loop_tag(tag)


def _match_custom_naming(tag: str, naming: dict[str, Any]) -> dict[str, Any] | None:
    """Check if tag matches valve_pattern or mode_suffix from the naming block."""
    valve_pattern = naming.get("valve_pattern")
    if valve_pattern:
        loop_id = _extract_from_pattern(tag, valve_pattern)
        if loop_id is not None:
            return {"tag": tag, "role": ROLE_OUT, "loop": loop_id}

    mode_suffix = naming.get("mode_suffix")
    if mode_suffix and tag.endswith(mode_suffix):
        loop_id = tag[: -len(mode_suffix)].rstrip("_.-")
        return {"tag": tag, "role": ROLE_MODE, "loop": loop_id}

    return None


def _extract_from_pattern(text: str, pattern_template: str) -> str | None:
    """Extract loop identifier using a template containing '{loop}'."""
    escaped = re.escape(pattern_template)
    regex_str = "^" + escaped.replace(r"\{loop\}", r"(?P<loop>[A-Za-z0-9_-]+)") + "$"
    match = re.match(regex_str, text, re.IGNORECASE)
    return match.group("loop") if match else None


def _match_delimited_suffix(tag: str) -> dict[str, Any] | None:
    """Extract loop role and loop ID from dot, underscore, or dash separated tags."""
    match = re.search(r"^(?P<loop>.+?)[._/-](?P<suffix>[a-zA-Z]+)$", tag)
    if not match:
        return None
    suffix = match.group("suffix").lower()
    role = SUFFIX_TO_ROLE.get(suffix)
    if role is None:
        return None
    return {"tag": tag, "role": role, "loop": match.group("loop")}


def _classify_non_loop_tag(tag: str) -> dict[str, Any]:
    """Assign role for tags that do not follow loop naming conventions."""
    upper = tag.upper()
    if "TARGET" in upper or "PRED" in upper:
        return {"tag": tag, "role": ROLE_TARGET}
    if "LAB" in upper or "ANALYZ" in upper:
        return {"tag": tag, "role": ROLE_LAB}
    return {"tag": tag, "role": ROLE_INPUT}


def loops_from_signals(signals: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Assemble complete and analysable control loop definitions from signal rows.

    # In plain words:
    Groups signals by loop ID and constructs loop definitions. Any candidate loop
    missing an output (OUT) actuator tag is omitted as non-analysable.
    """
    grouped: dict[str, dict[str, str]] = {}
    for sig in signals:
        loop_id = sig.get("loop")
        role = sig.get("role")
        if loop_id and role in LOOP_ROLES:
            slots = grouped.setdefault(loop_id, {})
            slots[role] = sig["tag"]

    loops: list[dict[str, Any]] = []
    for loop_id, slots in grouped.items():
        if ROLE_OUT in slots:
            loop_entry: dict[str, Any] = {"id": loop_id, "out": slots[ROLE_OUT]}
            for role in (ROLE_PV, ROLE_SP, ROLE_MODE):
                if role in slots:
                    loop_entry[role] = slots[role]
            loops.append(loop_entry)
    return sorted(loops, key=lambda item: str(item["id"]))

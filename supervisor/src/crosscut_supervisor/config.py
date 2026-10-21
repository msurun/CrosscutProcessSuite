"""Supervisor configuration as data (ADR 009/010): immutable objects and the check that builds them.

The JSON layout is fixed by ``schemas/supervisor.schema.json``; like the fuzzy package this module
validates by hand (no jsonschema dependency) and adds cross-checks a schema cannot express.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from crosscut_fuzzy.model import FuzzySystem

MODES = ("off", "advisory")
BLOCK_STATES = frozenset({"manual", "saturated", "flatline", "unknown"})
WARN_STATES = frozenset({"oscillating"})
_REQUIRED = (
    "schema_version", "id", "fuzzy_system_id", "output_id", "target_loop", "mode", "gates",
    "silent_band", "min_activation", "min_interval_s", "display_clamp",
)
_OPTIONAL = ("description", "fuzzy_version_id")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SupervisorConfigError(ValueError):
    """A supervisor configuration that is invalid (the message names the field)."""


@dataclass(frozen=True)
class GateRule:
    """Loop states that block advice and states that only warn for one gating loop."""

    loop: str
    block_on: frozenset[str]
    warn_on: frozenset[str]


@dataclass(frozen=True)
class SupervisorConfig:
    """A validated advisory supervisor configuration."""

    schema_version: str
    id: str
    fuzzy_system_id: str
    output_id: str
    target_loop: str
    mode: str
    gates: tuple[GateRule, ...]
    silent_band: float
    min_activation: float
    min_interval_s: float
    display_clamp: tuple[float, float]
    description: str = ""
    fuzzy_version_id: str | None = None


def load_config(doc: Mapping[str, Any]) -> SupervisorConfig:
    """Validate ``doc`` against the supervisor schema and cross-check it.

    Cross-check choice: ``gates`` may be empty (no gating); when it is not empty the
    ``target_loop`` must be one of the gated loops, so the loop being advised is never ungated.

    Raises:
        SupervisorConfigError: naming the offending field.
    """
    _check_keys(doc)
    gates = tuple(_gate(item) for item in _list(doc, "gates"))
    config = SupervisorConfig(
        schema_version=_pattern(doc, "schema_version", _VERSION),
        id=_pattern(doc, "id", _ID),
        fuzzy_system_id=_text(doc, "fuzzy_system_id"),
        output_id=_text(doc, "output_id"),
        target_loop=_text(doc, "target_loop"),
        mode=_mode(doc),
        gates=gates,
        silent_band=_number(doc, "silent_band", low=0.0),
        min_activation=_number(doc, "min_activation", low=0.0, high=1.0),
        min_interval_s=_number(doc, "min_interval_s", low=0.0),
        display_clamp=_clamp(doc),
        description=_optional_text(doc, "description") or "",
        fuzzy_version_id=_optional_text(doc, "fuzzy_version_id"),
    )
    _cross_check(config)
    return config


def check_against_system(config: SupervisorConfig, system: FuzzySystem) -> None:
    """Require ``config.output_id`` to be an output variable of ``system``.

    Raises:
        SupervisorConfigError: if the fuzzy system has no such output.
    """
    if config.output_id not in [variable.id for variable in system.outputs]:
        raise SupervisorConfigError(
            f"output_id: {config.output_id!r} is not an output of fuzzy system {system.name!r}"
        )


def _check_keys(doc: Mapping[str, Any]) -> None:
    """Required keys present, no unknown keys (additionalProperties false)."""
    for key in _REQUIRED:
        if key not in doc:
            raise SupervisorConfigError(f"{key}: required field is missing")
    for key in doc:
        if key not in _REQUIRED and key not in _OPTIONAL:
            raise SupervisorConfigError(f"{key}: unknown field")


def _text(doc: Mapping[str, Any], key: str) -> str:
    """A non-empty string field."""
    value = doc[key]
    if not isinstance(value, str) or not value:
        raise SupervisorConfigError(f"{key}: must be a non-empty string")
    return value


def _optional_text(doc: Mapping[str, Any], key: str) -> str | None:
    """An optional string field (description may be empty, the version id may not)."""
    if key not in doc:
        return None
    if key == "description":
        if not isinstance(doc[key], str):
            raise SupervisorConfigError(f"{key}: must be a string")
        return str(doc[key])
    return _text(doc, key)


def _pattern(doc: Mapping[str, Any], key: str, pattern: re.Pattern[str]) -> str:
    """A string field that must match ``pattern``."""
    value = doc[key]
    if not isinstance(value, str) or not pattern.match(value):
        raise SupervisorConfigError(f"{key}: {value!r} does not match {pattern.pattern}")
    return value


def _mode(doc: Mapping[str, Any]) -> str:
    """The mode: only ``off`` or ``advisory`` exist (no write path)."""
    if doc["mode"] not in MODES:
        raise SupervisorConfigError(f"mode: must be one of {list(MODES)}, got {doc['mode']!r}")
    return str(doc["mode"])


def _number(
    doc: Mapping[str, Any], key: str, low: float | None = None, high: float | None = None
) -> float:
    """A real number (not a bool) within optional inclusive bounds."""
    return _as_number(doc[key], key, low, high)


def _as_number(
    value: Any, key: str, low: float | None = None, high: float | None = None
) -> float:
    """Check one value is a number within bounds and return it as float."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SupervisorConfigError(f"{key}: must be a number")
    if (low is not None and value < low) or (high is not None and value > high):
        raise SupervisorConfigError(f"{key}: {value} is outside [{low}, {high}]")
    return float(value)


def _clamp(doc: Mapping[str, Any]) -> tuple[float, float]:
    """The display clamp: exactly two numbers."""
    value = doc["display_clamp"]
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise SupervisorConfigError("display_clamp: must be an array of exactly 2 numbers")
    return (_as_number(value[0], "display_clamp"), _as_number(value[1], "display_clamp"))


def _list(doc: Mapping[str, Any], key: str) -> list[Any]:
    """An array field."""
    if not isinstance(doc[key], list | tuple):
        raise SupervisorConfigError(f"{key}: must be an array")
    return list(doc[key])


def _gate(item: Any) -> GateRule:
    """One gate entry: loop plus optional block_on / warn_on state sets."""
    if not isinstance(item, Mapping):
        raise SupervisorConfigError("gates: every entry must be an object")
    for key in item:
        if key not in ("loop", "block_on", "warn_on"):
            raise SupervisorConfigError(f"gates.{key}: unknown field")
    if not isinstance(item.get("loop"), str) or not item["loop"]:
        raise SupervisorConfigError("gates.loop: must be a non-empty string")
    return GateRule(
        loop=item["loop"],
        block_on=_states(item, "block_on", BLOCK_STATES),
        warn_on=_states(item, "warn_on", WARN_STATES),
    )


def _states(item: Mapping[str, Any], key: str, allowed: frozenset[str]) -> frozenset[str]:
    """A unique list of loop states drawn from ``allowed``."""
    values = item.get(key, [])
    if not isinstance(values, list | tuple) or len(set(values)) != len(values):
        raise SupervisorConfigError(f"gates.{key}: must be an array of unique states")
    unknown = [value for value in values if value not in allowed]
    if unknown:
        raise SupervisorConfigError(f"gates.{key}: {unknown} not in {sorted(allowed)}")
    return frozenset(values)


def _cross_check(config: SupervisorConfig) -> None:
    """Rules the schema cannot express: clamp order, unique gate loops, target gated."""
    low, high = config.display_clamp
    if not low < high:
        raise SupervisorConfigError("display_clamp: first value must be below the second")
    loops = [gate.loop for gate in config.gates]
    if len(set(loops)) != len(loops):
        raise SupervisorConfigError("gates.loop: gate loops must be unique")
    if loops and config.target_loop not in loops:
        raise SupervisorConfigError("target_loop: must be one of the gate loops when gates exist")

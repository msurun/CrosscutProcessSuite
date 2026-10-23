"""Soft sensor configuration as data: immutable object and the hand validation that builds it.

The JSON layout is fixed by ``schemas/softsensor.schema.json``; like the anomaly package this
module validates by hand (no jsonschema dependency). Error messages start with the field name.
Only ``off`` and ``advisory`` exist as modes: no write path.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MODES = ("off", "advisory")
_REQUIRED = ("schema_version", "id", "target_tag", "input_tags", "mode")
_OPTIONAL = (
    "description", "lags_s", "lab_delay_s", "sample_period_s", "max_components", "cv_blocks",
)
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEFAULT_LAGS_S = (0.0, 300.0, 900.0, 1800.0)


class SoftSensorConfigError(ValueError):
    """A soft sensor configuration that is invalid (the message names the field)."""


@dataclass(frozen=True)
class SoftSensorConfig:
    """A validated advisory soft sensor configuration."""

    id: str
    target_tag: str
    input_tags: tuple[str, ...]
    lags_s: tuple[float, ...] = DEFAULT_LAGS_S
    lab_delay_s: float = 3600.0
    sample_period_s: float = 60.0
    max_components: int = 8
    cv_blocks: int = 5
    mode: str = "advisory"
    schema_version: str = "1.0.0"
    description: str = ""


def load_config(doc: Mapping[str, Any]) -> SoftSensorConfig:
    """Validate ``doc`` against the soft sensor schema and build the configuration.

    Raises:
        SoftSensorConfigError: naming the offending field.
    """
    _check_keys(doc)
    description = doc.get("description", "")
    if not isinstance(description, str):
        raise SoftSensorConfigError("description: must be a string")
    return SoftSensorConfig(
        id=_pattern(doc, "id", _ID),
        target_tag=_name(doc["target_tag"], "target_tag"),
        input_tags=_names(doc["input_tags"], "input_tags"),
        lags_s=_lags(doc.get("lags_s", list(DEFAULT_LAGS_S))),
        lab_delay_s=_number(doc, "lab_delay_s", 3600.0, 0.0, False),
        sample_period_s=_number(doc, "sample_period_s", 60.0, 0.0, True),
        max_components=_integer(doc, "max_components", 8, 1),
        cv_blocks=_integer(doc, "cv_blocks", 5, 2),
        mode=_mode(doc),
        schema_version=_pattern(doc, "schema_version", _VERSION),
        description=description,
    )


def _check_keys(doc: Mapping[str, Any]) -> None:
    """Required keys present, no unknown keys (additionalProperties false)."""
    for key in _REQUIRED:
        if key not in doc:
            raise SoftSensorConfigError(f"{key}: required field is missing")
    for key in doc:
        if key not in _REQUIRED and key not in _OPTIONAL:
            raise SoftSensorConfigError(f"{key}: unknown field")


def _pattern(doc: Mapping[str, Any], key: str, pattern: re.Pattern[str]) -> str:
    """A string field that must match ``pattern``."""
    value = doc[key]
    if not isinstance(value, str) or not pattern.match(value):
        raise SoftSensorConfigError(f"{key}: {value!r} does not match {pattern.pattern}")
    return value


def _mode(doc: Mapping[str, Any]) -> str:
    """The mode: only ``off`` or ``advisory`` exist."""
    if doc["mode"] not in MODES:
        raise SoftSensorConfigError(f"mode: must be one of {list(MODES)}, got {doc['mode']!r}")
    return str(doc["mode"])


def _name(value: Any, key: str) -> str:
    """A non-empty tag name."""
    if not isinstance(value, str) or not value:
        raise SoftSensorConfigError(f"{key}: must be a non-empty string")
    return value


def _names(value: Any, key: str) -> tuple[str, ...]:
    """At least one unique non-empty tag name."""
    if not isinstance(value, list | tuple) or not value:
        raise SoftSensorConfigError(f"{key}: must be a non-empty array")
    names = tuple(_name(v, key) for v in value)
    if len(set(names)) != len(names):
        raise SoftSensorConfigError(f"{key}: entries must be unique")
    return names


def _lags(value: Any) -> tuple[float, ...]:
    """Unique non-negative lags in seconds (a negative lag would be a future value)."""
    if not isinstance(value, list | tuple) or not value:
        raise SoftSensorConfigError("lags_s: must be a non-empty array")
    for v in value:
        if isinstance(v, bool) or not isinstance(v, int | float) or v < 0:
            raise SoftSensorConfigError("lags_s: entries must be numbers >= 0")
    if len(set(value)) != len(value):
        raise SoftSensorConfigError("lags_s: entries must be unique")
    return tuple(float(v) for v in value)


def _number(
    doc: Mapping[str, Any], key: str, default: float, low: float, strict: bool
) -> float:
    """A real number (not a bool) above ``low`` (strict) or at least ``low``."""
    value = doc.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SoftSensorConfigError(f"{key}: must be a number")
    if value < low or (strict and value == low):
        word = "above" if strict else "at least"
        raise SoftSensorConfigError(f"{key}: {value} must be {word} {low}")
    return float(value)


def _integer(doc: Mapping[str, Any], key: str, default: int, low: int) -> int:
    """An integer (not a bool) of at least ``low``; ``default`` if absent."""
    value = doc.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SoftSensorConfigError(f"{key}: must be an integer")
    if value < low:
        raise SoftSensorConfigError(f"{key}: {value} must be at least {low}")
    return value

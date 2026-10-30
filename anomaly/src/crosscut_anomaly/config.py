"""Anomaly detector configuration as data (ADR 010): immutable object and the check that builds it.

The JSON layout is fixed by ``schemas/anomaly.schema.json``; like the supervisor package this
module validates by hand (no jsonschema dependency). Error messages start with the field name.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MODES = ("off", "advisory")
_REQUIRED = ("schema_version", "id", "tags", "mode")
_OPTIONAL = (
    "description", "variance_fraction", "alpha", "min_consecutive", "close_after",
    "sample_period_s", "dynamic_lags", "stuck_samples", "ramp_min_hours", "counter_like_share",
)
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AnomalyConfigError(ValueError):
    """An anomaly configuration that is invalid (the message names the field)."""


@dataclass(frozen=True)
class AnomalyConfig:
    """A validated advisory anomaly detector configuration."""

    schema_version: str
    id: str
    tags: tuple[str, ...]
    mode: str
    description: str = ""
    variance_fraction: float = 0.90
    alpha: float = 0.99
    min_consecutive: int = 5
    close_after: int = 10
    sample_period_s: float = 60.0
    dynamic_lags: int = 0
    stuck_samples: int = 0
    ramp_min_hours: float = 6.0
    counter_like_share: float = 0.9


def load_config(doc: Mapping[str, Any]) -> AnomalyConfig:
    """Validate ``doc`` against the anomaly schema and build the configuration.

    Raises:
        AnomalyConfigError: naming the offending field.
    """
    _check_keys(doc)
    description = doc.get("description", "")
    if not isinstance(description, str):
        raise AnomalyConfigError("description: must be a string")
    return AnomalyConfig(
        schema_version=_pattern(doc, "schema_version", _VERSION),
        id=_pattern(doc, "id", _ID),
        tags=_tags(doc["tags"]),
        mode=_mode(doc),
        description=description,
        variance_fraction=_number(doc, "variance_fraction", 0.90, 0.5, 0.999),
        alpha=_number(doc, "alpha", 0.99, 0.9, 0.9999),
        min_consecutive=_integer(doc, "min_consecutive", 5),
        close_after=_integer(doc, "close_after", 10),
        sample_period_s=_period(doc),
        dynamic_lags=_lags(doc),
        stuck_samples=_stuck(doc),
        ramp_min_hours=_positive(doc, "ramp_min_hours", 6.0),
        counter_like_share=_number(doc, "counter_like_share", 0.9, 0.5, 1.0),
    )


def _check_keys(doc: Mapping[str, Any]) -> None:
    """Required keys present, no unknown keys (additionalProperties false)."""
    for key in _REQUIRED:
        if key not in doc:
            raise AnomalyConfigError(f"{key}: required field is missing")
    for key in doc:
        if key not in _REQUIRED and key not in _OPTIONAL:
            raise AnomalyConfigError(f"{key}: unknown field")


def _pattern(doc: Mapping[str, Any], key: str, pattern: re.Pattern[str]) -> str:
    """A string field that must match ``pattern``."""
    value = doc[key]
    if not isinstance(value, str) or not pattern.match(value):
        raise AnomalyConfigError(f"{key}: {value!r} does not match {pattern.pattern}")
    return value


def _mode(doc: Mapping[str, Any]) -> str:
    """The mode: only ``off`` or ``advisory`` exist (no write path)."""
    if doc["mode"] not in MODES:
        raise AnomalyConfigError(f"mode: must be one of {list(MODES)}, got {doc['mode']!r}")
    return str(doc["mode"])


def _tags(value: Any) -> tuple[str, ...]:
    """At least three unique non-empty tag names."""
    if not isinstance(value, list | tuple):
        raise AnomalyConfigError("tags: must be an array")
    if any(not isinstance(tag, str) or not tag for tag in value):
        raise AnomalyConfigError("tags: every entry must be a non-empty string")
    if len(set(value)) != len(value):
        raise AnomalyConfigError("tags: entries must be unique")
    if len(value) < 3:
        raise AnomalyConfigError("tags: at least 3 tags are required")
    return tuple(value)


def _number(
    doc: Mapping[str, Any], key: str, default: float, low: float, high: float
) -> float:
    """A real number (not a bool) within inclusive bounds; ``default`` if absent."""
    value = doc.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AnomalyConfigError(f"{key}: must be a number")
    if not low <= value <= high:
        raise AnomalyConfigError(f"{key}: {value} is outside [{low}, {high}]")
    return float(value)


def _integer(doc: Mapping[str, Any], key: str, default: int) -> int:
    """An integer (not a bool) of at least 1; ``default`` if absent."""
    value = doc.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnomalyConfigError(f"{key}: must be an integer")
    if value < 1:
        raise AnomalyConfigError(f"{key}: {value} must be at least 1")
    return value


def _period(doc: Mapping[str, Any]) -> float:
    """The sample period in seconds: a number above zero."""
    value = doc.get("sample_period_s", 60)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AnomalyConfigError("sample_period_s: must be a number")
    if not value > 0:
        raise AnomalyConfigError(f"sample_period_s: {value} must be above 0")
    return float(value)


def _positive(doc: Mapping[str, Any], key: str, default: float) -> float:
    """A real number (not a bool) above zero; ``default`` if absent."""
    value = doc.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AnomalyConfigError(f"{key}: must be a number")
    if not value > 0:
        raise AnomalyConfigError(f"{key}: {value} must be above 0")
    return float(value)


def _int_value(doc: Mapping[str, Any], key: str) -> int:
    """An integer (not a bool) field; 0 if absent."""
    value = doc.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnomalyConfigError(f"{key}: must be an integer")
    return value


def _lags(doc: Mapping[str, Any]) -> int:
    """Dynamic PCA lags: an integer in 0..10 (0 = static PCA)."""
    value = _int_value(doc, "dynamic_lags")
    if not 0 <= value <= 10:
        raise AnomalyConfigError(f"dynamic_lags: {value} is outside [0, 10]")
    return value


def _stuck(doc: Mapping[str, Any]) -> int:
    """Stuck-sensor run length: 0 (off) or at least 3 samples."""
    value = _int_value(doc, "stuck_samples")
    if value != 0 and value < 3:
        raise AnomalyConfigError(f"stuck_samples: {value} must be 0 (off) or at least 3")
    return value

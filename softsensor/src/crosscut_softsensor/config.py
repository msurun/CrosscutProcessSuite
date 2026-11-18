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
    "reference_inputs", "backup",
)
_REFERENCE_KEYS = ("tag", "window_s", "shift_s", "min_coverage", "bias_weight")
_BACKUP_KEYS = ("enabled", "measured_tag", "frozen_s", "range_lo", "range_hi", "return_hold_s")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEFAULT_LAGS_S = (0.0, 300.0, 900.0, 1800.0)


class SoftSensorConfigError(ValueError):
    """A soft sensor configuration that is invalid (the message names the field)."""


@dataclass(frozen=True)
class ReferenceInput:
    """A reference measurement used as a model input through a causal window mean.

    The feature at time t is the mean of the tag over (t - shift_s - window_s, t - shift_s];
    it is valid only when the share of bins with data (coverage) is at least ``min_coverage``.
    ``bias_weight`` is the EWMA weight of the lab-minus-reference bias check. No defaults.
    """

    tag: str
    window_s: float
    shift_s: float
    min_coverage: float
    bias_weight: float


@dataclass(frozen=True)
class BackupConfig:
    """Backup mode: the virtual sensor takes over while the measured value is invalid.

    ``measured_tag`` is the analyser tag. It is invalid when its quality is bad (no good
    sample in the bin), it is frozen (unchanged for ``frozen_s``), it lies outside
    [``range_lo``, ``range_hi``] (engineering units of the tag) or ``flag_tag`` is non-zero.
    The measurement returns only after it was valid for ``return_hold_s`` (hysteresis).
    No plant defaults: every field except ``flag_tag`` is required.
    """

    measured_tag: str
    frozen_s: float
    range_lo: float
    range_hi: float
    return_hold_s: float
    flag_tag: str | None = None


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
    reference_inputs: tuple[ReferenceInput, ...] = ()
    backup: BackupConfig | None = None


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
        reference_inputs=_references(doc.get("reference_inputs", [])),
        backup=_backup(doc.get("backup")),
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


def _references(value: Any) -> tuple[ReferenceInput, ...]:
    """Reference inputs: every field of every entry is required (no plant defaults)."""
    if not isinstance(value, list | tuple):
        raise SoftSensorConfigError("reference_inputs: must be an array")
    refs = tuple(_reference(entry, i) for i, entry in enumerate(value))
    if len({r.tag for r in refs}) != len(refs):
        raise SoftSensorConfigError("reference_inputs: tags must be unique")
    return refs


def _reference(entry: Any, index: int) -> ReferenceInput:
    """One reference input: required keys, no unknown keys, ranges as in the schema."""
    where = f"reference_inputs[{index}]"
    if not isinstance(entry, Mapping):
        raise SoftSensorConfigError(f"{where}: must be an object")
    for key in entry:
        if key not in _REFERENCE_KEYS:
            raise SoftSensorConfigError(f"{where}.{key}: unknown field")
    for key in _REFERENCE_KEYS:
        if key not in entry:
            raise SoftSensorConfigError(f"{where}.{key}: required field is missing")
    return ReferenceInput(
        tag=_name(entry["tag"], f"{where}.tag"),
        window_s=_ranged(entry, "window_s", where, 0.0, None, True),
        shift_s=_ranged(entry, "shift_s", where, 0.0, None, False),
        min_coverage=_ranged(entry, "min_coverage", where, 0.0, 1.0, True),
        bias_weight=_ranged(entry, "bias_weight", where, 0.0, 1.0, True),
    )


def _ranged(
    entry: Mapping[str, Any], key: str, where: str, low: float, high: float | None, strict: bool
) -> float:
    """A number above (strict) or at least ``low`` and at most ``high`` (if given)."""
    value = entry[key]
    name = f"{where}.{key}"
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SoftSensorConfigError(f"{name}: must be a number")
    if value < low or (strict and value == low) or (high is not None and value > high):
        raise SoftSensorConfigError(f"{name}: {value} is out of range")
    return float(value)


def _backup(entry: Any) -> BackupConfig | None:
    """The backup block; ``None`` when absent or ``enabled`` is false."""
    if entry is None:
        return None
    if not isinstance(entry, Mapping):
        raise SoftSensorConfigError("backup: must be an object")
    for key in entry:
        if key not in (*_BACKUP_KEYS, "flag_tag"):
            raise SoftSensorConfigError(f"backup.{key}: unknown field")
    if "enabled" not in entry or not isinstance(entry["enabled"], bool):
        raise SoftSensorConfigError("backup.enabled: required boolean")
    return _backup_enabled(entry) if entry["enabled"] else None


def _backup_enabled(entry: Mapping[str, Any]) -> BackupConfig:
    """All fields of an enabled backup block, each required, with range checks."""
    for key in _BACKUP_KEYS:
        if key not in entry:
            raise SoftSensorConfigError(f"backup.{key}: required field is missing")
    flag = entry.get("flag_tag")
    low = _ranged(entry, "range_lo", "backup", float("-inf"), None, False)
    high = _ranged(entry, "range_hi", "backup", float("-inf"), None, False)
    if low >= high:
        raise SoftSensorConfigError("backup.range_lo: must be below range_hi")
    return BackupConfig(
        measured_tag=_name(entry["measured_tag"], "backup.measured_tag"),
        frozen_s=_ranged(entry, "frozen_s", "backup", 0.0, None, True),
        range_lo=low,
        range_hi=high,
        return_hold_s=_ranged(entry, "return_hold_s", "backup", 0.0, None, False),
        flag_tag=None if flag is None else _name(flag, "backup.flag_tag"),
    )

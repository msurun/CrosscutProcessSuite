"""Load declarative loop templates with their packaged JSON schema.

A loop template is the generic knowledge of one loop type (flow, level, temperature, ...):
expected dynamics, KPI limits, diagnosis rules, tuning rule and target, allowed tests and a
safe default step. Templates are data so a site can edit them without a code change.
"""

from __future__ import annotations

import json
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

SCHEMA_NAME = "loop_template.schema.json"

# Field pairs that must satisfy min <= max. The schema cannot compare two properties,
# so the loader checks them and raises a message that names the template and the pair.
RANGE_PAIRS: tuple[tuple[str, str], ...] = (
    ("gain_min", "gain_max"),
    ("time_constant_s_min", "time_constant_s_max"),
    ("dead_time_s_min", "dead_time_s_max"),
)


class LoopTemplateError(ValueError):
    """A loop template cannot be read or violates the loop template contract."""


def _read_json(path: Traversable) -> Any:
    """Read JSON and identify the file when reading or decoding fails."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise LoopTemplateError(
            f"Invalid loop template file {path}: {error}. Fix the file."
        ) from error


def _validator() -> Draft202012Validator:
    """Build the validator from the schema shipped next to the data files."""
    return Draft202012Validator(_read_json(files(__package__).joinpath(SCHEMA_NAME)))


def validate_loop_template(record: Any) -> dict[str, Any]:
    """Return a template after schema and range checks, or raise LoopTemplateError.

    Used by the loader and by the API when a site saves an edited template, so both
    paths apply exactly the same contract.
    """
    try:
        _validator().validate(record)
    except ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise LoopTemplateError(
            f"Invalid loop template at {location}: {error.message}. Fix the template."
        ) from error
    _check_ranges(record)
    return record


def _check_ranges(record: dict[str, Any]) -> None:
    """Reject a dynamics range whose minimum is above its maximum."""
    dynamics = record["dynamics"]
    for low_name, high_name in RANGE_PAIRS:
        if dynamics[low_name] > dynamics[high_name]:
            raise LoopTemplateError(
                f"Invalid loop template {record['key']}: {low_name} is above {high_name}. "
                "Swap the bounds."
            )


def load_loop_templates(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return validated templates keyed by ``key``.

    ``directory`` overrides the packaged data folder (tests and site overrides use it).
    Raises LoopTemplateError for an unreadable folder, an invalid file or a duplicate key.
    """
    packaged = files(__package__)
    folder = packaged if directory is None else directory
    records: dict[str, dict[str, Any]] = {}
    for path in _template_paths(folder):
        record = validate_loop_template(_read_json(path))
        if record["key"] in records:
            raise LoopTemplateError(f"Duplicate loop template key in {path}: {record['key']}")
        records[record["key"]] = record
    if not records:
        raise LoopTemplateError(f"No loop template JSON files found in {folder}; add a template.")
    return records


def _template_paths(folder: Traversable) -> list[Traversable]:
    """Find JSON records in a stable name order, skipping the packaged schema."""
    try:
        paths = sorted(folder.iterdir(), key=lambda path: path.name)
    except OSError as error:
        raise LoopTemplateError(f"Cannot read loop templates in {folder}: {error}") from error
    return [path for path in paths if path.name.endswith(".json") and path.name != SCHEMA_NAME]

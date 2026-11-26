"""Load declarative vendor profile records with their packaged JSON schema.

Keep validation independent of vendor parameter conversions to avoid import cycles.
"""

from __future__ import annotations

import json
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

SCHEMA_NAME = "vendor_profile.schema.json"


class VendorProfileError(ValueError):
    """A profile cannot be read or violates the vendor profile contract."""


def _read_json(path: Traversable) -> Any:
    """Read JSON and identify the file when reading or decoding fails."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise VendorProfileError(
            f"Invalid vendor profile file {path}: {error}. Fix the file."
        ) from error


def load_vendor_profiles(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return validated records; raise VendorProfileError for invalid or duplicate profiles."""
    packaged = files(__package__)
    validator = Draft202012Validator(_read_json(packaged.joinpath(SCHEMA_NAME)))
    folder = packaged if directory is None else directory
    records: dict[str, dict[str, Any]] = {}
    for path in _profile_paths(folder):
        record = _load_profile(path, validator)
        if record["key"] in records:
            raise VendorProfileError(f"Duplicate vendor profile key in {path}: {record['key']}")
        records[record["key"]] = record
    if not records:
        raise VendorProfileError(f"No vendor profile JSON files found in {folder}; add a profile.")
    return records


def _profile_paths(folder: Traversable) -> list[Traversable]:
    """Find JSON records, preserving the original Siemens-before-ABB report order."""
    try:
        paths = sorted(folder.iterdir(), key=lambda path: path.name, reverse=True)
    except OSError as error:
        raise VendorProfileError(f"Cannot read vendor profiles in {folder}: {error}") from error
    return [path for path in paths if path.name.endswith(".json") and path.name != SCHEMA_NAME]


def _load_profile(path: Traversable, validator: Draft202012Validator) -> dict[str, Any]:
    """Validate a single record before any caller constructs a vendor form."""
    record = _read_json(path)
    try:
        validator.validate(record)
    except ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise VendorProfileError(
            f"Invalid vendor profile {path} at {location}: {error.message}. Fix the file."
        ) from error
    return record

"""Load and validate soft-sensor presets, and bind their roles to catalogue tags.

A preset is data (PRODUCT 4.2): target and input ROLES, model structure, lab sample contract,
validity checks, deployment gate and a provenance row. The user binds each role to a catalogue
tag; binding checks that every required role is bound and that the tag unit equals the role unit.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

PACKAGE_DIR = Path(__file__).resolve().parent
SCHEMA_NAME = "softsensor-preset.schema.json"


class PresetError(ValueError):
    """A preset file cannot be read or violates the preset contract."""


class PresetBindingError(ValueError):
    """Role bindings do not satisfy a preset (missing role, unknown tag, unit mismatch)."""


def _read_json(path: Path) -> Any:
    """Read JSON; every failure names the file."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise PresetError(f"{path.name}: cannot read preset file: {error}") from error



def _runtime_schema() -> dict[str, Any]:
    """Extend the v1 packaged contract with executable #156 structure declarations.

    The canonical schema lies outside this task's writable scope; keeping the v1
    file unchanged preserves its shared copy while this loader validates extensions.
    """
    schema = _read_json(PACKAGE_DIR / SCHEMA_NAME)
    model = schema["properties"]["model"]["properties"]
    model["allowed_now"]["items"]["enum"] = model["planned"]["items"]["enum"]
    model["physics"] = {
        "type": "object", "additionalProperties": False,
        "required": ["formula", "roles", "unit"],
        "properties": {
            "formula": {"enum": ["belt_net_power", "pump_hydraulic_power",
                                  "valve_incompressible", "slurry_mass_balance",
                                  "cyclone_loading_proxy", "integrated_net_mass"]},
            "roles": {"type": "array", "minItems": 1, "uniqueItems": True,
                      "items": {"$ref": "#/$defs/role"}},
            "unit": {"type": "string", "minLength": 1},
        },
    }
    return schema

def validate_preset(record: Any, source: str = "<preset>") -> dict[str, Any]:
    """Return the record after schema and cross-field checks; errors name ``source`` and field."""
    schema = _runtime_schema()
    try:
        Draft202012Validator(schema).validate(record)
    except ValidationError as error:
        field = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise PresetError(f"{source}: field {field}: {error.message}") from error
    _check_cross_fields(record, source)
    return record  # type: ignore[no-any-return]


def _check_cross_fields(record: dict[str, Any], source: str) -> None:
    """Checks a JSON schema cannot express: ordered ranges, unique roles, delay bounds."""
    _check_range(record["target"], "target", source)
    roles = [record["target"]["role"]]
    for index, entry in enumerate(record["inputs"]):
        _check_range(entry, f"inputs.{index}", source)
        roles.append(entry["role"])
    if len(set(roles)) != len(roles):
        raise PresetError(
            f"{source}: field inputs: role names must be unique and differ from the target"
        )
    _check_physics(record, source)
    lab = record.get("lab_sample")
    if lab and lab["report_delay_s_min"] > lab["report_delay_s_max"]:
        raise PresetError(
            f"{source}: field lab_sample.report_delay_s_min: above report_delay_s_max"
        )



def _check_physics(record: dict[str, Any], source: str) -> None:
    """Require every physics role to be a declared input and the formula arity to match."""
    physics = record["model"].get("physics")
    if physics is None:
        return
    roles = {entry["role"] for entry in record["inputs"]}
    arity = {"belt_net_power": 3, "pump_hydraulic_power": 4, "valve_incompressible": 4,
             "slurry_mass_balance": 3, "cyclone_loading_proxy": 3, "integrated_net_mass": 1}
    if set(physics["roles"]) - roles:
        raise PresetError(f"{source}: field model.physics.roles: use declared input roles")
    if len(physics["roles"]) != arity[physics["formula"]]:
        raise PresetError(f"{source}: field model.physics.roles: formula role count differs")

def _check_range(entry: Mapping[str, Any], field: str, source: str) -> None:
    """Reject range_min above range_max."""
    if "range_min" in entry and "range_max" in entry and entry["range_min"] > entry["range_max"]:
        raise PresetError(f"{source}: field {field}.range_min: above range_max")


def load_presets(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return validated presets keyed by ``key``; ``directory`` overrides the packaged folder."""
    folder = PACKAGE_DIR if directory is None else directory
    try:
        paths = sorted(folder.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise PresetError(f"{folder}: cannot read preset folder: {error}") from error
    records: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.name.endswith(".json") or path.name == SCHEMA_NAME:
            continue
        record = validate_preset(_read_json(path), path.name)
        if record["key"] in records:
            raise PresetError(f"{path.name}: field key: duplicate preset key {record['key']}")
        records[record["key"]] = record
    if not records:
        raise PresetError(f"{folder}: no preset JSON files found")
    return records


def bind_roles(
    preset: Mapping[str, Any],
    bindings: Mapping[str, str],
    catalogue: Mapping[str, str],
) -> dict[str, str]:
    """Check ``bindings`` (role -> tag id) against ``catalogue`` (tag id -> unit).

    Raises PresetBindingError for an unknown role, a missing required role (target included),
    a tag absent from the catalogue or a tag unit different from the role unit. Units of the
    pseudo-unit ``any`` accept every tag unit. Returns the checked bindings.
    """
    expected = {preset["target"]["role"]: (preset["target"]["unit"], True)}
    for entry in preset["inputs"]:
        expected[entry["role"]] = (entry["unit"], entry["required"])
    unknown = sorted(set(bindings) - set(expected))
    if unknown:
        raise PresetBindingError(f"{preset['key']}: unknown role(s) {unknown}")
    missing = sorted(
        role for role, (_, required) in expected.items() if required and role not in bindings
    )
    if missing:
        raise PresetBindingError(f"{preset['key']}: required role(s) not bound: {missing}")
    for role, tag in bindings.items():
        _check_tag(preset["key"], role, tag, expected[role][0], catalogue)
    return dict(bindings)


def _check_tag(key: str, role: str, tag: str, unit: str, catalogue: Mapping[str, str]) -> None:
    """One binding: tag known and unit equal to the role unit."""
    if tag not in catalogue:
        raise PresetBindingError(f"{key}: role {role}: tag {tag!r} is not in the catalogue")
    if unit != "any" and catalogue[tag] != unit:
        raise PresetBindingError(
            f"{key}: role {role}: tag {tag!r} has unit {catalogue[tag]!r}, expected {unit!r}"
        )

"""Role table handling for the Crosscut API.

Loads the packaged default role table, applies a validated override when present,
and enforces the gateway safety invariants (ADR 013).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema.exceptions import SchemaError, ValidationError

DEFAULT_ROLES_FILE = "auth-roles.default.json"
ROLES_SCHEMA_FILE = "auth-roles.schema.json"
OVERRIDE_RELATIVE = Path("_auth") / "roles.json"
INVARIANT_PERMISSIONS = ("gw.kill", "gw.mode.down", "gw.reject")
SERVICE_ROLE = "service"


class RolesError(ValueError):
    """Raised when the default role file cannot be read or fails validation."""


def schemas_dir() -> Path:
    """Return the directory that contains the role schema files."""
    env_dir = os.getenv("CROSSCUT_SCHEMAS_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    # api/src/crosscut_api/auth/roles.py -> parents[4] is the project root
    return Path(__file__).resolve().parents[4] / "schemas"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object, rejecting duplicate keys with RolesError."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RolesError(f"duplicate key {key!r} in roles JSON")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    """Reject non-finite numbers in JSON with RolesError."""
    raise RolesError(f"non-finite number {name} is not allowed in roles JSON")


def _read_json(file_path: Path) -> dict[str, Any]:
    """Read file_path as UTF-8 JSON and return the top-level object."""
    try:
        raw_text = file_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise RolesError(f"cannot read file {file_path}: {exc}") from exc
    try:
        data = json.loads(
            raw_text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise RolesError(f"invalid JSON in {file_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RolesError(f"JSON root in {file_path} must be an object")
    return data


def _validate_against_schema(data: dict[str, Any], schema_path: Path) -> None:
    """Validate data with the JSON schema located at schema_path."""
    from jsonschema import Draft202012Validator

    try:
        schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RolesError(f"cannot read schema file {schema_path}: {exc}") from exc
    try:
        Draft202012Validator(schema_doc).validate(data)
    except (ValidationError, SchemaError) as exc:
        raise RolesError(f"schema validation error: {exc}") from exc


def _parse_roles(data: dict[str, Any]) -> dict[str, frozenset[str]]:
    """Extract a mapping from role name to its permission set."""
    roles_section = data.get("roles")
    if not isinstance(roles_section, dict):
        raise RolesError("'roles' must be a JSON object")
    result: dict[str, frozenset[str]] = {}
    for role_name, role_doc in roles_section.items():
        if not isinstance(role_doc, dict):
            raise RolesError(f"definition of role {role_name!r} must be an object")
        perms = role_doc.get("permissions")
        if not isinstance(perms, list) or not all(isinstance(p, str) for p in perms):
            raise RolesError(f"role {role_name!r} must have a list of string permissions")
        result[role_name] = frozenset(perms)
    return result


def _find_invariant_violations(table: dict[str, frozenset[str]]) -> list[str]:
    """Return messages describing all invariant violations in table."""
    messages: list[str] = []
    for role_name, granted in table.items():
        if role_name == SERVICE_ROLE:
            extra = granted - {"gw.propose"}
            if extra:
                messages.append(
                    f"service role has extra permission(s): {', '.join(sorted(extra))}"
                )
        else:
            missing = set(INVARIANT_PERMISSIONS) - granted
            if missing:
                messages.append(
                    f"role {role_name} missing permission(s): {', '.join(sorted(missing))}"
                )
    return messages


def _enforce_invariants(table: dict[str, frozenset[str]]) -> None:
    """Raise RolesError if any invariant violation is found in table."""
    violations = _find_invariant_violations(table)
    if violations:
        raise RolesError("; ".join(violations))


def _truncate(text: str, limit: int = 300) -> str:
    """Return text truncated to limit characters."""
    return text[:limit] if len(text) > limit else text


@dataclass(frozen=True)
class RoleTable:
    """Immutable mapping of role identifiers to their permission sets."""

    roles: dict[str, frozenset[str]]
    warnings: tuple[str, ...] = ()
    source: str = "default"

    def known(self, name: str) -> bool:
        """Return True if name exists in the role table."""
        return name in self.roles

    def names(self) -> list[str]:
        """Return the sorted list of all role identifiers in the table."""
        return sorted(self.roles)

    def permissions_for(self, role_names: Iterable[str]) -> frozenset[str]:
        """Return the union of permissions for role_names; unknown roles add none."""
        collected: set[str] = set()
        for role_name in role_names:
            collected.update(self.roles.get(role_name, frozenset()))
        return frozenset(collected)


def _load_default() -> RoleTable:
    """Load the packaged default role table; invariant issues only warn."""
    schema_dir = schemas_dir()
    data = _read_json(schema_dir / DEFAULT_ROLES_FILE)
    _validate_against_schema(data, schema_dir / ROLES_SCHEMA_FILE)
    table = _parse_roles(data)
    issues = _find_invariant_violations(table)
    warnings: tuple[str, ...] = ()
    if issues:
        warnings = (f"default roles break invariant: {'; '.join(issues)}",)
    return RoleTable(roles=table, warnings=warnings, source="default")


def _load_override(root: Path) -> RoleTable:
    """Load and strictly validate the override at root / OVERRIDE_RELATIVE."""
    data = _read_json(root / OVERRIDE_RELATIVE)
    _validate_against_schema(data, schemas_dir() / ROLES_SCHEMA_FILE)
    table = _parse_roles(data)
    _enforce_invariants(table)
    return RoleTable(roles=table, warnings=(), source="override")


def load_roles(root: Path | None) -> RoleTable:
    """Return the effective role table; a bad override falls back to the default."""
    default_table = _load_default()
    if root is None or not (root / OVERRIDE_RELATIVE).is_file():
        return default_table
    try:
        return _load_override(root)
    except (RolesError, OSError, ValidationError, SchemaError) as exc:
        reason = _truncate(str(exc), 300)
        combined = default_table.warnings + (f"roles override ignored: {reason}",)
        return RoleTable(roles=default_table.roles, warnings=combined, source="default")

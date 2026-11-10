"""Authorization logic for Crosscut Gateway (Phase 2, #46).

Loads role definitions, validates them against a JSON schema, and decides whether a role set may
run a command. Roles are static data on disk; the decision functions here are pure and side-effect
free, so they are easy to test and reuse.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from crosscut_gateway.actor import normalize_actor

PERMISSIONS: frozenset[str] = frozenset(
    {
        "data.view",
        "ctl.view",
        "ctl.operate",
        "gw.view",
        "audit.view",
        "gw.kill",
        "gw.mode.down",
        "analysis.run",
        "job.stop",
        "job.manage",
        "gw.approve",
        "gw.approve.tuning",
        "gw.reject",
        "gw.re_enable.hold_off",
        "gw.re_enable.stopped",
        "data.import",
        "config.edit",
        "connector.use",
        "gw.propose",
        "gw.mode.up.advisory",
        "gw.mode.up.dry_run",
        "gw.mode.up.confirm",
        "gw.mode.up.supervised",
        "policy.edit",
        "gw.kill.reset",
        "policy.pin",
        "policy.reload",
        "users.manage",
    }
)

# Operating modes from the least to the most permissive; the index is the "step" on the dial.
MODES: tuple[str, ...] = ("off", "advisory", "dry_run", "confirm", "supervised")

# Permissions that hand control to a human; no automated role may be granted them.
FORCED_HUMAN_PERMISSIONS: frozenset[str] = frozenset(
    {"gw.kill", "gw.mode.down", "gw.reject"}
)

# The single role allowed to run without human oversight; it may only propose.
SERVICE_ROLE = "service"

# Maximum number of parent directories to walk when searching for schema files.
_MAX_ANCHOR_LEVELS = 10

# Maps a simple command to the permission it requires. More complex commands are handled
# by their own helper functions in authorize().
_COMMAND_PERMISSIONS: dict[str, str] = {
    "propose": "gw.propose",
    "propose_params": "gw.propose",
    "approve": "gw.approve",
    "reject": "gw.reject",
    "mv_availability": "gw.view",
    "kill": "gw.kill",
    "kill_reset": "gw.kill.reset",
    "policy_draft": "policy.edit",
    "policy_pin": "policy.pin",
    "policy_reload": "policy.reload",
}

# Approving a queued PID parameter set needs this permission (ADR 014); gw.approve is not enough.
TUNING_APPROVE_PERMISSION = "gw.approve.tuning"
PENDING_KIND_PARAMS = "pid_param"
_SERVICE_ACTOR_PREFIX = "svc:"

# The permission suffix for an upward mode change is the mode name itself.
_UPWARD_PERMISSION_PREFIX = "gw.mode.up."


class AuthzError(ValueError):
    """Raised when role data is missing, malformed, or violates a safety invariant."""


def _find_up(relative_name: str) -> Path:
    """Walk up from this package's directory (at most 10 levels) to find relative_name.

    Raises AuthzError when no ancestor directory contains the file.
    """
    current = Path(__file__).resolve().parent
    for _level in range(_MAX_ANCHOR_LEVELS):
        candidate = current / relative_name
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    raise AuthzError(f"file {relative_name} not found in any parent directory")


def default_roles_path() -> Path:
    """Return the path to schemas/auth-roles.default.json."""
    return _find_up("schemas/auth-roles.default.json")


def roles_schema_path() -> Path:
    """Return the path to schemas/auth-roles.schema.json."""
    return _find_up("schemas/auth-roles.schema.json")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object from pairs, raising AuthzError when a key appears twice."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuthzError(f"duplicate key {key!r} in roles JSON")
        result[key] = value
    return result


def _reject_constant(name: str) -> NoReturn:
    """Refuse the non-standard NaN, Infinity and -Infinity JSON tokens."""
    raise AuthzError(f"non-finite number {name} is not allowed in roles JSON")


def _read_and_parse_json(path: Path) -> dict[str, Any]:
    """Read path as UTF-8 (BOM tolerated) and parse strict JSON, mapping errors to AuthzError."""
    try:
        raw_text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise AuthzError(f"cannot read roles file {path}: {error}") from error
    try:
        data = json.loads(
            raw_text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except AuthzError:
        raise
    except ValueError as error:
        raise AuthzError(f"invalid JSON in roles file {path}: {error}") from error
    if not isinstance(data, dict):
        raise AuthzError(f"roles file {path} must contain a JSON object")
    return data


def _load_validator_class() -> Any:
    """Import jsonschema's Draft 2020-12 validator lazily, reporting a missing package."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        message = f"jsonschema is required to validate roles files: {error}"
        raise AuthzError(message) from error
    return Draft202012Validator


def _validate_schema(data: dict[str, Any]) -> None:
    """Validate data against schemas/auth-roles.schema.json, raising AuthzError on failure."""
    validator_class = _load_validator_class()
    schema_path = roles_schema_path()
    try:
        schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = validator_class(schema_doc)
        errors = sorted(validator.iter_errors(data), key=lambda issue: list(issue.path))
    except Exception as error:
        raise AuthzError(f"schema loading or validation failed: {error}") from error
    if errors:
        issues = "; ".join(f"{list(issue.path)}: {issue.message}" for issue in errors)
        raise AuthzError(f"roles schema validation failed: {issues}")


def _extract_permissions(role_name: str, role_doc: Any) -> list[str]:
    """Return the raw permission list for one role, validating its shape."""
    if not isinstance(role_doc, dict):
        raise AuthzError(f"role {role_name!r} must be a JSON object")
    permissions = role_doc.get("permissions")
    if not isinstance(permissions, list) or not all(
        isinstance(permission, str) for permission in permissions
    ):
        raise AuthzError(f"role {role_name!r} must have a list of string permissions")
    return permissions


def _check_human_role(role_name: str, granted: frozenset[str]) -> None:
    """Raise AuthzError if a non-service role is missing a forced-human permission."""
    for required in FORCED_HUMAN_PERMISSIONS:
        if required not in granted:
            raise AuthzError(
                f"role {role_name!r} is missing forced-human permission {required!r}"
            )


def _check_service_role(granted: frozenset[str]) -> None:
    """Raise AuthzError if the service role is granted anything besides gw.propose."""
    allowed = {"gw.propose"}
    for extra in granted - allowed:
        raise AuthzError(f"role {SERVICE_ROLE!r} must not have permission {extra!r}")


def _enforce_invariants(table: dict[str, frozenset[str]]) -> None:
    """Apply the safety invariants to every role in the loaded table."""
    for role_name, granted in table.items():
        if role_name == SERVICE_ROLE:
            _check_service_role(granted)
        else:
            _check_human_role(role_name, granted)


def load_roles(path: Path | None = None) -> dict[str, frozenset[str]]:
    """Load, validate and enforce invariants on a roles file.

    Parameters
    ----------
    path: Roles JSON file; None means the packaged default roles file.

    Returns
    -------
    Mapping from role name to the frozenset of permissions it grants.

    Raises
    ------
    AuthzError: file missing, malformed JSON, schema violation or invariant violation.
    """
    resolved_path = default_roles_path() if path is None else path
    data = _read_and_parse_json(resolved_path)
    _validate_schema(data)
    roles_doc = data.get("roles")
    if not isinstance(roles_doc, dict):
        raise AuthzError(f"roles file {resolved_path} must contain a 'roles' object")
    table = {
        role_name: frozenset(_extract_permissions(role_name, role_doc))
        for role_name, role_doc in roles_doc.items()
    }
    _enforce_invariants(table)
    return table


def roles_or_default(
    path: Path | None,
) -> tuple[dict[str, frozenset[str]], str | None]:
    """Load roles from path, falling back to the default table on any failure.

    Returns (table, None) on success, or (default_table, reason) when path cannot be used.
    """
    if path is None:
        return load_roles(None), None
    try:
        return load_roles(path), None
    except (AuthzError, OSError) as error:
        return load_roles(None), str(error)


@dataclass(frozen=True)
class AuthRequest:
    """A single authorization question: which roles want to run cmd with these args?"""

    roles: Sequence[str]
    cmd: str
    args: Mapping[str, Any]
    mode: str
    target_state: str | None = None
    pending_kind: str | None = None
    actor: str = ""


def _effective_permissions(
    roles: Sequence[str], table: Mapping[str, frozenset[str]]
) -> frozenset[str]:
    """Union the permissions granted to roles that exist in table; unknown roles give nothing."""
    granted: set[str] = set()
    for role_name in roles:
        granted.update(table.get(role_name, frozenset()))
    return frozenset(granted)


def _check_permission(granted: frozenset[str], permission: str) -> tuple[bool, str]:
    """Allow when permission is granted, otherwise report a missing_permission reason."""
    if permission in granted:
        return True, "ok"
    return False, f"missing_permission:{permission}"


def _re_enable_permission(target_state: str | None) -> str:
    """Stopped paths require the stopped permission; hold_off requires the hold_off permission."""
    if target_state == "hold_off":
        return "gw.re_enable.hold_off"
    return "gw.re_enable.stopped"


def _is_service(request: AuthRequest) -> bool:
    """True for the service principal: a ``svc:`` actor or any holder of the service role."""
    actor = normalize_actor(request.actor)
    return actor.startswith(_SERVICE_ACTOR_PREFIX) or SERVICE_ROLE in request.roles


def _authorize_simple(
    cmd: str, granted: frozenset[str], request: AuthRequest
) -> tuple[bool, str]:
    """Authorize commands whose permission depends only on a lookup."""
    if cmd == "re_enable":
        permission = _re_enable_permission(request.target_state)
        return _check_permission(granted, permission)
    if cmd == "propose_params" and _is_service(request):
        return False, "service_cannot_propose_tuning"
    if cmd == "approve" and request.pending_kind == PENDING_KIND_PARAMS:
        return _check_permission(granted, TUNING_APPROVE_PERMISSION)
    permission = _COMMAND_PERMISSIONS[cmd]
    return _check_permission(granted, permission)


def _authorize_set_mode(
    request: AuthRequest, granted: frozenset[str]
) -> tuple[bool, str]:
    """Authorize a set_mode command: downward needs gw.mode.down, upward needs a step check."""
    if request.mode not in MODES:
        return False, "bad_mode"
    new_mode = request.args.get("mode")
    if not isinstance(new_mode, str) or new_mode not in MODES:
        return False, "bad_mode"
    if new_mode == request.mode:
        return True, "ok"
    current_index = MODES.index(request.mode)
    new_index = MODES.index(new_mode)
    if new_index < current_index:
        return _check_permission(granted, "gw.mode.down")
    return _authorize_upward(request, granted, current_index, new_index)


def _authorize_upward(
    request: AuthRequest,
    granted: frozenset[str],
    current_index: int,
    new_index: int,
) -> tuple[bool, str]:
    """Authorize an upward mode change: exactly one step, within cap, and holding the permission."""
    if new_index - current_index != 1:
        return False, "mode_step_too_large"
    cap_result = _check_cap(request.args, new_index)
    if cap_result is not None:
        return cap_result
    permission = _UPWARD_PERMISSION_PREFIX + MODES[new_index]
    return _check_permission(granted, permission)


def _check_cap(
    args: Mapping[str, Any], new_index: int
) -> tuple[bool, str] | None:
    """Return a denial when args has a cap above which the new mode may not go, else None."""
    if "cap" not in args:
        return None
    cap = args["cap"]
    if not isinstance(cap, str) or cap not in MODES:
        return False, "bad_mode"
    if new_index > MODES.index(cap):
        return False, "above_cap"
    return None


def authorize(
    request: AuthRequest, table: Mapping[str, frozenset[str]]
) -> tuple[bool, str]:
    """Decide whether request.roles may run request.cmd.

    Returns (True, "ok") when allowed, otherwise (False, reason) with reason one of
    'unknown_cmd', 'bad_mode', 'mode_step_too_large', 'above_cap',
    'service_cannot_propose_tuning' or 'missing_permission:<perm>'.
    """
    granted = _effective_permissions(request.roles, table)
    if request.cmd == "set_mode":
        return _authorize_set_mode(request, granted)
    if request.cmd in _COMMAND_PERMISSIONS or request.cmd == "re_enable":
        return _authorize_simple(request.cmd, granted, request)
    return False, "unknown_cmd"

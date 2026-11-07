"""Site auth settings: the optional ``<root>/_auth/config.json`` (ADR 013, "Configurable defaults").

A missing file means the defaults, which equal the built-in behaviour. A file that is
unreadable, breaks the schema (``schemas/auth-config.schema.json``) or sets an unsafe
combination is refused with an error naming the field, so the API does not start.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from crosscut_api.auth.roles import schemas_dir
from crosscut_api.auth.sessions import AuthConfig

CONFIG_RELATIVE = Path("_auth") / "config.json"
SCHEMA_FILE = "auth-config.schema.json"
_UNEXPECTED = re.compile(r"\('([^']*)' was unexpected|\('(.*?)'(?:,|\))")


class AuthSettingsError(ValueError):
    """Raised when the auth settings file cannot be used; the message names the field."""


@dataclass(frozen=True)
class AuthSettings:
    """The site-level settings in the units used in the file; defaults are the safe values."""

    session_idle_minutes: int = 60
    session_absolute_hours: int = 12
    stepup_valid_minutes: int = 5
    lockout_failures: int = 5
    lockout_base_minutes: int = 5
    lockout_max_minutes: int = 60
    login_rate_per_ip_per_min: int = 20
    password_min_length: int = 12
    require_second_admin_for_password_reset: bool = True
    kill_file_enabled: bool = True
    allowed_origins: tuple[str, ...] = ()
    secure_cookie: str = "auto"


def _read(path: Path) -> dict[str, Any]:
    """Read the settings file as a JSON object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthSettingsError(f"{path}: cannot read settings: {exc}") from exc
    if not isinstance(data, dict):
        raise AuthSettingsError(f"{path}: settings must be a JSON object")
    return data


def _error_field(error: ValidationError) -> str:
    """Return the offending field name of a schema error."""
    if error.validator == "additionalProperties":
        match = _UNEXPECTED.search(error.message)
        return match.group(1) if match and match.group(1) else "(unknown key)"
    return ".".join(str(part) for part in error.absolute_path) or "(root)"


def _validate(data: dict[str, Any], path: Path) -> None:
    """Raise AuthSettingsError for the first schema violation, naming its field."""
    schema = json.loads((schemas_dir() / SCHEMA_FILE).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=_error_field)
    if errors:
        raise AuthSettingsError(f"{path}: field {_error_field(errors[0])}: {errors[0].message}")


def _check_relations(settings: AuthSettings, path: Path) -> None:
    """Reject combinations the per-field bounds cannot express."""
    if settings.lockout_max_minutes < settings.lockout_base_minutes:
        raise AuthSettingsError(
            f"{path}: field lockout_max_minutes: must be at least lockout_base_minutes"
        )


def parse_settings(data: dict[str, Any], path: Path = CONFIG_RELATIVE) -> AuthSettings:
    """Validate a settings mapping and return the settings; omitted keys keep defaults."""
    _validate(data, path)
    values = dict(data)
    if "allowed_origins" in values:
        values["allowed_origins"] = tuple(values["allowed_origins"])
    settings = replace(AuthSettings(), **values)
    _check_relations(settings, path)
    return settings


def load_auth_settings(root: Path | None) -> AuthSettings:
    """Return the settings of a data root; a missing file gives the defaults."""
    if root is None or not (root / CONFIG_RELATIVE).is_file():
        return AuthSettings()
    path = root / CONFIG_RELATIVE
    return parse_settings(_read(path), path)


def to_config(settings: AuthSettings, base: AuthConfig | None = None) -> AuthConfig:
    """Map settings onto an ``AuthConfig``, keeping the scrypt cost of ``base``."""
    base = base if base is not None else AuthConfig()
    return replace(
        base,
        min_password_length=settings.password_min_length,
        idle_timeout_s=settings.session_idle_minutes * 60.0,
        absolute_timeout_s=settings.session_absolute_hours * 3600.0,
        stepup_valid_s=settings.stepup_valid_minutes * 60.0,
        max_failed_logins=settings.lockout_failures,
        lock_base_s=settings.lockout_base_minutes * 60.0,
        lock_max_s=settings.lockout_max_minutes * 60.0,
        ip_rate_limit=settings.login_rate_per_ip_per_min,
        allowed_origins=settings.allowed_origins,
        require_second_admin=settings.require_second_admin_for_password_reset,
        secure_cookie=settings.secure_cookie,
        kill_file_enabled=settings.kill_file_enabled,
    )


def load_auth_config(root: Path | None, base: AuthConfig | None = None) -> AuthConfig:
    """Return the effective ``AuthConfig`` of a data root (file settings over defaults)."""
    return to_config(load_auth_settings(root), base)


def settings_view(config: AuthConfig) -> dict[str, Any]:
    """Return the effective settings of ``config`` in file units, for the admin route."""
    return {
        "session_idle_minutes": config.idle_timeout_s / 60,
        "session_absolute_hours": config.absolute_timeout_s / 3600,
        "stepup_valid_minutes": config.stepup_valid_s / 60,
        "lockout_failures": config.max_failed_logins,
        "lockout_base_minutes": config.lock_base_s / 60,
        "lockout_max_minutes": config.lock_max_s / 60,
        "login_rate_per_ip_per_min": config.ip_rate_limit,
        "password_min_length": config.min_password_length,
        "require_second_admin_for_password_reset": config.require_second_admin,
        "kill_file_enabled": config.kill_file_enabled,
        "allowed_origins": list(config.allowed_origins),
        "secure_cookie": config.secure_cookie,
    }

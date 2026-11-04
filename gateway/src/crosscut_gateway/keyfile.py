"""Locate and read the gateway HMAC key file.

The key lives in a secrets directory, overridable with the CROSSCUT_SECRETS_DIR variable.
On POSIX a key file that is group- or world-writable, or world-readable, is refused.
read_key never raises: a missing, unreadable, too-short or insecure file yields None.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

SECRETS_ENV = "CROSSCUT_SECRETS_DIR"
KEY_FILE_NAME = "gateway-hmac.key"
MIN_KEY_BYTES = 32
_IS_POSIX = os.name == "posix"
_GROUP_OR_WORLD_WRITE = 0o022
_WORLD_ANY = 0o007


def secrets_dir(root: Path) -> Path:
    """Return the secrets directory from the environment, else root/_secrets."""
    override = os.environ.get(SECRETS_ENV, "")
    if override:
        return Path(override)
    return root / "_secrets"


def default_key_path(root: Path) -> Path:
    """Return the path of the gateway HMAC key file inside the secrets directory."""
    return secrets_dir(root) / KEY_FILE_NAME


def mode_problem(mode: int) -> str | None:
    """Return the problem name for a file mode, or None when the mode is acceptable."""
    if mode & _GROUP_OR_WORLD_WRITE:
        return "key_file_group_or_world_writable"
    if mode & _WORLD_ANY:
        return "key_file_world_readable"
    return None


def key_permission_problem(path: Path) -> str | None:
    """Return the permission problem of the key file on POSIX, None otherwise or if unstatable."""
    if not _IS_POSIX:
        return None
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return None
    return mode_problem(mode)


def key_acl_status(path: Path) -> str:
    """Return 'unchecked' off POSIX, 'insecure' for a loose key file, else 'ok'."""
    if not _IS_POSIX:
        return "unchecked"
    return "insecure" if key_permission_problem(path) is not None else "ok"


def read_key(path: Path) -> bytes | None:
    """Return the raw key bytes, or None when missing, insecure, unreadable or under 32 bytes."""
    if key_permission_problem(path) is not None:
        return None
    try:
        data = path.read_bytes()
    except (OSError, ValueError):
        return None
    if len(data) < MIN_KEY_BYTES:
        return None
    return data

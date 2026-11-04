"""Locate and read the gateway HMAC key file.

The key lives in a secrets directory, overridable with the CROSSCUT_SECRETS_DIR variable.
read_key never raises: a missing, unreadable or too-short file yields None.
"""

from __future__ import annotations

import os
from pathlib import Path

SECRETS_ENV = "CROSSCUT_SECRETS_DIR"
KEY_FILE_NAME = "gateway-hmac.key"
MIN_KEY_BYTES = 32


def secrets_dir(root: Path) -> Path:
    """Return the secrets directory from the environment, else root/_secrets."""
    override = os.environ.get(SECRETS_ENV, "")
    if override:
        return Path(override)
    return root / "_secrets"


def default_key_path(root: Path) -> Path:
    """Return the path of the gateway HMAC key file inside the secrets directory."""
    return secrets_dir(root) / KEY_FILE_NAME


def read_key(path: Path) -> bytes | None:
    """Return the raw key bytes, or None when missing, unreadable or under 32 bytes."""
    try:
        data = path.read_bytes()
    except (OSError, ValueError):
        return None
    if len(data) < MIN_KEY_BYTES:
        return None
    return data

"""Persistence helpers for the gateway state directory <root>/_gateway.

Writes JSON atomically (temp file, fsync, os.replace with a Windows retry), manages the KILLED
kill latch file and reads JSON objects tolerantly, returning None for any unusable file.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

KILLED_NAME = "KILLED"
NONCE_NAME = "nonce-cache.json"
_REPLACE_ATTEMPTS = 50
_REPLACE_DELAY_S = 0.01


def write_json_atomic(target: Path, data: dict[str, Any]) -> None:
    """Write *data* as JSON to *target* so readers never see a partial file.

    Args:
        target: Destination file; its parent directories are created when missing.
        data: JSON-serialisable mapping to store.

    Raises:
        OSError: The file could not be written or moved into place.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".latch-", suffix=".tmp")
    tmp_file = Path(tmp_name)
    try:
        _dump_and_sync(fd, data)
        _replace_with_retry(tmp_file, target)
    except BaseException:
        tmp_file.unlink(missing_ok=True)
        raise


def _dump_and_sync(fd: int, data: dict[str, Any]) -> None:
    """Serialise *data* to the open descriptor *fd* and flush it to disk."""
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_with_retry(source: Path, target: Path) -> None:
    """Move *source* over *target*, retrying while a reader on Windows holds *target* open.

    Args:
        source: File to move into place.
        target: Destination that readers may have open.

    Raises:
        PermissionError: The last attempt still failed.
    """
    for _ in range(_REPLACE_ATTEMPTS - 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            time.sleep(_REPLACE_DELAY_S)
    os.replace(source, target)


def write_kill_latch(gateway_dir: Path, actor: str, at_utc: str) -> None:
    """Persist the KILLED latch recording who triggered the kill and when.

    Args:
        gateway_dir: The <root>/_gateway directory.
        actor: Identity of the operator who issued the kill.
        at_utc: ISO-8601 UTC timestamp of the kill.

    Raises:
        OSError: The latch file could not be written.
    """
    write_json_atomic(gateway_dir / KILLED_NAME, {"actor": actor, "at_utc": at_utc})


def kill_latch_present(gateway_dir: Path) -> bool:
    """Return True when the KILLED latch file exists in *gateway_dir*."""
    return (gateway_dir / KILLED_NAME).exists()


def clear_kill_latch(gateway_dir: Path) -> None:
    """Remove the KILLED latch file; a missing file is not an error.

    Args:
        gateway_dir: The <root>/_gateway directory.

    Raises:
        OSError: The file exists but could not be removed.
    """
    (gateway_dir / KILLED_NAME).unlink(missing_ok=True)


def read_json_object(path: Path) -> dict[str, Any] | None:
    """Read a JSON object from *path*, or return None when it is unusable.

    Args:
        path: File expected to hold a JSON object.

    Returns:
        The parsed object, or None if the file is missing, unreadable, not valid
        UTF-8/JSON, nested too deeply, or not a JSON object.
    """
    try:
        loaded = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return loaded if isinstance(loaded, dict) else None

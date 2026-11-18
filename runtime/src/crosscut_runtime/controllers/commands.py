"""Operator command queue of one controller: ``<root>/_runtime/controllers/<id>.commands.json``.

The API appends commands (switch_on, switch_off, standby); the runtime takes them all at the
start of a cycle. Taking renames the file first, so a command is delivered exactly once.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from crosscut_runtime.controllers.host import CONTROLLERS_FOLDER
from crosscut_runtime.controllers.state import COMMANDS, SWITCH_OFF
from crosscut_runtime.store import RUNTIME_FOLDER, write_json_atomic


def commands_path(root: Path, controller_id: str) -> Path:
    """Path of the command queue of one controller."""
    return root / RUNTIME_FOLDER / CONTROLLERS_FOLDER / f"{controller_id}.commands.json"


def enqueue_command(root: Path, controller_id: str, command: str) -> None:
    """Append a command to the queue (single writer: the API process).

    Raises:
        ValueError: for a command the state machine does not know.
    """
    if command not in COMMANDS:
        raise ValueError(f"unknown command {command!r}")
    path = commands_path(root, controller_id)
    write_json_atomic(path, {"commands": [*_read(path), command]})


def take_commands(root: Path, controller_id: str) -> list[str]:
    """Read and clear the queue atomically; a missing or corrupt file gives an empty list."""
    path = commands_path(root, controller_id)
    taken = path.with_name(f"{path.name}.{os.getpid()}.taken")
    try:
        os.replace(path, taken)
    except FileNotFoundError:
        return []
    try:
        return _read(taken)
    finally:
        taken.unlink(missing_ok=True)


def pick_command(commands: list[str]) -> str | None:
    """The command to apply this cycle: ``switch_off`` wins, else the newest, else none."""
    if SWITCH_OFF in commands:
        return SWITCH_OFF
    return commands[-1] if commands else None


def _read(path: Path) -> list[str]:
    """Valid commands of a queue file, in order."""
    try:
        items = json.loads(path.read_text(encoding="utf-8")).get("commands", [])
    except (FileNotFoundError, json.JSONDecodeError, AttributeError, OSError):
        return []
    return [c for c in items if c in COMMANDS] if isinstance(items, list) else []

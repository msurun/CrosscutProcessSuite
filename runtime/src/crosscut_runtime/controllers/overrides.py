"""Operator overrides of one controller: ``<root>/_runtime/controllers/<id>.operator.json``.

The API writes, per variable id, an optional ``enabled`` flag and an optional ``operator``
range ``{lo, hi}``. The host reads the file every cycle: an override replaces the catalogue's
``enabled_default`` and operator limits; everything else of the catalogue stays as it is.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from crosscut_runtime.store import RUNTIME_FOLDER, write_json_atomic

CONTROLLERS_FOLDER = "controllers"
Overrides = dict[str, dict[str, Any]]


def overrides_path(root: Path, controller_id: str) -> Path:
    """Path of the operator override file of one controller."""
    return root / RUNTIME_FOLDER / CONTROLLERS_FOLDER / f"{controller_id}.operator.json"


def read_overrides(root: Path, controller_id: str) -> Overrides:
    """Overrides per variable id; a missing or corrupt file gives no overrides."""
    try:
        text = overrides_path(root, controller_id).read_text(encoding="utf-8")
        variables = json.loads(text).get("variables", {})
    except (FileNotFoundError, json.JSONDecodeError, AttributeError, OSError):
        return {}
    if not isinstance(variables, dict):
        return {}
    return {k: v for k, v in variables.items() if isinstance(v, dict)}


def write_overrides(root: Path, controller_id: str, overrides: Mapping[str, Any]) -> None:
    """Replace the override file atomically (single writer: the API process)."""
    write_json_atomic(overrides_path(root, controller_id), {"variables": dict(overrides)})


def apply_overrides(doc: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of the controller document with the overrides applied to its variables."""
    out = copy.deepcopy(dict(doc))
    for variable in out.get("variables", []):
        override = overrides.get(variable["id"])
        if override:
            _apply_one(variable, override)
    return out


def _apply_one(variable: dict[str, Any], override: Mapping[str, Any]) -> None:
    """Apply one variable's override in place."""
    if isinstance(override.get("enabled"), bool):
        variable["enabled_default"] = override["enabled"]
    operator = override.get("operator")
    if isinstance(operator, dict) and {"lo", "hi"} <= operator.keys():
        variable.setdefault("limits", {})["operator"] = {
            "lo": operator["lo"],
            "hi": operator["hi"],
        }


def economics_path(root: Path, controller_id: str) -> Path:
    """Path of the operator objective of one controller (replaces the catalogue's economics)."""
    return root / RUNTIME_FOLDER / CONTROLLERS_FOLDER / f"{controller_id}.economics.json"


def read_economics(root: Path, controller_id: str) -> dict[str, Any] | None:
    """The operator objective block, or ``None`` (missing or corrupt file: use the catalogue)."""
    try:
        data = json.loads(economics_path(root, controller_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    block = data.get("economics") if isinstance(data, dict) else None
    return block if isinstance(block, dict) else None


def write_economics(root: Path, controller_id: str, block: Mapping[str, Any] | None) -> None:
    """Store the objective block atomically; ``None`` removes the override."""
    path = economics_path(root, controller_id)
    if block is None:
        path.unlink(missing_ok=True)
        return
    write_json_atomic(path, {"economics": dict(block)})

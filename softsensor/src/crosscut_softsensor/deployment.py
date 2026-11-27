"""Stored deployment of a soft sensor: mode, validation results and the gate decision.

Files under ``<data root>/_softsensor``: ``<sid>.deployment.json`` (mode, who changed it, lab
stamp contract) and ``<sid>.validation.json`` (preset key and validation results). The mode is
written only by the audited API action; the runtime job only reads it and re-checks the gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crosscut_softsensor.deployment_gate import (
    REFUSAL_TEXT,
    GateDecision,
    ValidationResults,
    evaluate_gate,
)
from crosscut_softsensor.online import MODES
from crosscut_softsensor.presets import load_presets

FOLDER = "_softsensor"
DEFAULT_STAMP = {"meaning": "sample", "window_s": 0.0}


def _read(path: Path) -> dict[str, Any] | None:
    """A JSON object file, None when absent."""
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, dict) else None


def read_deployment(root: Path, sid: str) -> dict[str, Any]:
    """The stored deployment; a sensor without one is ``off``."""
    doc = _read(Path(root) / FOLDER / f"{sid}.deployment.json") or {}
    mode = doc.get("mode", "off")
    return {"mode": mode if mode in MODES else "off", "changed_by": doc.get("changed_by"),
            "changed_utc": doc.get("changed_utc"), "lab_stamp": doc.get("lab_stamp", DEFAULT_STAMP)}


def read_validation(root: Path, sid: str) -> dict[str, Any] | None:
    """The stored validation ({preset, results}) or None."""
    return _read(Path(root) / FOLDER / f"{sid}.validation.json")


def gate_for(root: Path, sid: str) -> tuple[GateDecision | None, dict[str, Any] | None]:
    """Gate decision on the stored validation and the preset; None decision when none is stored."""
    validation = read_validation(root, sid)
    if validation is None:
        return None, None
    preset = load_presets()[validation["preset"]]
    results = ValidationResults(**validation["results"])
    return evaluate_gate(preset["deployment_gate"], results), preset


def gate_view(root: Path, sid: str) -> dict[str, Any]:
    """The gate result as shown to the console (refusal text when nothing is stored)."""
    try:
        decision, _ = gate_for(root, sid)
    except (KeyError, TypeError, ValueError) as error:
        return {"available": False, "deploy": False, "skill": None,
                "reasons": [f"stored validation is unusable: {error}"], "message": REFUSAL_TEXT}
    if decision is None:
        return {"available": False, "deploy": False, "skill": None,
                "reasons": ["no stored validation"], "message": REFUSAL_TEXT}
    return {"available": True, "deploy": decision.deploy, "skill": decision.skill,
            "reasons": list(decision.reasons), "message": decision.message}

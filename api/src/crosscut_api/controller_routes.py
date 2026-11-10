"""Operator console routes for the APC core controllers (Phase 2.5, step 7).

Reads the controller entries of the site catalogue joined with the records the runtime host
writes under ``<root>/_runtime/controllers/``. Writes only two things: operator commands
(``enqueue_command``) and per-variable operator overrides (``<id>.operator.json``). Every
command and override is appended to the API auth audit before it takes effect.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from crosscut_connectors.site import SiteError, load_site
from crosscut_runtime.controllers.commands import enqueue_command
from crosscut_runtime.controllers.host import record_path
from crosscut_runtime.controllers.overrides import (
    apply_overrides,
    read_overrides,
    write_overrides,
)
from crosscut_runtime.store import read_variable_status
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir

Doc = dict[str, Any]
DEFAULT_CYCLE_S = 30
RECORD_DEFAULTS: Doc = {
    "state": "off",
    "reason": "new",
    "last_cycle_utc": None,
    "last_duration_s": None,
    "overruns": 0,
    "consecutive_overruns": 0,
    "liveness_utc": None,
    "last_explanation": "",
}


class CommandBody(BaseModel):
    """Body of ``POST /controllers/{id}/command``."""

    command: Literal["switch_on", "switch_off", "standby"]


class Bounds(BaseModel):
    """An operator range."""

    lo: float
    hi: float


class VariableBody(BaseModel):
    """Body of ``PUT /controllers/{id}/variables/{vid}``; no ``operator`` removes the override."""

    enabled: bool
    operator: Bounds | None = None


def _read_record(root: Path, controller_id: str) -> Doc:
    """The host's record as stored (never restored: this is what the host last wrote)."""
    try:
        data = json.loads(record_path(root, controller_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _site_controllers(root: Path) -> list[Doc]:
    """Controller entries of the site catalogue; empty when there is no readable site."""
    try:
        return [dict(c) for c in load_site(root).get("controllers", [])]
    except SiteError:
        return []


def _find(root: Path, controller_id: str) -> Doc:
    """One controller entry, or HTTP 404."""
    for entry in _site_controllers(root):
        if entry["id"] == controller_id:
            return entry
    raise HTTPException(status_code=404, detail=f"no controller {controller_id!r}")


def _effective(root: Path, entry: Doc) -> Doc:
    """The controller entry with the operator overrides applied."""
    return apply_overrides(entry, read_overrides(root, entry["id"]))


def _summary(root: Path, entry: Doc) -> Doc:
    """List row of one controller: record fields plus the disabled variable ids."""
    record = {**RECORD_DEFAULTS, **_read_record(root, entry["id"])}
    off = [
        v["id"] for v in _effective(root, entry)["variables"] if not v.get("enabled_default", True)
    ]
    return {
        "id": entry["id"],
        "type": entry["type"],
        "description": entry.get("description", ""),
        "cycle_s": entry.get("cycle_s", DEFAULT_CYCLE_S),
        **{key: record[key] for key in RECORD_DEFAULTS},
        "disabled": off,
    }


def _variable_row(var: Doc, catalogue: Doc, status: Doc | None) -> Doc:
    """One variable of the detail view: limits (catalogue and effective) and live status."""
    state = status or {}
    return {
        "id": var["id"],
        "role": var["role"],
        "binding": var["binding"],
        "enabled": var.get("enabled_default", True),
        "limits": {
            **var.get("limits", {}),
            "operator_catalogue": catalogue.get("limits", {}).get("operator"),
        },
        "status": state.get("status"),
        "reasons": list(state.get("reasons", [])),
        "value": state.get("value"),
        "sp_value": state.get("sp_value"),
        "source_utc": state.get("source_utc"),
    }


def _detail(root: Path, entry: Doc) -> Doc:
    """Summary plus the variable rows with their live statuses."""
    statuses = {s["variable_id"]: s for s in read_variable_status(root).get(entry["id"], [])}
    catalogue = {v["id"]: v for v in entry["variables"]}
    rows = [
        _variable_row(v, catalogue[v["id"]], statuses.get(v["id"]))
        for v in _effective(root, entry)["variables"]
    ]
    return {**_summary(root, entry), "variables": rows}


def _check_operator(var: Doc, bounds: Bounds) -> None:
    """422 unless lo < hi and the range lies inside the engineering range."""
    problems: list[str] = []
    if bounds.lo >= bounds.hi:
        problems.append("operator.lo must be below operator.hi")
    eng = var.get("limits", {}).get("eng")
    if eng and not (eng["lo"] <= bounds.lo and bounds.hi <= eng["hi"]):
        problems.append(
            f"operator range must lie inside engineering range {eng['lo']}..{eng['hi']}"
        )
    if problems:
        raise HTTPException(status_code=422, detail=problems)


def _find_variable(entry: Doc, variable_id: str) -> Doc:
    """One variable of a controller entry, or HTTP 404."""
    for var in entry["variables"]:
        if var["id"] == variable_id:
            found: Doc = var
            return found
    raise HTTPException(status_code=404, detail=f"no variable {variable_id!r}")


def _override_of(body: VariableBody) -> Doc:
    """The stored override for a request body."""
    override: Doc = {"enabled": body.enabled}
    if body.operator is not None:
        override["operator"] = body.operator.model_dump()
    return override


class _Endpoints:
    """Handlers of the controller routes."""

    def __init__(self, root: Path, clock: Callable[[], float]) -> None:
        """Bind the data root and the audit clock."""
        self._root, self._clock = root, clock

    def list(self) -> Doc:
        """All controllers of the site with their last known state."""
        return {"controllers": [_summary(self._root, e) for e in _site_controllers(self._root)]}

    def detail(self, controller_id: str) -> Doc:
        """One controller with its variables; 404 when the site has no such controller."""
        return _detail(self._root, _find(self._root, controller_id))

    def command(
        self,
        controller_id: str,
        body: CommandBody,
        actor: Annotated[ActorContext, Depends(actor_of)],
    ) -> Doc:
        """Queue an operator command. Switching off needs ctl.operate only, never a step-up."""
        _find(self._root, controller_id)
        actor.require("ctl.operate")
        self._audit("controller_command", actor, controller=controller_id, command=body.command)
        try:
            enqueue_command(self._root, controller_id, body.command)
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=503, detail="command_not_queued") from error
        return {"accepted": True, "controller": controller_id, "command": body.command}

    def variable(
        self,
        controller_id: str,
        variable_id: str,
        body: VariableBody,
        actor: Annotated[ActorContext, Depends(actor_of)],
    ) -> Doc:
        """Set the operator override of one variable (on/off and operator limits)."""
        entry = _find(self._root, controller_id)
        var = _find_variable(entry, variable_id)
        actor.require("ctl.operate")
        if body.operator is not None:
            _check_operator(var, body.operator)
        override = _override_of(body)
        text = json.dumps(override, sort_keys=True)
        self._audit(
            "controller_override",
            actor,
            controller=controller_id,
            variable=variable_id,
            override=text,
        )
        overrides = {**read_overrides(self._root, controller_id), variable_id: override}
        write_overrides(self._root, controller_id, overrides)
        return _detail(self._root, entry)

    def _audit(self, event: str, actor: ActorContext, **fields: str) -> None:
        """Append to the API auth audit; no audit line, no action (503)."""
        audit = AuthAudit(auth_dir(self._root) / AUDIT_FILE, self._clock)
        try:
            audit.append(event, actor=actor.actor, source_ip=actor.source_ip, **fields)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail="audit_unavailable") from error


def build_controller_router(root: Path, clock: Callable[[], float] = time.time) -> APIRouter:
    """Create the router of the operator console: list, detail, command, variable override."""
    endpoints = _Endpoints(root, clock)
    router = APIRouter()
    router.add_api_route("/controllers", endpoints.list, methods=["GET"])
    router.add_api_route("/controllers/{controller_id}", endpoints.detail, methods=["GET"])
    router.add_api_route(
        "/controllers/{controller_id}/command", endpoints.command, methods=["POST"]
    )
    router.add_api_route(
        "/controllers/{controller_id}/variables/{variable_id}",
        endpoints.variable,
        methods=["PUT"],
    )
    return router

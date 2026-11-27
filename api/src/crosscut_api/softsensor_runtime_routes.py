"""Online soft sensor routes: runtime view, stored validation and the audited mode change.

Backup and primary need ``require_deployable`` on the stored validation; a refusal answers HTTP
409 with the exact gate text. Every attempt (done or refused) is audited before it takes effect.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from crosscut_runtime.jobs.softsensor import state_path
from crosscut_runtime.store import write_json_atomic
from crosscut_softsensor.config import SoftSensorConfig, SoftSensorConfigError, load_config
from crosscut_softsensor.deployment import FOLDER, gate_for, gate_view, read_deployment
from crosscut_softsensor.deployment_gate import (
    DeploymentRefused,
    ValidationResults,
    require_deployable,
)
from crosscut_softsensor.online import STAMP_MEANINGS
from crosscut_softsensor.presets import load_presets
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParam
from pydantic import BaseModel

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir

Actor = Annotated[ActorContext, Depends(actor_of)]
Sid = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Document = dict[str, Any]


class ModeRequest(BaseModel):
    """Requested mode and, optionally, the lab stamp contract (meaning and composite window)."""

    mode: Literal["off", "shadow", "backup", "primary"]
    stamp_meaning: str | None = None
    stamp_window_s: float | None = None


class ValidationRequest(BaseModel):
    """Preset key and validation results to store for the deployment gate."""

    preset: str
    rmse_model: float
    rmse_baseline: float
    scored_coverage: float
    n_samples: int
    baseline: str
    same_information_cutoff: bool = True


class SoftSensorRuntimeEndpoints:
    """Handlers bound to one data root."""

    def __init__(self, root: Path, clock: Callable[[], float] = time.time) -> None:
        """Bind the data root and clock."""
        self.root, self.clock = Path(root), clock

    def _config(self, sid: str) -> SoftSensorConfig:
        """The sensor configuration (404 unknown, 422 invalid)."""
        path = self.root / FOLDER / f"{sid}.json"
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"unknown soft sensor: {sid}")
        try:
            return load_config(json.loads(path.read_text(encoding="utf-8")))
        except (SoftSensorConfigError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def runtime(self, sid: Sid, actor: Actor) -> Document:
        """Mode, latest output, last lab residual, failover events and the gate result."""
        actor.require("data.view")
        self._config(sid)
        return self._view(sid)

    def _view(self, sid: str) -> Document:
        """Assemble the runtime view from the deployment, state and gate."""
        deployment = read_deployment(self.root, sid)
        try:
            state = json.loads(state_path(self.root, sid).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        return {"sensor_id": sid, "mode": deployment["mode"],
                "changed_by": deployment["changed_by"], "changed_utc": deployment["changed_utc"],
                "output": state.get("output"), "last_lab": state.get("last_lab"),
                "events": state.get("events", []), "gate": gate_view(self.root, sid)}

    def put_validation(self, sid: Sid, body: ValidationRequest, actor: Actor) -> Document:
        """Store validation results (audited); the gate is evaluated on them at mode change."""
        actor.require("config.edit")
        self._config(sid)
        fields = body.model_dump()
        preset = fields.pop("preset")
        if preset not in load_presets():
            raise HTTPException(status_code=422, detail=f"unknown preset: {preset}")
        self._audit("softsensor_validation", actor, {"sensor": sid, "preset": preset})
        write_json_atomic(self.root / FOLDER / f"{sid}.validation.json",
                          {"preset": preset, "results": fields})
        return self._view(sid)

    def put_mode(self, sid: Sid, body: ModeRequest, actor: Actor) -> Document:
        """Change the mode; backup and primary require a passing gate (409 with the exact text)."""
        actor.require("config.edit")
        config = self._config(sid)
        fields = {"sensor": sid, "mode": body.mode}
        if body.mode == "backup" and config.backup is None:
            raise HTTPException(status_code=422, detail="backup mode needs an enabled backup block")
        if body.mode in ("backup", "primary"):
            self._require_gate(sid, actor, fields)
        stamp = self._stamp(sid, body)
        self._audit("softsensor_mode", actor, fields)
        now = datetime.fromtimestamp(self.clock(), UTC).isoformat()
        write_json_atomic(self.root / FOLDER / f"{sid}.deployment.json",
                          {"mode": body.mode, "changed_by": actor.actor, "changed_utc": now,
                           "lab_stamp": stamp})
        return self._view(sid)

    def _require_gate(self, sid: str, actor: ActorContext, fields: dict[str, str]) -> None:
        """Pass the gate or audit the refusal and answer 409 with the exact refusal text."""
        try:
            decision, preset = gate_for(self.root, sid)
            if decision is None or preset is None:
                raise DeploymentRefused(gate_view(self.root, sid)["message"])
            require_deployable(preset, ValidationResults(**self._results(sid)))
        except DeploymentRefused as error:
            self._audit("softsensor_mode_refused", actor, fields)
            raise HTTPException(status_code=409, detail=str(error)) from error

    def _results(self, sid: str) -> dict[str, Any]:
        """The stored validation results as keyword arguments."""
        path = self.root / FOLDER / f"{sid}.validation.json"
        results: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))["results"]
        return results

    def _stamp(self, sid: str, body: ModeRequest) -> dict[str, Any]:
        """The lab stamp contract: the request's, else the stored one."""
        stamp = dict(read_deployment(self.root, sid)["lab_stamp"])
        if body.stamp_meaning is not None:
            if body.stamp_meaning not in STAMP_MEANINGS:
                raise HTTPException(status_code=422, detail="stamp_meaning: invalid")
            stamp["meaning"] = body.stamp_meaning
        if body.stamp_window_s is not None:
            stamp["window_s"] = max(0.0, body.stamp_window_s)
        return stamp

    def _audit(self, event: str, actor: ActorContext, fields: dict[str, str]) -> None:
        """Append an audit record before the action takes effect."""
        audit = AuthAudit(auth_dir(self.root) / AUDIT_FILE, self.clock)
        try:
            audit.append(event, actor=actor.actor, source_ip=actor.source_ip, **fields)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail="audit_unavailable") from error


def build_softsensor_runtime_router(
    root: Path, clock: Callable[[], float] = time.time
) -> APIRouter:
    """Routes: GET runtime, PUT mode, PUT validation."""
    endpoints = SoftSensorRuntimeEndpoints(root, clock)
    router = APIRouter()
    router.add_api_route("/softsensor/{sid}/runtime", endpoints.runtime, methods=["GET"])
    router.add_api_route("/softsensor/{sid}/mode", endpoints.put_mode, methods=["PUT"])
    router.add_api_route("/softsensor/{sid}/validation", endpoints.put_validation, methods=["PUT"])
    return router

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
from crosscut_softsensor.comparison import ComparisonData, ComparisonOptions, compare_preset
from crosscut_softsensor.config import SoftSensorConfig, SoftSensorConfigError, load_config
from crosscut_softsensor.deployment import FOLDER, gate_for, gate_view, read_deployment
from crosscut_softsensor.deployment_gate import (
    REFUSAL_TEXT,
    DeploymentRefused,
    ValidationResults,
    require_deployable,
)
from crosscut_softsensor.online import STAMP_MEANINGS
from crosscut_softsensor.presets import load_presets
from crosscut_softsensor.reference import build_model_features, lag_gap
from crosscut_softsensor.validation_store import build_record, file_sha256
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParam
from pydantic import BaseModel

from crosscut_api.anomaly_routes import WindowRequest
from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir
from crosscut_api.softsensor_routes import QualityLoader, SecondsLoader, _SoftSensorEndpoints
from crosscut_api.target_alignment import aligned_labs

Actor = Annotated[ActorContext, Depends(actor_of)]
Sid = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Document = dict[str, Any]


class ModeRequest(BaseModel):
    """Requested mode and, optionally, the lab stamp contract (meaning and composite window)."""

    mode: Literal["off", "shadow", "backup", "primary"]
    stamp_meaning: str | None = None
    stamp_window_s: float | None = None


class ValidateRequest(WindowRequest):
    """Preset to validate against (and the structure, default the deployed PLS) on a window."""

    preset: str = "lab_quality_inference"
    structure: str = "pls"


class SoftSensorRuntimeEndpoints:
    """Handlers bound to one data root."""

    def __init__(
        self, root: Path, clock: Callable[[], float], load_seconds: SecondsLoader,
        load_quality: QualityLoader,
    ) -> None:
        """Bind the data root, clock and the dataset loaders."""
        self.root, self.clock = Path(root), clock
        self.load_seconds, self.load_quality = load_seconds, load_quality

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

    def validate(
        self, dataset_id: str, sid: Sid, body: ValidateRequest, actor: Actor
    ) -> Document:
        """Run the comparison table on a stored dataset window and store the result (audited)."""
        actor.require("analysis.run")
        config = self._config(sid)
        preset = load_presets().get(body.preset)
        if preset is None or body.structure not in preset["model"]["allowed_now"]:
            raise HTTPException(status_code=422, detail="unknown preset or structure")
        model_file = self.root / FOLDER / f"{sid}.model.json"
        if not model_file.is_file():
            raise HTTPException(status_code=404, detail=f"model not fitted: {sid}")
        table, window = self._compare(dataset_id, sid, config, preset, body)
        origin = {"dataset_id": dataset_id, "window": window,
                  "model_file_sha256": file_sha256(model_file)}
        record = build_record(preset, body.structure, table, origin)
        self._audit("softsensor_validate", actor, {"sensor": sid, "dataset": dataset_id,
                                                   "validation_hash": record["hash"]})
        write_json_atomic(self.root / FOLDER / f"{sid}.validation.json", record)
        return self._view(sid)

    def _compare(
        self, dataset_id: str, sid: str, config: SoftSensorConfig, preset: dict[str, Any],
        body: ValidateRequest,
    ) -> tuple[Any, dict[str, float]]:
        """Bin the dataset window, build causal features and run the blocked comparison."""
        source = _SoftSensorEndpoints(self.root, self.load_seconds, self.load_quality)
        t_s, columns = source._binned(dataset_id, config, body)  # noqa: SLF001
        features = build_model_features(columns, config)
        labs = aligned_labs(self.root, source._lab_rows(sid), config)  # noqa: SLF001
        data = ComparisonData(features.x, t_s, labs, tuple(features.names))
        gap = lag_gap(config)
        options = ComparisonOptions(config.cv_blocks, gap, gap)
        try:
            table = compare_preset(preset, data, options)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return table, {"start_s": float(t_s[0]), "end_s": float(t_s[-1])}

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
            if decision is None or preset is None or not decision.deploy:
                raise DeploymentRefused(REFUSAL_TEXT)
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
    root: Path, load_seconds: SecondsLoader, load_quality: QualityLoader,
    clock: Callable[[], float] = time.time,
) -> APIRouter:
    """Routes: GET runtime, PUT mode, POST validate (server-side validation)."""
    endpoints = SoftSensorRuntimeEndpoints(root, clock, load_seconds, load_quality)
    router = APIRouter()
    router.add_api_route("/softsensor/{sid}/runtime", endpoints.runtime, methods=["GET"])
    router.add_api_route("/softsensor/{sid}/mode", endpoints.put_mode, methods=["PUT"])
    router.add_api_route("/datasets/{dataset_id}/softsensor/{sid}/validate", endpoints.validate,
                         methods=["POST"])
    return router

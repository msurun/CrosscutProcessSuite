"""Read verified MPC models and save audited edits as immutable artifact versions.

The editor preserves identification verdicts and records lineage in the hashed payload.
"""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any
from uuid import uuid4

import numpy as np
from crosscut_artifacts.manifest import ArtifactError, read_manifest
from crosscut_mpc.artifact import PAYLOAD, load_ident_model, save_ident_model
from crosscut_mpc.identification import IdentifiedModel
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParameter
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir
from crosscut_api.mpc_simulation_routes import artifact_directory

MAX_PAIRS = 64  # Eight CV rows by eight MV/DV columns, as in the simulator.
ModelId = Annotated[str, PathParameter(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ActorDep = Annotated[ActorContext, Depends(actor_of)]
Document = dict[str, Any]


class PairEdit(BaseModel):
    """One FOPDT path in CV/input order; times are seconds and gain is CV/input units."""

    model_config = ConfigDict(extra="forbid")
    input_name: str = Field(min_length=1, max_length=128)
    cv_name: str = Field(min_length=1, max_length=128)
    gain: Finite
    time_constant_s: Finite = Field(gt=0)
    dead_time_s: Finite = Field(ge=0)
    enabled: bool = Field(strict=True)


class ModelEdit(BaseModel):
    """A complete edited grid, pinned to its parent and attributed by a mandatory reason."""

    model_config = ConfigDict(extra="forbid")
    parent_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    author: Nonblank
    reason: Nonblank
    pairs: list[PairEdit] = Field(min_length=1, max_length=MAX_PAIRS)


def checked_model_directory(root: Path, model_id: str) -> Path:
    """Resolve an existing artifact without following the store outside the data root."""
    directory = artifact_directory(root, model_id)
    if not directory.resolve().is_relative_to(root.resolve()):
        raise HTTPException(status_code=422, detail="artifact_outside_data_root")
    return directory


def pair_document(model: IdentifiedModel, row: int, column: int) -> Document:
    """Return one parameter set and its unchanged identification-quality verdict."""
    quality = model.quality[row][column]
    return {"input_name": model.input_names[column], "cv_name": model.cv_names[row],
            "gain": float(model.gains[row, column]),
            "time_constant_s": float(model.time_constants_s[row, column]),
            "dead_time_s": float(model.dead_times_s[row, column]),
            "enabled": model.enabled is None or model.enabled[row][column],
            "quality": {"passed": quality.passed, "reasons": list(quality.reasons),
                        "free_run_r2": quality.free_run_r2 if np.isfinite(quality.free_run_r2)
                        else None, "excitation_events": quality.excitation_events}}


def model_document(directory: Path, model_id: str) -> Document:
    """Read verified payloads and serialize the grid with its hashed edit attribution."""
    manifest = read_manifest(directory, verify=True)
    sha256 = next(entry["sha256"] for entry in manifest["payload"] if entry["path"] == PAYLOAD)
    model = load_ident_model(directory, sha256)
    metadata = model.edit_metadata or {}
    pairs = [pair_document(model, row, column) for row in range(len(model.cv_names))
             for column in range(len(model.input_names))]
    return {"model_id": model_id, "sha256": sha256, "input_names": list(model.input_names),
            "cv_names": list(model.cv_names), "cycle_s": model.cycle_s, "pairs": pairs,
            **{key: metadata.get(key) for key in
               ("parent_model_id", "parent_sha256", "author", "reason")}}


def edited_model(parent: IdentifiedModel, body: ModelEdit, metadata: Document) -> IdentifiedModel:
    """Build copied CV-by-input matrices, refusing missing, unknown or duplicate paths."""
    expected = {(cv, name) for cv in parent.cv_names for name in parent.input_names}
    indexed = {(pair.cv_name, pair.input_name): pair for pair in body.pairs}
    if len(indexed) != len(body.pairs) or set(indexed) != expected:
        raise ValueError("Provide every CV/input pair exactly once")
    grid = [[indexed[cv, name] for name in parent.input_names] for cv in parent.cv_names]
    time_constants = np.array([[pair.time_constant_s for pair in row] for row in grid])
    # Matrices keep the identification shape (CV,input); disabled paths retain their fit.
    return replace(parent, gains=np.array([[pair.gain for pair in row] for row in grid]),
                   time_constants_s=time_constants,
                   dead_times_s=np.array([[pair.dead_time_s for pair in row] for row in grid]),
                   enabled=tuple(tuple(pair.enabled for pair in row) for row in grid),
                   edit_metadata=metadata)


def append_edit_audit(root: Path, actor: ActorContext, document: Document) -> None:
    """Fail closed if the standard API audit cannot durably record a version's identity."""
    fields = {key: document[key] for key in ("model_id", "sha256", "parent_model_id",
                                            "parent_sha256", "author", "reason")}
    try:
        AuthAudit(auth_dir(root) / AUDIT_FILE).append(
            "mpc_model_version_created", actor=actor.actor, source_ip=actor.source_ip, **fields)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=503, detail="audit_unavailable") from error


def publish_version(root: Path, model: IdentifiedModel, actor: ActorContext) -> Document:
    """Stage a complete bundle and audit its hash before exposing a fresh model id."""
    store = root / "_mpc" / "models"
    model_id = uuid4().hex
    with TemporaryDirectory(prefix=".model-edit-", dir=store) as temporary:
        staging = Path(temporary) / "artifact"
        metadata = model.edit_metadata or {}
        save_ident_model(staging, model, [str(metadata["parent_sha256"])])
        document = model_document(staging, model_id)
        append_edit_audit(root, actor, document)
        staging.rename(store / model_id)
    return document


def save_version(root: Path, model_id: str, body: ModelEdit, actor: ActorContext) -> Document:
    """Pin a verified parent, preserve its verdicts and publish an attributed child artifact."""
    directory = checked_model_directory(root, model_id)
    parent = load_ident_model(directory, body.parent_sha256)
    metadata = {"parent_model_id": model_id, "parent_sha256": body.parent_sha256,
                "author": body.author, "reason": body.reason, "actor": actor.actor}
    return publish_version(root, edited_model(parent, body, metadata), actor)


def build_model_router(root: Path) -> APIRouter:
    """Expose verified reads to MPC viewers and immutable edits to config editors."""
    router = APIRouter()

    @router.get("/mpc/models/{model_id}")
    def read(model_id: ModelId, actor: ActorDep) -> Document:
        """Read the matrix and quality gates without changing an artifact."""
        actor.require("gw.view")
        try:
            return model_document(checked_model_directory(root, model_id), model_id)
        except (ArtifactError, ValueError, KeyError, TypeError, OSError, StopIteration) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/mpc/models/{model_id}/versions", status_code=201)
    def create(model_id: ModelId, body: ModelEdit, actor: ActorDep) -> Document:
        """Save an edited copy while retaining the original and its integrity pin."""
        actor.require("config.edit")
        try:
            return save_version(root, model_id, body, actor)
        except (ArtifactError, ValueError, KeyError, TypeError, OSError, StopIteration) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return router

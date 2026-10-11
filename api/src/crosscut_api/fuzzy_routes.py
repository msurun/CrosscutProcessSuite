"""HTTP routes of the fuzzy module: list, load and save rule bases, what-if inference, replay.

Rule bases are configuration kept in ``<data root>/_fuzzy``; nothing here writes to a plant.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import numpy as np
from crosscut_fuzzy.library import list_systems, load_document, save_document
from crosscut_fuzzy.model import FuzzyModelError, FuzzySystem, system_from_dict
from crosscut_fuzzy.payload import infer_payload, replay_payload
from crosscut_fuzzy.versions import diff_documents, list_versions, load_version, save_version
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

USER_DIR_NAME = "_fuzzy"
DEFAULT_REPLAY_POINTS = 1500
WideTable = tuple[np.ndarray, dict[str, np.ndarray]]


class InferRequest(BaseModel):
    """A rule base (possibly unsaved, as edited on screen) and one set of input values."""

    document: dict[str, Any]
    inputs: dict[str, float]


class DiffRequest(BaseModel):
    """Two rule base documents to compare."""

    old: dict[str, Any]
    new: dict[str, Any]


class ReplayRequest(BaseModel):
    """A rule base and the part of a dataset to replay it on (seconds from the first sample)."""

    document: dict[str, Any]
    start_s: float | None = None
    end_s: float | None = None
    max_points: Annotated[int, Field(ge=2, le=5000)] = DEFAULT_REPLAY_POINTS


def build_fuzzy_router(root: Path, load_wide: Callable[[str], WideTable]) -> APIRouter:
    """Routes for the rule bases stored under ``root`` and for replay on ``root``'s datasets."""
    router = APIRouter()
    user_dir = root / USER_DIR_NAME

    @router.get("/fuzzy")
    def get_systems() -> list[dict[str, str]]:
        """Bundled examples and the user's saved systems."""
        return list_systems(user_dir)

    @router.get("/fuzzy/{system_id}")
    def get_system(system_id: str) -> dict[str, Any]:
        """One rule base document."""
        try:
            return load_document(system_id, user_dir)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=f"unknown system: {system_id}") from error
        except FuzzyModelError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.put("/fuzzy/{system_id}")
    def put_system(system_id: str, document: dict[str, Any]) -> dict[str, Any]:
        """Validate and save a rule base as the user's system (configuration only)."""
        try:
            save_document(system_id, document, user_dir)
            save_version(system_id, document, user_dir, now=datetime.now(UTC))
        except FuzzyModelError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return document

    @router.get("/fuzzy/{system_id}/versions")
    def get_versions(system_id: str) -> list[str]:
        """Version ids of the saved snapshots, newest first."""
        try:
            return list_versions(system_id, user_dir)
        except FuzzyModelError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/fuzzy/{system_id}/versions/{version_id}")
    def get_version(system_id: str, version_id: str) -> dict[str, Any]:
        """One saved snapshot of a rule base."""
        try:
            return load_version(system_id, version_id, user_dir)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="unknown version") from error
        except FuzzyModelError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/fuzzy/diff")
    def post_diff(request: DiffRequest) -> list[dict[str, Any]]:
        """Structural differences between two rule base documents (codes, not prose)."""
        return diff_documents(request.old, request.new)

    @router.post("/fuzzy/infer")
    def post_infer(request: InferRequest) -> dict[str, Any]:
        """What-if: evaluate the given rule base on one set of input values."""
        system = _system_or_422(request.document)
        try:
            return infer_payload(system, request.inputs)
        except FuzzyModelError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/datasets/{dataset_id}/fuzzy/replay")
    def post_replay(dataset_id: str, request: ReplayRequest) -> dict[str, Any]:
        """Replay the given rule base over recorded data (what it would have said)."""
        system = _system_or_422(request.document)
        t_ns, columns = _window(load_wide(dataset_id), request)
        try:
            return replay_payload(system, t_ns, columns, request.max_points)
        except FuzzyModelError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return router


def _system_or_422(document: dict[str, Any]) -> FuzzySystem:
    """The system built from the document, or HTTP 422 with the reason."""
    try:
        return system_from_dict(document)
    except FuzzyModelError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _window(table: WideTable, request: ReplayRequest) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """The timestamps and columns inside the requested window."""
    t_ns, columns = table
    seconds = (t_ns - t_ns[0]) / 1e9
    keep = np.ones(len(t_ns), dtype=bool)
    if request.start_s is not None:
        keep &= seconds >= request.start_s
    if request.end_s is not None:
        keep &= seconds <= request.end_s
    if not keep.any():
        raise HTTPException(status_code=422, detail="no samples in the requested window")
    return t_ns[keep], {tag: values[keep] for tag, values in columns.items()}

"""Learn normal equipment operation from catalogue-owned dataset signals.

Models remain local advisory files; UTC exclusions use the record's actual time origin.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import numpy as np
from crosscut_anomaly.equipment_learning import equipment_variables, learn_equipment
from crosscut_connectors.site import SiteError, load_site
from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from crosscut_api.anomaly_routes import _AnomalyEndpoints

NS_PER_SECOND = 1_000_000_000  # Nanoseconds per elapsed second.
EQUIPMENT_PATTERN = r"^[A-Za-z0-9_.:-]+$"
EquipmentId = Annotated[str, PathParam(pattern=EQUIPMENT_PATTERN)]
WideLoader = Callable[[str], tuple[np.ndarray, dict[str, Any]]]
QualityLoader = Callable[[str], dict[str, np.ndarray]]


class LearnRequest(BaseModel):
    """UTC spans the engineer wants excluded from normal-operation learning."""

    exclusions: list[tuple[datetime, datetime]] = Field(default_factory=list)


def _relative_exclusions(request: LearnRequest, origin_s: float) -> list[list[float]]:
    """Convert aware UTC intervals to elapsed seconds, rejecting reversed spans."""
    windows = []
    for start, end in request.exclusions:
        if start.tzinfo is None or end.tzinfo is None:
            raise HTTPException(status_code=422, detail="exclusions need timezone-aware dates")
        if start > end:
            raise HTTPException(status_code=422, detail="exclusion start must not exceed end")
        windows.append([start.timestamp() - origin_s, end.timestamp() - origin_s])
    return windows


def _catalogue(root: Path) -> dict[str, Any]:
    """Read the catalogue, reporting a missing or malformed site as HTTP 422."""
    try:
        return load_site(root)
    except SiteError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _equipment(site: dict, equipment_id: str) -> dict:
    """Resolve a safe equipment id before allowing any model path to be built."""
    if not re.fullmatch(EQUIPMENT_PATTERN, equipment_id) or equipment_id in {".", ".."}:
        raise HTTPException(status_code=422, detail="equipment id is not a safe identifier")
    for entry in site.get("equipment", []):
        if entry["id"] == equipment_id:
            return entry
    raise HTTPException(status_code=404, detail=f"unknown equipment: {equipment_id}")


class EquipmentEndpoints:
    """Bind learning and summaries to one data root and its aligned dataset loaders."""

    def __init__(self, root: Path, load_wide: WideLoader, load_quality: QualityLoader) -> None:
        """Store the local root and aligned value and quality readers."""
        self.root = root
        self.load_wide = load_wide
        self.load_quality = load_quality

    def learn(self, dataset_id: str, equipment_id: EquipmentId, request: LearnRequest) -> dict:
        """Fit the selected equipment and atomically save its JSON model."""
        site = _catalogue(self.root)
        equipment = _equipment(site, equipment_id)
        timestamps, data = self.load_wide(dataset_id)
        if not len(timestamps):
            raise HTTPException(status_code=422, detail="dataset has no samples to learn")
        origin_s = float(timestamps[0]) / NS_PER_SECOND
        times = (timestamps - timestamps[0]) / NS_PER_SECOND
        exclusions = _relative_exclusions(request, origin_s)
        data = _quality_filtered(data, self.load_quality(dataset_id))
        try:
            model = learn_equipment(times, data, equipment, site.get("loops", []), exclusions)
        except (ValueError, KeyError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        document = {**model.to_dict(), "dataset_id": dataset_id}
        _AnomalyEndpoints._write(self._path(equipment_id), document)
        return document

    def models(self) -> list[dict]:
        """Return learned or absent status for every equipment entry in catalogue order."""
        site = _catalogue(self.root)
        return [self._summary(site, entry["id"]) for entry in site.get("equipment", [])
                if entry.get("level", "equipment") == "equipment"]

    def _summary(self, site: dict, equipment_id: str) -> dict:
        """Read one stored summary without inventing a learned state for absent files."""
        _equipment(site, equipment_id)
        path = self._path(equipment_id)
        document = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return {"equipment_id": equipment_id, "status": document.get("status", "none"),
                "windows": document.get("windows", []),
                "variables": document.get("variables", equipment_variables(site, equipment_id))}

    def _path(self, equipment_id: str) -> Path:
        """Return the local model path for an already validated catalogue identifier."""
        return self.root / "_anomaly" / "equipment" / f"{equipment_id}.model.json"


def _quality_filtered(data: dict, quality: dict) -> dict[str, np.ndarray]:
    """Mark bad or uncertain historian values missing before any training rule runs."""
    # Aligned float columns retain engineering units; historian quality zero means good.
    return {tag: np.where(quality[tag] == 0, values, np.nan) for tag, values in data.items()}


def build_equipment_anomaly_router(
    root: Path, load_wide: WideLoader, load_quality: QualityLoader,
) -> APIRouter:
    """Build the two catalogue-equipment learning routes for one local data root."""
    router = APIRouter()
    endpoints = EquipmentEndpoints(root, load_wide, load_quality)
    router.add_api_route("/datasets/{dataset_id}/equipment/{equipment_id}/learn",
                         endpoints.learn, methods=["POST"])
    router.add_api_route("/equipment/models", endpoints.models, methods=["GET"])
    return router

"""HTTP routes for catalogue role suggestions and mapping persistence (Phase 1, #37).

Bridges the site catalogue with active analysis modules by inferring tag roles, validating
mapping documents, and syncing signals to control loops, anomaly detection, and soft sensors.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from crosscut_connectors.role_mapping import loops_from_signals, suggest_roles
from crosscut_connectors.site import load_site, save_site, site_path, validate_site
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

ANOMALY_DIR = "_anomaly"
SOFTSENSOR_DIR = "_softsensor"
DEFAULT_CONFIG_ID = "default"
SCHEMA_VERSION = "1.0.0"


class SuggestRequest(BaseModel):
    """Tags and optional site naming block to analyze."""

    tags: list[str] = Field(default_factory=list)
    naming: dict[str, Any] = Field(default_factory=dict)
    dataset_id: str | None = None


class MappingRequest(BaseModel):
    """Mapped signals and complete loop definitions to persist."""

    signals: list[dict[str, Any]] = Field(default_factory=list)
    loops: list[dict[str, Any]] = Field(default_factory=list)


class _CatalogueEndpoints:
    """HTTP endpoints bound to the project data root."""

    def __init__(self, root: Path, load_tags: Any | None = None) -> None:
        self.root = root
        self.load_tags = load_tags

    def post_suggest(self, request: SuggestRequest) -> dict[str, Any]:
        """Infer canonical roles and construct loop candidates for tags."""
        tags = self._resolve_tags(request)
        signals = suggest_roles(tags, naming=request.naming)
        loops = loops_from_signals(signals)
        return {"signals": signals, "loops": loops}

    def _resolve_tags(self, request: SuggestRequest) -> list[str]:
        """Return explicit tags from the request, or read them from a dataset."""
        if request.tags:
            return request.tags
        if request.dataset_id and self.load_tags:
            ds_dir = self.root / request.dataset_id
            return [t["id"] for t in self.load_tags(ds_dir)]
        return []

    def get_mapping(self) -> dict[str, Any]:
        """Return currently saved signals and loops from the site catalogue."""
        if not site_path(self.root).exists():
            return {"signals": [], "loops": []}
        doc = load_site(self.root)
        return {
            "signals": doc.get("signals", []),
            "loops": doc.get("loops", []),
        }

    def put_mapping(self, request: Annotated[MappingRequest, Body()]) -> dict[str, Any]:
        """Validate, persist mapping to site.json, and sync default module configs."""
        doc = self._get_or_create_site_doc()
        doc["signals"] = request.signals
        doc["loops"] = request.loops
        self._ensure_tags_declared(doc, request.signals, request.loops)

        problems = validate_site(doc)
        if problems:
            raise HTTPException(status_code=422, detail=problems)

        save_site(self.root, doc)
        _sync_anomaly_config(self.root, request.signals)
        _sync_softsensor_config(self.root, request.signals)
        return {"status": "ok", "signals": doc["signals"], "loops": doc["loops"]}

    def _get_or_create_site_doc(self) -> dict[str, Any]:
        """Load the existing site document, or initialise a minimal valid skeleton."""
        if site_path(self.root).exists():
            return load_site(self.root)
        return {
            "schema_version": 1,
            "site": {"name": "Site"},
            "tags": [],
            "signals": [],
            "loops": [],
        }

    def _ensure_tags_declared(
        self,
        doc: dict[str, Any],
        signals: list[dict[str, Any]],
        loops: list[dict[str, Any]],
    ) -> None:
        """Register any newly mapped tags in the site tags list if not present."""
        existing = {t["id"] for t in doc.get("tags", [])}
        for sig in signals:
            tag_id = sig.get("tag")
            if tag_id and tag_id not in existing:
                doc["tags"].append({"id": tag_id})
                existing.add(tag_id)
        for loop in loops:
            for slot in ("pv", "sp", "out", "mode"):
                tag_id = loop.get(slot)
                if tag_id and tag_id not in existing:
                    doc["tags"].append({"id": tag_id})
                    existing.add(tag_id)


def _sync_anomaly_config(root: Path, signals: list[dict[str, Any]]) -> None:
    """Create or update default anomaly detector config from input signals."""
    input_tags = [
        sig["tag"]
        for sig in signals
        if sig.get("role") == "input" and sig.get("module") in (None, "anomaly")
    ]
    if len(input_tags) < 3:
        return
    folder = root / ANOMALY_DIR
    folder.mkdir(parents=True, exist_ok=True)
    config_path = folder / f"{DEFAULT_CONFIG_ID}.json"
    if not config_path.exists():
        cfg = {
            "schema_version": SCHEMA_VERSION,
            "id": DEFAULT_CONFIG_ID,
            "description": "Default anomaly detector from catalogue mapping",
            "tags": input_tags,
            "mode": "advisory",
        }
        config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _sync_softsensor_config(root: Path, signals: list[dict[str, Any]]) -> None:
    """Create or update default soft sensor config from target and input signals."""
    input_tags = [
        sig["tag"]
        for sig in signals
        if sig.get("role") == "input" and sig.get("module") in (None, "softsensor")
    ]
    target_tag = next(
        (sig["tag"] for sig in signals if sig.get("role") == "target"),
        None,
    )
    if not target_tag or not input_tags:
        return
    folder = root / SOFTSENSOR_DIR
    folder.mkdir(parents=True, exist_ok=True)
    config_path = folder / f"{DEFAULT_CONFIG_ID}.json"
    if not config_path.exists():
        cfg = {
            "schema_version": SCHEMA_VERSION,
            "id": DEFAULT_CONFIG_ID,
            "description": "Default soft sensor from catalogue mapping",
            "target_tag": target_tag,
            "input_tags": input_tags,
            "mode": "advisory",
        }
        config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def build_catalogue_router(root: Path, load_tags: Any | None = None) -> APIRouter:
    """Construct FastAPI router for /catalogue routes."""
    endpoints = _CatalogueEndpoints(root, load_tags)
    router = APIRouter()
    router.add_api_route("/catalogue/suggest", endpoints.post_suggest, methods=["POST"])
    router.add_api_route("/catalogue/mapping", endpoints.get_mapping, methods=["GET"])
    router.add_api_route("/catalogue/mapping", endpoints.put_mapping, methods=["PUT"])
    return router


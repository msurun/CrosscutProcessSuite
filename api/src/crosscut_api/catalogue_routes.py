"""HTTP routes for catalogue role suggestions and mapping persistence (Phase 1, #37).

Bridges the site catalogue with active analysis modules by inferring tag roles, validating
mapping documents, and syncing signals to control loops, anomaly detection, and soft sensors.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any

from crosscut_connectors.role_mapping import loops_from_signals, suggest_roles
from crosscut_connectors.site import validate_site
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.site_version_routes import store_draft, working_site

ANOMALY_DIR = "_anomaly"
SOFTSENSOR_DIR = "_softsensor"
DEFAULT_CONFIG_ID = "default"
SCHEMA_VERSION = "1.0.0"
GENERATED_SUFFIX = ".generated.sha256"


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
        doc = working_site(self.root)
        if doc is None:
            return {"signals": [], "loops": []}
        return {
            "signals": doc.get("signals", []),
            "loops": doc.get("loops", []),
        }

    def put_mapping(
        self,
        request: Annotated[MappingRequest, Body()],
        actor: Annotated[ActorContext, Depends(actor_of)],
    ) -> dict[str, Any]:
        """Validate, store the mapping in the site draft, and sync default module configs."""
        doc = self._get_or_create_site_doc()
        doc["signals"] = request.signals
        doc["loops"] = request.loops
        self._ensure_tags_declared(doc, request.signals, request.loops)

        problems = validate_site(doc)
        if problems:
            raise HTTPException(status_code=422, detail=problems)

        store_draft(self.root, doc, actor.actor)
        module_configs = {
            "anomaly": _sync_anomaly_config(self.root, request.signals),
            "softsensor": _sync_softsensor_config(self.root, request.signals),
        }
        stale = sorted(k for k, v in module_configs.items() if v and v["status"] == "conflict")
        return {
            "status": "ok",
            "signals": doc["signals"],
            "loops": doc["loops"],
            "module_configs": module_configs,
            "stale_configs": stale,
        }

    def _get_or_create_site_doc(self) -> dict[str, Any]:
        """Load the existing site document, or initialise a minimal valid skeleton."""
        working = working_site(self.root)
        if working is not None:
            return working
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


def _config_text(config: dict[str, Any]) -> str:
    """The exact text a generated module config is stored as."""
    return json.dumps(config, indent=2)


def _digest(text: str) -> str:
    """Short stable fingerprint of a config text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stamp_path(config_path: Path) -> Path:
    """Sidecar file that records the fingerprint of the config the catalogue generated."""
    return config_path.with_name(f"{config_path.stem}{GENERATED_SUFFIX}")


def _sync_generated_config(config_path: Path, config: dict[str, Any]) -> dict[str, str]:
    """Write a catalogue-generated module config without overwriting hand edits.

    A sidecar stores the fingerprint of the text the catalogue last generated. A config whose
    current text still matches the sidecar was never edited, so a remap updates it. Any other
    existing config (edited by hand, or of unknown origin) is left untouched and reported as
    ``conflict`` so the API can show it as stale.

    Returns:
        ``{"status": created | updated | unchanged | conflict, "path": <file name>}``.
    """
    text = _config_text(config)
    stamp = _stamp_path(config_path)
    status = _decide_status(config_path, stamp, text)
    if status in ("created", "updated"):
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(text, encoding="utf-8")
    if status != "conflict":
        stamp.write_text(_digest(text), encoding="utf-8")
    return {"status": status, "path": config_path.name}


def _decide_status(config_path: Path, stamp: Path, new_text: str) -> str:
    """What to do with the config file: created, updated, unchanged or conflict."""
    if not config_path.exists():
        return "created"
    current = config_path.read_text(encoding="utf-8")
    if current == new_text:
        return "unchanged"
    generated = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else None
    return "updated" if generated == _digest(current) else "conflict"


def _sync_anomaly_config(root: Path, signals: list[dict[str, Any]]) -> dict[str, str] | None:
    """Create or update the default anomaly detector config from input signals."""
    input_tags = [
        sig["tag"]
        for sig in signals
        if sig.get("role") == "input" and sig.get("module") in (None, "anomaly")
    ]
    if len(input_tags) < 3:
        return None
    cfg = {
        "schema_version": SCHEMA_VERSION,
        "id": DEFAULT_CONFIG_ID,
        "description": "Default anomaly detector from catalogue mapping",
        "tags": input_tags,
        "mode": "advisory",
    }
    return _sync_generated_config(root / ANOMALY_DIR / f"{DEFAULT_CONFIG_ID}.json", cfg)


def _sync_softsensor_config(root: Path, signals: list[dict[str, Any]]) -> dict[str, str] | None:
    """Create or update the default soft sensor config from target and input signals."""
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
        return None
    cfg = {
        "schema_version": SCHEMA_VERSION,
        "id": DEFAULT_CONFIG_ID,
        "description": "Default soft sensor from catalogue mapping",
        "target_tag": target_tag,
        "input_tags": input_tags,
        "mode": "advisory",
    }
    return _sync_generated_config(root / SOFTSENSOR_DIR / f"{DEFAULT_CONFIG_ID}.json", cfg)


def build_catalogue_router(root: Path, load_tags: Any | None = None) -> APIRouter:
    """Construct FastAPI router for /catalogue routes."""
    endpoints = _CatalogueEndpoints(root, load_tags)
    router = APIRouter()
    router.add_api_route("/catalogue/suggest", endpoints.post_suggest, methods=["POST"])
    router.add_api_route("/catalogue/mapping", endpoints.get_mapping, methods=["GET"])
    router.add_api_route("/catalogue/mapping", endpoints.put_mapping, methods=["PUT"])
    return router


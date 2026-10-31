"""HTTP routes for industrial source connectors (Phase 1, #43).

Bridges the site catalogue data sources with read-only connector adapters (OPC UA, CSV, SQL).
Enables connection testing, hierarchical browsing, and live tag sampling from the web GUI.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from crosscut_connectors.base import (
    CAP_BROWSE,
    CAP_READ_LIVE,
    NotSupportedError,
    SourceConnectionError,
)
from crosscut_connectors.registry import connector_from_source
from crosscut_connectors.site import load_site, site_path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class ReadLiveRequest(BaseModel):
    """List of node or tag identifiers to read from the live connection."""

    tags: list[str] = Field(default_factory=list)


def _find_source(root: Path, source_id: str) -> dict[str, Any]:
    """Locate a source entry inside the site document by its unique identifier."""
    if not site_path(root).exists():
        raise HTTPException(status_code=404, detail="Site catalogue does not exist")
    site_doc = load_site(root)
    sources = site_doc.get("sources", [])
    for src in sources:
        if src.get("id") == source_id:
            return src
    raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found in site catalogue")


class _ConnectorEndpoints:
    """HTTP endpoints for source testing, address space browsing, and live reading."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def list_sources(self) -> dict[str, Any]:
        """List configured data sources from the site catalogue."""
        if not site_path(self.root).exists():
            return {"sources": []}
        site_doc = load_site(self.root)
        return {"sources": site_doc.get("sources", [])}

    def test_source(self, source_id: str) -> dict[str, Any]:
        """Verify network connectivity and return supported capabilities."""
        source = _find_source(self.root, source_id)
        try:
            conn = connector_from_source(source)
            caps = sorted(list(conn.capabilities()))
            return {"status": "ok", "source_id": source_id, "capabilities": caps}
        except (SourceConnectionError, ValueError) as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    def browse_source(self, source_id: str, node_id: str | None = None) -> dict[str, Any]:
        """Inspect hierarchical address space nodes starting at root or given node."""
        source = _find_source(self.root, source_id)
        try:
            conn = connector_from_source(source)
            if CAP_BROWSE not in conn.capabilities():
                msg = f"Source '{source_id}' does not support browsing"
                raise HTTPException(status_code=400, detail=msg)
            nodes = conn.browse(node_id=node_id)
            return {"source_id": source_id, "node_id": node_id, "nodes": [asdict(n) for n in nodes]}
        except NotSupportedError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except SourceConnectionError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    def read_live(self, source_id: str, request: ReadLiveRequest) -> dict[str, Any]:
        """Sample current values, timestamps, and quality codes for given tags."""
        source = _find_source(self.root, source_id)
        try:
            conn = connector_from_source(source)
            if CAP_READ_LIVE not in conn.capabilities():
                msg = f"Source '{source_id}' does not support live reading"
                raise HTTPException(status_code=400, detail=msg)
            values = conn.read_live(request.tags)
            return {"source_id": source_id, "values": {k: asdict(v) for k, v in values.items()}}
        except NotSupportedError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except SourceConnectionError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error


def build_connector_router(root: Path) -> APIRouter:
    """Build and return FastAPI router for source connector operations."""
    endpoints = _ConnectorEndpoints(root)
    router = APIRouter()
    router.add_api_route("/sources", endpoints.list_sources, methods=["GET"])
    router.add_api_route("/sources/{source_id}/test", endpoints.test_source, methods=["POST"])
    router.add_api_route("/sources/{source_id}/browse", endpoints.browse_source, methods=["GET"])
    router.add_api_route("/sources/{source_id}/read-live", endpoints.read_live, methods=["POST"])
    return router

"""HTTP routes of the site catalogue: read, replace and the import settings it states.

Wraps crosscut_connectors.site; the file lives in ``<data root>/_site/site.json``. Nothing here
reaches a plant.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from crosscut_connectors.site import (
    SiteError,
    load_site,
    read_settings_from_site,
    save_site,
    site_path,
    validate_site,
)
from crosscut_loops.plant_import import ReadSettings
from fastapi import APIRouter, Body, HTTPException


class _SiteEndpoints:
    """The site route handlers, bound to the data root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def get_site(self) -> dict[str, Any]:
        """The site file as stored (404 when the project has none yet)."""
        return self._load_or_404()

    def put_site(self, document: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        """Validate and replace the site file (422 with the problems when not acceptable)."""
        problems = validate_site(document)
        if problems:
            raise HTTPException(status_code=422, detail=problems)
        save_site(self.root, document)
        return document

    def get_import_settings(self) -> dict[str, Any]:
        """The settings the wide-file import would use: the site's values over the defaults."""
        settings = ReadSettings(**read_settings_from_site(self._load_or_404()))
        out = asdict(settings)
        out["missing_codes"] = list(settings.missing_codes)
        out["time_names"] = sorted(settings.time_names)
        return out

    def _load_or_404(self) -> dict[str, Any]:
        """The stored site file, 404 when absent and 422 when unreadable."""
        if not site_path(self.root).exists():
            raise HTTPException(status_code=404, detail="no site file")
        try:
            return load_site(self.root)
        except SiteError as error:
            raise HTTPException(status_code=422, detail=[str(error)]) from error


def build_site_router(root: Path) -> APIRouter:
    """Routes for GET/PUT /site and GET /site/import-settings."""
    endpoints = _SiteEndpoints(root)
    router = APIRouter()
    router.add_api_route("/site", endpoints.get_site, methods=["GET"])
    router.add_api_route("/site", endpoints.put_site, methods=["PUT"])
    router.add_api_route("/site/import-settings", endpoints.get_import_settings, methods=["GET"])
    return router

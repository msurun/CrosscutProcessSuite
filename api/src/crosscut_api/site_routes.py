"""HTTP routes of the site catalogue: the import settings it states plus the version routes.

Wraps crosscut_connectors.site; the published file lives in ``<data root>/_site/site.json``,
draft and versions are in site_version_routes. Nothing here reaches a plant.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from crosscut_connectors.site import (
    SiteError,
    load_site,
    read_settings_from_site,
    site_path,
)
from crosscut_loops.plant_import import ReadSettings
from fastapi import APIRouter, HTTPException

from crosscut_api.site_version_routes import build_site_version_router


class _SiteEndpoints:
    """The site route handlers, bound to the data root."""

    def __init__(self, root: Path) -> None:
        self.root = root

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
    router.include_router(build_site_version_router(root))
    router.add_api_route("/site/import-settings", endpoints.get_import_settings, methods=["GET"])
    return router

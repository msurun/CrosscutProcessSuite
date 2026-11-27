"""Dependencies view of the catalogue: stale configs, models and jobs, and re-confirmation (#166).

``GET /dependencies`` lists what no longer matches the published catalogue with the reason and the
possible actions (relearn, re-confirm, edit config). ``POST /dependencies/confirm`` lets an engineer
accept the catalogue as it is for one dependent; it is audited in the catalogue audit chain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from crosscut_connectors.dependency_index import (
    DependencyError,
    IndexUnreadableError,
    confirm,
    load_index,
    stale_items,
)
from crosscut_connectors.site import SiteError, load_site
from fastapi import APIRouter, Body, Depends, HTTPException

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.site_versions import current_version, versions_dir

ActorDep = Annotated[ActorContext, Depends(actor_of)]
MAX_NOTE = 500


def _site(root: Path) -> dict[str, Any]:
    """The published catalogue; 404 when there is none."""
    try:
        return load_site(root)
    except (SiteError, OSError) as error:
        raise HTTPException(status_code=404, detail="no site file") from error


class _DependencyEndpoints:
    """The handlers, bound to the data root."""

    def __init__(self, root: Path) -> None:
        """Bind to ``root``; confirmations go to the catalogue audit chain."""
        self.root = root
        self.audit = AuthAudit(versions_dir(root) / "audit.jsonl")

    def get_dependencies(self) -> dict[str, Any]:
        """Stale dependents of the published catalogue and how many dependents are tracked."""
        site = _site(self.root)
        try:
            return {
                "published_version": current_version(self.root),
                "tracked": len(load_index(self.root)["items"]),
                "items": stale_items(self.root, site),
            }
        except IndexUnreadableError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    def post_confirm(self, actor: ActorDep, body: Annotated[dict[str, Any], Body()]) -> Any:
        """Accept the catalogue for one stale dependent: an engineer's audited decision."""
        actor.require("config.edit")
        key, note = str(body.get("key", "")), str(body.get("note", "")).strip()
        if not note or len(note) > MAX_NOTE:
            raise HTTPException(status_code=422, detail="a note of 1-500 characters is required")
        try:
            entry = confirm(
                self.root, _site(self.root), key, current_version(self.root), actor.actor, note
            )
        except IndexUnreadableError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DependencyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        self.audit.append("dependency_confirm", actor=actor.actor, key=key, note=note,
                          version=current_version(self.root) or 0)
        return {"key": key, "confirmed": entry["confirmed"]}


def build_dependency_router(root: Path) -> APIRouter:
    """Routes: ``GET /dependencies`` and ``POST /dependencies/confirm``."""
    endpoints = _DependencyEndpoints(root)
    router = APIRouter()
    router.add_api_route("/dependencies", endpoints.get_dependencies, methods=["GET"])
    router.add_api_route("/dependencies/confirm", endpoints.post_confirm, methods=["POST"])
    return router

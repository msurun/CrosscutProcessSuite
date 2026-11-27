"""HTTP routes for the CSV round trip of the site's tag section (issue #144).

The site's tags go out as a flat CSV for editing in a spreadsheet and come
back through the same endpoint; a dry run reports problems without touching
the site, and a real import saves only when the file is clean. Both directions work on the
working copy: the draft when there is one, else the published site; an import lands in the draft.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from crosscut_connectors.catalogue_csv import (
    CsvImport,
    RowError,
    apply_tags_import,
    export_tags_csv,
    parse_tags_csv,
)
from crosscut_connectors.site import SiteError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.site_version_routes import store_draft, working_site

CSV_MEDIA_TYPE = "text/csv"  # what the tag CSV travels as
DOWNLOAD_NAME = "tags.csv"  # the file name a browser saves the download under
WHOLE_FILE_ROW = 0  # RowError row for a problem of the file, not of one line


class _CatalogueCsvEndpoints:
    """The /site/tags.csv route handlers, bound to the data root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def get_tags_csv(self) -> Response:
        """The site's tags as a CSV download (404 when the project has none yet)."""
        csv_text = export_tags_csv(self._load_or_404())
        headers = {"Content-Disposition": f'attachment; filename="{DOWNLOAD_NAME}"'}
        return Response(csv_text, media_type=CSV_MEDIA_TYPE, headers=headers)

    async def post_tags_csv(
        self,
        request: Request,
        actor: ActorContext = Depends(actor_of),  # noqa: B008
        dry_run: bool = False,
    ) -> JSONResponse:
        """Read a tag CSV back in, reporting problems and saving only clean files."""
        text = (await request.body()).decode("utf-8")
        site = self._load_or_404()
        result = parse_tags_csv(text, site)
        if dry_run:
            return self._answer(result, applied=False, status=200)
        if result.errors:
            return self._answer(result, applied=False, status=422)
        return self._apply(site, result, actor.actor)

    def _apply(self, site: dict[str, Any], result: CsvImport, actor: str) -> JSONResponse:
        """Save a clean import into the draft, 422 when the result is refused.

        409 ``pending_exists``/``busy`` come from the draft store (HTTPException passes through).
        """
        try:
            store_draft(self.root, apply_tags_import(site, result), actor)
        except (SiteError, ValueError) as error:
            # a clean CSV can still build a site the validator refuses (unknown source)
            refused = CsvImport(tags=[], errors=[RowError(WHOLE_FILE_ROW, "", str(error))])
            return self._answer(refused, applied=False, status=422)
        return self._answer(result, applied=True, status=200)

    def _answer(self, result: CsvImport, applied: bool, status: int) -> JSONResponse:
        """The JSON answer for one import attempt: problems, tag count, applied."""
        payload = {
            "errors": [asdict(error) for error in result.errors],
            "tags": len(result.tags),
            "applied": applied,
        }
        return JSONResponse(content=payload, status_code=status)

    def _load_or_404(self) -> dict[str, Any]:
        """The working copy (draft, else published), 404 when absent and 422 when unreadable."""
        try:
            site = working_site(self.root)
        except SiteError as error:
            raise HTTPException(status_code=422, detail=[str(error)]) from error
        if site is None:
            raise HTTPException(status_code=404, detail="no site file")
        return site


def build_catalogue_csv_router(root: Path) -> APIRouter:
    """Routes for GET/POST /site/tags.csv (CSV round trip of the tag section)."""
    endpoints = _CatalogueCsvEndpoints(root)
    router = APIRouter()
    router.add_api_route("/site/tags.csv", endpoints.get_tags_csv, methods=["GET"])
    router.add_api_route("/site/tags.csv", endpoints.post_tags_csv, methods=["POST"])
    return router

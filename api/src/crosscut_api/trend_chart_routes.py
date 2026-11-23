"""Saved trend charts per user: list, read, create, replace, delete and copy (issue #204).

One JSON file per chart under ``<data root>/_trends/charts/<id>.json``, validated against
``schemas/trend-chart.schema.json``. A chart belongs to the signed-in user; a shared chart is
visible to everyone, only its owner changes it, and sharing needs ``config.edit``.
"""

from __future__ import annotations

import functools
import json
import os
import secrets
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from jsonschema import Draft202012Validator

from crosscut_api.auth.actor import ActorContext, actor_of

Doc = dict[str, Any]
SCHEMA_FILE = "trend-chart.schema.json"
SHARE_PERMISSION = "config.edit"
MAX_AXES_PER_PANE = 3
# Fields the API owns: a client may send them, but the stored values always win.
SERVER_FIELDS = ("schema_version", "id", "owner", "created_utc", "updated_utc")


def charts_dir(root: Path) -> Path:
    """Folder holding the saved charts of a data root."""
    return root / "_trends" / "charts"


@functools.lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    """Compiled validator of the chart schema (``CROSSCUT_SCHEMAS_DIR`` overrides the folder)."""
    override = os.environ.get("CROSSCUT_SCHEMAS_DIR")
    base = Path(override) if override else Path(__file__).resolve().parents[3] / "schemas"
    return Draft202012Validator(json.loads((base / SCHEMA_FILE).read_text(encoding="utf-8")))


def chart_problems(chart: Doc) -> list[str]:
    """Schema errors plus the cross-field rules the schema cannot state; empty when valid."""
    problems = [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
                for e in _validator().iter_errors(chart)]
    if problems:
        return problems
    return _axis_problems(chart["axes"], chart["series"])


def _axis_problems(axes: list[Doc], series: list[Doc]) -> list[str]:
    """Unique axis ids, at most three axes per pane, and every series on a known axis."""
    ids = Counter(axis["id"] for axis in axes)
    problems = [f"axes: duplicate id {name!r}" for name, n in ids.items() if n > 1]
    panes = Counter(axis.get("pane", 0) for axis in axes)
    problems += [f"axes: pane {pane} has {n} axes (max {MAX_AXES_PER_PANE})"
                 for pane, n in panes.items() if n > MAX_AXES_PER_PANE]
    problems += [f"series[{i}]: unknown axis {s['axis']!r}"
                 for i, s in enumerate(series) if s["axis"] not in ids]
    return problems


def _utc_now(clock: Callable[[], float]) -> str:
    """The clock time as an ISO 8601 UTC string with second resolution."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock()))


def _write_atomic(path: Path, chart: Doc) -> None:
    """Write a chart file through a temporary file so readers never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(chart, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


class ChartStore:
    """The chart files of one data root; unreadable files are skipped, never served."""

    def __init__(self, root: Path) -> None:
        """Bind the store to a data root."""
        self.folder = charts_dir(root)

    def all(self) -> list[Doc]:
        """Every readable chart, ordered by name."""
        if not self.folder.is_dir():
            return []
        charts = [self._read(path) for path in sorted(self.folder.glob("*.json"))]
        return sorted((c for c in charts if c is not None), key=lambda c: c["name"].lower())

    def get(self, chart_id: str) -> Doc | None:
        """One chart, or None when the id is malformed, missing or unreadable."""
        if not (len(chart_id) == 12 and chart_id.isalnum() and chart_id.islower()):
            return None
        return self._read(self.folder / f"{chart_id}.json")

    def put(self, chart: Doc) -> None:
        """Store a chart that already passed ``chart_problems``."""
        _write_atomic(self.folder / f"{chart['id']}.json", chart)

    def delete(self, chart_id: str) -> None:
        """Remove a chart file; a missing file is not an error."""
        (self.folder / f"{chart_id}.json").unlink(missing_ok=True)

    @staticmethod
    def _read(path: Path) -> Doc | None:
        """Parse and validate one chart file; None when it is absent or broken."""
        try:
            chart = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return chart if isinstance(chart, dict) and not chart_problems(chart) else None


def _summary(chart: Doc, actor: ActorContext) -> Doc:
    """List entry of a chart: identity, sharing and whether the caller may change it."""
    keys = ("id", "name", "owner", "shared", "updated_utc")
    return {**{k: chart.get(k) for k in keys}, "mine": chart["owner"] == actor.actor}


def _visible(chart: Doc, actor: ActorContext) -> bool:
    """A chart is visible to its owner and, when shared, to everyone."""
    return bool(chart["shared"]) or chart["owner"] == actor.actor


class _Endpoints:
    """Handlers of the ``/trends/charts`` routes."""

    def __init__(self, root: Path, clock: Callable[[], float]) -> None:
        """Bind the chart store and the clock that stamps created and updated times."""
        self._store, self._clock = ChartStore(root), clock

    def list(self, actor: Annotated[ActorContext, Depends(actor_of)]) -> Doc:
        """The caller's charts and the shared charts of the site."""
        charts = [c for c in self._store.all() if _visible(c, actor)]
        return {"charts": [_summary(c, actor) for c in charts]}

    def read(self, chart_id: str, actor: Annotated[ActorContext, Depends(actor_of)]) -> Doc:
        """One chart the caller may see (404 otherwise, so ids of private charts do not leak)."""
        return self._visible_or_404(chart_id, actor)

    def create(
        self, body: Annotated[Doc, Body()], actor: Annotated[ActorContext, Depends(actor_of)]
    ) -> Doc:
        """Save a new chart owned by the caller."""
        now = _utc_now(self._clock)
        stamp = {"id": secrets.token_hex(6), "owner": actor.actor, "created_utc": now}
        return self._save(body, stamp, actor)

    def replace(
        self,
        chart_id: str,
        body: Annotated[Doc, Body()],
        actor: Annotated[ActorContext, Depends(actor_of)],
    ) -> Doc:
        """Replace a chart the caller owns."""
        old = self._owned_or_error(chart_id, actor)
        stamp = {k: old[k] for k in ("id", "owner", "created_utc") if k in old}
        return self._save(body, stamp, actor)

    def remove(self, chart_id: str, actor: Annotated[ActorContext, Depends(actor_of)]) -> Doc:
        """Delete a chart the caller owns."""
        self._owned_or_error(chart_id, actor)
        self._store.delete(chart_id)
        return {"deleted": chart_id}

    def copy(self, chart_id: str, actor: Annotated[ActorContext, Depends(actor_of)]) -> Doc:
        """Copy a visible chart into the caller's own, unshared charts."""
        source = self._visible_or_404(chart_id, actor)
        body = {**source, "name": f"{source['name']} (copy)"[:120], "shared": False}
        return self.create(body, actor)

    def _save(self, body: Doc, stamp: Doc, actor: ActorContext) -> Doc:
        """Merge the server fields over the body, check sharing and validity, then store."""
        chart = {k: v for k, v in body.items() if k not in SERVER_FIELDS}
        chart.update(stamp, schema_version=1, updated_utc=_utc_now(self._clock))
        chart.setdefault("shared", False)
        if chart["shared"] is True and not actor.can(SHARE_PERMISSION):
            raise HTTPException(status_code=403, detail="sharing a chart needs config.edit")
        problems = chart_problems(chart)
        if problems:
            raise HTTPException(status_code=422, detail=problems)
        self._store.put(chart)
        return chart

    def _visible_or_404(self, chart_id: str, actor: ActorContext) -> Doc:
        """The chart when the caller may see it, else 404."""
        chart = self._store.get(chart_id)
        if chart is None or not _visible(chart, actor):
            raise HTTPException(status_code=404, detail="no such chart")
        return chart

    def _owned_or_error(self, chart_id: str, actor: ActorContext) -> Doc:
        """The chart when the caller owns it; 404 when invisible, 403 when shared by another."""
        chart = self._visible_or_404(chart_id, actor)
        if chart["owner"] != actor.actor:
            raise HTTPException(status_code=403, detail="only the owner changes a chart")
        return chart


def build_trend_chart_router(root: Path, clock: Callable[[], float] = time.time) -> APIRouter:
    """Routes for the saved trend charts of the signed-in user."""
    endpoints = _Endpoints(root, clock)
    router = APIRouter()
    router.add_api_route("/trends/charts", endpoints.list, methods=["GET"])
    router.add_api_route("/trends/charts", endpoints.create, methods=["POST"])
    router.add_api_route("/trends/charts/{chart_id}", endpoints.read, methods=["GET"])
    router.add_api_route("/trends/charts/{chart_id}", endpoints.replace, methods=["PUT"])
    router.add_api_route("/trends/charts/{chart_id}", endpoints.remove, methods=["DELETE"])
    router.add_api_route("/trends/charts/{chart_id}/copy", endpoints.copy, methods=["POST"])
    return router

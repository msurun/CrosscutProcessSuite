"""Administration routes (issue #170): the health report and the log export.

``GET /admin/health`` needs ``data.view`` (the runtime page permission) and is read-only.
``GET /admin/logs/export`` needs ``users.manage`` and appends an audit entry (``log_export``)
to the sign-in audit chain before it returns the zip.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import Annotated, Any

from crosscut_runtime.store import JobStoreError, RuntimeStore
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit, AuthAuditError
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir
from crosscut_api.health import HealthSources, build_report
from crosscut_api.log_export import LogRangeError, build_export, parse_instant

DEFAULT_RANGE = timedelta(hours=24)
AUDIT_TAIL_BYTES = 8192
VERSION_PACKAGES = ("crosscut-api", "crosscut-runtime", "crosscut-gateway", "crosscut-connectors")
ActorDep = Annotated[ActorContext, Depends(actor_of)]


def _read_json(path: Path) -> dict[str, Any] | None:
    """A JSON object from ``path``; ``None`` when the file is missing or not an object."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _auth_audit_last(root: Path) -> datetime | None:
    """Time of the newest record of the sign-in audit chain, read from the file tail."""
    try:
        with (auth_dir(root) / AUDIT_FILE).open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - AUDIT_TAIL_BYTES))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
        stamp = json.loads(lines[-1])["t_ns"]
        return datetime.fromtimestamp(int(stamp) / 1e9, tz=UTC)
    except (OSError, ValueError, KeyError, IndexError):
        return None


def _package_versions() -> dict[str, str | None]:
    """Installed version of each Crosscut package; ``None`` for one that is not installed."""
    found: dict[str, str | None] = {}
    for name in VERSION_PACKAGES:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = None
    return found


def default_sources(root: Path) -> HealthSources:
    """The real sources: state files under the data root, the disk and the installed packages."""
    store = RuntimeStore(root)

    def runtime_state() -> dict[str, Any]:
        try:
            return store.load_state()
        except JobStoreError:
            return {}

    def jobs() -> list[dict[str, Any]]:
        try:
            return list(store.load_jobs().get("jobs", []))
        except JobStoreError:
            return []

    def disk() -> tuple[int, int]:
        usage = shutil.disk_usage(root)
        return usage.free, usage.total

    return HealthSources(
        now=lambda: datetime.now(UTC),
        runtime_state=runtime_state,
        jobs=jobs,
        gateway_state=lambda: _read_json(root / "_gateway" / "state.json"),
        auth_audit_last=lambda: _auth_audit_last(root),
        disk=disk,
        versions=_package_versions,
    )


def _audit_of(request: Request, root: Path) -> AuthAudit:
    """The app's shared audit writer, or one over the same file when the app has none."""
    shared = getattr(request.app.state, "auth_audit", None)
    return shared if shared is not None else AuthAudit(auth_dir(root) / AUDIT_FILE, time.time)


def _range(start: str | None, end: str | None) -> tuple[datetime, datetime]:
    """The requested range; the last 24 hours when both ends are missing."""
    stop = parse_instant(end) if end else datetime.now(UTC)
    begin = parse_instant(start) if start else stop - DEFAULT_RANGE
    return begin, stop


class _AdminEndpoints:
    """Handlers of the administration routes."""

    def __init__(self, root: Path, sources: HealthSources) -> None:
        """Keep the data root and the health sources."""
        self._root = root
        self._sources = sources

    def health(self) -> dict[str, Any]:
        """GET /admin/health: every health item with ok, warning or error and a reason."""
        return build_report(self._sources)

    def export_logs(
        self,
        request: Request,
        actor: ActorDep,
        start: Annotated[str | None, Query()] = None,
        end: Annotated[str | None, Query()] = None,
    ) -> Response:
        """GET /admin/logs/export: zip of the scrubbed log lines of the range; audited.

        Needs a fresh step-up (428 otherwise), like any download of site data.
        """
        actor.require_stepup()
        try:
            begin, stop = _range(start, end)
            payload, names = build_export(self._root, begin, stop)
        except LogRangeError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        self._audit(request, actor, (begin, stop), names)
        name = f"crosscut-logs-{stop.strftime('%Y%m%dT%H%M%SZ')}.zip"
        return Response(payload, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    def _audit(
        self,
        request: Request,
        actor: ActorContext,
        span: tuple[datetime, datetime],
        names: list[str],
    ) -> None:
        """Append the ``log_export`` record; without it the export is refused (503)."""
        try:
            _audit_of(request, self._root).append(
                "log_export", actor=actor.actor, start=span[0].isoformat(), end=span[1].isoformat(),
                files=",".join(names), source_ip=actor.source_ip,
            )
        except (AuthAuditError, OSError) as error:
            raise HTTPException(status_code=503, detail="audit unavailable") from error


def build_admin_router(root: Path, sources: HealthSources | None = None) -> APIRouter:
    """Router of ``/admin/health`` and ``/admin/logs/export``; tests pass fake ``sources``."""
    endpoints = _AdminEndpoints(root, sources or default_sources(root))
    router = APIRouter(prefix="/admin")
    router.add_api_route("/health", endpoints.health, methods=["GET"])
    router.add_api_route("/logs/export", endpoints.export_logs, methods=["GET"])
    return router


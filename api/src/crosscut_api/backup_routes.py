"""Administration routes for backup and restore of configuration, no history (issue #167).

``GET /admin/backup`` downloads the zip, ``POST /admin/backup/inspect`` is the dry run of an
uploaded zip, ``POST /admin/backup/restore?confirm=<archive sha256>`` restores exactly the archive
that was inspected. Both mutating paths need a fresh step-up and write an audit line first
(no audit line, no change). The raw zip is the request body; nothing here touches secrets.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir
from crosscut_api.backup import (
    MAX_ARCHIVE_BYTES,
    BackupError,
    Report,
    RollbackError,
    build_backup,
    inspect_backup,
    restore_backup,
    restrict_permissions,
    sha256_hex,
)

Doc = dict[str, Any]
PERMISSION = "users.manage"


def _utc(clock: Callable[[], float]) -> str:
    """The clock time as an ISO 8601 UTC string with second resolution."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock()))


async def _body(request: Request) -> bytes:
    """The raw request body; 413 above the archive size limit."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="backup_too_large")
    data = await request.body()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="backup_too_large")
    return data


class _Endpoints:
    """Handlers bound to one data root and clock."""

    def __init__(self, root: Path, clock: Callable[[], float]) -> None:
        self.root = root
        self._clock = clock

    def download(self, actor: Annotated[ActorContext, Depends(actor_of)]) -> Response:
        """Build and return the backup zip."""
        actor.require(PERMISSION)
        actor.require_stepup()
        created = _utc(self._clock)
        data = build_backup(self.root, created)
        self._audit("backup_created", actor, created_utc=created, archive_sha256=sha256_hex(data))
        name = f"crosscut-backup-{created.replace(':', '').replace('-', '')}.zip"
        return Response(
            content=data, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )  # fmt: skip

    async def inspect(
        self, request: Request, actor: Annotated[ActorContext, Depends(actor_of)]
    ) -> Doc:
        """Dry run of an uploaded archive: validation and the list of changes."""
        actor.require(PERMISSION)
        actor.require_stepup()
        report, _ = inspect_backup(self.root, await _body(request))
        self._audit(
            "backup_inspected", actor, archive_sha256=report.archive_sha256, ok=str(report.ok)
        )
        return report.as_dict()

    async def restore(
        self, request: Request, confirm: str, actor: Annotated[ActorContext, Depends(actor_of)]
    ) -> Doc:
        """Restore the uploaded archive when it is the one that was inspected (``confirm``)."""
        actor.require(PERMISSION)
        actor.require_stepup()
        data = await _body(request)
        if sha256_hex(data) != confirm:
            raise HTTPException(status_code=409, detail="confirm_mismatch")
        now = _utc(self._clock)
        try:
            report = restore_backup(self.root, data, now, lambda r: self._audit_restore(actor, r))
        except BackupError as error:
            raise HTTPException(status_code=422, detail=error.problems) from error
        except RollbackError as error:
            self._audit_best_effort("backup_rollback_failed", actor, archive_sha256=confirm)
            raise HTTPException(status_code=500, detail="rollback_failed") from error
        except OSError as error:
            self._audit_best_effort("backup_restore_failed", actor, archive_sha256=confirm)
            raise HTTPException(status_code=500, detail="restore_failed_rolled_back") from error
        return {**report.as_dict(), "restored": True}

    def _audit_restore(self, actor: ActorContext, report: Report) -> None:
        """The audit line written before the first live file changes."""
        self._audit(
            "backup_restored", actor, archive_sha256=report.archive_sha256,
            created_utc=report.created_utc, files=str(len(report.changes)),
        )  # fmt: skip

    def _audit_best_effort(self, event: str, actor: ActorContext, **fields: str) -> None:
        """Audit a failure; an audit problem must not hide the original error."""
        try:
            self._audit(event, actor, **fields)
        except HTTPException:
            pass

    def _audit(self, event: str, actor: ActorContext, **fields: str) -> None:
        """Append to the API auth audit; no audit line, no change (503)."""
        audit_path = auth_dir(self.root) / AUDIT_FILE
        audit = AuthAudit(audit_path, self._clock)
        try:
            audit.append(event, actor=actor.actor, source_ip=actor.source_ip, **fields)
            restrict_permissions(audit_path)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail="audit_unavailable") from error


def build_backup_router(root: Path, clock: Callable[[], float] = time.time) -> APIRouter:
    """Routes for download, dry run and restore of a configuration backup."""
    e = _Endpoints(root, clock)
    router = APIRouter()
    router.add_api_route("/admin/backup", e.download, methods=["GET"])
    router.add_api_route("/admin/backup/inspect", e.inspect, methods=["POST"])
    router.add_api_route("/admin/backup/restore", e.restore, methods=["POST"])
    return router

"""Routes of the versioned site catalogue: draft, versions, diff, publish and approval (#165).

Edits go to a draft (``PUT /site``); ``POST /site/publish`` stores the draft as the next
immutable version and makes it the published catalogue the runtime reads. When the diff
changes a loop or controller with active writes (``catalogue_approval``), publishing only
creates a pending record that a second engineer, not the requester, approves or rejects. This is the
same self-approval rule as the tuning proposals (``same_actor``); the record is a file so a
restart does not lose it. Every draft save, publish request, publish, approval and rejection
is appended to the hash-chained audit ``_site/versions/audit.jsonl``.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from crosscut_connectors.site import SiteError, load_site, site_path, validate_site
from crosscut_connectors.site_diff import diff_sites
from crosscut_connectors.site_versions import (
    SiteBusyError,
    VersionCorruptError,
    VersionMissingError,
    current_version,
    discard_draft,
    document_sha256,
    get_version,
    list_versions,
    load_draft,
    publish_document,
    published_sha256,
    read_json,
    save_draft,
    site_dir,
    site_lock,
    versions_dir,
    write_json,
)
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.actor_names import same_actor
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.catalogue_approval import active_writes, approval_reasons

Doc = dict[str, Any]
ActorDep = Annotated[ActorContext, Depends(actor_of)]
BodyDoc = Annotated[Doc | None, Body()]
PENDING_FILE = "pending_publish.json"
MAX_NOTE = 500


def _conflict(code: str) -> HTTPException:
    """A 409 whose detail is a stable machine code."""
    return HTTPException(status_code=409, detail=code)


@contextmanager
def locked(root: Path) -> Iterator[None]:
    """The catalogue lock; a second holder is answered with 409 ``busy``."""
    try:
        with site_lock(root):
            yield
    except SiteBusyError as error:
        raise _conflict("busy") from error


def store_draft(root: Path, document: Doc, actor: str) -> None:
    """Save an already validated document as the draft and audit it (shared with /config/site).

    Refused (409 ``pending_exists``) while a publish request waits: the approver is judging a
    fixed document, and the draft must not drift under it.
    """
    with locked(root):
        if read_json(site_dir(root) / PENDING_FILE) is not None:
            raise _conflict("pending_exists")
        save_draft(root, document)
        AuthAudit(versions_dir(root) / "audit.jsonl").append(
            "draft_save", actor=actor, sha256=document_sha256(document)
        )


def working_site(root: Path) -> Doc | None:
    """The draft when there is one, else the published catalogue, None when neither exists."""
    draft = load_draft(root)
    if draft is not None:
        return draft
    return load_site(root) if site_path(root).exists() else None


class _VersionEndpoints:
    """The handlers, bound to the data root."""

    def __init__(self, root: Path) -> None:
        """Bind to ``root``; the audit log lives in the versions folder."""
        self.root = root
        self.audit = AuthAudit(versions_dir(root) / "audit.jsonl")

    # --- reading ---------------------------------------------------------------------------

    def get_site(self) -> Doc:
        """The working copy: the draft when there is one, else the published catalogue."""
        try:
            working = working_site(self.root)
        except SiteError as error:
            raise HTTPException(status_code=422, detail=[str(error)]) from error
        return working if working is not None else self._published_or_404()

    def get_status(self) -> Doc:
        """Published version, draft badge, change summary and any pending publish request."""
        published = self._published()
        draft = load_draft(self.root)
        diff = diff_sites(published or {}, draft) if draft is not None else None
        pending = self._pending()
        return {
            "published_version": current_version(self.root),
            "has_published": published is not None,
            "published_matches_version": self._matches_version(),
            "has_draft": draft is not None,
            "draft_changed": bool(diff and not diff["empty"]),
            "draft_sections": sorted(diff["sections"]) if diff else [],
            "pending": None if pending is None else self._pending_view(pending),
        }

    def list_versions(self) -> Doc:
        """Metadata of every version, newest first."""
        return {"versions": list(reversed(list_versions(self.root)))}

    def get_version(self, number: int) -> Doc:
        """One version: its metadata and stored document."""
        try:
            meta, document = get_version(self.root, number)
        except VersionMissingError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except VersionCorruptError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"meta": meta, "document": document}

    def get_diff(self, a: str, b: str) -> Doc:
        """Structured difference from a to b (version number, ``published`` or ``draft``)."""
        return {"a": a, "b": b, **diff_sites(self._resolve(a), self._resolve(b))}

    # --- editing ---------------------------------------------------------------------------

    def put_site(self, document: Annotated[Doc, Body()], actor: ActorDep) -> Doc:
        """Validate the document and store it as the draft (the published file is untouched)."""
        problems = validate_site(document)
        if problems:
            raise HTTPException(status_code=422, detail=problems)
        store_draft(self.root, document, actor.actor)
        return document

    def delete_draft(self, actor: ActorDep) -> Doc:
        """Throw the draft away (refused while a publish request waits)."""
        with locked(self.root):
            if self._pending() is not None:
                raise _conflict("pending_exists")
            discard_draft(self.root)
            self.audit.append("draft_discard", actor=actor.actor)
        return {"discarded": True}

    # --- publishing ------------------------------------------------------------------------

    def publish(self, actor: ActorDep, body: BodyDoc = None) -> Any:
        """Publish the draft, or create the pending request when a second engineer must approve."""
        note = self._note(body)
        with locked(self.root):
            return self._publish_locked(actor, note)

    def _publish_locked(self, actor: ActorContext, note: str) -> Any:
        """The body of ``publish``, run while the catalogue lock is held."""
        draft = load_draft(self.root)
        if draft is None:
            raise _conflict("no_draft")
        if self._pending() is not None:
            raise _conflict("pending_exists")
        published = self._published() or {}
        diff = diff_sites(published, draft)
        if diff["empty"]:
            raise _conflict("no_changes")
        reasons = approval_reasons(diff, active_writes(self.root, published), published, draft)
        if not reasons:
            return self._publish(draft, actor.actor, note, None)
        pending = self._store_pending(draft, actor.actor, note, reasons)
        self.audit.append(
            "publish_requested", actor=actor.actor, pending=pending["id"], reasons=",".join(reasons)
        )
        return self._accepted(pending)

    def get_pending(self) -> Doc:
        """The pending publish request with its diff, 404 when there is none."""
        pending = self._pending()
        if pending is None:
            raise HTTPException(status_code=404, detail="no pending publish")
        return self._pending_view(pending)

    def approve(self, actor: ActorDep) -> Doc:
        """Publish the pending request; the approver must be another user than the requester."""
        actor.require("config.edit")
        with locked(self.root):
            return self._approve_locked(actor)

    def _approve_locked(self, actor: ActorContext) -> Doc:
        """The body of ``approve``, run while the catalogue lock is held."""
        pending = self._require_pending()
        if same_actor(pending["requested_by"], actor.actor):
            raise HTTPException(status_code=403, detail="self_approval")
        if document_sha256(pending["document"]) != pending.get("document_sha256"):
            self.audit.append("publish_tampered", actor=actor.actor, pending=pending["id"])
            raise _conflict("pending_modified")
        if pending["base_sha256"] != published_sha256(self.root):
            self._clear_pending()
            self.audit.append("publish_stale", actor=actor.actor, pending=pending["id"])
            raise _conflict("stale_base")
        meta = self._publish(
            pending["document"], pending["requested_by"], pending["note"], actor.actor
        )
        self._clear_pending()
        self.audit.append(
            "publish_approved", actor=actor.actor, pending=pending["id"], version=meta["version"]
        )
        return meta

    def reject(self, actor: ActorDep, body: BodyDoc = None) -> Doc:
        """Reject (or, by the requester, withdraw) the pending request; the draft is kept."""
        with locked(self.root):
            pending = self._require_pending()
            self._clear_pending()
        reason = str((body or {}).get("reason", ""))[:MAX_NOTE]
        self.audit.append(
            "publish_rejected", actor=actor.actor, pending=pending["id"], reason=reason
        )
        return {"rejected": pending["id"]}

    # --- helpers ---------------------------------------------------------------------------

    def _publish(self, document: Doc, author: str, note: str, approver: str | None) -> Doc:
        """Store the version, audit it and return its metadata."""
        try:
            meta = publish_document(self.root, document, author, note, approver)
        except SiteError as error:
            self.audit.append("publish_failed", actor=approver or author, reason=str(error))
            raise HTTPException(status_code=409, detail=str(error)) from error
        self.audit.append(
            "publish",
            actor=approver or author,
            author=author,
            approver=approver or "",
            version=meta["version"],
            sha256=meta["sha256"],
            note=note,
        )
        return meta

    @staticmethod
    def _note(body: Doc | None) -> str:
        """The publish note from the body (optional, bounded)."""
        note = str((body or {}).get("note", "")).strip()
        if len(note) > MAX_NOTE:
            raise HTTPException(status_code=422, detail="note too long")
        return note

    def _accepted(self, pending: Doc) -> Any:
        """A 202 response for a request waiting for approval."""
        return JSONResponse(status_code=202, content=self._pending_view(pending))

    def _published(self) -> Doc | None:
        """The published catalogue, None when there is none; 422 when unreadable."""
        if not site_path(self.root).exists():
            return None
        try:
            return load_site(self.root)
        except SiteError as error:
            raise HTTPException(status_code=422, detail=[str(error)]) from error

    def _published_or_404(self) -> Doc:
        """The published catalogue or 404."""
        published = self._published()
        if published is None:
            raise HTTPException(status_code=404, detail="no site file")
        return published

    def _matches_version(self) -> bool | None:
        """True when the published file equals the newest stored version (None: no versions)."""
        versions = list_versions(self.root)
        if not versions:
            return None
        return bool(versions[-1]["sha256"] == published_sha256(self.root))

    def _resolve(self, name: str) -> Doc:
        """A document by name: ``draft``, ``published`` or a version number."""
        if name == "draft":
            draft = load_draft(self.root)
            if draft is None:
                raise HTTPException(status_code=404, detail="no draft")
            return draft
        if name == "published":
            return self._published() or {}
        try:
            return get_version(self.root, int(name))[1]
        except (ValueError, VersionMissingError) as error:
            raise HTTPException(status_code=404, detail=f"unknown version {name}") from error
        except VersionCorruptError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    def _pending(self) -> Doc | None:
        """The pending request, None when there is none."""
        return read_json(site_dir(self.root) / PENDING_FILE)

    def _require_pending(self) -> Doc:
        """The pending request or 404."""
        pending = self._pending()
        if pending is None:
            raise HTTPException(status_code=404, detail="no pending publish")
        return pending

    def _store_pending(self, draft: Doc, author: str, note: str, reasons: list[str]) -> Doc:
        """Persist the request: it holds the exact document the approver is asked to accept."""
        pending = {
            "id": secrets.token_hex(8),
            "requested_by": author,
            "requested_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "note": note,
            "reasons": reasons,
            "base_sha256": published_sha256(self.root),
            "document_sha256": document_sha256(draft),
            "document": draft,
        }
        write_json(site_dir(self.root) / PENDING_FILE, pending)
        return pending

    def _clear_pending(self) -> None:
        """Remove the pending request."""
        (site_dir(self.root) / PENDING_FILE).unlink(missing_ok=True)

    def _pending_view(self, pending: Doc) -> Doc:
        """The client view: the request metadata and its diff against the published version."""
        diff = diff_sites(self._published() or {}, pending["document"])
        view = {k: v for k, v in pending.items() if k != "document"}
        return {**view, "diff": diff}


def build_site_version_router(root: Path) -> APIRouter:
    """Routes: ``/site`` (working copy), ``/site/status``, versions, diff, draft and publishing."""
    e = _VersionEndpoints(root)
    router = APIRouter()
    add = router.add_api_route
    add("/site", e.get_site, methods=["GET"])
    add("/site", e.put_site, methods=["PUT"])
    add("/site/draft", e.delete_draft, methods=["DELETE"])
    add("/site/status", e.get_status, methods=["GET"])
    add("/site/versions", e.list_versions, methods=["GET"])
    add("/site/versions/{number}", e.get_version, methods=["GET"])
    add("/site/diff", e.get_diff, methods=["GET"])
    add("/site/publish", e.publish, methods=["POST"])
    add("/site/publish/pending", e.get_pending, methods=["GET"])
    add("/site/publish/approve", e.approve, methods=["POST"])
    add("/site/publish/reject", e.reject, methods=["POST"])
    return router

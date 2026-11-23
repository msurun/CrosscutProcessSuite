"""Add, edit and delete catalogue sources and their secrets from the console (issue #208).

A source entry lives in ``site.json`` (no credentials, PRODUCT 3.1); its password or token goes
to the operating-system secret store under ``source.<id>`` and the entry only names it through
``auth.credential_ref``. Secret values are never returned, logged or written to the audit; every
change is audited (no audit line, no change) and storing a secret needs a fresh step-up.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from crosscut_connectors.base import ConnectorError
from crosscut_connectors.registry import connector_from_source
from crosscut_connectors.secret_store import (
    SecretStore,
    SecretStoreError,
    default_store,
    ref_for_source,
)
from crosscut_connectors.site import SiteError, load_site, save_site, site_path, validate_site
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir

Doc = dict[str, Any]
# Auth kinds that need a secret; kerberos uses the service account of the process.
SECRET_KINDS = ("basic", "bearer")


class SecretBody(BaseModel):
    """Body of ``PUT /sources/{id}/secret``; the value is write-only."""

    value: str = Field(min_length=1, max_length=4096)


def _site(root: Path) -> Doc:
    """The site document, or an empty one to start from; 422 when the file is unreadable."""
    if not site_path(root).exists():
        return {"schema_version": 1, "site": {"name": "Site"}, "tags": []}
    try:
        return load_site(root)
    except SiteError as error:
        raise HTTPException(status_code=422, detail=[str(error)]) from error


def _index(site: Doc, source_id: str) -> int | None:
    """Position of the source in the site's ``sources`` list, or None."""
    for i, source in enumerate(site.get("sources", [])):
        if source.get("id") == source_id:
            return i
    return None


def _with_source(site: Doc, source: Doc) -> Doc:
    """A copy of the site with ``source`` added or replacing the entry of the same id."""
    out = copy.deepcopy(site)
    sources = out.setdefault("sources", [])
    at = _index(out, source["id"])
    if at is None:
        sources.append(source)
    else:
        sources[at] = source
    return out


def _checked(site: Doc) -> Doc:
    """The site when valid, else 422 with the problems."""
    problems = validate_site(site)
    if problems:
        raise HTTPException(status_code=422, detail=problems)
    return site


def _users_of(site: Doc, source_id: str) -> list[str]:
    """Catalogue tags read from the source; a source in use is not deleted."""
    return [str(t["id"]) for t in site.get("tags", []) if t.get("source") == source_id]


class _Endpoints:
    """Handlers of the source management routes."""

    def __init__(self, root: Path, store: Callable[[], SecretStore], clock: Callable[[], float]):
        """Bind the data root, the secret store factory and the audit clock."""
        self.root, self._store, self._clock = root, store, clock

    def put_source(
        self,
        source_id: str,
        body: Annotated[Doc, Body()],
        actor: Annotated[ActorContext, Depends(actor_of)],
    ) -> Doc:
        """Add or replace a source; the id in the path wins over the body."""
        actor.require("config.edit")
        source = {**body, "id": source_id}
        site = _checked(_with_source(_site(self.root), source))
        self._audit("source_saved", actor, source=source_id)
        save_site(self.root, site)
        return {**source, "secret_stored": self._stored(source_id)}

    def delete_source(
        self, source_id: str, actor: Annotated[ActorContext, Depends(actor_of)]
    ) -> Doc:
        """Delete an unused source and its stored secret; 409 while catalogue tags use it."""
        actor.require("config.edit")
        site = _site(self.root)
        at = _index(site, source_id)
        if at is None:
            raise HTTPException(status_code=404, detail="no such source")
        if users := _users_of(site, source_id):
            raise HTTPException(
                status_code=409, detail={"code": "source_in_use", "tags": users[:20]}
            )
        self._audit("source_deleted", actor, source=source_id)
        del site["sources"][at]
        save_site(self.root, _checked(site))
        self._forget(source_id)
        return {"deleted": source_id}

    def secret_status(
        self, source_id: str, actor: Annotated[ActorContext, Depends(actor_of)]
    ) -> Doc:
        """Whether a secret is stored for the source (never the value)."""
        actor.require("config.edit")
        self._existing(source_id)
        return {"source": source_id, "stored": self._stored(source_id)}

    def put_secret(
        self, source_id: str, body: SecretBody, actor: Annotated[ActorContext, Depends(actor_of)]
    ) -> Doc:
        """Store the source's secret and point its auth at it (basic or bearer auth only)."""
        actor.require("config.edit")
        site, source = self._existing(source_id)
        auth = dict(source.get("auth") or {})
        if auth.get("kind") not in SECRET_KINDS:
            raise HTTPException(status_code=409, detail="set auth kind basic or bearer first")
        ref = ref_for_source(source_id)
        pointed = {**source, "auth": {"kind": auth["kind"], "credential_ref": ref}}
        updated = _checked(_with_source(site, pointed))
        self._audit("source_secret_set", actor, source=source_id)
        self._write_secret(ref, body.value)
        save_site(self.root, updated)
        return {"source": source_id, "stored": True}

    def delete_secret(
        self, source_id: str, actor: Annotated[ActorContext, Depends(actor_of)]
    ) -> Doc:
        """Forget the stored secret; the source keeps its reference and fails until a new one."""
        actor.require("config.edit")
        self._existing(source_id)
        self._audit("source_secret_deleted", actor, source=source_id)
        self._forget(source_id)
        return {"source": source_id, "stored": False}

    def test_draft(
        self, body: Annotated[Doc, Body()], actor: Annotated[ActorContext, Depends(actor_of)]
    ) -> Doc:
        """Try a source entry before saving it: connect and report the capabilities."""
        actor.require("connector.use")
        _checked(_with_source(_site(self.root), {**body, "id": str(body.get("id") or "draft")}))
        try:
            caps = sorted(connector_from_source(body).capabilities())
        except (ConnectorError, ValueError) as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return {"status": "ok", "capabilities": caps}

    def _existing(self, source_id: str) -> tuple[Doc, Doc]:
        """The site and the named source; 404 when it does not exist."""
        site = _site(self.root)
        at = _index(site, source_id)
        if at is None:
            raise HTTPException(status_code=404, detail="no such source")
        return site, site["sources"][at]

    def _stored(self, source_id: str) -> bool:
        """True when the secret store holds a value for the source (False if the store is down)."""
        try:
            return self._store().get(ref_for_source(source_id)) is not None
        except (SecretStoreError, ValueError):
            return False

    def _write_secret(self, ref: str, value: str) -> None:
        """Write to the secret store; 503 when the store is unavailable."""
        try:
            self._store().set(ref, value)
        except SecretStoreError as error:
            raise HTTPException(status_code=503, detail=str(error)) from None

    def _forget(self, source_id: str) -> None:
        """Delete the stored secret; 503 when the store is unavailable."""
        try:
            self._store().delete(ref_for_source(source_id))
        except SecretStoreError as error:
            raise HTTPException(status_code=503, detail=str(error)) from None

    def _audit(self, event: str, actor: ActorContext, **fields: str) -> None:
        """Append to the API auth audit; no audit line, no change (503)."""
        audit = AuthAudit(auth_dir(self.root) / AUDIT_FILE, self._clock)
        try:
            audit.append(event, actor=actor.actor, source_ip=actor.source_ip, **fields)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail="audit_unavailable") from error


def build_source_admin_router(
    root: Path,
    store: Callable[[], SecretStore] = default_store,
    clock: Callable[[], float] = time.time,
) -> APIRouter:
    """Routes that add, edit and delete sources and their secrets."""
    e = _Endpoints(root, store, clock)
    router = APIRouter()
    router.add_api_route("/sources/test-draft", e.test_draft, methods=["POST"])
    router.add_api_route("/sources/{source_id}", e.put_source, methods=["PUT"])
    router.add_api_route("/sources/{source_id}", e.delete_source, methods=["DELETE"])
    router.add_api_route("/sources/{source_id}/secret", e.secret_status, methods=["GET"])
    router.add_api_route("/sources/{source_id}/secret", e.put_secret, methods=["PUT"])
    router.add_api_route("/sources/{source_id}/secret", e.delete_secret, methods=["DELETE"])
    return router

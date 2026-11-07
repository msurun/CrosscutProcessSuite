"""Two-person routes for the Crosscut auth API (ADR 013): password resets and approvals.

With ``require_second_admin_for_password_reset`` on, ``POST /auth/users/{u}/password-reset``
only creates a pending change; a different administrator approves it with step-up.
Passwords are stored as scrypt records, never as plaintext, and never returned.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from crosscut_api.auth.deps import AuthContext, AuthGuards, Principal, client_ip
from crosscut_api.auth.pending import KIND_PASSWORD_RESET
from crosscut_api.auth.store import UserNotFoundError
from crosscut_api.auth_user_routes import PERMISSION, JsonBody, public_view, reset_changes


class _PendingEndpoints:
    """Handlers for the password-reset request, the pending list and approval."""

    def __init__(self, ctx: AuthContext, guards: AuthGuards) -> None:
        """Bind the handlers to the auth context and its permission guards."""
        self._ctx = ctx
        self._guards = guards
        self.read_guard = guards.require(PERMISSION)
        self.write_guard = guards.require_stepup(PERMISSION)

    def list_pending(self) -> dict[str, Any]:
        """Return the live pending changes without their stored values."""
        return {"pending": [item.public() for item in self._ctx.pending.items()]}

    def password_reset(
        self, username: str, request: Request, body: JsonBody, response: Response
    ) -> dict[str, Any]:
        """Reset another user's password, or create the pending change for a second admin."""
        ctx = self._ctx
        actor = self._guards.principal(request)
        if actor.username == username:
            raise HTTPException(status_code=403, detail="use /auth/password for your own password")
        if ctx.users.get(username) is None:
            raise HTTPException(status_code=404, detail="user not found")
        changes = reset_changes(ctx, body.get("password"))
        if not ctx.config.require_second_admin:
            return self._apply(actor, request, username, changes)
        item = ctx.pending.add(KIND_PASSWORD_RESET, username, actor.username, changes)
        ctx.audit.append(
            "pending_create", actor=actor.username, target=username, kind=item.kind, id=item.id
        )
        response.status_code = 202
        return item.public()

    def approve(self, pending_id: str, request: Request) -> dict[str, Any]:
        """Apply a pending change approved by an administrator other than its requester."""
        ctx = self._ctx
        actor = self._guards.principal(request)
        item = ctx.pending.get(pending_id)
        if item is None:
            raise HTTPException(status_code=404, detail="pending change not found")
        if item.requested_by == actor.username:
            raise HTTPException(status_code=403, detail="cannot approve own change")
        ctx.pending.remove(pending_id)
        self._apply(actor, request, item.target, item.changes)
        ctx.audit.append(
            "pending_approve",
            actor=actor.username,
            target=item.target,
            kind=item.kind,
            requested_by=item.requested_by,
            ip=client_ip(request),
        )
        return item.public()

    def _apply(
        self, actor: Principal, request: Request, username: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        """Store the changes, revoke the target's sessions and audit the update."""
        try:
            after = self._ctx.users.update(username, changes)
        except UserNotFoundError as exc:
            raise HTTPException(status_code=404, detail="user not found") from exc
        self._ctx.sessions.destroy_user(username)
        self._ctx.audit.append(
            "user_update",
            actor=actor.username,
            target=username,
            ip=client_ip(request),
            fields=",".join(sorted(k for k in changes if k != "password")) or "password",
        )
        return public_view(after)


def build_pending_router(ctx: AuthContext, guards: AuthGuards) -> APIRouter:
    """Build the two-person router (under /auth); writes also need step-up."""
    endpoints = _PendingEndpoints(ctx, guards)
    reads = [Depends(endpoints.read_guard)]
    writes = [Depends(endpoints.write_guard)]
    router = APIRouter(prefix="/auth", tags=["auth"])
    router.add_api_route("/pending", endpoints.list_pending, methods=["GET"], dependencies=reads)
    router.add_api_route(
        "/users/{username}/password-reset",
        endpoints.password_reset,
        methods=["POST"],
        dependencies=writes,
    )
    router.add_api_route(
        "/pending/{pending_id}/approve", endpoints.approve, methods=["POST"], dependencies=writes
    )
    return router


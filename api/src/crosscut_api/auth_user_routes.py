"""Admin user-management routes for the Crosscut auth API (ADR 013).

Lists, creates, updates and deletes local users under the ``users.manage`` permission.
Mutating routes require step-up login. Passwords and hashes are never logged,
audited or returned, and sessions are revoked when credentials or access change.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from crosscut_api.auth.deps import AuthContext, AuthGuards, Principal, client_ip, json_body
from crosscut_api.auth.lockout import to_iso
from crosscut_api.auth.passwords import hash_password, password_problem
from crosscut_api.auth.store import UserExistsError, UserNotFoundError, new_user_record

PERMISSION = "users.manage"
USERNAME_PATTERN = re.compile(r"[a-z][a-z0-9._-]{2,31}")
PUBLIC_FIELDS = (
    "username",
    "display_name",
    "roles",
    "disabled",
    "must_change_password",
    "created_at",
    "password_changed_at",
    "failed_logins",
    "locked_until",
    "source",
)
EDITABLE_FIELDS = frozenset(
    {"display_name", "roles", "disabled", "must_change_password", "password"}
)
ACCOUNT_FIELDS = frozenset({"roles", "disabled"})
SESSION_FIELDS = frozenset({"roles", "disabled", "password"})
JsonBody = Annotated[dict[str, Any], Depends(json_body)]


def public_view(user: dict[str, Any]) -> dict[str, Any]:
    """Return the client-facing view of a user record; the password object is excluded."""
    return {field: user.get(field) for field in PUBLIC_FIELDS}


def _checked_str(value: object, name: str) -> str:
    """Return a required string value, raising 422 when it is absent or not a string."""
    if value is None:
        raise HTTPException(status_code=422, detail=f"{name} is required")
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{name} must be a string")
    return value


def _checked_username(value: object) -> str:
    """Return a username that matches the naming pattern."""
    username = _checked_str(value, "username")
    if USERNAME_PATTERN.fullmatch(username) is None:
        raise HTTPException(status_code=422, detail="invalid username")
    return username


def _checked_display_name(value: object) -> str:
    """Return a display name that is not blank."""
    name = _checked_str(value, "display_name")
    if not name.strip():
        raise HTTPException(status_code=422, detail="display_name must not be blank")
    return name


def _checked_flag(value: object, name: str) -> bool:
    """Return a boolean field value, raising 422 when it is not a boolean."""
    if not isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"{name} must be a boolean")
    return value


def _checked_roles(ctx: AuthContext, value: object) -> list[str]:
    """Return a non-empty, unique list of role names that all exist in the role table."""
    if not isinstance(value, list) or not value:
        raise HTTPException(status_code=422, detail="roles must be a non-empty list")
    if not all(isinstance(role, str) for role in value):
        raise HTTPException(status_code=422, detail="roles must be strings")
    if len(set(value)) != len(value):
        raise HTTPException(status_code=422, detail="roles must be unique")
    if not all(ctx.roles.known(role) for role in value):
        raise HTTPException(status_code=422, detail="unknown role")
    return [str(role) for role in value]


def _password_record(ctx: AuthContext, value: object) -> dict[str, Any]:
    """Validate a new password and return its scrypt record; the plaintext is not kept."""
    password = _checked_str(value, "password")
    problem = password_problem(password, ctx.config.min_password_length)
    if problem is not None:
        raise HTTPException(status_code=422, detail=problem)
    return hash_password(password, ctx.config.scrypt)


def _build_user(ctx: AuthContext, body: dict[str, Any]) -> dict[str, Any]:
    """Validate a create body and build the schema-valid user record to store."""
    user = new_user_record(
        _checked_username(body.get("username")),
        _checked_display_name(body.get("display_name")),
        _checked_roles(ctx, body.get("roles")),
        _password_record(ctx, body.get("password")),
        ctx.clock(),
    )
    user["must_change_password"] = _checked_flag(
        body.get("must_change_password", True), "must_change_password"
    )
    return user


def _reset_changes(ctx: AuthContext, value: object) -> dict[str, Any]:
    """Return the changes of an administrative password reset, which forces a new password."""
    return {
        "password": _password_record(ctx, value),
        "password_changed_at": to_iso(ctx.clock()),
        "must_change_password": True,
        "failed_logins": 0,
        "locked_until": None,
    }


def _field_changes(ctx: AuthContext, name: str, value: object) -> dict[str, Any]:
    """Validate one editable field of a PATCH body and return its stored changes."""
    if name == "display_name":
        return {name: _checked_display_name(value)}
    if name == "roles":
        return {name: _checked_roles(ctx, value)}
    if name == "password":
        return _reset_changes(ctx, value)
    return {name: _checked_flag(value, name)}


def _update_changes(ctx: AuthContext, body: dict[str, Any], is_self: bool) -> dict[str, Any]:
    """Validate a PATCH body and return the field changes to store."""
    if set(body) - EDITABLE_FIELDS:
        raise HTTPException(status_code=422, detail="unknown field")
    if is_self and set(body) & ACCOUNT_FIELDS:
        raise HTTPException(status_code=403, detail="cannot change own roles or disabled flag")
    if is_self and "password" in body:
        raise HTTPException(status_code=403, detail="use /auth/password for your own password")
    changes: dict[str, Any] = {}
    for name, value in body.items():
        changes.update(_field_changes(ctx, name, value))
    return changes


def _update_audit_fields(
    body: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, str]:
    """Describe an update for the audit log: changed field names and role transitions only."""
    fields = {"fields": ",".join(sorted(body))}
    if "roles" in body:
        fields["old_roles"] = ",".join(before.get("roles", []))
        fields["new_roles"] = ",".join(after.get("roles", []))
    return fields


class _UserEndpoints:
    """Synchronous handlers for the user admin routes."""

    def __init__(self, ctx: AuthContext, guards: AuthGuards) -> None:
        """Bind the handlers to the auth context and its permission guards."""
        self._ctx = ctx
        self._guards = guards
        self.read_guard = guards.require(PERMISSION)
        self.write_guard = guards.require_stepup(PERMISSION)

    def _actor(self, request: Request) -> Principal:
        """Return the caller; the write guard has already validated the request."""
        return self._guards.principal(request)

    def _existing(self, username: str) -> dict[str, Any]:
        """Return a user record, raising 404 when it does not exist."""
        user = self._ctx.users.get(username)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        return user

    def list_users(self) -> dict[str, Any]:
        """Return every user, sorted by username, in the public view."""
        users = sorted(self._ctx.users.list_users(), key=lambda user: str(user["username"]))
        return {"users": [public_view(user) for user in users]}

    def get_user(self, username: str) -> dict[str, Any]:
        """Return one user in the public view."""
        return public_view(self._existing(username))

    def create_user(self, request: Request, body: JsonBody) -> dict[str, Any]:
        """Create a local user; the response is the public view, never the password."""
        actor = self._actor(request)
        user = _build_user(self._ctx, body)
        try:
            self._ctx.users.create(user)
        except UserExistsError as exc:
            raise HTTPException(status_code=409, detail="user exists") from exc
        self._ctx.audit.append(
            "user_create",
            actor=actor.username,
            target=user["username"],
            roles=",".join(user["roles"]),
            ip=client_ip(request),
        )
        return public_view(user)

    def update_user(self, username: str, request: Request, body: JsonBody) -> dict[str, Any]:
        """Apply a validated PATCH; access-related changes revoke the user's sessions."""
        actor = self._actor(request)
        before = self._existing(username)
        changes = _update_changes(self._ctx, body, is_self=actor.username == username)
        try:
            after = self._ctx.users.update(username, changes)
        except UserNotFoundError as exc:
            raise HTTPException(status_code=404, detail="user not found") from exc
        if set(body) & SESSION_FIELDS:
            self._ctx.sessions.destroy_user(username)
        self._ctx.audit.append(
            "user_update",
            actor=actor.username,
            target=username,
            ip=client_ip(request),
            **_update_audit_fields(body, before, after),
        )
        return public_view(after)

    def delete_user(self, username: str, request: Request) -> dict[str, bool]:
        """Delete a user and revoke its sessions; administrators cannot delete themselves."""
        actor = self._actor(request)
        if actor.username == username:
            raise HTTPException(status_code=403, detail="cannot delete own account")
        try:
            self._ctx.users.delete(username)
        except UserNotFoundError as exc:
            raise HTTPException(status_code=404, detail="user not found") from exc
        self._ctx.sessions.destroy_user(username)
        self._ctx.audit.append(
            "user_delete",
            actor=actor.username,
            target=username,
            ip=client_ip(request),
        )
        return {"ok": True}


def build_users_router(ctx: AuthContext, guards: AuthGuards) -> APIRouter:
    """Build the users router (under /auth); writes also need step-up."""
    endpoints = _UserEndpoints(ctx, guards)
    reads = [Depends(endpoints.read_guard)]
    writes = [Depends(endpoints.write_guard)]
    router = APIRouter(prefix="/auth/users", tags=["auth"])
    router.add_api_route("", endpoints.list_users, methods=["GET"], dependencies=reads)
    router.add_api_route("/{username}", endpoints.get_user, methods=["GET"], dependencies=reads)
    router.add_api_route(
        "", endpoints.create_user, methods=["POST"], status_code=201, dependencies=writes
    )
    router.add_api_route(
        "/{username}", endpoints.update_user, methods=["PATCH"], dependencies=writes
    )
    router.add_api_route(
        "/{username}", endpoints.delete_user, methods=["DELETE"], dependencies=writes
    )
    return router

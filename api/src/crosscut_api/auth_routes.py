"""Authentication HTTP routes: login, logout, session, password change and step-up.

Handlers are thin and delegate to the services in ``crosscut_api.auth``. Passwords,
hashes and tokens are never logged, audited or returned; login and me return the
session CSRF token, which the client needs for unsafe requests.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from crosscut_api.auth import lockout, passwords
from crosscut_api.auth.deps import (
    COOKIE_NAME,
    AuthContext,
    AuthGuards,
    Principal,
    build_auth_context,
    check_origin,
    client_ip,
    json_body,
    session_payload,
    string_field,
)
from crosscut_api.auth.roles import RoleTable
from crosscut_api.auth.sessions import AuthConfig, Session
from crosscut_api.auth.store import UserStore
from crosscut_api.auth_user_routes import build_users_router

DEFAULT_CONFIG: AuthConfig = AuthConfig()
ATTEMPT_NAME_LIMIT = 64


def _attempted(username: str) -> str:
    """Return a submitted username as it may appear in the audit log (truncated)."""
    return username[:ATTEMPT_NAME_LIMIT]


def _principal_for(
    user: dict[str, Any],
    session: Session,
    token: str,
    roles: RoleTable,
) -> Principal:
    """Build the caller's principal from a fresh user record and its session."""
    known = tuple(name for name in user.get("roles", []) if roles.known(name))
    return Principal(
        username=session.username,
        display_name=str(user.get("display_name", "")),
        roles=known,
        permissions=roles.permissions_for(known),
        must_change_password=bool(user.get("must_change_password", False)),
        session=session,
        token=token,
    )


def _field(body: dict[str, Any], name: str) -> str:
    """Return a required string field; ``string_field`` raises 422 when it is invalid."""
    value = string_field(body, name)
    return "" if value is None else value


def _stored_user(ctx: AuthContext, username: str) -> dict[str, Any]:
    """Return the stored record of the signed-in user, or 401 when it has vanished."""
    user = ctx.users.get(username)
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def _check_new_password(old: str, new: str, config: AuthConfig) -> None:
    """Enforce the password policy and require the new password to differ from the old."""
    problem = passwords.password_problem(new, config.min_password_length)
    if problem is not None:
        raise HTTPException(status_code=422, detail=problem)
    if new == old:
        raise HTTPException(status_code=422, detail="new password must differ")


def _password_changes(new: str, ctx: AuthContext) -> dict[str, Any]:
    """Build the user-record changes that store a newly chosen password."""
    return {
        "password": passwords.hash_password(new, ctx.config.scrypt),
        "password_changed_at": lockout.to_iso(ctx.clock()),
        "must_change_password": False,
        **lockout.success_changes(),
    }


class _AuthEndpoints:
    """HTTP endpoint handlers for login, logout, session inspection and re-authentication."""

    def __init__(self, ctx: AuthContext, guards: AuthGuards) -> None:
        """Bind the handlers to the shared auth context and guards."""
        self._ctx = ctx
        self._guards = guards

    def login(
        self,
        request: Request,
        response: Response,
        body: Annotated[dict[str, Any], Depends(json_body)],
    ) -> dict[str, Any]:
        """Verify username and password, then open a session with its cookie."""
        ip = self._admit(request)
        username = _field(body, "username")
        password = _field(body, "password")
        user = self._active_user(username, password, ip)
        self._ensure_unlocked(user, ip)
        if not passwords.verify_password(password, user["password"]):
            self._record_failure(user, ip, "login_fail", reason="bad_password")
            raise HTTPException(status_code=401, detail="invalid credentials")
        return self._open_session(request, response, user)

    def logout(self, request: Request, response: Response) -> dict[str, bool]:
        """Destroy the current session and clear its cookie."""
        principal = self._guards.authenticated(request)
        self._ctx.sessions.destroy(principal.token)
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
        self._ctx.audit.append(
            "logout",
            actor=principal.username,
            ip=client_ip(request),
            sid=principal.session.sid,
        )
        return {"ok": True}

    def me(self, request: Request) -> dict[str, Any]:
        """Describe the signed-in caller and its session."""
        principal = self._guards.authenticated(request)
        return session_payload(principal, self._ctx)

    def change_password(
        self,
        request: Request,
        body: Annotated[dict[str, Any], Depends(json_body)],
    ) -> dict[str, bool]:
        """Replace the caller's password and end its other sessions."""
        principal = self._guards.authenticated(request)
        ip = client_ip(request)
        old = _field(body, "old_password")
        new = _field(body, "new_password")
        user = _stored_user(self._ctx, principal.username)
        if not passwords.verify_password(old, user["password"]):
            self._record_failure(user, ip, "password_change_fail")
            raise HTTPException(status_code=403, detail="current password is incorrect")
        _check_new_password(old, new, self._ctx.config)
        self._ctx.users.update(principal.username, _password_changes(new, self._ctx))
        self._ctx.sessions.destroy_user(principal.username, keep=principal.session.key)
        self._ctx.audit.append(
            "password_change",
            actor=principal.username,
            ip=ip,
            sid=principal.session.sid,
        )
        return {"ok": True}

    def stepup(
        self,
        request: Request,
        body: Annotated[dict[str, Any], Depends(json_body)],
    ) -> dict[str, Any]:
        """Re-verify the caller's password to mark the session as recently authenticated."""
        principal = self._guards.authenticated(request)
        ip = client_ip(request)
        password = _field(body, "password")
        user = _stored_user(self._ctx, principal.username)
        if not passwords.verify_password(password, user["password"]):
            self._record_failure(user, ip, "stepup_fail")
            raise HTTPException(status_code=403, detail="password is incorrect")
        self._ctx.sessions.mark_stepup(principal.session)
        self._ctx.audit.append(
            "stepup_ok",
            actor=principal.username,
            ip=ip,
            sid=principal.session.sid,
        )
        return {"ok": True, "valid_for_s": self._ctx.config.stepup_valid_s}

    def _admit(self, request: Request) -> str:
        """Check initialisation, origin and the per-IP rate limit; return the client IP."""
        ctx = self._ctx
        if not ctx.users.initialised():
            raise HTTPException(status_code=503, detail="not initialised")
        check_origin(request, ctx.config)
        ip = client_ip(request)
        if not ctx.limiter.allow(ip):
            ctx.audit.append("login_rate_limited", ip=ip)
            raise HTTPException(status_code=429, detail="too many attempts")
        return ip

    def _active_user(self, username: str, password: str, ip: str) -> dict[str, Any]:
        """Return the enabled user record; unknown or disabled accounts still burn a hash."""
        ctx = self._ctx
        user = ctx.users.get(username)
        if user is not None and not user.get("disabled"):
            return user
        passwords.dummy_verify(password, ctx.config.scrypt)
        reason = "unknown_user" if user is None else "disabled"
        ctx.audit.append("login_fail", actor=_attempted(username), ip=ip, reason=reason)
        raise HTTPException(status_code=401, detail="invalid credentials")

    def _ensure_unlocked(self, user: dict[str, Any], ip: str) -> None:
        """Reject the login with 423 and a Retry-After header while the account is locked."""
        now = self._ctx.clock()
        if not lockout.is_locked(user, now):
            return
        self._ctx.audit.append("login_locked", actor=user["username"], ip=ip)
        retry_after = math.ceil(lockout.lock_remaining_s(user, now))
        raise HTTPException(
            status_code=423,
            detail="account locked",
            headers={"Retry-After": str(retry_after)},
        )

    def _record_failure(
        self,
        user: dict[str, Any],
        ip: str,
        event: str,
        **fields: object,
    ) -> None:
        """Count one failed attempt, audit it, and audit a lockout when it triggers."""
        ctx = self._ctx
        username = str(user["username"])
        changes, newly_locked = lockout.failure_changes(user, ctx.clock(), ctx.config)
        ctx.users.update(username, changes)
        ctx.audit.append(event, actor=_attempted(username), ip=ip, **fields)
        if newly_locked:
            ctx.audit.append(
                "lockout",
                actor=_attempted(username),
                ip=ip,
                locked_until=changes["locked_until"],
            )

    def _open_session(
        self,
        request: Request,
        response: Response,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        """Start a session for a verified user, set its cookie and audit the login."""
        ctx = self._ctx
        ip = client_ip(request)
        username = str(user["username"])
        fresh = ctx.users.update(username, lockout.success_changes())
        token, session = ctx.sessions.create(username, ip)
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            samesite="strict",
            path="/",
            secure=request.url.scheme == "https",
        )
        ctx.audit.append("login_ok", actor=username, ip=ip, sid=session.sid)
        principal = _principal_for(fresh, session, token, ctx.roles)
        return session_payload(principal, ctx)


def build_auth_router(
    root: Path,
    config: AuthConfig = DEFAULT_CONFIG,
    clock: Callable[[], float] = time.time,
    users: UserStore | None = None,
) -> APIRouter:
    """Create the ``/auth`` router and include the user-administration routes.

    Args:
        root: Data root holding the ``_auth`` folder.
        config: Authentication configuration.
        clock: Source of the current POSIX time.
        users: Optional user store; defaults to a JSON store under ``root``.

    Returns:
        The configured ``APIRouter``.
    """
    ctx = build_auth_context(root, config, clock, users)
    guards = AuthGuards(ctx)
    endpoints = _AuthEndpoints(ctx, guards)
    router = APIRouter(prefix="/auth", tags=["auth"])
    router.add_api_route("/login", endpoints.login, methods=["POST"])
    router.add_api_route("/logout", endpoints.logout, methods=["POST"])
    router.add_api_route("/me", endpoints.me, methods=["GET"])
    router.add_api_route("/password", endpoints.change_password, methods=["POST"])
    router.add_api_route("/stepup", endpoints.stepup, methods=["POST"])
    router.include_router(build_users_router(ctx, guards))
    return router

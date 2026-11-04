"""Authentication dependencies for the Crosscut API routes.

Builds the auth context, resolves the session principal from the cookie, and
exposes FastAPI dependencies for origin, CSRF, permission and step-up checks.
"""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.lockout import AttemptTracker, IpRateLimiter
from crosscut_api.auth.roles import RoleTable, load_roles
from crosscut_api.auth.sessions import AuthConfig, Session, SessionStore
from crosscut_api.auth.store import JsonUserStore, UserStore, auth_dir

COOKIE_NAME = "cc_session"
CSRF_HEADER = "X-Crosscut-CSRF"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
AUDIT_FILE = "auth-audit.jsonl"
_DEFAULT_CONFIG = AuthConfig()


@dataclass(frozen=True)
class AuthContext:
    """Shared authentication services for one API application."""

    config: AuthConfig
    clock: Callable[[], float]
    users: UserStore
    sessions: SessionStore
    roles: RoleTable
    audit: AuthAudit
    limiter: IpRateLimiter
    root: Path
    attempts: AttemptTracker = field(default_factory=AttemptTracker)


def build_auth_context(
    root: Path,
    config: AuthConfig = _DEFAULT_CONFIG,
    clock: Callable[[], float] = time.time,
    users: UserStore | None = None,
) -> AuthContext:
    """Create the authentication services rooted at a data directory.

    Args:
        root: Data root holding the ``_auth`` folder.
        config: Authentication configuration.
        clock: Source of the current POSIX time.
        users: Optional user store; defaults to a JSON store under ``root``.

    Returns:
        A fully wired ``AuthContext``.
    """
    return AuthContext(
        config=config,
        clock=clock,
        users=users if users is not None else JsonUserStore(root),
        sessions=SessionStore(config, clock),
        roles=load_roles(root),
        audit=AuthAudit(auth_dir(root) / AUDIT_FILE, clock),
        limiter=IpRateLimiter(config.ip_rate_limit, config.ip_rate_window_s, clock),
        root=root,
        attempts=AttemptTracker(),
    )


@dataclass(frozen=True)
class Principal:
    """The authenticated caller resolved for a single request."""

    username: str
    display_name: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    must_change_password: bool
    session: Session
    token: str


def client_ip(request: Request) -> str:
    """Return the client host address, or ``"unknown"`` when unavailable."""
    client = request.client
    return client.host if client is not None else "unknown"


def _body_error() -> HTTPException:
    """Return the 422 error used for request bodies that are not JSON objects."""
    return HTTPException(status_code=422, detail="body must be a JSON object")


async def json_body(request: Request) -> dict[str, Any]:
    """Parse the request body as a JSON object.

    The error response never echoes the submitted content.

    Args:
        request: The incoming request.

    Returns:
        The decoded JSON object.

    Raises:
        HTTPException: 422 when the body is not valid JSON or not an object.
    """
    try:
        body = await request.json()
    except ValueError:
        raise _body_error() from None
    if not isinstance(body, dict):
        raise _body_error()
    return body


def string_field(body: dict[str, Any], name: str, required: bool = True) -> str | None:
    """Return a string field from a parsed body, validating its type.

    Args:
        body: Parsed JSON object.
        name: Field name to read.
        required: Whether a missing or null field is an error.

    Returns:
        The string value, or ``None`` when an optional field is absent.

    Raises:
        HTTPException: 422 when a required field is missing or the value is not a string.
    """
    value = body.get(name)
    if value is None:
        if required:
            raise HTTPException(status_code=422, detail=f"{name} is required")
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{name} must be a string")
    return value


def check_origin(request: Request, config: AuthConfig) -> None:
    """Reject cross-origin requests that carry an Origin header not on the allow list.

    Args:
        request: The incoming request.
        config: Authentication configuration with the allowed origins.

    Raises:
        HTTPException: 403 when the Origin header is present and not allowed.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return
    same_origin = f"{request.url.scheme}://{request.headers.get('host')}"
    if origin != same_origin and origin not in config.allowed_origins:
        raise HTTPException(status_code=403, detail="origin not allowed")


def _build_principal(
    user: dict[str, Any],
    session: Session,
    token: str,
    role_table: RoleTable,
) -> Principal:
    """Assemble a principal from the current user record and role table."""
    known = tuple(name for name in user.get("roles", []) if role_table.known(name))
    return Principal(
        username=session.username,
        display_name=str(user.get("display_name", "")),
        roles=known,
        permissions=role_table.permissions_for(known),
        must_change_password=bool(user.get("must_change_password", False)),
        session=session,
        token=token,
    )


def _check_csrf(request: Request, principal: Principal) -> None:
    """Require the CSRF header to match the session's CSRF token.

    Raises:
        HTTPException: 403 when the header is missing or does not match.
    """
    supplied = request.headers.get(CSRF_HEADER, "")
    expected = principal.session.csrf
    if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="csrf token missing or invalid")


def _ensure_allowed(principal: Principal, permission: str) -> None:
    """Raise 403 when the principal must change its password or lacks the permission.

    Raises:
        HTTPException: 403 with a reason when access is denied.
    """
    if principal.must_change_password:
        raise HTTPException(status_code=403, detail="password change required")
    if permission not in principal.permissions:
        raise HTTPException(status_code=403, detail="forbidden")


class AuthGuards:
    """Factory of FastAPI dependencies that enforce authentication and authorisation."""

    def __init__(self, ctx: AuthContext) -> None:
        """Bind the guards to an auth context."""
        self._ctx = ctx

    def principal(self, request: Request) -> Principal:
        """Resolve the session principal from the cookie.

        Raises:
            HTTPException: 503 when the users file is missing, 401 when the session
                is absent, expired, or belongs to a missing or disabled user.
        """
        ctx = self._ctx
        if not ctx.users.initialised():
            raise HTTPException(status_code=503, detail="not initialised")
        token = request.cookies.get(COOKIE_NAME)
        session = ctx.sessions.get(token)
        if session is None or token is None:
            raise HTTPException(status_code=401, detail="not authenticated")
        user = ctx.users.get(session.username)
        if user is None or user.get("disabled"):
            ctx.sessions.destroy(token)
            raise HTTPException(status_code=401, detail="not authenticated")
        return _build_principal(user, session, token, ctx.roles)

    def authenticated(self, request: Request) -> Principal:
        """Return the principal; unsafe methods also need a valid origin and CSRF token."""
        principal = self.principal(request)
        if request.method not in SAFE_METHODS:
            check_origin(request, self._ctx.config)
            _check_csrf(request, principal)
        return principal

    def _checked(self, request: Request, permission: str) -> Principal:
        """Authenticate the request and require ``permission``."""
        principal = self.authenticated(request)
        _ensure_allowed(principal, permission)
        return principal

    def require(self, permission: str) -> Callable[[Request], Principal]:
        """Return a dependency that requires ``permission`` on an authenticated request."""

        def dependency(request: Request) -> Principal:
            """Run the authentication and permission checks for one request."""
            return self._checked(request, permission)

        return dependency

    def require_stepup(self, permission: str) -> Callable[[Request], Principal]:
        """Return a dependency that requires ``permission`` and a recent step-up login."""

        def dependency(request: Request) -> Principal:
            """Run the permission and step-up checks for one request."""
            principal = self._checked(request, permission)
            if not self._ctx.sessions.stepup_valid(principal.session):
                raise HTTPException(status_code=403, detail="step-up required")
            return principal

        return dependency


def session_payload(principal: Principal, ctx: AuthContext) -> dict[str, Any]:
    """Describe the caller's session for the client; contains no password data.

    Args:
        principal: The authenticated caller.
        ctx: The auth context used for the step-up check.

    Returns:
        A JSON-serialisable mapping of user, roles, permissions and session state.
    """
    return {
        "user": {"username": principal.username, "display_name": principal.display_name},
        "roles": list(principal.roles),
        "permissions": sorted(principal.permissions),
        "csrf": principal.session.csrf,
        "must_change_password": principal.must_change_password,
        "stepup_valid": ctx.sessions.stepup_valid(principal.session),
    }

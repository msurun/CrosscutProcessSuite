"""App-level FastAPI enforcer that authorises every request against the route table.

Default deny: a route missing from the permission table is refused, public routes
short-circuit, and step-up is required for sensitive writes. Stamps the resolved
actor on ``request.state`` so handlers never re-read the session.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request

from crosscut_api.auth.actor import STEPUP_PERMISSIONS, actor_from_principal
from crosscut_api.auth.deps import (
    PASSWORD_CHANGE_REQUIRED_DETAIL,
    SAFE_METHODS,
    STEP_UP_REQUIRED_DETAIL,
    AuthContext,
    AuthGuards,
    Principal,
    client_ip,
)
from crosscut_api.auth.route_permissions import AUTHENTICATED, PUBLIC_ROUTES, AnyOf, requirement_for

STEPUP_ERROR_DETAIL = STEP_UP_REQUIRED_DETAIL


def _route_key(request: Request) -> tuple[str, str]:
    """Return the (upper-case method, route path template) used as a table key."""
    route = request.scope.get("route")
    path = getattr(route, "path", "")
    return request.method.upper(), path


def _is_public(key: tuple[str, str]) -> bool:
    """Return ``True`` when the (method, path) pair is listed as public."""
    return key in PUBLIC_ROUTES


def _has_any(principal: Principal, permissions: frozenset[str] | tuple[str, ...]) -> bool:
    """Return ``True`` when the principal holds at least one of ``permissions``."""
    return any(permission in principal.permissions for permission in permissions)


def _check_requirement(principal: Principal, requirement: str | AnyOf) -> None:
    """Raise 403 unless the principal satisfies the route requirement.

    Args:
        principal: The authenticated caller.
        requirement: A single permission name or an ``AnyOf`` set.

    Raises:
        HTTPException: 403 ``"password_change_required"`` when the user must rotate
            the password; 403 ``"forbidden"`` when the permission is missing.
    """
    if principal.must_change_password:
        raise HTTPException(status_code=403, detail=PASSWORD_CHANGE_REQUIRED_DETAIL)
    if isinstance(requirement, str):
        allowed = requirement in principal.permissions
    elif isinstance(requirement, AnyOf):
        allowed = _has_any(principal, requirement.permissions)
    else:
        raise TypeError(f"unsupported route requirement type: {type(requirement).__name__}")
    if not allowed:
        raise HTTPException(status_code=403, detail="forbidden")


def _require_stepup(
    ctx: AuthContext,
    principal: Principal,
    requirement: str | AnyOf,
    method: str,
) -> None:
    """Raise 428 when an unsafe request needs a fresh step-up login.

    Safe methods (GET/HEAD/OPTIONS) never require step-up. Only a plain
    permission name can appear in ``STEPUP_PERMISSIONS``.

    Raises:
        HTTPException: 428 with ``"step_up_required"`` when step-up is stale.
    """
    if method in SAFE_METHODS:
        return
    if not isinstance(requirement, str) or requirement not in STEPUP_PERMISSIONS:
        return
    if not ctx.sessions.stepup_valid(principal.session):
        raise HTTPException(status_code=428, detail=STEPUP_ERROR_DETAIL)


def _resolve_requirement(method: str, path: str) -> str | AnyOf:
    """Return the requirement for a route, refusing unmapped routes.

    Raises:
        HTTPException: 403 ``"route not permitted"`` when the route is unmapped.
    """
    requirement = requirement_for(method, path)
    if requirement is None:
        raise HTTPException(status_code=403, detail="route not permitted")
    return requirement


def _authenticate(guards: AuthGuards, request: Request) -> Principal:
    """Return the authenticated principal, or raise the guard's HTTP error."""
    return guards.authenticated(request)


def make_enforcer(guards: AuthGuards, ctx: AuthContext) -> Callable[[Request], None]:
    """Build the app-level dependency that authorises each request.

    The returned dependency runs in order: skip public routes, authenticate,
    look up the requirement (default deny), enforce permission and step-up,
    then attach the resolved actor to ``request.state.actor``.

    Args:
        guards: The auth guards bound to ``ctx``.
        ctx: The shared auth context used for session step-up checks.

    Returns:
        A plain function usable with ``FastAPI(dependencies=[Depends(enforcer)])``.
    """

    def enforce(request: Request) -> None:
        """Authorise the request and stamp ``request.state.actor``."""
        method, path = _route_key(request)
        if _is_public((method, path)):
            return
        principal = _authenticate(guards, request)
        requirement = _resolve_requirement(method, path)
        if requirement != AUTHENTICATED:
            _check_requirement(principal, requirement)
        _require_stepup(ctx, principal, requirement, method)
        stepup_ok = ctx.sessions.stepup_valid(principal.session)
        request.state.actor = actor_from_principal(principal, stepup_ok, client_ip(request))

    return enforce

"""Actor context for the Crosscut API routes.

Provides the actor context for the API routes, which is used to determine the
permissions and roles of the actor.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from crosscut_api.auth.deps import STEP_UP_REQUIRED_DETAIL, Principal, client_ip

STEPUP_PERMISSIONS: frozenset[str] = frozenset(
    {"gw.mode.up.supervised", "policy.pin", "gw.kill.reset", "users.manage"}
)
# Routes that need a fresh step-up whatever permission they map to (method, path template).
STEPUP_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/tuning/proposals/{proposal_id}/escape"),
        ("POST", "/tuning/intents/{key}/resolve"),
    }
)

@dataclass(frozen=True)
class ActorContext:
    """The actor context for the API routes."""

    actor: str
    roles: tuple[str, ...]
    session: str
    source_ip: str
    stepup: bool
    permissions: frozenset[str] | None

    def can(self, permission: str) -> bool:
        """Return True if the actor has the permission.

        Args:
            permission: The permission to check.

        Returns:
            True if the actor has the permission, False otherwise.
        """
        return self.permissions is None or permission in self.permissions

    def require(self, permission: str) -> None:
        """Raise 403 when the actor does not have the permission.

        Args:
            permission: The permission to check.

        Raises:
            HTTPException: 403 when the actor does not have the permission.
        """
        if not self.can(permission):
            raise HTTPException(status_code=403, detail="forbidden")

    def require_stepup(self) -> None:
        """Raise 428 when the actor does not have a valid step-up.

        Raises:
            HTTPException: 428 when the actor does not have a valid step-up.
        """
        if not self.stepup:
            raise HTTPException(status_code=428, detail=STEP_UP_REQUIRED_DETAIL)

def local_actor(source_ip: str) -> ActorContext:
    """Return the actor context for a local actor.

    Args:
        source_ip: The source IP address of the actor.

    Returns:
        The actor context for a local actor.
    """
    return ActorContext(
        actor="local-dev",
        roles=("lead",),
        session="0" * 16,
        source_ip=source_ip,
        stepup=True,
        permissions=None,
    )

def actor_of(request: Request) -> ActorContext:
    """Return the actor context for the request, failing closed when auth is on.

    The local actor (full authority) is used only when authentication is disabled. With
    authentication enabled, a request that carries no stamped actor is refused.

    Args:
        request: The request to get the actor context for.

    Returns:
        The actor context for the request.

    Raises:
        HTTPException: 401 when auth is enabled and no actor was stamped on the request.
    """
    stamped = getattr(request.state, "actor", None)
    if stamped:
        return stamped
    if getattr(request.app.state, "auth_enabled", False):
        raise HTTPException(status_code=401, detail="not authenticated")
    return local_actor(client_ip(request))

def actor_from_principal(principal: Principal, stepup: bool, source_ip: str) -> ActorContext:
    """Return the actor context for the principal.

    Args:
        principal: The principal to get the actor context for.
        stepup: Whether the actor has a valid step-up.
        source_ip: The source IP address of the actor.

    Returns:
        The actor context for the principal.
    """
    return ActorContext(
        actor=principal.username,
        roles=principal.roles,
        session=principal.session.sid,
        source_ip=source_ip,
        stepup=stepup,
        permissions=principal.permissions,
    )

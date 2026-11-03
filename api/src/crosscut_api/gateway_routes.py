"""HTTP routes over the Write Gateway engine (Phase 2, #46).

Provides status inspection, pending proposal approval, mode management, target
re-enabling, emergency kill, and cryptographic audit log queries.
Roles are not implemented yet (#47): every route is unauthenticated until #47,
and confirm/approve must later require the engineer role.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

VALID_MODES: frozenset[str] = frozenset(
    {"off", "advisory", "dry_run", "confirm", "supervised"}
)


class ModeUpdate(BaseModel):
    """Payload for updating the operating mode of the gateway."""

    mode: str


class GatewayClient(Protocol):
    """Operations the HTTP layer needs from a running Write Gateway process."""

    def mode(self) -> str:
        """Return the active operating mode."""

    def status(self) -> dict[str, str]:
        """Return the state of each target tag."""

    def pending(self) -> list[dict[str, str | float | int]]:
        """Return proposals awaiting confirmation, each with its stable key."""

    def approve(self, key: str) -> dict[str, object]:
        """Approve and execute a queued proposal; raises KeyError if unknown."""

    def reject(self, key: str) -> None:
        """Discard a queued proposal without writing; raises KeyError if unknown."""

    def kill(self) -> None:
        """Trigger the emergency kill switch on all targets."""

    def re_enable(self, tag: str) -> None:
        """Re-enable a stopped target; ValueError if refused, KeyError if unknown."""

    def set_mode(self, mode: str) -> None:
        """Change the operating mode; raises ValueError if invalid."""

    def audit(self, limit: int) -> dict[str, object]:
        """Return the newest audit records and the chain integrity flag."""


def _resolve_gateway(provider: Callable[[], GatewayClient | None]) -> GatewayClient:
    """Resolve the running gateway from the provider, or raise HTTP 503."""
    gateway = provider()
    if gateway is None:
        raise HTTPException(status_code=503, detail="gateway not running")
    return gateway


def _validate_mode(mode: str) -> str:
    """Validate that mode is one of the recognized gateway operating modes."""
    if mode not in VALID_MODES:
        raise HTTPException(status_code=422, detail=f"unknown mode: {mode}")
    return mode


class _GatewayEndpoints:
    """Route handler collection bound to a GatewayClient provider."""

    def __init__(self, provider: Callable[[], GatewayClient | None]) -> None:
        self._provider = provider

    def _gw(self) -> GatewayClient:
        return _resolve_gateway(self._provider)

    def get_status(self) -> dict[str, Any]:
        """GET /gateway/status: Current mode, per-target states, and pending count."""
        gw = self._gw()
        return {
            "mode": gw.mode(),
            "targets": gw.status(),
            "pending": len(gw.pending()),
        }

    def get_pending(self) -> list[dict[str, str | float | int]]:
        """GET /gateway/pending: List of proposals awaiting confirmation."""
        gw = self._gw()
        return gw.pending()

    def post_approve(self, key: str) -> dict[str, Any]:
        """POST /gateway/pending/{key}/approve: Approve and execute queued proposal."""
        gw = self._gw()
        try:
            return gw.approve(key)
        except KeyError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except TimeoutError as err:
            raise HTTPException(status_code=504, detail="gateway did not answer") from err

    def post_reject(self, key: str) -> dict[str, Any]:
        """POST /gateway/pending/{key}/reject: Discard queued proposal without writing."""
        gw = self._gw()
        try:
            gw.reject(key)
        except KeyError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except TimeoutError as err:
            raise HTTPException(status_code=504, detail="gateway did not answer") from err
        return {"ok": True}

    def post_kill(self) -> dict[str, Any]:
        """POST /gateway/kill: Trigger emergency kill switch."""
        gw = self._gw()
        try:
            gw.kill()
        except TimeoutError as err:
            raise HTTPException(status_code=504, detail="gateway did not answer") from err
        return {"ok": True}

    def post_re_enable(self, tag: str) -> dict[str, Any]:
        """POST /gateway/targets/{tag}/re-enable: Re-enable a stopped target."""
        gw = self._gw()
        try:
            gw.re_enable(tag)
        except ValueError as err:
            raise HTTPException(status_code=409, detail=str(err)) from err
        except KeyError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except TimeoutError as err:
            raise HTTPException(status_code=504, detail="gateway did not answer") from err
        return {"ok": True}

    def put_mode(self, body: ModeUpdate) -> dict[str, Any]:
        """PUT /gateway/mode: Change operating mode of the gateway."""
        gw = self._gw()
        valid_mode = _validate_mode(body.mode)
        try:
            gw.set_mode(valid_mode)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
        except TimeoutError as err:
            raise HTTPException(status_code=504, detail="gateway did not answer") from err
        return {"ok": True, "mode": valid_mode}

    def get_audit(self, limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, Any]:
        """GET /gateway/audit: Return newest audit records and chain integrity flag."""
        gw = self._gw()
        return gw.audit(limit)


def build_gateway_router(provider: Callable[[], GatewayClient | None]) -> APIRouter:
    """Construct and return the FastAPI router for Write Gateway management."""
    endpoints = _GatewayEndpoints(provider)
    router = APIRouter(prefix="/gateway")
    router.add_api_route("/status", endpoints.get_status, methods=["GET"])
    router.add_api_route("/pending", endpoints.get_pending, methods=["GET"])
    router.add_api_route("/pending/{key}/approve", endpoints.post_approve, methods=["POST"])
    router.add_api_route("/pending/{key}/reject", endpoints.post_reject, methods=["POST"])
    router.add_api_route("/kill", endpoints.post_kill, methods=["POST"])
    router.add_api_route("/targets/{tag}/re-enable", endpoints.post_re_enable, methods=["POST"])
    router.add_api_route("/mode", endpoints.put_mode, methods=["PUT"])
    router.add_api_route("/audit", endpoints.get_audit, methods=["GET"])
    return router


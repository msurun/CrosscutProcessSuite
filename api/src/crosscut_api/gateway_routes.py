"""HTTP routes over the Write Gateway engine (Phase 2, #46).

Provides status inspection, the live policy view, pending proposal approval, mode management,
target
re-enabling, emergency kill and kill reset, policy draft, pin and reload, and
cryptographic audit log queries.

Roles are enforced (ADR docs/adr/013-roles-and-authority.md). Permissions for
approve, reject, kill, reads and policy actions are checked app-level, and step-up
for kill reset and policy pin is enforced there too. Mode changes and re-enabling
are checked here because their permission depends on the current mode or target state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.deps import STEP_UP_REQUIRED_DETAIL
from crosscut_api.gateway_client import (
    EXPLAINED_FORBIDDEN,
    GatewayConflict,
    GatewaySigningError,
    StepUpRequired,
)

MODES: tuple[str, ...] = ("off", "advisory", "dry_run", "confirm", "supervised")
VALID_MODES: frozenset[str] = frozenset(MODES)
ActorDep = Annotated[ActorContext, Depends(actor_of)]


def policy_digest(document: dict[str, Any]) -> str:
    """Return the digest the gateway expects when pinning a policy document.

    It is the SHA-256 hex digest of the canonical JSON bytes: sorted keys, compact
    separators and unescaped UTF-8. The API cannot import the gateway, so this mirrors it.
    """
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ModeUpdate(BaseModel):
    """Payload for updating the operating mode of the gateway."""

    mode: str


class PolicyPin(BaseModel):
    """Payload for pinning a policy document by its digest."""

    digest: str


class GatewayClient(Protocol):
    """Operations the HTTP layer needs from a running Write Gateway process."""

    def mode(self) -> str:
        """Return the active operating mode."""

    def status(self) -> dict[str, str]:
        """Return the state of each target tag."""

    def pending(self) -> list[dict[str, str | float | int]]:
        """Return proposals awaiting confirmation, each with its stable key."""

    def approve(self, key: str, actor: ActorContext | None = None) -> dict[str, object]:
        """Approve and execute a queued proposal; raises KeyError if unknown."""

    def reject(self, key: str, actor: ActorContext | None = None) -> None:
        """Discard a queued proposal without writing; raises KeyError if unknown."""

    def kill(self, actor: ActorContext | None = None) -> None:
        """Trigger the emergency kill switch on all targets."""

    def kill_reset(self, actor: ActorContext | None = None) -> None:
        """Clear the emergency kill switch; raises ValueError if refused."""

    def re_enable(self, tag: str, actor: ActorContext | None = None) -> None:
        """Re-enable a stopped target; ValueError if refused, KeyError if unknown."""

    def set_mode(self, mode: str, actor: ActorContext | None = None) -> None:
        """Change the operating mode; raises ValueError if invalid."""

    def audit(self, limit: int) -> dict[str, object]:
        """Return the newest audit records and the chain integrity flag."""

    def draft_policy(self) -> dict[str, Any] | None:
        """Return the draft record {"document", "author", "saved_at"}, or None without one."""

    def live_policy(self) -> dict[str, Any] | None:
        """Return the verified live policy {"document", "pin"}, or None when not pinned."""

    def policy_draft(self, document: dict[str, Any], actor: ActorContext | None = None) -> None:
        """Store a new draft policy document; raises ValueError if refused."""

    def policy_pin(self, digest: str, actor: ActorContext | None = None) -> None:
        """Pin the policy with the given digest; raises ValueError if refused."""

    def policy_reload(self, actor: ActorContext | None = None) -> None:
        """Reload the pinned policy; raises ValueError if refused."""


@contextmanager
def _gateway_errors(value_error_status: int | None = None) -> Iterator[None]:
    """Translate gateway and permission failures into HTTP errors.

    A gateway state conflict is 409 and a missing step-up 428. Any other ValueError becomes
    value_error_status when one is given, and propagates otherwise.
    """
    try:
        yield
    except GatewaySigningError as err:
        raise HTTPException(status_code=503, detail=str(err)) from err
    except TimeoutError as err:
        raise HTTPException(status_code=504, detail="gateway did not answer") from err
    except StepUpRequired as err:
        raise HTTPException(status_code=428, detail=STEP_UP_REQUIRED_DETAIL) from err
    except PermissionError as err:
        detail = str(err) if str(err) in EXPLAINED_FORBIDDEN else "forbidden"
        raise HTTPException(status_code=403, detail=detail) from err
    except KeyError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except GatewayConflict as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    except ValueError as err:
        if value_error_status is None:
            raise
        raise HTTPException(status_code=value_error_status, detail=str(err)) from err


def _refuse_param_set(gw: GatewayClient, key: str) -> None:
    """409 use_tuning_endpoint when ``key`` is a queued PID parameter set (kind pid_param).

    A parameter set belongs to a tuning proposal record; approving or rejecting it here would
    leave the record out of step with the gateway. The keys come from state.json pending_params.
    """
    lister = getattr(gw, "pending_params", None)
    if lister is None:
        return
    try:
        held = any(entry.get("key") == key for entry in lister())
    except (OSError, ValueError, TypeError) as err:
        raise HTTPException(status_code=503, detail="gateway state unreadable") from err
    if held:
        raise HTTPException(status_code=409, detail="use_tuning_endpoint")


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


def mode_permission(current: str, target: str) -> str:
    """Return the permission a mode change needs, or raise 409 for a multi-step rise.

    Args:
        current: The gateway's current operating mode.
        target: The requested operating mode.

    Returns:
        "gw.mode.down" for a lowering or same-level change, or "gw.mode.up.<target>"
        for a rise of exactly one step.

    Raises:
        HTTPException: 409 when the mode would rise by more than one step.
    """
    current_index = MODES.index(current)
    target_index = MODES.index(target)
    if target_index <= current_index:
        return "gw.mode.down"
    if target_index == current_index + 1:
        return f"gw.mode.up.{target}"
    raise HTTPException(status_code=409, detail="mode can rise only one step at a time")


def _authorize_mode(gw: GatewayClient, actor: ActorContext, target: str) -> None:
    """Require the permission for the mode change, plus step-up for supervised."""
    permission = mode_permission(gw.mode(), target)
    actor.require(permission)
    if permission == "gw.mode.up.supervised":
        actor.require_stepup()


def _re_enable_permission(gw: GatewayClient, tag: str) -> str:
    """Return the permission needed to re-enable a target, or raise 404 if unknown."""
    state = gw.status().get(tag)
    if state is None:
        raise HTTPException(status_code=404, detail=f"unknown target: {tag}")
    return "gw.re_enable.hold_off" if state == "hold_off" else "gw.re_enable.stopped"


class _GatewayEndpoints:
    """Route handler collection bound to a GatewayClient provider."""

    def __init__(self, provider: Callable[[], GatewayClient | None]) -> None:
        self._provider = provider

    def _gw(self) -> GatewayClient:
        return _resolve_gateway(self._provider)

    def get_status(self, actor: ActorDep) -> dict[str, Any]:
        """GET /gateway/status: Current mode, per-target states, and pending count."""
        gw = self._gw()
        with _gateway_errors():
            return {"mode": gw.mode(), "targets": gw.status(), "pending": len(gw.pending())}

    def get_pending(self, actor: ActorDep) -> list[dict[str, str | float | int]]:
        """GET /gateway/pending: List of proposals awaiting confirmation."""
        gw = self._gw()
        with _gateway_errors():
            return gw.pending()

    def post_approve(self, key: str, actor: ActorDep) -> dict[str, Any]:
        """POST /gateway/pending/{key}/approve: Approve and execute queued proposal."""
        gw = self._gw()
        with _gateway_errors():
            _refuse_param_set(gw, key)
            return gw.approve(key, actor=actor)

    def post_reject(self, key: str, actor: ActorDep) -> dict[str, Any]:
        """POST /gateway/pending/{key}/reject: Discard queued proposal without writing."""
        gw = self._gw()
        with _gateway_errors():
            _refuse_param_set(gw, key)
            gw.reject(key, actor=actor)
        return {"ok": True}

    def post_kill(self, actor: ActorDep) -> dict[str, Any]:
        """POST /gateway/kill: Trigger emergency kill switch."""
        gw = self._gw()
        with _gateway_errors():
            gw.kill(actor=actor)
        return {"ok": True}

    def post_kill_reset(self, actor: ActorDep) -> dict[str, Any]:
        """POST /gateway/kill/reset: Clear the emergency kill switch."""
        gw = self._gw()
        with _gateway_errors(value_error_status=409):
            gw.kill_reset(actor=actor)
        return {"ok": True}

    def post_re_enable(self, tag: str, actor: ActorDep) -> dict[str, Any]:
        """POST /gateway/targets/{tag}/re-enable: Re-enable a stopped target."""
        gw = self._gw()
        with _gateway_errors(value_error_status=409):
            actor.require(_re_enable_permission(gw, tag))
            gw.re_enable(tag, actor=actor)
        return {"ok": True}

    def put_mode(self, body: ModeUpdate, actor: ActorDep) -> dict[str, Any]:
        """PUT /gateway/mode: Change operating mode of the gateway."""
        gw = self._gw()
        valid_mode = _validate_mode(body.mode)
        with _gateway_errors(value_error_status=422):
            _authorize_mode(gw, actor, valid_mode)
            gw.set_mode(valid_mode, actor=actor)
        return {"ok": True, "mode": valid_mode}

    def get_audit(
        self, actor: ActorDep, limit: int = Query(default=200, ge=1, le=1000)
    ) -> dict[str, Any]:
        """GET /gateway/audit: Return newest audit records and chain integrity flag."""
        gw = self._gw()
        with _gateway_errors():
            return gw.audit(limit)

    def get_policy(self, actor: ActorDep) -> dict[str, Any]:
        """GET /gateway/policy: The live pinned policy, its pin, mode cap and both digests.

        ``digest`` is the canonical digest of the document; ``file_digest`` is the SHA-256 of the
        live file bytes, which the verified pin names (``pin.digest``).
        """
        gw = self._gw()
        with _gateway_errors():
            live = gw.live_policy()
        if live is None:
            return {
                "document": None,
                "pin": None,
                "mode_cap": None,
                "digest": None,
                "file_digest": None,
            }
        document = live["document"]
        mode_cap = document.get("mode")
        return {
            "document": document,
            "pin": live["pin"],
            "mode_cap": mode_cap if isinstance(mode_cap, str) else None,
            "digest": policy_digest(document),
            "file_digest": live["pin"].get("digest"),
        }

    def get_policy_draft(self, actor: ActorDep) -> dict[str, Any]:
        """GET /gateway/policy/draft: The draft document with author, time and digest."""
        draft = self._load_draft()
        document = draft["document"]
        return {
            "document": document,
            "author": draft["author"],
            "saved_at": draft["saved_at"],
            "digest": policy_digest(document),
        }

    def _load_draft(self) -> dict[str, Any]:
        """Return the stored draft record, or raise 404 "no draft"."""
        gw = self._gw()
        with _gateway_errors():
            draft = gw.draft_policy()
        if draft is None:
            raise HTTPException(status_code=404, detail="no draft")
        return draft

    def put_policy_draft(
        self, body: Annotated[dict[str, Any], Body()], actor: ActorDep
    ) -> dict[str, Any]:
        """PUT /gateway/policy/draft: Store a draft; 422 names the target and field at fault."""
        gw = self._gw()
        with _gateway_errors(value_error_status=422):
            gw.policy_draft(body, actor=actor)
        return {"ok": True, "digest": policy_digest(body)}

    def post_policy_pin(self, body: PolicyPin, actor: ActorDep) -> dict[str, Any]:
        """POST /gateway/policy/pin: Pin the reviewed draft; 409 draft_changed if it moved."""
        gw = self._gw()
        with _gateway_errors(value_error_status=409):
            self._require_reviewed_draft(gw, body.digest)
            gw.policy_pin(body.digest, actor=actor)
        return {"ok": True}

    @staticmethod
    def _require_reviewed_draft(gw: GatewayClient, digest: str) -> None:
        """Raise ValueError (409) unless the stored draft still has the reviewed digest."""
        draft = gw.draft_policy()
        if draft is None:
            raise ValueError("no_draft")
        if policy_digest(draft["document"]) != digest:
            raise ValueError("draft_changed")

    def post_policy_reload(self, actor: ActorDep) -> dict[str, Any]:
        """POST /gateway/policy/reload: Reload the pinned policy."""
        gw = self._gw()
        with _gateway_errors(value_error_status=409):
            gw.policy_reload(actor=actor)
        return {"ok": True}


def build_gateway_router(provider: Callable[[], GatewayClient | None]) -> APIRouter:
    """Construct and return the FastAPI router for Write Gateway management."""
    endpoints = _GatewayEndpoints(provider)
    router = APIRouter(prefix="/gateway")
    router.add_api_route("/status", endpoints.get_status, methods=["GET"])
    router.add_api_route("/pending", endpoints.get_pending, methods=["GET"])
    router.add_api_route("/pending/{key}/approve", endpoints.post_approve, methods=["POST"])
    router.add_api_route("/pending/{key}/reject", endpoints.post_reject, methods=["POST"])
    router.add_api_route("/kill", endpoints.post_kill, methods=["POST"])
    router.add_api_route("/kill/reset", endpoints.post_kill_reset, methods=["POST"])
    router.add_api_route("/targets/{tag}/re-enable", endpoints.post_re_enable, methods=["POST"])
    router.add_api_route("/mode", endpoints.put_mode, methods=["PUT"])
    router.add_api_route("/audit", endpoints.get_audit, methods=["GET"])
    router.add_api_route("/policy", endpoints.get_policy, methods=["GET"])
    router.add_api_route("/policy/draft", endpoints.get_policy_draft, methods=["GET"])
    router.add_api_route("/policy/draft", endpoints.put_policy_draft, methods=["PUT"])
    router.add_api_route("/policy/pin", endpoints.post_policy_pin, methods=["POST"])
    router.add_api_route("/policy/reload", endpoints.post_policy_reload, methods=["POST"])
    return router

"""Command authentication gate for the write gateway; fails closed.

Unsigned commands are refused unless they are kill. While no key is loaded, signed commands are
refused unless they are kill or a set_mode that does not raise the mode. Verified envelopes then
pass role authorization, the self-approval rule and the policy_pin step-up rule. Envelopes that
fail verification are attributed to "unverified:<claimed actor>" in the audit trail.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from crosscut_gateway.actor import ActorContext
from crosscut_gateway.authz import MODES, AuthRequest, authorize
from crosscut_gateway.envelope import MIN_KEY_BYTES, NonceCache, verify_envelope
from crosscut_gateway.policy_file import canonical_bytes

if TYPE_CHECKING:
    from crosscut_gateway.engine import WriteGateway

_NONCE_WINDOW_S = 120
_UNKNOWN_ACTOR = "unknown"
_UNSIGNED_ACTOR = "unsigned"
_UNVERIFIED_PREFIX = "unverified:"
_UNVERIFIED_REASONS = frozenset({"malformed", "bad_signature", "key_too_short"})
_START_GRACE_NS = 1_000_000_000


def roles_digest(table: Mapping[str, frozenset[str]]) -> str:
    """Return the SHA-256 hex digest of the canonical JSON form of a role table."""
    canonical: dict[str, Any] = {role: sorted(perms) for role, perms in table.items()}
    return hashlib.sha256(canonical_bytes(canonical)).hexdigest()


@dataclass(frozen=True)
class GateVerdict:
    """Outcome of authenticating one command: whether it may proceed, why, and who sent it."""

    ok: bool
    reason: str
    ctx: ActorContext


def _claimed_actor(cmd_data: object) -> str:
    """Return the actor named in auth.actor, or 'unknown' when it is absent or malformed."""
    if not isinstance(cmd_data, dict):
        return _UNKNOWN_ACTOR
    auth = cmd_data.get("auth")
    if not isinstance(auth, dict):
        return _UNKNOWN_ACTOR
    actor = auth.get("actor")
    if isinstance(actor, str) and actor:
        return actor
    return _UNKNOWN_ACTOR


def _cmd_id(cmd_data: object) -> str:
    """Return the envelope id when it is a string, otherwise an empty string."""
    if not isinstance(cmd_data, dict):
        return ""
    value = cmd_data.get("id")
    return value if isinstance(value, str) else ""


def _ctx(cmd_data: object, actor: str) -> ActorContext:
    """Return an ActorContext for actor that carries the envelope's command id."""
    return ActorContext(actor=actor, cmd_id=_cmd_id(cmd_data))


def _refusal(cmd_data: object, reason: str) -> GateVerdict:
    """Return a refused verdict attributed to the claimed actor."""
    return GateVerdict(False, reason, _ctx(cmd_data, _claimed_actor(cmd_data)))


def _unverified_refusal(cmd_data: object, reason: str) -> GateVerdict:
    """Return a refused verdict for an envelope whose signature did not verify."""
    actor = _UNVERIFIED_PREFIX + _claimed_actor(cmd_data)
    return GateVerdict(False, reason, _ctx(cmd_data, actor))


def _verify_refusal(cmd_data: dict[str, Any], reason: str) -> GateVerdict:
    """Return the refusal for a failed verification, attributed as unverified when so classed."""
    if reason in _UNVERIFIED_REASONS:
        return _unverified_refusal(cmd_data, reason)
    return _refusal(cmd_data, reason)


def _is_safe_downgrade(args: object, gateway: WriteGateway) -> bool:
    """Return True when set_mode args name a known mode that does not raise the current mode."""
    if not isinstance(args, dict):
        return False
    new = args.get("mode")
    if not isinstance(new, str) or new not in MODES:
        return False
    current = gateway.mode
    return current in MODES and MODES.index(new) <= MODES.index(current)


def _check_unsigned(cmd_data: dict[str, Any]) -> GateVerdict:
    """Allow an unsigned kill command; refuse every other unsigned command."""
    if cmd_data.get("cmd") == "kill":
        return GateVerdict(True, "ok", _ctx(cmd_data, _UNSIGNED_ACTOR))
    return _unverified_refusal(cmd_data, "unsigned_not_allowed")


def _check_keyless(cmd_data: dict[str, Any], gateway: WriteGateway) -> GateVerdict:
    """Refuse signed commands while no key is loaded, except kill and set_mode downgrades."""
    actor = _UNVERIFIED_PREFIX + _claimed_actor(cmd_data)
    command = cmd_data.get("cmd")
    if command == "kill":
        return GateVerdict(True, "ok", _ctx(cmd_data, actor))
    if command == "set_mode" and _is_safe_downgrade(cmd_data.get("args"), gateway):
        return GateVerdict(True, "ok", _ctx(cmd_data, actor))
    return _unverified_refusal(cmd_data, "key_missing")


def _predates_start(cmd_data: dict[str, Any], start_ns: int | None) -> bool:
    """Return True when a verified envelope was issued before the gate started, less a grace."""
    if start_ns is None:
        return False
    issued = cmd_data["auth"]["issued_at_ns"]
    return bool(issued < start_ns - _START_GRACE_NS)


def _effective_args(cmd: str, args: dict[str, Any], gateway: WriteGateway) -> dict[str, Any]:
    """Return a copy of args; for set_mode the cap is always the gateway's own mode_cap."""
    effective = dict(args)
    if cmd == "set_mode":
        effective["cap"] = gateway.mode_cap
    return effective


def _policy_denial(
    cmd: str, args: dict[str, Any], auth: dict[str, Any], gateway: WriteGateway
) -> str | None:
    """Return the refusal reason for the approve and policy_pin rules, or None when they pass."""
    if cmd == "approve":
        proposer = gateway.pending_proposer(args.get("key"))
        if proposer is not None and proposer == auth["actor"]:
            return "self_approval"
    if cmd == "policy_pin" and auth.get("stepup") is not True:
        return "stepup_required"
    return None


def _envelope_ctx(cmd_data: dict[str, Any]) -> ActorContext:
    """Return the ActorContext recorded in the auth block of a verified envelope."""
    auth = cmd_data["auth"]
    return ActorContext(
        actor=auth["actor"],
        roles=tuple(auth["roles"]),
        session=auth["session"],
        source_ip=auth["source_ip"],
        cmd_id=_cmd_id(cmd_data),
    )


def _authorize_verified(
    cmd_data: dict[str, Any], gateway: WriteGateway, table: Mapping[str, frozenset[str]]
) -> GateVerdict:
    """Apply role authorization and the approve and policy_pin rules to a verified envelope."""
    auth: dict[str, Any] = cmd_data["auth"]
    cmd: str = cmd_data["cmd"]
    args: dict[str, Any] = cmd_data["args"]
    target = gateway.target_state(args.get("tag")) if cmd == "re_enable" else None
    request = AuthRequest(
        roles=auth["roles"],
        cmd=cmd,
        args=_effective_args(cmd, args, gateway),
        mode=gateway.mode,
        target_state=target,
    )
    allowed, reason = authorize(request, table)
    if not allowed:
        return _refusal(cmd_data, reason)
    denial = _policy_denial(cmd, args, auth, gateway)
    if denial is not None:
        return _refusal(cmd_data, denial)
    return GateVerdict(True, "ok", _envelope_ctx(cmd_data))


class AuthGate:
    """Authenticate command envelopes before they reach the write gateway."""

    def __init__(
        self,
        roles: Mapping[str, frozenset[str]],
        clock: Callable[[], float],
        start_ns: int | None = None,
    ) -> None:
        """Store the role table, clock and optional process start time (ns), plus a nonce cache.

        When ``start_ns`` is given, verified envelopes issued more than one second before it are
        refused as predating the start, so a restart cannot replay envelopes from an earlier run.
        """
        self._roles: dict[str, frozenset[str]] = dict(roles)
        self._clock = clock
        self._start_ns = start_ns
        self._key: bytes | None = None
        self._nonces = NonceCache(window_s=_NONCE_WINDOW_S, clock=clock)

    def set_key(self, key: bytes | None) -> None:
        """Load the HMAC key; a missing key or one shorter than MIN_KEY_BYTES leaves none loaded."""
        if key is None or len(key) < MIN_KEY_BYTES:
            self._key = None
        else:
            self._key = key

    @property
    def key_ok(self) -> bool:
        """Return True when a usable HMAC key is loaded."""
        return self._key is not None

    @property
    def key(self) -> bytes | None:
        """Return the loaded HMAC key, or None when none is loaded."""
        return self._key

    def nonce_snapshot(self) -> dict[str, dict[str, float]]:
        """Return the live nonces and envelope ids, for saving across a restart."""
        return self._nonces.snapshot()

    def restore_nonces(self, data: object) -> None:
        """Reload nonces and ids saved by nonce_snapshot; malformed data is ignored."""
        self._nonces.restore(data)

    def check(self, cmd_data: object, gateway: WriteGateway) -> GateVerdict:
        """Decide whether cmd_data may run against gateway; never raises on any input."""
        if not isinstance(cmd_data, dict):
            return _unverified_refusal(cmd_data, "malformed")
        if "sig" not in cmd_data:
            return _check_unsigned(cmd_data)
        key = self._key
        if key is None:
            return _check_keyless(cmd_data, gateway)
        return self._check_signed(cmd_data, gateway, key)

    def _check_signed(
        self, cmd_data: dict[str, Any], gateway: WriteGateway, key: bytes
    ) -> GateVerdict:
        """Verify signature, freshness and replay, then authorize the verified envelope."""
        now_ns = int(self._clock() * 1e9)
        try:
            valid, reason = verify_envelope(cmd_data, key, now_ns, self._nonces)
        except RecursionError:
            return _unverified_refusal(cmd_data, "malformed")
        if not valid:
            return _verify_refusal(cmd_data, reason)
        if _predates_start(cmd_data, self._start_ns):
            return _refusal(cmd_data, "predates_start")
        return _authorize_verified(cmd_data, gateway, self._roles)

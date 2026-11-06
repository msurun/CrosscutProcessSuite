"""PID parameter sets in the write gateway (ADR 014 sections 2 to 4).

Kept out of ``engine.py``: propose, queue, approve and apply of an atomic parameter set, plus
the read-back tick. A parameter set is confirm-only (``KIND_MODE_CAP``), out-of-range values are
refused, never clamped, and nothing is released, watched by a watchdog or kept alive by a
heartbeat: the values persist in the control system. Every transport error fails closed
(``stopped:comm``) and is audited.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from crosscut_gateway.actor import normalize_actor
from crosscut_gateway.engine_params_apply import (
    COMM_ERRORS,
    ParamCommError,
    WriteOutcome,
    live_check,
    within,
    write_set,
)
from crosscut_gateway.interfaces import (
    ParamControlSystem,
    ParamItem,
    ParamPolicy,
    ParamSetProposal,
    WriteDecision,
)
from crosscut_gateway.policy import KIND_PID_PARAM, KIND_SETPOINT, check_param_items

MODE_ORDER = {"off": 0, "advisory": 1, "dry_run": 2, "confirm": 3, "supervised": 4}

# The most permissive mode in which a kind of target is still acted on directly.
KIND_MODE_CAP = {KIND_SETPOINT: "supervised", KIND_PID_PARAM: "confirm"}

PARAM_EXPIRY_MAX_NS = 12 * 3600 * 1_000_000_000  # 12 hours, the cap of ADR 014
PARAM_MAX_FUTURE_NS = 5 * 1_000_000_000  # 5 seconds of clock skew
_SERVICE_PREFIX = "svc:"


def effective_mode(kind: str, mode: str) -> str:
    """The more restrictive of the global ``mode`` and the cap of the target ``kind``."""
    cap = KIND_MODE_CAP[kind]
    return mode if MODE_ORDER[mode] <= MODE_ORDER[cap] else cap


def _num(value: object) -> str:
    """Canonical text of a number; -0.0 equals 0.0, anything else falls back to repr."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return repr(value)
    return f"{(value if value != 0 else 0.0):.17g}"


def param_set_key(proposal: ParamSetProposal) -> str:
    """SHA-256 hex over the canonical (proposal_id, items, proposer, t_ns): the idempotency key.

    ``reason``, ``expires_ns`` and ``rollback_of`` are not part of it. Units: t_ns in ns.
    """
    items = [
        [i.param, i.target, i.unit, i.vendor_form, _num(i.from_value), _num(i.to_value)]
        for i in proposal.items
    ]
    fields = [proposal.proposal_id, items, proposal.proposer, int(proposal.t_ns)]
    payload = json.dumps(fields, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ParamConfig:
    """Parameter policies by target tag and the control system that reads and writes them."""

    policies: dict[str, ParamPolicy]
    plant: ParamControlSystem | None = None


@dataclass(frozen=True)
class ParamEnv:
    """What the manager needs from the gateway: clock, mode, kill latch, caller, audit sink."""

    now_ns: Callable[[], int]
    clock_started: Callable[[], bool]
    mode: Callable[[], str]
    killed: Callable[[], bool]
    actor: Callable[[], str | None]
    emit: Callable[[str, dict[str, str]], None]


@dataclass(frozen=True)
class PendingParams:
    """A queued parameter set, its idempotency key and the actor who proposed it."""

    key: str
    proposal: ParamSetProposal
    proposer_actor: str | None


def _state_reason(state: str) -> str:
    """Refusal reason of a target that is not enabled, e.g. ``target_stopped_comm``."""
    return f"target_{state.replace(':', '_')}"


class ParamManager:
    """State and flows of the ``pid_param`` targets of one gateway."""

    def __init__(self, env: ParamEnv, config: ParamConfig) -> None:
        """Start every parameter target enabled, with nothing pending and nothing applied."""
        self._env = env
        self._policies = config.policies
        self._plant = config.plant
        self._states: dict[str, str] = {tag: "enabled" for tag in config.policies}
        self._pending: dict[str, PendingParams] = {}
        self._seen: dict[str, WriteDecision] = {}
        self._ids: dict[str, str] = {}
        self._last_applied: dict[str, float] = {}
        self._last_apply_ns: dict[str, int] = {}

    # ------------------------------------------------------------------ queries

    def policies(self) -> dict[str, ParamPolicy]:
        """Copy of the parameter policies by target tag."""
        return dict(self._policies)

    def has_target(self, tag: object) -> bool:
        """True when ``tag`` is a parameter target."""
        return isinstance(tag, str) and tag in self._states

    def states(self) -> dict[str, str]:
        """Copy of the per-target states."""
        return dict(self._states)

    def pending(self) -> list[PendingParams]:
        """Queued parameter sets in arrival order."""
        return list(self._pending.values())

    def has_pending(self, key: object) -> bool:
        """True when ``key`` names a queued parameter set."""
        return isinstance(key, str) and key in self._pending

    def pending_proposer(self, key: object) -> str | None:
        """The actor who queued the set ``key``, or None."""
        if not isinstance(key, str) or key not in self._pending:
            return None
        return self._pending[key].proposer_actor

    # ------------------------------------------------------------------ propose

    def propose(self, proposal: ParamSetProposal) -> WriteDecision:
        """Screen a parameter set and record, dry-run or queue it per the effective mode."""
        key = param_set_key(proposal)
        cached = self._replay(proposal, key)
        if cached is not None:
            return cached
        if self._ids.get(proposal.proposal_id, key) != key:
            return self._conflict(proposal, key)
        self._ids[proposal.proposal_id] = key
        self._emit("param_proposal", proposal, key, "")
        refusal = self._screen(proposal)
        if refusal is not None:
            return self._refuse(proposal, key, refusal)
        return self._dispatch(proposal, key)

    def _replay(self, proposal: ParamSetProposal, key: str) -> WriteDecision | None:
        """The cached decision of an identical earlier proposal (audited as a duplicate)."""
        cached = self._seen.get(key)
        if cached is not None:
            self._emit("param_duplicate", proposal, key, cached.reason_code)
        return cached

    def _conflict(self, proposal: ParamSetProposal, key: str) -> WriteDecision:
        """Refuse a known proposal id carrying different content; the first one stays valid."""
        decision = WriteDecision(accepted=False, reason_code="id_conflict")
        self._emit("param_decision", proposal, key, "id_conflict")
        return decision

    def _refuse(
        self, proposal: ParamSetProposal, key: str, refusal: tuple[str, str]
    ) -> WriteDecision:
        """Audit a refusal (code, detail), cache it for replay and return it."""
        code, detail = refusal
        decision = WriteDecision(accepted=False, reason_code=code)
        self._emit("param_decision", proposal, key, code, value=detail)
        self._seen[key] = decision
        return decision

    def _screen(self, proposal: ParamSetProposal) -> tuple[str, str] | None:
        """First applicable refusal (code, detail) of a proposal, or None to go on."""
        checks = (
            self._screen_mode,
            self._screen_origin,
            self._screen_shape,
            self._screen_targets,
            self._screen_timing,
            self._screen_values,
        )
        for check in checks:
            refusal = check(proposal)
            if refusal is not None:
                return refusal
        return None

    def _screen_mode(self, proposal: ParamSetProposal) -> tuple[str, str] | None:
        """Refuse while the gateway is off or killed, or has no control system for parameters."""
        if self._env.mode() == "off":
            return "mode_off", ""
        if self._env.killed():
            return "killed", ""
        if self._plant is None:
            return "no_param_plant", ""
        return None

    def _screen_origin(self, proposal: ParamSetProposal) -> tuple[str, str] | None:
        """A service principal may never propose a tuning change (ADR 014)."""
        for name in (self._env.actor(), proposal.proposer):
            if name is not None and normalize_actor(name).startswith(_SERVICE_PREFIX):
                return "service_cannot_propose_tuning", ""
        return None

    def _screen_shape(self, proposal: ParamSetProposal) -> tuple[str, str] | None:
        """Refuse an empty set, a repeated target or an item that belongs to another loop."""
        targets = [item.target for item in proposal.items]
        if len(set(targets)) != len(targets):
            return "duplicate_target", ""
        for item in proposal.items:
            policy = self._policies.get(item.target)
            if policy is not None and policy.loop != proposal.loop_id:
                return "loop_mismatch", item.target
        return None

    def _screen_timing(self, proposal: ParamSetProposal) -> tuple[str, str] | None:
        """Expiry window and per-loop minimum interval between applies."""
        now = self._env.now_ns()
        if proposal.expires_ns - proposal.t_ns > PARAM_EXPIRY_MAX_NS:
            return "expiry_too_long", ""
        if not self._env.clock_started():
            return None
        if proposal.expires_ns <= now:
            return "expired", ""
        if proposal.t_ns > now + PARAM_MAX_FUTURE_NS:
            return "bad_time", ""
        return self._interval_refusal(proposal.loop_id, proposal.items)

    def _interval_refusal(
        self, loop_id: str, items: tuple[ParamItem, ...]
    ) -> tuple[str, str] | None:
        """Refuse an apply that follows the previous apply of the loop too closely."""
        last = self._last_apply_ns.get(loop_id)
        if last is None:
            return None
        known = [self._policies[i.target] for i in items if i.target in self._policies]
        wait_s = max((policy.min_interval_s for policy in known), default=0.0)
        if self._env.now_ns() - last < wait_s * 1e9:
            return "min_interval", ""
        return None

    def _screen_targets(self, proposal: ParamSetProposal) -> tuple[str, str] | None:
        """Every target must be enabled; only one set per loop may wait for approval."""
        for item in proposal.items:
            state = self._states.get(item.target)
            if state is not None and state != "enabled":
                return _state_reason(state), item.target
        queues = effective_mode(KIND_PID_PARAM, self._env.mode()) == "confirm"
        if queues and any(p.proposal.loop_id == proposal.loop_id for p in self._pending.values()):
            return "loop_busy", ""
        return None

    def _screen_values(self, proposal: ParamSetProposal) -> tuple[str, str] | None:
        """Policy checks of the set against its own ``from`` values (refuse, never clamp)."""
        current = {item.target: item.from_value for item in proposal.items}
        codes = check_param_items(self._policies, proposal.items, current)
        return (codes[0], ",".join(codes)) if codes else None

    def _dispatch(self, proposal: ParamSetProposal, key: str) -> WriteDecision:
        """Route a screened set by the effective mode (``supervised`` behaves as ``confirm``)."""
        mode = effective_mode(KIND_PID_PARAM, self._env.mode())
        if mode == "advisory":
            return self._record_ok(proposal, key, "ok")
        if mode == "dry_run":
            return self._dry_run(proposal, key)
        if mode == "confirm":
            return self._queue(proposal, key)
        return self._refuse(proposal, key, ("mode_unsupported", ""))

    def _record_ok(self, proposal: ParamSetProposal, key: str, code: str) -> WriteDecision:
        """Audit and cache an accepted decision without touching the control system."""
        decision = WriteDecision(accepted=True, reason_code=code)
        self._emit("param_decision", proposal, key, code)
        self._seen[key] = decision
        return decision

    def _queue(self, proposal: ParamSetProposal, key: str) -> WriteDecision:
        """Queue the set for approval by a second person."""
        self._pending[key] = PendingParams(key, proposal, self._env.actor())
        decision = WriteDecision(accepted=True, reason_code="queued")
        self._emit("param_queued", proposal, key, "queued")
        self._seen[key] = decision
        return decision

    def _dry_run(self, proposal: ParamSetProposal, key: str) -> WriteDecision:
        """Run the live checks and log what would be written; nothing is written."""
        assert self._plant is not None
        try:
            check = live_check(self._plant, self._policies, proposal.items)
        except ParamCommError as exc:
            return self._comm_refusal(proposal, key, exc.target)
        if check.codes:
            return self._refuse(proposal, key, (check.codes[0], check.detail))
        return self._record_ok(proposal, key, "dry_run")

    # ------------------------------------------------------------------ approve / reject

    def approve(self, key: str) -> WriteDecision:
        """Approve a queued set: gate checks, live checks, writes with read-back.

        Raises:
            KeyError: When ``key`` is not a queued parameter set.
        """
        pending = self._pending.get(key)
        if pending is None:
            raise KeyError(f"unknown pending proposal key: {key}")
        early = self._approve_gate(pending)
        if early is not None:
            return early
        del self._pending[key]
        return self._apply(pending)

    def _approve_gate(self, pending: PendingParams) -> WriteDecision | None:
        """Kill, target states, mode, expiry, self-approval and interval, in that order."""
        proposal = pending.proposal
        refusal = self._gate_state(proposal)
        if refusal is not None:
            return self._drop_refused(pending, refusal)
        if effective_mode(KIND_PID_PARAM, self._env.mode()) != "confirm":
            self._emit("param_decision", proposal, pending.key, "not_confirm_mode")
            return WriteDecision(accepted=False, reason_code="not_confirm_mode")
        refusal = self._gate_time(proposal)
        if refusal is not None:
            return self._drop_refused(pending, refusal)
        if self._is_self_approval(pending):
            self._emit("param_self_approval", proposal, pending.key, "self_approval")
            return WriteDecision(accepted=False, reason_code="self_approval")
        return None

    def _gate_state(self, proposal: ParamSetProposal) -> tuple[str, str] | None:
        """Refuse while killed or when a target left ``enabled`` since it was queued."""
        if self._env.killed():
            return "killed", ""
        for item in proposal.items:
            state = self._states.get(item.target)
            if state != "enabled":
                return _state_reason(str(state)), item.target
        return None

    def _gate_time(self, proposal: ParamSetProposal) -> tuple[str, str] | None:
        """Refuse an expired set or one that follows the previous apply too closely."""
        if self._env.clock_started() and proposal.expires_ns <= self._env.now_ns():
            return "expired", ""
        return self._interval_refusal(proposal.loop_id, proposal.items)

    def _is_self_approval(self, pending: PendingParams) -> bool:
        """True when the current actor is the one who queued the set."""
        current = self._env.actor()
        if pending.proposer_actor is None or current is None:
            return False
        return normalize_actor(pending.proposer_actor) == normalize_actor(current)

    def _drop_refused(self, pending: PendingParams, refusal: tuple[str, str]) -> WriteDecision:
        """Remove a queued set that can no longer be applied, audit and cache the refusal."""
        self._pending.pop(pending.key, None)
        return self._refuse(pending.proposal, pending.key, refusal)

    def reject(self, key: str) -> None:
        """Drop a queued set without writing.

        Raises:
            KeyError: When ``key`` is not a queued parameter set.
        """
        pending = self._pending.pop(key, None)
        if pending is None:
            raise KeyError(f"unknown pending proposal key: {key}")
        self._seen[key] = WriteDecision(accepted=False, reason_code="rejected")
        self._emit("param_rejected", pending.proposal, key, "rejected")

    # ------------------------------------------------------------------ apply

    def _apply(self, pending: PendingParams) -> WriteDecision:
        """Live checks, then the ordered writes; any failure leaves the loop as it was."""
        assert self._plant is not None
        proposal, key = pending.proposal, pending.key
        try:
            check = live_check(self._plant, self._policies, proposal.items)
        except ParamCommError as exc:
            return self._comm_refusal(proposal, key, exc.target)
        if check.codes:
            return self._refuse(proposal, key, (check.codes[0], check.detail))
        outcome = write_set(self._plant, self._policies, proposal.items)
        if outcome.ok:
            return self._applied(proposal, key)
        return self._failed(proposal, key, outcome)

    def _comm_refusal(self, proposal: ParamSetProposal, key: str, target: str) -> WriteDecision:
        """Fail closed after a transport error before any write: stop ``target`` and refuse."""
        self._set_state(target, "stopped:comm")
        self._emit("comm_loss", proposal, key, "comm_loss", tag=target)
        return self._refuse(proposal, key, ("comm_loss", target))

    def _applied(self, proposal: ParamSetProposal, key: str) -> WriteDecision:
        """Remember the applied values for read-back and audit every item as param_write."""
        for item in proposal.items:
            self._last_applied[item.target] = item.to_value
            self._emit(
                "param_write", proposal, key, "applied", tag=item.target,
                applied_from=str(item.from_value), applied_to=str(item.to_value),
            )
        self._last_apply_ns[proposal.loop_id] = self._env.now_ns()
        decision = WriteDecision(accepted=True, reason_code="applied")
        self._seen[key] = decision
        return decision

    def _failed(
        self, proposal: ParamSetProposal, key: str, outcome: WriteOutcome
    ) -> WriteDecision:
        """Stop the failing target, audit the revert and raise the DCS alarm if it failed too."""
        state = "stopped:comm" if outcome.code == "comm_loss" else "stopped:readback"
        self._set_state(outcome.failed_target, state)
        for tag in outcome.revert_failed:
            self._set_state(tag, "stopped:comm")
        code = "revert_failed" if outcome.revert_failed else outcome.code
        if outcome.written:
            self._emit(
                "partial_revert", proposal, key, outcome.code, tag=outcome.failed_target,
                written=",".join(outcome.written), revert_failed=",".join(outcome.revert_failed),
            )
        if outcome.revert_failed:
            tags = ",".join(outcome.revert_failed)
            self._emit("alarm_check_dcs", proposal, key, "revert_failed", tag=tags)
        return self._refuse(proposal, key, (code, outcome.failed_target))

    # ------------------------------------------------------------------ tick and lifecycle

    def tick(self) -> None:
        """Read back every applied target; a changed value means someone changed it at the DCS.

        Read-back only: nothing is released, written back or kept alive.
        """
        if self._plant is None:
            return
        for tag in list(self._last_applied):
            if self._states.get(tag) == "enabled":
                self._check_readback(self._plant, tag)

    def _check_readback(self, plant: ParamControlSystem, tag: str) -> None:
        """Compare one target with its last applied value."""
        expected = self._last_applied[tag]
        try:
            actual = plant.read_param(tag)
        except COMM_ERRORS:
            self._last_applied.pop(tag, None)
            self._set_state(tag, "stopped:comm")
            self._emit_tag("comm_loss", tag, "comm_loss")
            return
        if within(actual, expected, self._policies[tag].readback_tolerance):
            return
        self._last_applied.pop(tag, None)
        self._set_state(tag, "hold_off")
        self._emit_tag(
            "param_changed_externally", tag, "param_changed_externally",
            value=str(actual), expected=str(expected), review="invalid",
        )

    def kill(self) -> None:
        """Kill switch: every target is killed and all queued sets are dropped."""
        for tag in self._states:
            self._set_state(tag, "killed")
        self._flush_all("killed")
        self._last_applied.clear()

    def reset_kill(self) -> None:
        """After a kill reset every target needs an explicit re-enable."""
        for tag in self._states:
            self._states[tag] = "stopped:kill"
        self._last_applied.clear()

    def re_enable(self, tag: str) -> None:
        """Re-enable a stopped or held-off target; the next apply sets a new baseline.

        Raises:
            KeyError: When ``tag`` is not a parameter target.
            ValueError: When the target cannot be re-enabled from its current state.
        """
        if tag not in self._states:
            raise KeyError(f"unknown tag: {tag}")
        state = self._states[tag]
        if state == "killed":
            raise ValueError("cannot re-enable a killed target")
        if state != "hold_off" and not state.startswith("stopped:"):
            raise ValueError(f"cannot re-enable from state '{state}'")
        self._states[tag] = "enabled"
        self._emit_tag("re_enable", tag, "re_enable")

    def swap_policies(self, policies: dict[str, ParamPolicy]) -> None:
        """Replace the parameter policies; every queued set is dropped with audit first.

        Kept targets keep their state, new ones start enabled, removed ones are forgotten.
        """
        self._flush_all("policy_reload")
        for tag in set(self._states) - set(policies):
            del self._states[tag]
            self._last_applied.pop(tag, None)
        for tag in set(policies) - set(self._states):
            self._states[tag] = "enabled"
        self._policies = dict(policies)

    def _set_state(self, tag: str, state: str) -> None:
        """Change a target's state; queued sets that use it are flushed when it leaves enabled."""
        old = self._states.get(tag)
        self._states[tag] = state
        if old == "enabled" and state != "enabled":
            self._flush_tag(tag)

    def _flush_tag(self, tag: str) -> None:
        """Drop the queued sets that contain ``tag``."""
        keys = [
            key
            for key, pend in self._pending.items()
            if any(item.target == tag for item in pend.proposal.items)
        ]
        for key in keys:
            self._flush(key, "flushed")

    def _flush_all(self, reason: str) -> None:
        """Drop every queued set."""
        for key in list(self._pending):
            self._flush(key, reason)

    def _flush(self, key: str, reason: str) -> None:
        """Drop one queued set, cache the refusal and audit it."""
        pending = self._pending.pop(key, None)
        if pending is None:
            return
        self._seen[key] = WriteDecision(accepted=False, reason_code="flushed")
        self._emit("param_flushed", pending.proposal, key, reason)

    # ------------------------------------------------------------------ audit

    def _emit(
        self, event: str, proposal: ParamSetProposal, key: str, reason: str, **more: str
    ) -> None:
        """Audit a proposal-level event; ``tag``, ``value`` and further fields come as keywords."""
        fields = {
            "tag": ",".join(item.target for item in proposal.items),
            "value": "",
            "proposer": proposal.proposer,
            "reason_code": reason,
            "proposal_id": proposal.proposal_id,
            "loop": proposal.loop_id,
            "key": key,
        }
        fields.update(more)
        self._env.emit(event, fields)

    def _emit_tag(self, event: str, tag: str, reason: str, **more: str) -> None:
        """Audit a target-level event (no proposal)."""
        fields = {"tag": tag, "value": "", "proposer": "", "reason_code": reason}
        fields.update(more)
        self._env.emit(event, fields)


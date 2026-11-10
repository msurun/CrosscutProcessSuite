"""PID parameter sets in the write gateway (ADR 014 sections 2 to 4).

Kept out of ``engine.py``: propose, queue, approve and apply of an atomic parameter set, plus
the read-back tick. A parameter set is confirm-only (``KIND_MODE_CAP``), out-of-range values are
refused, never clamped, and nothing is released, watched by a watchdog or kept alive by a
heartbeat: the values persist in the control system. Every transport error fails closed
(``stopped:comm``) and is audited.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from crosscut_gateway.actor import normalize_actor
from crosscut_gateway.engine_params_apply import (
    COMM_ERRORS,
    ParamCommError,
    WriteOutcome,
    live_check,
    revert_items,
    stored_value,
    within,
    write_set,
)
from crosscut_gateway.engine_params_ledger import AppliedLedger
from crosscut_gateway.interfaces import (
    ParamControlSystem,
    ParamPolicy,
    ParamSetProposal,
    WriteDecision,
)
from crosscut_gateway.param_intent_store import (
    ParamIntentItem,
    ParamIntentRecord,
    ParamIntentStore,
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

    ``rollback_of`` is part of it (a rollback is a different proposal); ``reason`` and
    ``expires_ns`` are not. Units: t_ns in ns.
    """
    items = [
        [i.param, i.target, i.unit, i.vendor_form, _num(i.from_value), _num(i.to_value)]
        for i in proposal.items
    ]
    fields = [
        proposal.proposal_id, items, proposal.proposer, int(proposal.t_ns), proposal.rollback_of
    ]
    payload = json.dumps(fields, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _make_intent_resolved_fields(
    record: ParamIntentRecord,
    key: str,
    read_values: Mapping[str, float],
    actor: str,
) -> dict[str, str]:
    """Format emission fields for an intent resolution event."""
    tags = ",".join(item.target for item in record.items)
    intended_str = ";".join(f"{i.target}={i.to_value}" for i in record.items)
    read_str = ";".join(f"{i.target}={read_values.get(i.target, '')}" for i in record.items)
    return {
        "tag": tags, "value": "", "proposer": record.proposer,
        "reason_code": "resolved", "proposal_id": record.proposal_id,
        "loop": record.loop_id, "key": key, "actor": actor,
        "intended": intended_str, "read": read_str,
        "intended_values": ",".join(str(i.to_value) for i in record.items),
        "read_values": ",".join(str(read_values.get(i.target, "")) for i in record.items),
    }


@dataclass(frozen=True)
class ParamConfig:
    """Parameter policies by target tag and the control system that reads and writes them."""

    policies: dict[str, ParamPolicy]
    plant: ParamControlSystem | None = None
    intent_store: ParamIntentStore | None = None


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
        self._store = config.intent_store or ParamIntentStore()
        self._states: dict[str, str] = {tag: "enabled" for tag in config.policies}
        self._pending: dict[str, PendingParams] = {}
        self._seen: dict[str, WriteDecision] = {}
        self._ids: dict[str, str] = {}
        self._last_applied: dict[str, float] = {}
        self._last_apply_ns: dict[str, int] = {}
        self._ledger = AppliedLedger()
        self._alarms: dict[str, str] = {}
        self._audit_open_intents_at_start()

    def _audit_open_intents_at_start(self) -> None:
        """Audit every open intent record discovered in the store during startup."""
        for record in self._store.load_open():
            self._emit_open_intent(record)

    def _emit_open_intent(self, record: ParamIntentRecord) -> None:
        """Audit an open intent found during startup as intent_open_at_start."""
        fields = {
            "tag": ",".join(item.target for item in record.items),
            "value": "",
            "proposer": record.proposer,
            "reason_code": "intent_open_at_start",
            "proposal_id": record.proposal_id,
            "loop": record.loop_id,
            "key": record.key,
        }
        self._env.emit("intent_open_at_start", fields)

    def replay_audit(self, records: Sequence[Mapping[str, str]]) -> None:
        """Rebuild the applied-set ledger from the audit records (after a restart)."""
        self._ledger.replay(records)

    def _same_value(self, tag: str, left: float, right: float) -> bool:
        """Exact equality of two stored values; for Float targets also after float32 rounding."""
        if left == right:
            return True
        if self._plant is None:
            return False
        return stored_value(self._plant, tag, left) == stored_value(self._plant, tag, right)

    def rollback_refusal(self, proposal: ParamSetProposal) -> str | None:
        """Why a proposal gets no rollback exemption (None = exempt); ledger data only.

        # In plain words:
        # ADR 014 section 6: a rollback skips min_interval and max_ratio ONLY when the gateway's
        # own audited ledger shows it restores the latest, not yet reverted, applied set (not a
        # rollback itself) with exactly the audited values. Limits and signs always apply.
        """
        if not proposal.rollback_of:
            return "not_a_rollback"
        return self._ledger.rollback_refusal(proposal, self._same_value)

    def is_verified_rollback(self, proposal: ParamSetProposal) -> bool:
        """True when the gateway's own ledger verifies the rollback (see rollback_refusal)."""
        return self.rollback_refusal(proposal) is None

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

    def alarms(self) -> dict[str, str]:
        """Targets with an open DCS alarm, by tag; the value is the reason, ``check_dcs``.

        The flag stays until the target is re-enabled (a person looked at the control system).
        """
        return dict(self._alarms)

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
            self._screen_proposer,
            self._screen_shape,
            self._screen_targets,
            self._screen_timing,
            self._screen_open_intent,
            self._screen_values,
        )
        for check in checks:
            refusal = check(proposal)
            if refusal is not None:
                return refusal
        return None

    def _screen_open_intent(self, proposal: ParamSetProposal) -> tuple[str, str] | None:
        """Refuse when a write intent is open for this loop; reconciliation is required."""
        if self.has_open_intent(proposal.loop_id):
            return "reconcile_required", proposal.loop_id
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

    def _screen_proposer(self, proposal: ParamSetProposal) -> tuple[str, str] | None:
        """A set without a named proposer is refused: self-approval could not be compared."""
        actor = self._env.actor()
        if actor is None or not normalize_actor(actor):
            return "proposer_required", ""
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
        if not self._env.clock_started():
            return "clock_not_started", ""
        now = self._env.now_ns()
        if proposal.expires_ns - proposal.t_ns > PARAM_EXPIRY_MAX_NS:
            return "expiry_too_long", ""
        if proposal.expires_ns <= now:
            return "expired", ""
        if proposal.t_ns > now + PARAM_MAX_FUTURE_NS:
            return "bad_time", ""
        if self.is_verified_rollback(proposal):
            return None
        return self._interval_refusal(proposal.loop_id)

    def _interval_refusal(self, loop_id: str) -> tuple[str, str] | None:
        """Refuse an apply that follows the previous apply of the loop too closely.

        The wait is the largest ``min_interval_s`` of ALL parameter policies of the loop, not
        only of the items of the new set (a Td-only set after a gain change must wait too).
        """
        last = self._last_apply_ns.get(loop_id)
        if last is None:
            return None
        loop_policies = [p for p in self._policies.values() if p.loop == loop_id]
        wait_s = max((policy.min_interval_s for policy in loop_policies), default=0.0)
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
        exempt = self.is_verified_rollback(proposal)
        codes = check_param_items(self._policies, proposal.items, current, exempt_ratio=exempt)
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
        exempt = self.is_verified_rollback(proposal)
        try:
            check = live_check(self._plant, self._policies, proposal.items, exempt_ratio=exempt)
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
        if self.has_open_intent(proposal.loop_id):
            return self._drop_refused(pending, ("reconcile_required", proposal.loop_id))
        refusal = self._gate_state(proposal)
        if refusal is not None:
            return self._drop_refused(pending, refusal)
        if effective_mode(KIND_PID_PARAM, self._env.mode()) != "confirm":
            self._emit("param_decision", proposal, pending.key, "not_confirm_mode")
            return WriteDecision(accepted=False, reason_code="not_confirm_mode")
        refusal = self._gate_time(proposal)
        if refusal is not None:
            return self._drop_refused(pending, refusal)
        return self._approver_refusal(pending)

    def _approver_refusal(self, pending: PendingParams) -> WriteDecision | None:
        """Refuse an approval without a named actor and a self-approval; the set stays queued."""
        proposal = pending.proposal
        current = self._env.actor()
        if current is None or not current.strip():
            self._emit("param_decision", proposal, pending.key, "actor_required")
            return WriteDecision(accepted=False, reason_code="actor_required")
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
        """Refuse before the clock runs, an expired set, or one too soon after the last apply."""
        if not self._env.clock_started():
            return "clock_not_started", ""
        if proposal.expires_ns <= self._env.now_ns():
            return "expired", ""
        if self.is_verified_rollback(proposal):
            return None
        return self._interval_refusal(proposal.loop_id)

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
        """Live checks, then the ordered writes; every outcome is decided and audited.

        The set is already off the queue, so any unexpected error ends in a ``plant_error``
        refusal instead of a set that vanishes without a decision.
        """
        assert self._plant is not None
        proposal, key = pending.proposal, pending.key
        if self._env.killed():  # last look before the first write
            return self._refuse(proposal, key, ("killed", ""))
        try:
            refusal, from_read = self._live_phase(proposal, key)
        except Exception as exc:  # noqa: BLE001 - nothing written yet; fail closed
            return self._plant_error(proposal, key, exc, wrote=False)
        if refusal is not None:
            return refusal
        result = self._execute_write_set(proposal, key)
        if isinstance(result, WriteDecision):
            return result
        if result.ok:
            return self._applied(proposal, key, (from_read, result.read_back))
        return self._failed(proposal, key, result)

    def _execute_write_set(
        self, proposal: ParamSetProposal, key: str
    ) -> WriteOutcome | WriteDecision:
        """Execute the plant writes after live checks pass, failing closed if intent fails."""
        assert self._plant is not None
        try:
            self._write_intent(proposal, key)
        except Exception as exc:  # noqa: BLE001 - fail closed with no plant write
            return self._refuse(proposal, key, ("intent_write_failed", type(exc).__name__))
        try:
            return write_set(self._plant, self._policies, proposal.items)
        except Exception as exc:  # noqa: BLE001 - writes may have happened: revert and stop
            return self._plant_error(proposal, key, exc, wrote=True)

    def _write_intent(self, proposal: ParamSetProposal, key: str) -> None:
        """Persist a new open intent record to durable storage before plant writes."""
        now_iso = datetime.now(UTC).isoformat()
        items = tuple(
            ParamIntentItem(item.target, item.from_value, item.to_value)
            for item in proposal.items
        )
        record = ParamIntentRecord(
            key=key,
            loop_id=proposal.loop_id,
            items=items,
            created_time=now_iso,
            state="open",
            proposal_id=proposal.proposal_id,
            proposer=proposal.proposer,
        )
        self._store.record_intent(record)

    def _live_phase(
        self, proposal: ParamSetProposal, key: str
    ) -> tuple[WriteDecision | None, Mapping[str, float]]:
        """Run the live checks: a refusal (or None) and the values read from the plant."""
        assert self._plant is not None
        exempt = self.is_verified_rollback(proposal)
        try:
            check = live_check(self._plant, self._policies, proposal.items, exempt_ratio=exempt)
        except ParamCommError as exc:
            return self._comm_refusal(proposal, key, exc.target), {}
        if check.codes:
            return self._refuse(proposal, key, (check.codes[0], check.detail)), {}
        unread = [item.target for item in proposal.items if item.target not in check.current]
        if unread:  # a from value that was not read cannot be checked: refuse, never assume
            return self._refuse(proposal, key, ("from_unread", unread[0])), {}
        return None, check.current

    def _plant_error(
        self, proposal: ParamSetProposal, key: str, exc: Exception, wrote: bool
    ) -> WriteDecision:
        """Refuse after an unexpected error; stop the targets if anything may be written."""
        failed: tuple[str, ...] = ()
        if wrote:
            assert self._plant is not None
            failed = revert_items(self._plant, self._policies, proposal.items)
            for item in proposal.items:
                self._set_state(item.target, "stopped:comm")
        name = type(exc).__name__
        self._emit("plant_error", proposal, key, "plant_error", value=name)
        self._raise_alarm(failed, (proposal, key), "revert_failed")
        return self._refuse(proposal, key, ("plant_error", name))

    def _raise_alarm(
        self, tags: Sequence[str], origin: tuple[ParamSetProposal, str], reason: str
    ) -> None:
        """Flag ``tags`` as ``check_dcs`` (visible in ``alarms()``) and audit the alarm."""
        if not tags:
            return
        for tag in tags:
            self._alarms[tag] = "check_dcs"
        proposal, key = origin
        self._emit("alarm_check_dcs", proposal, key, reason, tag=",".join(tags))

    def _comm_refusal(self, proposal: ParamSetProposal, key: str, target: str) -> WriteDecision:
        """Fail closed after a transport error before any write: stop ``target`` and refuse."""
        self._set_state(target, "stopped:comm")
        self._emit("comm_loss", proposal, key, "comm_loss", tag=target)
        return self._refuse(proposal, key, ("comm_loss", target))

    def _applied(
        self,
        proposal: ParamSetProposal,
        key: str,
        read: tuple[Mapping[str, float], Mapping[str, float]],
    ) -> WriteDecision:
        """Update the state first, then audit; a failing audit stops the targets and alarms.

        ``read`` holds the values read before (from) and after (to) the writes.
        """
        assert self._plant is not None
        for item in proposal.items:
            self._last_applied[item.target] = stored_value(self._plant, item.target, item.to_value)
        self._last_apply_ns[proposal.loop_id] = self._env.now_ns()
        decision = WriteDecision(accepted=True, reason_code="applied")
        self._seen[key] = decision
        audited = self._audit_applied(proposal, key, read)
        self._ledger.record(proposal, read, audited)  # only what was read, only after the audit
        if audited:
            self._close_intent_safe(key)
            return decision
        return self._audit_failed(proposal, key)

    def _audit_applied(
        self,
        proposal: ParamSetProposal,
        key: str,
        read: tuple[Mapping[str, float], Mapping[str, float]],
    ) -> bool:
        """Audit every item as ``param_write`` with the values read; False if any audit failed."""
        from_read, to_read = read
        ok = True
        for item in proposal.items:
            if item.target not in from_read or item.target not in to_read:
                ok = False  # a value that was not read is never replaced by proposal data
                continue
            try:
                self._emit(
                    "param_write", proposal, key, "applied", tag=item.target,
                    applied_from=str(from_read[item.target]),
                    applied_to=str(to_read[item.target]),
                    set_size=str(len(proposal.items)),
                    rollback_of=proposal.rollback_of or "",
                )
            except Exception:  # noqa: BLE001 - keep auditing the other items, then fail closed
                ok = False
        return ok

    def _audit_failed(self, proposal: ParamSetProposal, key: str) -> WriteDecision:
        """The tuning is in the plant but its audit failed: stop the targets and raise the alarm."""
        decision = WriteDecision(accepted=True, reason_code="applied_unaudited")
        self._seen[key] = decision
        tags = tuple(item.target for item in proposal.items)
        for tag in tags:
            self._alarms[tag] = "check_dcs"
            with contextlib.suppress(Exception):
                self._set_state(tag, "stopped:comm")
        with contextlib.suppress(Exception):  # the audit sink is what failed; the flag remains
            self._raise_alarm(tags, (proposal, key), "audit_failed")
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
        audit_ok = True
        if outcome.written:
            try:
                self._emit(
                    "partial_revert", proposal, key, outcome.code, tag=outcome.failed_target,
                    written=",".join(outcome.written),
                    revert_failed=",".join(outcome.revert_failed),
                )
            except Exception:  # noqa: BLE001 - keep failing closed
                audit_ok = False
        self._raise_alarm(outcome.revert_failed, (proposal, key), "revert_failed")
        if not outcome.revert_failed and audit_ok:
            self._close_intent_safe(key)
        return self._refuse(proposal, key, (code, outcome.failed_target))

    def _close_intent_safe(self, key: str) -> None:
        """Close an intent in the durable store; do not raise if closing fails."""
        try:
            self._store.close_intent(key)
        except Exception:  # noqa: BLE001
            pass

    def has_open_intent(self, loop_id: str) -> bool:
        """Return True when a write intent is currently open for *loop_id*."""
        return self._store.has_open_for_loop(loop_id)

    def open_intents(self) -> list[ParamIntentRecord]:
        """Return all open parameter write-intent records."""
        return self._store.load_open()

    def resolve_intent(self, key: str, actor: str) -> WriteDecision:
        """Resolve an open write intent by reading current plant values and closing it."""
        record = self._store.get(key)
        if record is None or record.state != "open":
            return WriteDecision(accepted=False, reason_code="intent_not_open")
        if self._plant is None:
            return WriteDecision(accepted=False, reason_code="no_param_plant")
        read_values = self._read_targets_for_resolve(record)
        if read_values is None:
            return WriteDecision(accepted=False, reason_code="read_failed")
        self._audit_intent_resolved(record, key, read_values, actor)
        self._close_intent_safe(key)
        return WriteDecision(accepted=True, reason_code="resolved")

    def _read_targets_for_resolve(
        self, record: ParamIntentRecord
    ) -> dict[str, float] | None:
        """Read all target values from the plant for intent resolution; None on any error."""
        assert self._plant is not None
        read_values: dict[str, float] = {}
        for item in record.items:
            try:
                val = self._plant.read_param(item.target)
                read_values[item.target] = float(val)
            except Exception:  # noqa: BLE001 - keep intent open on read error
                return None
        return read_values

    def _audit_intent_resolved(
        self,
        record: ParamIntentRecord,
        key: str,
        read_values: Mapping[str, float],
        actor: str,
    ) -> None:
        """Audit the resolution of an open intent with intended and live read values."""
        fields = _make_intent_resolved_fields(record, key, read_values, actor)
        self._env.emit("intent_resolved", fields)

    # ------------------------------------------------------------------ tick and lifecycle

    def tick(self) -> None:
        """Read back every applied target; a changed value means someone changed it at the DCS.

        Read-back only: nothing is released, written back or kept alive.
        """
        if self._plant is None:
            return
        for tag in list(self._last_applied):
            if self._states.get(tag) == "enabled":
                self._guarded_readback(self._plant, tag)

    def _guarded_readback(self, plant: ParamControlSystem, tag: str) -> None:
        """Read back one target; any unexpected error stops that target and is audited."""
        try:
            self._check_readback(plant, tag)
        except Exception as exc:  # noqa: BLE001 - one bad tag must not break the gateway tick
            self._last_applied.pop(tag, None)
            with contextlib.suppress(Exception):
                self._set_state(tag, "stopped:comm")
            with contextlib.suppress(Exception):
                self._emit_tag(
                    "param_tick_error", tag, "param_tick_error", value=type(exc).__name__
                )

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
            loop=self._policies[tag].loop,
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
        self._flush_all("kill_reset")
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
        self._alarms.pop(tag, None)
        self._emit_tag("re_enable", tag, "re_enable")

    def swap_policies(self, policies: dict[str, ParamPolicy]) -> None:
        """Replace the parameter policies; every queued set is dropped with audit first.

        Kept targets keep their state, new ones start enabled, removed ones are forgotten.
        """
        self._flush_all("policy_reload")
        for tag in set(self._states) - set(policies):
            del self._states[tag]
            self._last_applied.pop(tag, None)
            self._alarms.pop(tag, None)
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


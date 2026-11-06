"""Write Gateway engine (ADR 011/012, Phase 2 #46).

The only component that writes to a control system.

Holds per-target state, enforces policy in real time, and coordinates heartbeats
and kill-switch behaviour.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, cast

from crosscut_gateway import policy_file, policy_pin
from crosscut_gateway.actor import GATEWAY_ACTOR, ActorContext, normalize_actor
from crosscut_gateway.audit import AuditLog
from crosscut_gateway.engine_params import (
    MODE_ORDER,
    ParamConfig,
    ParamEnv,
    ParamManager,
    PendingParams,
)
from crosscut_gateway.interfaces import (
    ControlSystem,
    ParamControlSystem,
    ParamSetProposal,
    WriteDecision,
    WritePolicy,
    WriteProposal,
)
from crosscut_gateway.policy import PolicyError, proposal_key, validate_proposal

Mode = Literal["off", "advisory", "dry_run", "confirm", "supervised"]

_MODE_ORDER = MODE_ORDER

_COMM_ERRORS = (ConnectionError, OSError, TimeoutError)

PROPOSAL_MAX_AGE_NS = 60 * 1_000_000_000  # 60 seconds in nanoseconds
PROPOSAL_MAX_FUTURE_NS = 5 * 1_000_000_000  # 5 seconds in nanoseconds


class WriteGateway:
    """Per-target write state machine.

    Safety model: a target may only receive a write while its state is ``enabled`` and a
    valid heartbeat proves the gateway is alive. Any comm loss, read-back mismatch or
    operator override immediately hands control back to local by calling ``release``.
    All targets start enabled; ADR 011 start-up is governed by the mode (default off is
    the caller's responsibility).
    """

    def __init__(
        self,
        plant: ControlSystem,
        policies: dict[str, WritePolicy],
        mode: Mode,
        audit: AuditLog | None = None,
        *,
        params: ParamConfig | None = None,
    ) -> None:
        """Create the gateway.

        Args:
            plant: Control system abstraction.
            policies: Mapping tag -> policy. All tags are tracked, even when disabled.
            mode: Initial gateway mode.
            audit: Optional audit log; an in-memory log is used when omitted.
            params: PID parameter targets (ADR 014); the control system for them defaults to
                ``plant`` when that implements ``ParamControlSystem``.

        Raises:
            ValueError: When mode is not one of the defined Mode values, or a parameter target
                shares its tag with a setpoint target.
        """
        if mode not in _MODE_ORDER:
            raise ValueError(f"unknown mode: {mode}")
        params = _complete_params(plant, params)
        if set(params.policies) & set(policies):
            raise ValueError("a tag cannot be both a setpoint and a parameter target")
        self._plant = plant
        self._policies = policies
        self._mode: Mode = mode
        self._mode_cap: Mode = "supervised"
        self._audit = audit or AuditLog()
        self._actor: ActorContext | None = None

        self._now_ns = 0
        self._clock_started = False
        self._killed = False

        self._init_targets(policies)
        self._params = ParamManager(self._param_env(), params)

        # Proposal idempotency and confirm-mode queue.
        self._seen_proposals: dict[str, WriteDecision] = {}
        self._proposal_cache: dict[str, WriteProposal] = {}
        self._pending: dict[str, WriteProposal] = {}
        self._proposer_actor: dict[str, str | None] = {}

    # ------------------------------------------------------------------ public API

    @property
    def mode(self) -> Mode:
        """Return the active operating mode (read-only)."""
        return self._mode

    @property
    def mode_cap(self) -> Mode:
        """Return the most permissive mode allowed by the policy (read-only)."""
        return self._mode_cap

    @property
    def killed(self) -> bool:
        """Return True while the kill switch is engaged (read-only)."""
        return self._killed

    def target_state(self, tag: object) -> str | None:
        """Return the state of a target, or None for a non-str or unknown tag."""
        if not isinstance(tag, str):
            return None
        if self._params.has_target(tag):
            return self._params.states()[tag]
        return self._states.get(tag)

    def pending_proposer(self, key: object) -> str | None:
        """Return the actor that queued a pending proposal, or None when unknown."""
        if self._params.has_pending(key):
            return self._params.pending_proposer(key)
        if not isinstance(key, str) or key not in self._pending:
            return None
        return self._proposer_actor.get(key)

    def pending_kind(self, key: object) -> str | None:
        """Return ``pid_param`` or ``setpoint`` for a pending key, None when it is not pending."""
        if self._params.has_pending(key):
            return "pid_param"
        if isinstance(key, str) and key in self._pending:
            return "setpoint"
        return None

    def pending_params(self) -> list[PendingParams]:
        """Return the parameter sets queued for confirmation."""
        return self._params.pending()

    def propose_params(
        self,
        proposal: ParamSetProposal,
        *,
        actor_ctx: ActorContext | None = None,
    ) -> WriteDecision:
        """Process one PID parameter set (ADR 014); confirm-only, refused rather than clamped."""
        with self._acting(actor_ctx):
            return self._params.propose(proposal)

    def _param_env(self) -> ParamEnv:
        """Return the view of this gateway that the parameter manager works with."""
        return ParamEnv(
            now_ns=lambda: self._now_ns,
            clock_started=lambda: self._clock_started,
            mode=lambda: self._mode,
            killed=lambda: self._killed,
            actor=self._actor_name,
            emit=self._emit_param,
        )

    def _emit_param(self, event: str, fields: dict[str, str]) -> None:
        """Append a parameter audit record stamped with the mode and the acting principal."""
        record = {**fields, "mode": self._mode, **self._current_actor().audit_fields()}
        self._audit.append(event, record, self._now_ns)

    @contextmanager
    def _acting(self, ctx: ActorContext | None) -> Iterator[None]:
        """Attribute audit records written inside the block to ``ctx``; restore on exit."""
        previous = self._actor
        self._actor = ctx
        try:
            yield
        finally:
            self._actor = previous

    def _actor_name(self) -> str | None:
        """Return the calling actor's name, or None when the call carries no actor."""
        return None if self._actor is None else self._actor.actor

    def _current_actor(self) -> ActorContext:
        """Return the actor to attribute audit records to (gateway when none is set)."""
        return GATEWAY_ACTOR if self._actor is None else self._actor

    def propose(
        self,
        proposal: WriteProposal,
        *,
        actor_ctx: ActorContext | None = None,
    ) -> WriteDecision:
        """Process one proposal through the current gateway mode.

        Returns a cached decision for duplicate proposals; otherwise the new decision.
        Every proposal produces an audit record.

        Raises:
            KeyError: When the proposal tag has no policy.
        """
        with self._acting(actor_ctx):
            return self._propose(proposal)

    def _propose(self, proposal: WriteProposal) -> WriteDecision:
        """Run one proposal through the screening and dispatch steps."""
        key = proposal_key(proposal)
        if key in self._seen_proposals:
            self._audit_duplicate(proposal, self._seen_proposals[key])
            return self._seen_proposals[key]

        self._log_proposal("proposal", proposal, "")
        blocked = self._pre_screen(proposal, key)
        if blocked is not None:
            return blocked
        decision = self._screen(proposal, key)
        if not decision.accepted:
            return decision
        return self._dispatch(proposal, decision, key)

    def _pre_screen(self, proposal: WriteProposal, key: str) -> WriteDecision | None:
        """Refuse proposals outside the write window or on a blocked target; None to go on."""
        tag = proposal.target_tag
        if self._clock_started and not self._time_in_window(proposal.t_ns):
            decision = WriteDecision(accepted=False, reason_code="bad_time")
            self._audit_decision(tag, proposal, decision)
            return decision
        refusal = self._refusal_reason(tag)
        if refusal is None:
            return None
        return self._record(proposal, WriteDecision(accepted=False, reason_code=refusal), key)

    def _screen(self, proposal: WriteProposal, key: str) -> WriteDecision:
        """Apply the operator-override and policy checks; refusals are audited and cached."""
        tag = proposal.target_tag
        try:
            operator_override = self._check_operator_override(tag)
        except _COMM_ERRORS:
            return self._handle_comm_loss(tag, proposal, key, proposal.value)
        if operator_override:
            refused = WriteDecision(accepted=False, reason_code="operator_override")
            return self._record(proposal, refused, key)
        try:
            decision = self._evaluate_proposal(proposal)
        except _COMM_ERRORS:
            return self._handle_comm_loss(tag, proposal, key, proposal.value)
        if not decision.accepted:
            return self._record(proposal, decision, key)
        return decision

    def _dispatch(
        self,
        proposal: WriteProposal,
        decision: WriteDecision,
        key: str,
    ) -> WriteDecision:
        """Route an accepted proposal to the handler for the current mode."""
        if self._mode == "advisory":
            return self._record(proposal, decision, key)
        if self._mode == "dry_run":
            return self._do_dry_run(proposal, decision, key)
        if self._mode == "confirm":
            return self._do_queue(proposal, decision, key)
        if self._mode == "supervised":
            return self._write(proposal, decision, key)
        # Unknown internal mode: refuse loudly, never write by default.
        mode_decision = WriteDecision(accepted=False, reason_code="mode_unsupported")
        self._audit_decision(proposal.target_tag, proposal, mode_decision)
        return mode_decision

    def _do_dry_run(
        self,
        proposal: WriteProposal,
        decision: WriteDecision,
        key: str,
    ) -> WriteDecision:
        """Log what would be written without touching the plant."""
        value = self._effective_value(proposal, decision)
        self._log_proposal("dry_run_write", proposal, "dry_run", value)
        dry_decision = WriteDecision(accepted=True, reason_code="dry_run", clamped_value=value)
        self._seen_proposals[key] = dry_decision
        return dry_decision

    def _do_queue(
        self,
        proposal: WriteProposal,
        decision: WriteDecision,
        key: str,
    ) -> WriteDecision:
        """Queue an accepted proposal for operator confirmation."""
        value = self._effective_value(proposal, decision)
        self._pending[key] = proposal
        self._proposal_cache[key] = proposal
        self._proposer_actor[key] = self._actor_name()
        self._log_proposal("queued", proposal, "queued", value)
        queued_decision = WriteDecision(accepted=True, reason_code="queued", clamped_value=value)
        self._seen_proposals[key] = queued_decision
        return queued_decision

    def _effective_value(self, proposal: WriteProposal, decision: WriteDecision) -> float:
        """Return the clamped value when the policy clamped it, else the proposed value."""
        if decision.clamped_value is not None:
            return decision.clamped_value
        return proposal.value

    def _record(
        self,
        proposal: WriteProposal,
        decision: WriteDecision,
        key: str,
    ) -> WriteDecision:
        """Audit a decision, then cache it for idempotent replay."""
        self._audit_decision(proposal.target_tag, proposal, decision)
        self._seen_proposals[key] = decision
        return decision

    def tick(self, now_ns: int) -> None:
        """Run one gateway cycle: heartbeat, operator override check, read-back, release."""
        self._now_ns = max(self._now_ns, now_ns)
        self._clock_started = True

        if self._killed:
            self._release_all_killed()
            return

        self._params.tick()
        for tag in self._states:
            if not self._holding.get(tag, False):
                continue
            if self._tick_tag(tag):
                continue

        if any(
            self._holding.get(tag, False) and self._states[tag] == "enabled"
            for tag in self._states
        ):
            self._send_heartbeat_safely()

    def kill(self, *, actor_ctx: ActorContext | None = None) -> None:
        """Trigger the kill switch. Setpoints are released on the next tick."""
        with self._acting(actor_ctx):
            self._kill_all()

    def reset_kill(self, *, actor_ctx: ActorContext | None = None) -> None:
        """Clear the kill latch and drop to advisory mode (never above the policy cap).

        Safe to call when the kill switch is not engaged. Every target moves to
        ``stopped:kill`` with holding cleared and must be re-enabled explicitly.
        """
        with self._acting(actor_ctx):
            self._reset_kill()

    def _reset_kill(self) -> None:
        """Clear the kill latch, stop every target, and audit the reset."""
        self._killed = False
        for tag in self._states:
            self._holding[tag] = False
            self._set_state(tag, "stopped:kill")
        self._params.reset_kill()
        self._mode = _more_restrictive("advisory", self._mode_cap)
        self._log("kill_reset", "", "kill_reset")

    def _kill_all(self) -> None:
        """Set the kill latch, flush pending proposals and move every target to killed."""
        if not self._killed:
            self._log("kill", "", "killed")
        self._killed = True
        for tag in self._states:
            self._flush_pending_tag(tag)
            self._set_state(tag, "killed")
        self._params.kill()

    def status(self) -> dict[str, str]:
        """Return the current per-target state for all policy tags."""
        return {**self._states, **self._params.states()}

    def audit_records(self) -> list[dict[str, str]]:
        """Return all audit records in append order."""
        return self._audit.records()

    def release(self, tag: str, *, actor_ctx: ActorContext | None = None) -> None:
        """Immediately hand a setpoint back to local control (public helper)."""
        with self._acting(actor_ctx):
            self._release_target(tag, "manual")

    def re_enable(self, tag: str, *, actor_ctx: ActorContext | None = None) -> None:
        """Re-enable a target after it was stopped or hold-off has expired.

        Raises:
            KeyError: When tag has no policy.
            ValueError: When the target cannot be re-enabled from its current state.
        """
        with self._acting(actor_ctx):
            self._re_enable(tag)

    def _re_enable(self, tag: str) -> None:
        """Validate the target state and move it back to enabled."""
        if self._params.has_target(tag):
            self._params.re_enable(tag)
            return
        self._validate_tag(tag)
        state = self._states[tag]
        if state == "killed":
            raise ValueError("cannot re-enable a killed target")
        if state == "hold_off":
            if self._now_ns < self._hold_until_ns.get(tag, 0):
                raise ValueError("hold-off not over")
        elif not state.startswith("stopped:"):
            raise ValueError(f"cannot re-enable from state '{state}'")
        self._set_state(tag, "enabled")
        self._log("re_enable", tag, "re_enable")

    def pending(self) -> list[WriteProposal]:
        """Return proposals that are queued for confirmation in confirm mode."""
        return list(self._pending.values())

    def approve(self, key: str, *, actor_ctx: ActorContext | None = None) -> WriteDecision:
        """Approve a queued proposal and execute it immediately in supervised mode.

        An approver may not approve a proposal they submitted themselves.

        Raises:
            KeyError: When key is not a currently pending proposal.
        """
        with self._acting(actor_ctx):
            return self._approve(key)

    def _approve(self, key: str) -> WriteDecision:
        """Run the approval checks, then execute the pending proposal."""
        if self._params.has_pending(key):
            return self._params.approve(key)
        proposal = self._pending.get(key)
        if proposal is None:
            raise KeyError(f"unknown pending proposal key: {key}")

        if self._mode != "confirm":
            decision = WriteDecision(accepted=False, reason_code="not_confirm_mode")
            self._audit_decision(proposal.target_tag, proposal, decision)
            return decision

        if self._is_self_approval(key):
            decision = WriteDecision(accepted=False, reason_code="self_approval")
            self._log_proposal("self_approval", proposal, "self_approval")
            return decision

        self._pending.pop(key, None)
        self._proposer_actor.pop(key, None)
        self._proposal_cache.pop(key, None)
        blocked = self._queued_refusal(proposal, key)
        if blocked is not None:
            return blocked
        decision = self._screen(proposal, key)
        if not decision.accepted:
            return decision
        return self._write(proposal, decision, key)

    def _is_self_approval(self, key: str) -> bool:
        """Return True when the current actor is the one who proposed the pending key."""
        proposer = self._proposer_actor.get(key)
        current = self._actor_name()
        if proposer is None or current is None:
            return False
        return normalize_actor(proposer) == normalize_actor(current)

    def _queued_refusal(self, proposal: WriteProposal, key: str) -> WriteDecision | None:
        """Return the recorded refusal when the target or proposal age blocks a queued write."""
        tag = proposal.target_tag
        refusal = self._refusal_reason(tag)
        if refusal is None and self._now_ns - proposal.t_ns > (
            self._policies[tag].watchdog_s * 1_000_000_000
        ):
            refusal = "stale_proposal"
        if refusal is None:
            return None
        return self._record(proposal, WriteDecision(accepted=False, reason_code=refusal), key)

    def reject(self, key: str, *, actor_ctx: ActorContext | None = None) -> None:
        """Reject a queued proposal without writing.

        Raises:
            KeyError: When key is not a currently pending proposal.
        """
        with self._acting(actor_ctx):
            self._reject(key)

    def _reject(self, key: str) -> None:
        """Drop a pending proposal, cache the refusal and audit it."""
        if self._params.has_pending(key):
            self._params.reject(key)
            return
        proposal = self._pending.pop(key, None)
        if proposal is None:
            raise KeyError(f"unknown pending proposal key: {key}")
        self._proposer_actor.pop(key, None)
        self._proposal_cache.pop(key, None)
        decision = WriteDecision(accepted=False, reason_code="rejected")
        self._seen_proposals[key] = decision
        self._log_proposal("rejected", proposal, "rejected")

    def set_mode(self, mode: Mode, *, actor_ctx: ActorContext | None = None) -> None:
        """Change the operating mode of the gateway.

        Raises:
            ValueError: When mode is unknown or exceeds the configured mode cap.
        """
        with self._acting(actor_ctx):
            self._set_mode(mode)

    def _set_mode(self, mode: Mode) -> None:
        """Validate the requested mode against the cap, then switch and audit it."""
        if mode not in _MODE_ORDER:
            raise ValueError(f"unknown mode: {mode}")
        if _MODE_ORDER[mode] > _MODE_ORDER[self._mode_cap]:
            raise ValueError(
                f"mode '{mode}' exceeds policy cap '{self._mode_cap}'"
            )
        old = self._mode
        self._mode = mode
        self._log("mode_change", "", f"{old}->{mode}")

    # ------------------------------------------------------------------ internal helpers

    def _init_targets(self, policies: dict[str, WritePolicy]) -> None:
        """Create the per-target state. Invariant: exactly one entry per policy tag."""
        self._states: dict[str, str] = {tag: "enabled" for tag in policies}
        self._last_written: dict[str, float] = {}
        self._last_write_t_ns: dict[str, int] = {}
        self._hold_until_ns: dict[str, int] = {}
        self._holding: dict[str, bool] = {tag: False for tag in policies}

    def _validate_tag(self, tag: str) -> None:
        """Raise KeyError when a tag has no policy."""
        if tag not in self._policies:
            raise KeyError(f"unknown tag: {tag}")

    def _refusal_reason(self, tag: str) -> str | None:
        """Return the first applicable refusal reason, or None when the write may proceed."""
        if self._mode == "off":
            return "mode_off"
        if self._killed:
            return "killed"
        if tag not in self._policies:
            return "no_policy"
        state = self._states[tag]
        if state != "enabled":
            return f"target_{state.replace(':', '_')}"
        return None

    def _time_in_window(self, t_ns: int) -> bool:
        """Return True when t_ns is within the allowed proposal time window."""
        return (
            self._now_ns - PROPOSAL_MAX_AGE_NS
            <= t_ns
            <= self._now_ns + PROPOSAL_MAX_FUTURE_NS
        )

    def _check_operator_override(self, tag: str) -> bool:
        """Detect operator override when we are holding a setpoint; return True when overridden.

        Raises:
            _COMM_ERRORS: When plant.setpoint_source or plant.loop_mode fails.
        """
        if not self._holding.get(tag, False):
            return False
        if self._plant.setpoint_source(tag) == "remote":
            return False

        self._enter_hold_off(tag, "operator_override", "operator_override")
        return True

    def _tick_tag(self, tag: str) -> bool:
        """Handle one holding tag during tick; returns True when it was handled.

        Handles operator override (source and loop-mode change), read-back mismatch,
        communication loss and watchdog timeout in that order.
        """
        try:
            override = self._check_operator_override(tag)
        except _COMM_ERRORS:
            self._comm_loss(tag)
            return True
        if override:
            return True
        if self._check_loop_mode(tag):
            return True
        if self._check_readback(tag):
            return True
        return self._check_watchdog(tag)

    def _check_loop_mode(self, tag: str) -> bool:
        """Hold the target off when its loop mode left the allowed set; True when handled."""
        try:
            loop_mode = self._plant.loop_mode(tag)
        except _COMM_ERRORS:
            self._comm_loss(tag)
            return True
        if loop_mode not in self._policies[tag].allowed_loop_modes:
            self._enter_hold_off(tag, "operator_override", "mode_change")
            return True
        return False

    def _check_readback(self, tag: str) -> bool:
        """Hold the target off when read-back diverges from the last write; True when handled."""
        try:
            actual = self._plant.read(tag)
        except _COMM_ERRORS:
            self._comm_loss(tag)
            return True
        expected = self._last_written.get(tag)
        tolerance = self._policies[tag].readback_tolerance
        if expected is not None and abs(actual - expected) > tolerance:
            self._enter_hold_off(tag, "readback_mismatch", "readback_mismatch", value=str(actual))
            return True
        return False

    def _check_watchdog(self, tag: str) -> bool:
        """Release the target when its last write is older than the watchdog; True when released."""
        last_write_t_ns = self._last_write_t_ns.get(tag)
        if last_write_t_ns is None:
            return False
        if self._now_ns - last_write_t_ns <= self._policies[tag].watchdog_s * 1_000_000_000:
            return False
        self._release_target(tag, "watchdog")
        self._holding[tag] = False
        return True

    def _send_heartbeat_safely(self) -> None:
        """Send a heartbeat; any communication error stops all holding targets."""
        try:
            self._plant.send_heartbeat()
        except _COMM_ERRORS:
            for tag in self._states:
                if self._holding.get(tag, False):
                    self._comm_loss(tag)

    def _enter_hold_off(
        self,
        tag: str,
        event: str,
        reason: str,
        value: str = "",
    ) -> None:
        """Put a target into hold_off, release it, and audit the event."""
        self._set_state(tag, "hold_off")
        self._hold_until_ns[tag] = self._now_ns + int(
            self._policies[tag].hold_off_s * 1_000_000_000
        )
        self._holding[tag] = False
        self._release_target(tag, reason)
        self._log(event, tag, reason, value)

    def _comm_loss(self, tag: str) -> None:
        """Stop a target after a communication error and release it."""
        self._set_state(tag, "stopped:comm")
        self._holding[tag] = False
        self._release_target(tag, "comm_loss")
        self._log("comm_loss", tag, "comm_loss")

    def _handle_comm_loss(
        self,
        tag: str,
        proposal: WriteProposal,
        key: str,
        value: float,
    ) -> WriteDecision:
        """Handle a communication error during propose or approve."""
        self._comm_loss(tag)
        self._log_proposal("comm_loss", proposal, "comm_loss", value)
        decision = WriteDecision(accepted=False, reason_code="comm_loss")
        self._seen_proposals[key] = decision
        return decision

    def _evaluate_proposal(self, proposal: WriteProposal) -> WriteDecision:
        """Run policy validation with current plant state and history."""
        tag = proposal.target_tag
        policy = self._policies[tag]
        last_value = self._last_written.get(tag)
        if last_value is None:
            last_value = self._plant.read(tag)
        last_write_t_ns = self._last_write_t_ns.get(tag)
        return validate_proposal(
            policy,
            proposal,
            last_value,
            last_write_t_ns,
            self._plant.loop_mode(tag),
        )

    def _write(
        self,
        proposal: WriteProposal,
        decision: WriteDecision,
        key: str,
    ) -> WriteDecision:
        """Perform the supervised write and update per-target state.

        Returns the final cached decision. Side effects: plant write, heartbeat, audit,
        and possibly release + stop on failure.
        """
        tag = proposal.target_tag
        value = self._effective_value(proposal, decision)
        self._log_proposal("write_intent", proposal, decision.reason_code, value)
        try:
            success = self._plant.write(tag, value)
        except _COMM_ERRORS:
            return self._handle_comm_loss(tag, proposal, key, value)
        if not success:
            return self._fail_rejected(proposal, key, value)
        self._record_success(proposal, decision, key, value)
        try:
            self._plant.send_heartbeat()
        except _COMM_ERRORS:
            return self._handle_comm_loss(tag, proposal, key, value)
        return self._seen_proposals[key]

    def _fail_rejected(self, proposal: WriteProposal, key: str, value: float) -> WriteDecision:
        """Stop and release the target after the control system rejected a write."""
        tag = proposal.target_tag
        self._set_state(tag, "stopped:rejected")
        self._holding[tag] = False
        self._release_target(tag, "rejected")
        self._log_proposal(
            "rejected_by_control_system",
            proposal,
            "rejected_by_control_system",
            value,
        )
        rejected_decision = WriteDecision(accepted=False, reason_code="rejected_by_control_system")
        self._seen_proposals[key] = rejected_decision
        return rejected_decision

    def _record_success(
        self,
        proposal: WriteProposal,
        decision: WriteDecision,
        key: str,
        value: float,
    ) -> None:
        """Remember an accepted write for read-back, watchdog and idempotent replay."""
        tag = proposal.target_tag
        self._last_written[tag] = value
        self._last_write_t_ns[tag] = proposal.t_ns
        self._holding[tag] = True
        self._seen_proposals[key] = WriteDecision(
            accepted=True,
            reason_code=decision.reason_code,
            clamped_value=decision.clamped_value,
        )
        self._log_proposal("write", proposal, decision.reason_code, value)

    def _release_target(self, tag: str, reason: str) -> bool:
        """Hand a setpoint back to local control, auditing the result."""
        try:
            self._plant.release(tag)
        except _COMM_ERRORS:
            self._log("release", tag, "release_failed")
            return False
        self._log("release", tag, reason)
        return True

    def _release_all_killed(self) -> None:
        """Release every held target exactly once during the kill sequence; no heartbeat is sent."""
        for tag in self._states:
            if self._holding.get(tag, False):
                if self._release_target(tag, "killed"):
                    self._holding[tag] = False

    def _set_state(self, tag: str, state: str) -> None:
        """Change a target's state and flush its pending proposals when leaving enabled."""
        old_state = self._states.get(tag)
        self._states[tag] = state
        if old_state == "enabled" and state != "enabled":
            self._flush_pending_tag(tag)

    def _flush_pending_tag(self, tag: str) -> None:
        """Remove all pending proposals for a tag and audit the flush."""
        keys_to_remove = [
            key for key, proposal in self._pending.items() if proposal.target_tag == tag
        ]
        if keys_to_remove:
            for key in keys_to_remove:
                proposal = self._pending.pop(key, None)
                self._proposer_actor.pop(key, None)
                self._proposal_cache.pop(key, None)
                if proposal is not None:
                    self._seen_proposals[key] = WriteDecision(
                        accepted=False, reason_code="flushed"
                    )
                    self._log_proposal("flushed", proposal, "flushed")

    def _audit_decision(self, tag: str, proposal: WriteProposal, decision: WriteDecision) -> None:
        """Record a proposal decision in the audit log."""
        value = self._effective_value(proposal, decision)
        self._log_proposal("decision", proposal, decision.reason_code, value)

    def _audit_duplicate(self, proposal: WriteProposal, cached: WriteDecision) -> None:
        """Record a duplicate proposal in the audit log."""
        value = cached.clamped_value if cached.clamped_value is not None else proposal.value
        self._log_proposal("duplicate", proposal, cached.reason_code, value)

    def _log(self, event: str, tag: str, reason: str, value: str = "") -> None:
        """Append a simple audit record, stamped with the acting principal."""
        self._audit.append(
            event,
            {
                "tag": tag,
                "value": value,
                "proposer": "",
                "mode": self._mode,
                "reason_code": reason,
                **self._current_actor().audit_fields(),
            },
            self._now_ns,
        )

    def _log_proposal(
        self,
        event: str,
        proposal: WriteProposal,
        reason: str,
        value: float | None = None,
    ) -> None:
        """Append an audit record for a proposal."""
        audit_value = str(proposal.value) if value is None else str(value)
        self._audit.append(
            event,
            {
                "tag": proposal.target_tag,
                "value": audit_value,
                "proposer": proposal.proposer,
                "mode": self._mode,
                "reason_code": reason,
                **self._current_actor().audit_fields(),
            },
            self._now_ns,
        )

    def record_event(self, event: str, ctx: ActorContext, reason: str, value: str = "") -> None:
        """Append an operator-visible audit event that is not tied to a target."""
        with self._acting(ctx):
            self._log(event, "", reason, value)

    def swap_policies(
        self,
        policies: dict[str, WritePolicy],
        cap: Mode,
        *,
        digest: str = "",
        actor_ctx: ActorContext | None = None,
    ) -> None:
        """Replace policies and the mode cap; allowed only in mode off or advisory.

        Tags may be added or removed. Removed tags have pending proposals flushed first.
        The live mode is lowered to ``cap`` when it is above it.

        Raises:
            ValueError: When the gateway is in a mode above advisory.
        """
        with self._acting(actor_ctx):
            if self._mode not in ("off", "advisory"):
                raise ValueError("policy reload needs mode off or advisory")
            self._drop_removed_tags(set(self._policies) - set(policies))
            self._add_new_tags(set(policies) - set(self._policies))
            self._policies = dict(policies)
            self._mode_cap = cap
            if _MODE_ORDER[self._mode] > _MODE_ORDER[cap]:
                self._mode = cap
            self._log("policy_reload", "", "policy_reload", digest)

    def _drop_removed_tags(self, removed: set[str]) -> None:
        """Flush pending proposals and forget the state of tags a reload removed."""
        for tag in removed:
            self._flush_pending_tag(tag)
            self._states.pop(tag, None)
            self._holding.pop(tag, None)
            self._last_written.pop(tag, None)
            self._last_write_t_ns.pop(tag, None)
            self._hold_until_ns.pop(tag, None)

    def _add_new_tags(self, added: set[str]) -> None:
        """Start newly added tags as enabled and not holding."""
        for tag in added:
            self._states[tag] = "enabled"
            self._holding[tag] = False


def _complete_params(plant: ControlSystem, params: ParamConfig | None) -> ParamConfig:
    """Return ``params`` with the control system filled in from ``plant`` when it fits."""
    config = params or ParamConfig({})
    if config.plant is None and isinstance(plant, ParamControlSystem):
        return ParamConfig(config.policies, plant)
    return config


def _more_restrictive(a: Mode, b: Mode) -> Mode:
    """Return the less permissive of two gateway modes."""
    return a if _MODE_ORDER[a] <= _MODE_ORDER[b] else b


def start_from_policy_file(
    path: Path,
    plant: ControlSystem,
    mode: Mode,
    audit: AuditLog | None = None,
    *,
    key: bytes | None = None,
    allow_legacy_sidecar: bool = False,
) -> WriteGateway:
    """Build a WriteGateway from a pinned policy file.

    By default the file must carry a signed pin verified with ``key``. The unsigned
    ``allow_legacy_sidecar`` mode checks ``path.with_suffix(".sha256")`` instead and is kept
    only for older deployments.

    Args:
        path: Path to the write-policy JSON file.
        plant: Control system abstraction.
        mode: Requested gateway mode.
        audit: Optional audit log.
        key: Signing key that verifies the policy pin.
        allow_legacy_sidecar: Use the legacy SHA-256 sidecar check instead of a pin.

    Returns:
        A WriteGateway configured with the effective (more restrictive) mode.

    Raises:
        PolicyError: When the policy cannot be verified or parsed.
    """
    if allow_legacy_sidecar:
        targets, file_mode = _load_sidecar_policy(path)
    else:
        targets, file_mode = _load_pinned_policy(path, key)
    effective_mode = _more_restrictive(mode, file_mode)  # type: ignore[arg-type]
    gateway = WriteGateway(plant, targets, effective_mode, audit)
    gateway._mode_cap = cast(Mode, file_mode)  # the cap is the policy mode, not the start mode
    return gateway


def safe_gateway(plant: ControlSystem, audit: AuditLog | None = None) -> WriteGateway:
    """Return a gateway with no targets in mode off.

    This is the fallback used when the policy cannot be loaded while the kill latch is set:
    nothing can be written, but the service stays able to process a kill_reset.

    Args:
        plant: Control system abstraction.
        audit: Optional audit log.

    Returns:
        A WriteGateway that tracks no targets and refuses every write.
    """
    return WriteGateway(plant, {}, "off", audit)


def _load_sidecar_policy(path: Path) -> tuple[dict[str, WritePolicy], str]:
    """Verify the legacy ``.sha256`` sidecar digest, then parse the policy file."""
    digest_path = path.with_suffix(".sha256")
    expected_digest = digest_path.read_text(encoding="utf-8").strip()
    raw_bytes = path.read_bytes()
    actual_digest = hashlib.sha256(raw_bytes).hexdigest()
    if actual_digest.lower() != expected_digest.lower():
        raise PolicyError("policy file hash mismatch")
    targets, file_mode, _ = policy_file.load_policy_file(path, None)
    return targets, file_mode


def _load_pinned_policy(path: Path, key: bytes | None) -> tuple[dict[str, WritePolicy], str]:
    """Load a policy file whose signed pin is verified with ``key``."""
    if key is None:
        raise PolicyError("a signing key is required to load a pinned policy")
    targets, file_mode, _ = policy_pin.load_pinned_policy(path, key)
    return targets, file_mode

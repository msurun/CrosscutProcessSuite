"""Write Gateway engine (ADR 011/012, Phase 2 #46).

The only component that writes to a control system.

Holds per-target state, enforces policy in real time, and coordinates heartbeats
and kill-switch behaviour.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from crosscut_gateway import policy_file
from crosscut_gateway.audit import AuditLog
from crosscut_gateway.interfaces import SimControlSystem, WriteDecision, WritePolicy, WriteProposal
from crosscut_gateway.policy import PolicyError, proposal_key, validate_proposal

Mode = Literal["off", "advisory", "dry_run", "confirm", "supervised"]

_MODE_ORDER = {"off": 0, "advisory": 1, "dry_run": 2, "confirm": 3, "supervised": 4}

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
        plant: SimControlSystem,
        policies: dict[str, WritePolicy],
        mode: Mode,
        audit: AuditLog | None = None,
    ) -> None:
        """Create the gateway.

        Args:
            plant: Control system abstraction.
            policies: Mapping tag -> policy. All tags are tracked, even when disabled.
            mode: Initial gateway mode.
            audit: Optional audit log; an in-memory log is used when omitted.

        Raises:
            ValueError: When mode is not one of the defined Mode values.
        """
        if mode not in _MODE_ORDER:
            raise ValueError(f"unknown mode: {mode}")
        self._plant = plant
        self._policies = policies
        self._mode: Mode = mode
        self._mode_cap: Mode = "supervised"
        self._audit = audit or AuditLog()

        self._now_ns = 0
        self._clock_started = False
        self._killed = False

        self._init_targets(policies)

        # Proposal idempotency and confirm-mode queue.
        self._seen_proposals: dict[str, WriteDecision] = {}
        self._proposal_cache: dict[str, WriteProposal] = {}
        self._pending: dict[str, WriteProposal] = {}

    # ------------------------------------------------------------------ public API

    @property
    def mode(self) -> Mode:
        """Return the active operating mode (read-only)."""
        return self._mode

    def propose(self, proposal: WriteProposal) -> WriteDecision:
        """Process one proposal through the current gateway mode.

        Returns a cached decision for duplicate proposals; otherwise the new decision.
        Every proposal produces an audit record.

        Raises:
            KeyError: When the proposal tag has no policy.
        """
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

    def kill(self) -> None:
        """Trigger the kill switch. Setpoints are released on the next tick."""
        if not self._killed:
            self._log("kill", "", "killed")
        self._killed = True
        for tag in self._states:
            self._flush_pending_tag(tag)
            self._set_state(tag, "killed")

    def status(self) -> dict[str, str]:
        """Return the current per-target state for all policy tags."""
        return dict(self._states)

    def audit_records(self) -> list[dict[str, str]]:
        """Return all audit records in append order."""
        return self._audit.records()

    def release(self, tag: str) -> None:
        """Immediately hand a setpoint back to local control (public helper)."""
        self._release_target(tag, "manual")

    def re_enable(self, tag: str) -> None:
        """Re-enable a target after it was stopped or hold-off has expired.

        Raises:
            KeyError: When tag has no policy.
            ValueError: When the target cannot be re-enabled from its current state.
        """
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

    def approve(self, key: str) -> WriteDecision:
        """Approve a queued proposal and execute it immediately in supervised mode.

        Raises:
            KeyError: When key is not a currently pending proposal.
        """
        proposal = self._pending.get(key)
        if proposal is None:
            raise KeyError(f"unknown pending proposal key: {key}")

        if self._mode != "confirm":
            decision = WriteDecision(accepted=False, reason_code="not_confirm_mode")
            self._audit_decision(proposal.target_tag, proposal, decision)
            return decision

        self._pending.pop(key, None)
        self._proposal_cache.pop(key, None)
        blocked = self._queued_refusal(proposal, key)
        if blocked is not None:
            return blocked
        decision = self._screen(proposal, key)
        if not decision.accepted:
            return decision
        return self._write(proposal, decision, key)

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

    def reject(self, key: str) -> None:
        """Reject a queued proposal without writing.

        Raises:
            KeyError: When key is not a currently pending proposal.
        """
        proposal = self._pending.pop(key, None)
        if proposal is None:
            raise KeyError(f"unknown pending proposal key: {key}")
        self._proposal_cache.pop(key, None)
        decision = WriteDecision(accepted=False, reason_code="rejected")
        self._seen_proposals[key] = decision
        self._log_proposal("rejected", proposal, "rejected")

    def set_mode(self, mode: Mode) -> None:
        """Change the operating mode of the gateway.

        Raises:
            ValueError: When mode is unknown or exceeds the configured mode cap.
        """
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
        """Append a simple audit record."""
        self._audit.append(
            event,
            {
                "tag": tag,
                "value": value,
                "proposer": "",
                "mode": self._mode,
                "reason_code": reason,
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
            },
            self._now_ns,
        )


def _more_restrictive(a: Mode, b: Mode) -> Mode:
    """Return the less permissive of two gateway modes."""
    return a if _MODE_ORDER[a] <= _MODE_ORDER[b] else b


def start_from_policy_file(
    path: Path,
    plant: SimControlSystem,
    mode: Mode,
    audit: AuditLog | None = None,
) -> WriteGateway:
    """Build a WriteGateway from a policy file and its pinned SHA-256 digest.

    The sidecar file ``path.with_suffix(".sha256")`` must contain the expected digest;
    any mismatch raises ``PolicyError`` before the policy is parsed.

    Args:
        path: Path to the write-policy JSON file.
        plant: Control system abstraction.
        mode: Requested gateway mode.
        audit: Optional audit log.

    Returns:
        A WriteGateway configured with the effective (more restrictive) mode.
    """
    digest_path = path.with_suffix(".sha256")
    expected_digest = digest_path.read_text(encoding="utf-8").strip()
    raw_bytes = path.read_bytes()
    actual_digest = hashlib.sha256(raw_bytes).hexdigest()
    if actual_digest.lower() != expected_digest.lower():
        raise PolicyError("policy file hash mismatch")

    targets, file_mode, _ = policy_file.load_policy_file(path, None)
    effective_mode = _more_restrictive(mode, file_mode)  # type: ignore[arg-type]
    gateway = WriteGateway(plant, targets, effective_mode, audit)
    gateway._mode_cap = effective_mode
    return gateway

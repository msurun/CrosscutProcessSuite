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


class WriteGateway:
    """Per-target write state machine.

    Safety model: a target may only receive a write while its state is ``enabled`` and a
    valid heartbeat proves the gateway is alive. Any comm loss, read-back mismatch or
    operator override immediately hands control back to local by calling ``release``.
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
        """
        self._plant = plant
        self._policies = policies
        self._mode: Mode = mode
        self._audit = audit or AuditLog()

        self._now_ns = 0
        self._killed = False

        # Per-target state. Invariant: exactly one entry per policy tag.
        self._states: dict[str, str] = {tag: "enabled" for tag in policies}
        self._last_written: dict[str, float] = {}
        self._last_write_t_ns: dict[str, int] = {}
        self._hold_until_ns: dict[str, int] = {}
        self._holding: dict[str, bool] = {tag: False for tag in policies}

        # Proposal idempotency and confirm-mode queue.
        self._seen_proposals: dict[str, WriteDecision] = {}
        self._proposal_cache: dict[str, WriteProposal] = {}
        self._pending: dict[str, WriteProposal] = {}

    # ------------------------------------------------------------------ public API

    def propose(self, proposal: WriteProposal) -> WriteDecision:
        """Process one proposal through the current gateway mode.

        Returns a cached decision for duplicate proposals; otherwise the new decision.
        Every proposal produces an audit record.
        """
        key = proposal_key(proposal)
        if key in self._seen_proposals:
            return self._seen_proposals[key]

        self._now_ns = max(self._now_ns, proposal.t_ns)
        tag = proposal.target_tag

        self._audit.append(
            "proposal",
            {
                "tag": tag,
                "value": str(proposal.value),
                "proposer": proposal.proposer,
                "mode": self._mode,
                "reason_code": "",
            },
            self._now_ns,
        )

        refusal = self._refusal_reason(tag)
        if refusal is not None:
            decision = WriteDecision(accepted=False, reason_code=refusal)
            self._audit_decision(tag, proposal, decision)
            self._seen_proposals[key] = decision
            return decision

        operator_override = self._check_operator_override(tag)
        if operator_override:
            decision = WriteDecision(accepted=False, reason_code="operator_override")
            self._audit_decision(tag, proposal, decision)
            self._seen_proposals[key] = decision
            return decision

        decision = self._evaluate_proposal(proposal)
        if not decision.accepted:
            self._audit_decision(tag, proposal, decision)
            self._seen_proposals[key] = decision
            return decision

        if self._mode == "advisory":
            self._audit_decision(tag, proposal, decision)
            self._seen_proposals[key] = decision
            return decision

        value = decision.clamped_value if decision.clamped_value is not None else proposal.value

        if self._mode == "dry_run":
            self._audit.append(
                "dry_run_write",
                {
                    "tag": tag,
                    "value": str(value),
                    "proposer": proposal.proposer,
                    "mode": self._mode,
                    "reason_code": "dry_run",
                },
                self._now_ns,
            )
            dry_decision = WriteDecision(accepted=True, reason_code="dry_run", clamped_value=value)
            self._seen_proposals[key] = dry_decision
            return dry_decision

        if self._mode == "confirm":
            self._pending[key] = proposal
            self._proposal_cache[key] = proposal
            self._audit.append(
                "queued",
                {
                    "tag": tag,
                    "value": str(value),
                    "proposer": proposal.proposer,
                    "mode": self._mode,
                    "reason_code": "queued",
                },
                self._now_ns,
            )
            queued_decision = WriteDecision(
                accepted=True, reason_code="queued", clamped_value=value
            )
            self._seen_proposals[key] = queued_decision
            return queued_decision

        # supervised mode
        return self._write(tag, value, proposal, decision, key)

    def tick(self, now_ns: int) -> None:
        """Run one gateway cycle: heartbeat, operator override check, read-back, release."""
        self._now_ns = max(self._now_ns, now_ns)

        if self._killed:
            self._release_all_killed()
            return

        for tag in self._states:
            if not self._holding.get(tag, False):
                continue
            if self._check_operator_override(tag):
                continue
            if self._check_readback(tag):
                continue

        if any(
            self._holding.get(tag, False) and self._states[tag] == "enabled"
            for tag in self._states
        ):
            self._plant.send_heartbeat()

    def kill(self) -> None:
        """Trigger the kill switch. Setpoints are released on the next tick."""
        if not self._killed:
            self._audit.append(
                "kill",
                {
                    "tag": "",
                    "value": "",
                    "proposer": "",
                    "mode": self._mode,
                    "reason_code": "killed",
                },
                self._now_ns,
            )
        self._killed = True
        for tag in self._states:
            self._states[tag] = "killed"

    def status(self) -> dict[str, str]:
        """Return the current per-target state for all policy tags."""
        return dict(self._states)

    def audit_records(self) -> list[dict[str, str]]:
        """Return all audit records in append order."""
        return self._audit.records()

    def release(self, tag: str) -> None:
        """Immediately hand a setpoint back to local control (public helper)."""
        self._release_target(tag)

    def re_enable(self, tag: str) -> None:
        """Re-enable a target after it was stopped or hold-off has expired."""
        self._validate_tag(tag)
        state = self._states[tag]
        if state == "killed":
            raise ValueError("cannot re-enable a killed target")
        if state == "hold_off":
            if self._now_ns < self._hold_until_ns.get(tag, 0):
                raise ValueError("hold-off not over")
        elif not state.startswith("stopped:"):
            raise ValueError(f"cannot re-enable from state '{state}'")
        self._states[tag] = "enabled"
        self._audit.append(
            "re_enable",
            {
                "tag": tag,
                "value": "",
                "proposer": "",
                "mode": self._mode,
                "reason_code": "re_enable",
            },
            self._now_ns,
        )

    def pending(self) -> list[WriteProposal]:
        """Return proposals that are queued for confirmation in confirm mode."""
        return [proposal for proposal in self._pending.values()]

    def approve(self, key: str) -> WriteDecision:
        """Approve a queued proposal and execute it immediately in supervised mode."""
        proposal = self._pending.pop(key, None)
        if proposal is None:
            raise KeyError(f"unknown pending proposal key: {key}")
        self._proposal_cache.pop(key, None)

        tag = proposal.target_tag
        refusal = self._refusal_reason(tag)
        if refusal is not None:
            decision = WriteDecision(accepted=False, reason_code=refusal)
            self._seen_proposals[key] = decision
            self._audit_decision(tag, proposal, decision)
            return decision

        decision = self._evaluate_proposal(proposal)
        if not decision.accepted:
            self._seen_proposals[key] = decision
            self._audit_decision(tag, proposal, decision)
            return decision

        value = decision.clamped_value if decision.clamped_value is not None else proposal.value
        return self._write(tag, value, proposal, decision, key)

    def reject(self, key: str) -> None:
        """Reject a queued proposal without writing."""
        proposal = self._pending.pop(key, None)
        if proposal is None:
            raise KeyError(f"unknown pending proposal key: {key}")
        self._proposal_cache.pop(key, None)
        self._audit.append(
            "rejected",
            {
                "tag": proposal.target_tag,
                "value": str(proposal.value),
                "proposer": proposal.proposer,
                "mode": self._mode,
                "reason_code": "rejected",
            },
            self._now_ns,
        )

    def set_mode(self, mode: Mode) -> None:
        """Change the operating mode of the gateway."""
        self._mode = mode

    # ------------------------------------------------------------------ internal helpers

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

    def _check_operator_override(self, tag: str) -> bool:
        """Detect operator override when we are holding a setpoint; return True when overridden."""
        if not self._holding.get(tag, False):
            return False
        if self._plant.setpoint_source(tag) == "remote":
            return False

        policy = self._policies[tag]
        self._states[tag] = "hold_off"
        self._hold_until_ns[tag] = self._now_ns + int(policy.hold_off_s * 1e9)
        self._holding[tag] = False
        self._audit.append(
            "operator_override",
            {
                "tag": tag,
                "value": "",
                "proposer": "",
                "mode": self._mode,
                "reason_code": "operator_override",
            },
            self._now_ns,
        )
        return True

    def _check_readback(self, tag: str) -> bool:
        """Verify plant read-back matches last written value; release on mismatch."""
        policy = self._policies[tag]
        actual = self._plant.read(tag)
        expected = self._last_written.get(tag)
        if expected is None or abs(actual - expected) <= policy.readback_tolerance:
            return False

        self._states[tag] = "stopped:readback"
        self._holding[tag] = False
        self._release_target(tag)
        self._audit.append(
            "readback_mismatch",
            {
                "tag": tag,
                "value": str(actual),
                "proposer": "",
                "mode": self._mode,
                "reason_code": "readback_mismatch",
            },
            self._now_ns,
        )
        return True

    def _release_target(self, tag: str) -> None:
        """Hand a setpoint back to local control, ignoring communication failures."""
        try:
            self._plant.release(tag)
        except _COMM_ERRORS:
            pass

    def _release_all_killed(self) -> None:
        """Release every target exactly once during the kill sequence; no heartbeat is sent."""
        for tag in self._states:
            if self._holding.get(tag, False):
                self._release_target(tag)
                self._holding[tag] = False
            self._states[tag] = "killed"

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
        tag: str,
        value: float,
        proposal: WriteProposal,
        decision: WriteDecision,
        key: str,
    ) -> WriteDecision:
        """Perform the supervised write and update per-target state.

        Returns the final cached decision. Side effects: plant write, heartbeat, audit,
        and possibly release + stop on failure.
        """
        try:
            success = self._plant.write(tag, value)
        except _COMM_ERRORS:
            self._states[tag] = "stopped:comm"
            self._holding[tag] = False
            self._release_target(tag)
            self._audit.append(
                "comm_loss",
                {
                    "tag": tag,
                    "value": str(value),
                    "proposer": proposal.proposer,
                    "mode": self._mode,
                    "reason_code": "comm_loss",
                },
                self._now_ns,
            )
            comm_decision = WriteDecision(accepted=False, reason_code="comm_loss")
            self._seen_proposals[key] = comm_decision
            return comm_decision

        if not success:
            self._states[tag] = "stopped:rejected"
            self._holding[tag] = False
            self._audit.append(
                "rejected_by_control_system",
                {
                    "tag": tag,
                    "value": str(value),
                    "proposer": proposal.proposer,
                    "mode": self._mode,
                    "reason_code": "rejected_by_control_system",
                },
                self._now_ns,
            )
            rejected_decision = WriteDecision(
                accepted=False, reason_code="rejected_by_control_system"
            )
            self._seen_proposals[key] = rejected_decision
            return rejected_decision

        self._last_written[tag] = value
        self._last_write_t_ns[tag] = proposal.t_ns
        self._holding[tag] = True
        self._plant.send_heartbeat()
        self._audit.append(
            "write",
            {
                "tag": tag,
                "value": str(value),
                "proposer": proposal.proposer,
                "mode": self._mode,
                "reason_code": decision.reason_code,
            },
            self._now_ns,
        )
        final_decision = WriteDecision(
            accepted=True,
            reason_code=decision.reason_code,
            clamped_value=decision.clamped_value,
        )
        self._seen_proposals[key] = final_decision
        return final_decision

    def _audit_decision(self, tag: str, proposal: WriteProposal, decision: WriteDecision) -> None:
        """Record a proposal decision in the audit log."""
        value = decision.clamped_value if decision.clamped_value is not None else proposal.value
        self._audit.append(
            "decision",
            {
                "tag": tag,
                "value": str(value),
                "proposer": proposal.proposer,
                "mode": self._mode,
                "reason_code": decision.reason_code,
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
    return WriteGateway(plant, targets, effective_mode, audit)

"""Hardening tests for the write gateway engine (written before the engine fix).
Each test pins one safety behaviour; most are expected to fail until engine.py is hardened.
Time is the simulated clock from test_gateway_scenarios; no src file is touched here.
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from crosscut_gateway import engine
from crosscut_gateway.policy import proposal_key, validate_proposal
from test_gateway_scenarios import POLICY, TAG, S, SimPlant, proposal, run


class FaultPlant(SimPlant):
    """SimPlant whose reads, source, heartbeat and release can be made to fail."""

    def __init__(self) -> None:
        """Start with no faults injected and an empty release log."""
        super().__init__()
        self.fail_read = False
        self.fail_loop_mode = False
        self.fail_source = False
        self.fail_heartbeat = False
        self.fail_release = False
        self.releases: list[str] = []

    def read(self, tag: str) -> float:
        """Read the value, or raise if reads are set to fail."""
        if self.fail_read:
            raise ConnectionError("down")
        return super().read(tag)

    def loop_mode(self, tag: str) -> str:
        """Loop mode, or raise if mode reads are set to fail."""
        if self.fail_loop_mode:
            raise ConnectionError("down")
        return super().loop_mode(tag)

    def setpoint_source(self, tag: str) -> str:
        """Setpoint source, or raise if source reads are set to fail."""
        if self.fail_source:
            raise ConnectionError("down")
        return super().setpoint_source(tag)

    def send_heartbeat(self) -> None:
        """Send a heartbeat, or raise if heartbeats are set to fail."""
        if self.fail_heartbeat:
            raise ConnectionError("down")
        super().send_heartbeat()

    def release(self, tag: str) -> None:
        """Log the release, or raise if releases are set to fail."""
        if self.fail_release:
            raise ConnectionError("down")
        self.releases.append(tag)
        super().release(tag)


class StickyPlant(FaultPlant):
    """FaultPlant whose operator changes do not clear the setpoint owner."""

    def set_mode_by_operator(self, tag: str, mode: str) -> None:
        """Change the loop mode only."""
        self.modes[tag] = mode

    def set_setpoint_by_operator(self, tag: str, value: float) -> None:
        """Change the setpoint value only."""
        self.values[tag] = value


class SpyPlant(SimPlant):
    """SimPlant that calls an optional probe before each write and heartbeat."""

    def __init__(self) -> None:
        """Start with no probe installed."""
        super().__init__()
        self.probe: Callable[[str], None] | None = None

    def write(self, tag: str, value: float) -> bool:
        """Notify the probe of a write, then write."""
        if self.probe is not None:
            self.probe("write")
        return super().write(tag, value)

    def send_heartbeat(self) -> None:
        """Notify the probe of a heartbeat, then send it."""
        if self.probe is not None:
            self.probe("heartbeat")
        super().send_heartbeat()


def events(gw: engine.WriteGateway) -> list[str]:
    """Event names of the audit trail, in order."""
    return [r["event"] for r in gw.audit_records()]


def make(mode: str, plant: SimPlant | None = None) -> engine.WriteGateway:
    """Build a gateway in ``mode`` for TAG on ``plant`` (a fresh SimPlant by default)."""
    target = plant if plant is not None else SimPlant()
    return engine.WriteGateway(target, {TAG: POLICY}, mode)


def write_signed_policy(path: Path, mode: str) -> Path:
    """Write a policy file for TAG with its sha256 sidecar; return the policy path."""
    target = {
        "limits": POLICY.limits,
        "max_step": POLICY.max_step,
        "max_rate_per_s": POLICY.max_rate_per_s,
        "min_interval_s": POLICY.min_interval_s,
        "allowed_loop_modes": POLICY.allowed_loop_modes,
        "hold_off_s": POLICY.hold_off_s,
        "watchdog_s": POLICY.watchdog_s,
        "readback_tolerance": POLICY.readback_tolerance,
    }
    doc = {"version": 1, "mode": mode, "targets": {TAG: target}}
    path.write_text(json.dumps(doc), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".sha256").write_text(digest, encoding="utf-8")
    return path


def test_future_proposal_does_not_expire_hold_off() -> None:
    """A far-future proposal is refused as bad_time and cannot end hold-off."""
    plant = SimPlant()
    gw = make("supervised", plant)
    gw.propose(proposal(55.0))
    plant.set_setpoint_by_operator(TAG, 40.0)
    run(gw, plant, 1)
    assert gw.status()[TAG] == "hold_off"
    d = gw.propose(proposal(41.0, plant.now_ns + 3600 * S))
    assert not d.accepted
    assert d.reason_code == "bad_time"
    with pytest.raises(ValueError):
        gw.re_enable(TAG)


@pytest.mark.parametrize(
    ("offset_s", "expected_accept"),
    [(-61, False), (-59, True), (5, True), (6, False)],
)
def test_bad_time_window(offset_s: int, expected_accept: bool) -> None:
    """A proposal is accepted only within 60 s in the past and 5 s in the future."""
    plant = SimPlant()
    gw = make("supervised", plant)
    gw.tick(100 * S)
    d = gw.propose(proposal(55.0, 100 * S + offset_s * S))
    assert d.accepted == expected_accept
    if not expected_accept:
        assert d.reason_code == "bad_time"
        assert plant.writes == []


def test_unknown_mode_rejected_at_init() -> None:
    """A gateway cannot be built in a mode that is not defined."""
    with pytest.raises(ValueError):
        engine.WriteGateway(SimPlant(), {TAG: POLICY}, "bogus")  # type: ignore[arg-type]


def test_set_mode_unknown_rejected() -> None:
    """set_mode refuses a mode name that is not defined."""
    gw = make("supervised")
    with pytest.raises(ValueError):
        gw.set_mode("bogus")  # type: ignore[arg-type]


def test_set_mode_is_audited() -> None:
    """A mode change leaves a mode_change record in the audit trail."""
    gw = make("supervised")
    gw.set_mode("advisory")
    assert "mode_change" in events(gw)


def test_set_mode_cannot_exceed_policy_file_cap(tmp_path: Path) -> None:
    """A runtime set_mode cannot exceed the mode pinned in the policy file."""
    path = write_signed_policy(tmp_path / "write-policy.json", "dry_run")
    gw = engine.start_from_policy_file(
        path, SimPlant(), "supervised", allow_legacy_sidecar=True
    )
    with pytest.raises(ValueError):
        gw.set_mode("supervised")
    gw.set_mode("advisory")
    assert "mode_change" in events(gw)


def test_unknown_internal_mode_never_writes() -> None:
    """If the internal mode is corrupted to an unknown value, no write is sent."""
    plant = SimPlant()
    gw = make("supervised", plant)
    gw._mode = "bogus"  # type: ignore[assignment]
    d = gw.propose(proposal(55.0))
    assert not d.accepted
    assert plant.writes == []


def test_approve_refused_outside_confirm_mode() -> None:
    """Approving outside confirm mode is refused, writes nothing and keeps the proposal queued."""
    plant = SimPlant()
    gw = make("confirm", plant)
    p = proposal(55.0)
    gw.propose(p)
    key = proposal_key(p)
    gw.set_mode("supervised")
    d = gw.approve(key)
    assert not d.accepted
    assert d.reason_code == "not_confirm_mode"
    assert plant.writes == []
    assert key in [proposal_key(x) for x in gw.pending()]


def test_approve_runs_operator_override_check() -> None:
    """Approving a queued proposal re-checks for an operator override and refuses it."""
    plant = SimPlant()
    gw = make("supervised", plant)
    gw.propose(proposal(55.0))
    gw.set_mode("confirm")
    p2 = proposal(60.0, 2 * S)
    gw.propose(p2)
    plant.set_setpoint_by_operator(TAG, 40.0)
    d = gw.approve(proposal_key(p2))
    assert not d.accepted
    assert d.reason_code == "operator_override"
    assert len(plant.writes) == 1


def test_approve_refuses_stale_proposal() -> None:
    """A proposal queued longer than watchdog_s before approval is refused as stale."""
    plant = SimPlant()
    gw = make("confirm", plant)
    p = proposal(55.0)
    gw.propose(p)
    gw.tick(10 * S)
    d = gw.approve(proposal_key(p))
    assert not d.accepted
    assert d.reason_code == "stale_proposal"
    assert plant.writes == []


def test_pending_flushed_on_kill() -> None:
    """Kill discards every queued proposal, so approving one afterwards raises KeyError."""
    gw = make("confirm")
    p = proposal(55.0)
    gw.propose(p)
    key = proposal_key(p)
    gw.kill()
    assert gw.pending() == []
    with pytest.raises(KeyError):
        gw.approve(key)


def test_pending_flushed_on_hold_off() -> None:
    """An operator override during hold-off empties the pending queue."""
    plant = SimPlant()
    gw = make("supervised", plant)
    gw.propose(proposal(55.0))
    gw.set_mode("confirm")
    gw.propose(proposal(60.0, 2 * S))
    plant.set_setpoint_by_operator(TAG, 40.0)
    run(gw, plant, 1)
    assert gw.pending() == []


def test_operator_mode_change_while_remote_goes_hold_off() -> None:
    """An operator mode change while the gateway owns the setpoint releases it and holds off."""
    plant = StickyPlant()
    gw = make("supervised", plant)
    gw.propose(proposal(55.0))
    plant.set_mode_by_operator(TAG, "MAN")
    run(gw, plant, 1)
    assert gw.status()[TAG] == "hold_off"
    assert "operator_override" in events(gw)
    assert plant.releases == [TAG]
    assert plant.setpoint_source(TAG) == "local"


def test_operator_setpoint_change_while_remote_goes_hold_off() -> None:
    """An operator setpoint change while the gateway owns the setpoint causes hold-off."""
    plant = StickyPlant()
    gw = make("supervised", plant)
    gw.propose(proposal(55.0))
    plant.set_setpoint_by_operator(TAG, 40.0)
    run(gw, plant, 1)
    assert gw.status()[TAG] == "hold_off"
    assert "readback_mismatch" in events(gw)


@pytest.mark.parametrize("flag", ["fail_read", "fail_loop_mode", "fail_source"])
def test_tick_survives_comm_errors(flag: str) -> None:
    """A communication error during tick stops the target and does not raise."""
    plant = FaultPlant()
    gw = make("supervised", plant)
    gw.propose(proposal(55.0))
    setattr(plant, flag, True)
    plant.fail_release = True
    gw.tick(S)
    assert gw.status()[TAG] == "stopped:comm"
    assert "comm_loss" in events(gw)


@pytest.mark.parametrize("flag", ["fail_read", "fail_loop_mode"])
def test_propose_survives_comm_errors(flag: str) -> None:
    """A communication error during propose refuses the proposal as comm_loss."""
    plant = FaultPlant()
    gw = make("supervised", plant)
    setattr(plant, flag, True)
    d = gw.propose(proposal(55.0))
    assert not d.accepted
    assert d.reason_code == "comm_loss"
    assert gw.status()[TAG] == "stopped:comm"


def test_heartbeat_error_in_tick() -> None:
    """A heartbeat failure during tick stops the target with stopped:comm."""
    plant = FaultPlant()
    gw = make("supervised", plant)
    gw.propose(proposal(55.0))
    plant.fail_heartbeat = True
    gw.tick(S)
    assert gw.status()[TAG] == "stopped:comm"


def test_watchdog_releases_dead_proposer() -> None:
    """A dead proposer returns the plant to local; a later proposal takes it back."""
    plant = SimPlant()
    gw = make("supervised", plant)
    gw.propose(proposal(55.0))
    run(gw, plant, 4)
    assert plant.setpoint_source(TAG) == "remote"
    run(gw, plant, 2)
    assert plant.setpoint_source(TAG) == "local"
    assert gw.status()[TAG] == "enabled"
    assert "release" in events(gw)
    hb = plant.last_hb_ns
    run(gw, plant, 3)
    assert plant.last_hb_ns == hb
    d = gw.propose(proposal(60.0, plant.now_ns))
    assert d.accepted
    assert plant.setpoint_source(TAG) == "remote"


@pytest.mark.parametrize("last_value", [float("nan"), float("inf"), -1.0, 150.0])
def test_last_value_out_of_limits(last_value: float) -> None:
    """A non-finite or out-of-limit last value makes the proposal refused."""
    d = validate_proposal(
        POLICY, proposal(55.0), last_value=last_value, last_write_t_ns=None, loop_mode="CAS"
    )
    assert not d.accepted
    assert d.reason_code == "last_value_out_of_limits"


def test_last_value_out_of_limits_engine() -> None:
    """The engine refuses to write when the plant's current value is outside limits."""
    plant = SimPlant()
    plant.values[TAG] = 500.0
    gw = make("supervised", plant)
    d = gw.propose(proposal(55.0))
    assert not d.accepted
    assert d.reason_code == "last_value_out_of_limits"
    assert plant.writes == []


def test_last_value_inside_limits_accepted() -> None:
    """A last value of 50, inside limits, lets a valid proposal through validation."""
    d = validate_proposal(
        POLICY, proposal(55.0), last_value=50.0, last_write_t_ns=None, loop_mode="CAS"
    )
    assert d.accepted


def test_write_intent_precedes_write_and_result_precedes_heartbeat() -> None:
    """A write_intent record precedes the write; the write record precedes the heartbeat."""
    plant = SpyPlant()
    gw = make("supervised", plant)
    snaps: list[tuple[str, list[str]]] = []
    plant.probe = lambda name: snaps.append((name, events(gw)))
    d = gw.propose(proposal(55.0))
    assert d.accepted
    write_snaps = [ev for name, ev in snaps if name == "write"]
    hb_snaps = [ev for name, ev in snaps if name == "heartbeat"]
    assert write_snaps and hb_snaps
    assert write_snaps[0][-1] == "write_intent"
    assert hb_snaps[0][-1] == "write"


def test_heartbeat_error_in_write() -> None:
    """A heartbeat failure after a write is comm_loss and leaves the setpoint local."""
    plant = FaultPlant()
    plant.fail_heartbeat = True
    gw = make("supervised", plant)
    d = gw.propose(proposal(55.0))
    assert not d.accepted
    assert d.reason_code == "comm_loss"
    assert gw.status()[TAG] == "stopped:comm"
    assert plant.setpoint_source(TAG) == "local"


def test_rejected_by_control_system_releases() -> None:
    """A write refused by the control system releases the target and is audited."""
    plant = FaultPlant()
    plant.refuse = True
    gw = make("supervised", plant)
    gw.propose(proposal(55.0))
    assert plant.releases == [TAG]
    assert "release" in events(gw)


def test_kill_release_is_audited() -> None:
    """Killing the gateway while it owns the setpoint leaves a release record."""
    plant = SimPlant()
    gw = make("supervised", plant)
    gw.propose(proposal(55.0))
    gw.kill()
    gw.tick(S)
    assert "release" in events(gw)


def test_duplicate_is_audited() -> None:
    """Re-sending the same proposal records a duplicate and writes only once."""
    plant = SimPlant()
    gw = make("supervised", plant)
    p = proposal(55.0)
    gw.propose(p)
    gw.propose(p)
    assert events(gw).count("duplicate") == 1
    assert len(plant.writes) == 1


def test_failed_release_on_kill_is_retried() -> None:
    """A release that fails on kill is retried on a later tick until it succeeds."""
    plant = FaultPlant()
    gw = make("supervised", plant)
    gw.propose(proposal(55.0))
    plant.fail_release = True
    gw.kill()
    gw.tick(S)
    assert plant.setpoint_source(TAG) == "remote"
    plant.fail_release = False
    gw.tick(2 * S)
    assert plant.releases == [TAG]
    assert plant.setpoint_source(TAG) == "local"


def test_reject_caches_rejected() -> None:
    """A rejected proposal stays rejected if resent and is not queued again."""
    plant = SimPlant()
    gw = make("confirm", plant)
    p = proposal(55.0)
    gw.propose(p)
    gw.reject(proposal_key(p))
    d = gw.propose(p)
    assert not d.accepted
    assert d.reason_code == "rejected"
    assert gw.pending() == []
    assert events(gw).count("queued") == 1

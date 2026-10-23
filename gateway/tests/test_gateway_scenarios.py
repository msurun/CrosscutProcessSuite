"""Specification of the write gateway as strict-xfail scenarios (ADR 011).

Each test describes behaviour the gateway must have against a deterministic simulated control
system with a fake clock. They fail today because the fixture raises NotImplementedError.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from crosscut_gateway.interfaces import Gateway, WritePolicy, WriteProposal

TAG = "FIC101.SP"
S = 1_000_000_000  # one second in ns
pytestmark = pytest.mark.xfail(strict=True, reason="gateway not implemented (ADR 011)")

POLICY = WritePolicy(
    limits=(0.0, 100.0),
    max_step=10.0,
    max_rate_per_s=5.0,
    min_interval_s=1.0,
    allowed_loop_modes=("CAS",),
    hold_off_s=60.0,
    watchdog_s=5.0,
    readback_tolerance=0.5,
)


class SimPlant:
    """Deterministic simulated control system; time is ``now_ns`` and only moves when told."""

    def __init__(self, watchdog_s: float = POLICY.watchdog_s) -> None:
        """One loop in CAS mode with a local setpoint of 50."""
        self.now_ns = 0
        self.watchdog_ns = int(watchdog_s * S)
        self.values = {TAG: 50.0}
        self.modes = {TAG: "CAS"}
        self.remote = False
        self.last_hb_ns: int | None = None
        self.writes: list[tuple[int, str, float]] = []
        self.refuse = False
        self.readback_offset = 0.0
        self.fail_after: int | None = None  # communication dies after this many writes

    def advance(self, seconds: float) -> None:
        """Move the fake clock; on heartbeat loss the plant returns to its local setpoint."""
        self.now_ns += int(seconds * S)
        if self.remote and not self.heartbeat_seen():
            self.remote = False

    def read(self, tag: str) -> float:
        """Value as read back (may carry a fault offset)."""
        return self.values[tag] + self.readback_offset

    def write(self, tag: str, value: float) -> bool:
        """Accept a write unless refused or the link is dead (then raise ConnectionError)."""
        if self.fail_after is not None and len(self.writes) >= self.fail_after:
            raise ConnectionError("link down")
        if self.refuse or self.modes[tag] != "CAS":
            return False
        self.values[tag] = value
        self.remote = True
        self.writes.append((self.now_ns, tag, value))
        return True

    def heartbeat_seen(self) -> bool:
        """True while the last heartbeat is younger than the watchdog period."""
        return self.last_hb_ns is not None and self.now_ns - self.last_hb_ns <= self.watchdog_ns

    def send_heartbeat(self) -> None:
        """Record a heartbeat at the current time."""
        self.last_hb_ns = self.now_ns

    def loop_mode(self, tag: str) -> str:
        """Current loop mode."""
        return self.modes[tag]

    def setpoint_source(self, tag: str) -> str:
        """``remote`` while the gateway owns the setpoint, else ``local``."""
        return "remote" if self.remote else "local"

    def set_mode_by_operator(self, tag: str, mode: str) -> None:
        """Operator changes the mode; leaving CAS returns the setpoint to local."""
        self.modes[tag] = mode
        if mode != "CAS":
            self.remote = False

    def set_setpoint_by_operator(self, tag: str, value: float) -> None:
        """Operator takes the setpoint back."""
        self.values[tag] = value
        self.remote = False


@pytest.fixture
def sim() -> SimPlant:
    """A fresh simulated plant."""
    return SimPlant()


@pytest.fixture
def gateway_under_test(sim: SimPlant) -> Gateway:
    """The real gateway in ``supervised`` mode on ``sim`` with ``POLICY`` (not written yet)."""
    raise NotImplementedError("gateway not implemented (ADR 011)")


@pytest.fixture
def dry_run_gateway(sim: SimPlant) -> Gateway:
    """The real gateway in ``dry_run`` mode on ``sim`` with ``POLICY`` (not written yet)."""
    raise NotImplementedError("gateway not implemented (ADR 011)")


def start_from_policy_file(path: Path, sim: SimPlant) -> Gateway:
    """Start the gateway from a policy file whose sha256 is pinned (not written yet)."""
    raise NotImplementedError("gateway not implemented (ADR 011)")


def proposal(value: float, t_ns: int = 0, reason: str = "test") -> WriteProposal:
    """A proposal for the test tag."""
    return WriteProposal(TAG, value, "supervisor", t_ns, reason)


def run(gw: Gateway, sim: SimPlant, seconds: int) -> None:
    """Advance the plant clock one second at a time and tick the gateway each second."""
    for _ in range(seconds):
        sim.advance(1)
        gw.tick(sim.now_ns)


def test_cas_handover_take_and_give_back(gateway_under_test: Gateway, sim: SimPlant) -> None:
    """A write takes the setpoint remote; a kill gives it back to local."""
    assert gateway_under_test.propose(proposal(55.0)).accepted
    assert sim.setpoint_source(TAG) == "remote"
    gateway_under_test.kill()
    gateway_under_test.tick(sim.now_ns)
    assert sim.setpoint_source(TAG) == "local"


def test_watchdog_loss_returns_plant_to_local(gateway_under_test: Gateway, sim: SimPlant) -> None:
    """When the gateway stops ticking, the plant is local within watchdog_s."""
    gateway_under_test.propose(proposal(55.0))
    gateway_under_test.tick(sim.now_ns)
    sim.advance(POLICY.watchdog_s + 1)  # gateway dead: no more ticks
    assert sim.setpoint_source(TAG) == "local"


def test_rejected_write_stops_and_reports(gateway_under_test: Gateway, sim: SimPlant) -> None:
    """If the control system refuses, the gateway reports it and stops writing that target."""
    sim.refuse = True
    decision = gateway_under_test.propose(proposal(55.0))
    assert not decision.accepted
    sim.refuse = False
    sim.advance(10)
    assert not gateway_under_test.propose(proposal(56.0, sim.now_ns)).accepted
    assert sim.writes == []
    assert gateway_under_test.status()[TAG] != "enabled"


def test_limit_and_rate_clamp(gateway_under_test: Gateway, sim: SimPlant) -> None:
    """A written value never exceeds limits, max_step or max_rate_per_s."""
    d = gateway_under_test.propose(proposal(500.0))
    assert d.clamped_value is not None
    assert d.clamped_value <= POLICY.limits[1]
    assert abs(d.clamped_value - 50.0) <= POLICY.max_step
    sim.advance(POLICY.min_interval_s)
    d2 = gateway_under_test.propose(proposal(500.0, sim.now_ns))
    assert d2.clamped_value is not None
    assert d2.clamped_value - d.clamped_value <= POLICY.max_rate_per_s * POLICY.min_interval_s
    assert all(POLICY.limits[0] <= v <= POLICY.limits[1] for _, _, v in sim.writes)


def test_operator_override_and_hold_off(gateway_under_test: Gateway, sim: SimPlant) -> None:
    """After an operator setpoint change, no write for hold_off_s, then only after re-enable."""
    gateway_under_test.propose(proposal(55.0))
    sim.set_setpoint_by_operator(TAG, 40.0)
    n = len(sim.writes)
    run(gateway_under_test, sim, int(POLICY.hold_off_s) - 2)
    assert not gateway_under_test.propose(proposal(45.0, sim.now_ns)).accepted
    run(gateway_under_test, sim, 10)  # hold-off over, but no explicit re-enable
    assert not gateway_under_test.propose(proposal(45.0, sim.now_ns)).accepted
    assert len(sim.writes) == n


def test_readback_mismatch_stops_writing(gateway_under_test: Gateway, sim: SimPlant) -> None:
    """A read-back differing by more than the tolerance disables the target."""
    gateway_under_test.propose(proposal(55.0))
    sim.readback_offset = POLICY.readback_tolerance + 1.0
    gateway_under_test.tick(sim.now_ns)
    n = len(sim.writes)
    sim.advance(5)
    assert not gateway_under_test.propose(proposal(56.0, sim.now_ns)).accepted
    assert len(sim.writes) == n


def test_communication_loss_mid_write_fails_closed(
    gateway_under_test: Gateway, sim: SimPlant
) -> None:
    """A link failure during a write ends in a disabled target and local setpoint, no exception."""
    sim.fail_after = 0
    decision = gateway_under_test.propose(proposal(55.0))
    assert not decision.accepted
    assert sim.writes == []
    run(gateway_under_test, sim, int(POLICY.watchdog_s) + 1)
    assert sim.setpoint_source(TAG) == "local"
    assert gateway_under_test.status()[TAG] != "enabled"


def test_duplicate_proposal_is_idempotent(gateway_under_test: Gateway, sim: SimPlant) -> None:
    """The same proposal sent twice produces exactly one write."""
    p = proposal(55.0, t_ns=7)
    gateway_under_test.propose(p)
    gateway_under_test.propose(p)
    assert len(sim.writes) == 1


def test_mode_change_race_never_writes_in_wrong_mode(
    gateway_under_test: Gateway, sim: SimPlant
) -> None:
    """If the operator leaves CAS between proposals, the next one is refused, nothing written."""
    gateway_under_test.propose(proposal(55.0))
    sim.set_mode_by_operator(TAG, "MAN")
    n = len(sim.writes)
    sim.advance(5)
    decision = gateway_under_test.propose(proposal(56.0, sim.now_ns))
    assert not decision.accepted
    assert len(sim.writes) == n
    assert sim.setpoint_source(TAG) == "local"


def test_tampered_policy_file_refuses_to_start(tmp_path: Path, sim: SimPlant) -> None:
    """A policy file whose hash differs from the pinned one prevents startup."""
    policy = tmp_path / "write-policy.json"
    policy.write_text('{"limits": [0, 100]}', encoding="utf-8")
    pinned = tmp_path / "write-policy.sha256"
    pinned.write_text("0" * 64, encoding="utf-8")  # does not match
    with pytest.raises(ValueError, match="hash"):
        start_from_policy_file(policy, sim)
    assert sim.writes == []


def test_kill_switch_stops_writes_within_one_tick(
    gateway_under_test: Gateway, sim: SimPlant
) -> None:
    """After kill() and one tick, no write is accepted and the setpoint is local."""
    gateway_under_test.propose(proposal(55.0))
    gateway_under_test.kill()
    gateway_under_test.tick(sim.now_ns)
    n = len(sim.writes)
    sim.advance(10)
    assert not gateway_under_test.propose(proposal(56.0, sim.now_ns)).accepted
    assert len(sim.writes) == n
    assert sim.setpoint_source(TAG) == "local"


def test_dry_run_sends_nothing(dry_run_gateway: Gateway, sim: SimPlant) -> None:
    """A dry run writes an audit record of the would-be write and sends zero writes."""
    decision = dry_run_gateway.propose(proposal(55.0))
    dry_run_gateway.tick(sim.now_ns)
    assert sim.writes == []
    assert sim.values[TAG] == 50.0
    assert decision.clamped_value == 55.0
    assert dry_run_gateway.audit_records()

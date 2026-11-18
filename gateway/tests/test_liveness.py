"""Liveness of the runtime and its controllers at the gateway (ADR 015, #112)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WriteProposal
from crosscut_gateway.liveness import Beat, LivenessError, parse_beat
from crosscut_gateway.service import CommandError, GatewayService
from test_gateway_scenarios import POLICY, TAG, S, SimPlant
from test_gateway_service import FakeClock, outbox_payload, state_payload, write_command

CYCLE_S = 10.0  # ADR 015 minimum; 3 cycles = 30 s window
WATCHDOG_S = 60.0
LONG_POLICY = replace(POLICY, watchdog_s=WATCHDOG_S)


class Mono:
    """Controllable monotonic clock in ns."""

    def __init__(self) -> None:
        self.t_ns = 0

    def __call__(self) -> int:
        return self.t_ns


def beat(state: str = "on", sender: str = "c1", kind: str = "controller", **over: object) -> Beat:
    """A beat; controllers declare TAG, the runtime nothing."""
    base = Beat(kind, sender, state, 1, CYCLE_S, 3, (TAG,) if kind == "controller" else ())
    return replace(base, **over)  # type: ignore[arg-type]


def runtime_beat() -> Beat:
    """The runtime process beat."""
    return beat("running", "runtime", "runtime")


def proposal(proposer: str, t_s: float = 1.0) -> WriteProposal:
    """A proposal for TAG at time ``t_s``."""
    return WriteProposal(TAG, 55.0 + t_s, proposer, int(t_s * S), "test")


class World:
    """A supervised gateway on a sim plant with a controllable monotonic clock."""

    def __init__(self, hold: bool = True) -> None:
        self.mono = Mono()
        self.plant = SimPlant(WATCHDOG_S)
        self.gateway = WriteGateway(
            self.plant,  # type: ignore[arg-type]
            {TAG: LONG_POLICY},
            "supervised",
            monotonic_ns=self.mono,
        )
        self.gateway.tick(0)
        if hold:
            self.beats()
            self.gateway.propose(proposal("controller:c1", 0))

    def beats(self, *senders: str) -> None:
        """Runtime beat plus the controller beats (default c1) at the current time."""
        self.gateway.record_beat(runtime_beat())
        for sender in senders or ("c1",):
            self.gateway.record_beat(beat(sender=sender))

    def tick(self, seconds: float) -> None:
        """Move both clocks to ``seconds`` and run one gateway cycle."""
        self.mono.t_ns = self.plant.now_ns = int(seconds * S)
        self.gateway.tick(self.plant.now_ns)

    def events(self, name: str) -> list[dict]:
        """Audit records of one event."""
        return [r for r in self.gateway.audit_records() if r["event"] == name]

    def reasons(self, name: str) -> list[str]:
        """Reason codes of one audit event."""
        return [r["reason_code"] for r in self.events(name)]


def test_beats_in_time_keep_the_target() -> None:
    """A beat every cycle never releases or audits anything."""
    world = World()
    for second in (10, 20, 30, 40, 50):
        world.tick(second)
        world.beats()
    assert world.plant.remote is True
    assert world.events("controller_lost") == []


def test_loss_after_liveness_cycles_releases_and_audits() -> None:
    """Silence beyond 3 x cycle_s (30 s) releases the holder's target once."""
    world = World()
    world.tick(30)
    assert world.plant.remote is True  # exactly at the limit: not yet lost
    world.tick(31)
    assert world.plant.remote is False
    assert world.reasons("controller_lost") == ["controller:c1"]
    world.tick(32)
    assert len(world.events("controller_lost")) == 1
    assert world.gateway.liveness_view()["controllers"]["c1"]["lost"] is True


def test_new_beat_clears_the_loss_flag() -> None:
    """A beat after a loss shows the controller alive again."""
    world = World()
    world.tick(31)
    world.beats()
    world.tick(32)
    assert world.gateway.liveness_view()["controllers"]["c1"]["lost"] is False


def test_idle_controller_triggers_nothing() -> None:
    """A silent standby controller that holds nothing is no alarm and no audit event."""
    world = World(hold=False)
    world.gateway.record_beat(runtime_beat())
    world.gateway.record_beat(beat("standby"))
    world.tick(100)
    assert world.events("controller_lost") == [] and world.events("runtime_lost") == []
    assert world.gateway.liveness_view()["controllers"]["c1"]["lost"] is False


def test_other_controllers_are_not_touched() -> None:
    """Only the lost controller is audited; a live c2 stays quiet."""
    world = World()
    world.tick(25)
    world.beats("c2")
    world.tick(31)
    assert world.reasons("controller_lost") == ["controller:c1"]
    assert world.events("runtime_lost") == []


def test_lost_runtime_releases_every_controller() -> None:
    """A silent runtime process is lost together with the controllers that were on."""
    world = World()
    world.tick(25)
    world.gateway.record_beat(beat())  # the controller keeps beating, the runtime does not
    world.tick(31)
    assert world.plant.remote is False
    assert world.reasons("runtime_lost") == ["runtime"]
    assert world.reasons("controller_lost") == ["controller:c1"]


def test_runtime_alone_with_nothing_active_is_quiet() -> None:
    """A silent runtime whose controllers are off and hold nothing raises no event."""
    world = World(hold=False)
    world.gateway.record_beat(runtime_beat())
    world.gateway.record_beat(beat("off"))
    world.tick(100)
    assert world.events("runtime_lost") == []


def test_no_dcs_write_besides_the_one_heartbeat() -> None:
    """A beat and a loss add no plant write."""
    world = World()
    writes = len(world.plant.writes)
    world.tick(31)
    assert len(world.plant.writes) == writes


def test_beat_with_short_watchdog_is_refused() -> None:
    """watchdog_s 60 < 2 x cycle_s 40 is refused and audited."""
    world = World()
    with pytest.raises(LivenessError, match="watchdog_s"):
        world.gateway.record_beat(beat(cycle_s=40.0))
    assert len(world.events("liveness_refused")) == 1
    assert "c1" not in world.gateway.liveness_view()["controllers"]


def test_beat_is_checked_against_targets_the_controller_holds() -> None:
    """A beat that declares no targets still fails for a tag the controller holds."""
    world = World()
    with pytest.raises(LivenessError):
        world.gateway.record_beat(beat(cycle_s=40.0, targets=()))


def test_proposal_for_a_short_watchdog_tag_is_refused() -> None:
    """A controller with a 40 s cycle may not write a tag whose watchdog is 60 s."""
    world = World(hold=False)
    world.gateway.record_beat(runtime_beat())
    world.gateway.record_beat(beat(cycle_s=40.0, targets=()))
    decision = world.gateway.propose(proposal("controller:c1"))
    assert decision.reason_code == "liveness_watchdog_short"


@pytest.mark.parametrize(
    "over",
    [
        {"cycle_s": 9.9},
        {"cycle_s": 300.1},
        {"cycle_s": float("nan")},
        {"cycle_s": float("inf")},
        {"liveness_cycles": 1},
        {"liveness_cycles": 11},
        {"liveness_cycles": 10**30},
        {"count": 2**70},
        {"count": -1},
        {"kind": "other"},
    ],
)
def test_parse_clamps_what_the_sender_claims(over: dict) -> None:
    """cycle_s 10-300, liveness_cycles 2-10, bounded count, known kind."""
    args = {"kind": "controller", "id": "c", "state": "on", "count": 1, "cycle_s": 10.0,
            "liveness_cycles": 3, "targets": []}
    assert parse_beat(args).sender == "c"
    with pytest.raises(LivenessError):
        parse_beat({**args, **over})


def test_controller_without_beat_is_refused() -> None:
    """No beat, no writes: a controller that never beat gets liveness_missing."""
    world = World()
    assert world.gateway.propose(proposal("controller:never")).reason_code == "liveness_missing"


def test_controller_beat_without_runtime_beat_is_not_enough() -> None:
    """After a gateway restart both beats are needed before a controller may write."""
    world = World(hold=False)
    world.gateway.record_beat(beat())
    assert world.gateway.propose(proposal("controller:c1")).reason_code == "liveness_missing"
    world.gateway.record_beat(runtime_beat())
    assert world.gateway.propose(proposal("controller:c1", 2)).accepted is True


def test_refused_beat_blocks_the_controllers_writes() -> None:
    """A refused beat also drops the earlier valid beat."""
    world = World()
    with pytest.raises(LivenessError):
        world.gateway.record_beat(beat(cycle_s=40.0))
    assert world.gateway.propose(proposal("controller:c1")).reason_code == "liveness_missing"


def test_stale_beat_blocks_writes_and_fresh_beat_allows_them() -> None:
    """Writes stop once the beat is older than the window and resume with a new beat."""
    world = World()
    world.tick(31)
    assert world.gateway.propose(proposal("controller:c1", 31)).reason_code == "liveness_missing"
    world.beats()
    world.tick(32)
    assert world.gateway.propose(proposal("controller:c1", 32)).accepted is True


def test_other_proposers_need_no_beat() -> None:
    """Supervisors and operators are not controllers: no beat is asked of them."""
    world = World()
    assert world.gateway.propose(proposal("supervisor:s1")).reason_code != "liveness_missing"


def test_failed_release_is_retried_audited_once_and_alarms() -> None:
    """A failing release stays pending: one audit line, an alarm after 3, retried until it works."""
    world = World()
    attempts: list[str] = []

    def flaky(tag: str) -> None:
        attempts.append(tag)
        if len(attempts) < 5:
            raise ConnectionError("down")
        world.plant.remote = False

    world.plant.release = flaky  # type: ignore[method-assign]
    for second in (31, 32, 33):
        world.tick(second)
    assert world.gateway.alarms() == {TAG: "release_failed"}
    assert len(world.events("release_failed")) == 1
    for second in (34, 35, 36, 37):
        world.tick(second)
    assert len(attempts) == 5  # four failures, then success; nothing after
    failed = [r for r in world.events("release") if r["reason_code"] == "release_failed"]
    assert len(failed) == 1
    assert world.plant.remote is False
    assert world.gateway.alarms() == {}
    assert len(world.events("controller_lost")) == 1


def test_pending_release_skips_a_target_retaken_after_fresh_beats() -> None:
    """A fresh beat and a new proposal since the loss keep the target (no stale release)."""
    world = World()
    attempts: list[str] = []

    def failing(tag: str) -> None:
        attempts.append(tag)
        raise ConnectionError("down")

    world.plant.release = failing  # type: ignore[method-assign]
    world.tick(31)
    assert len(attempts) == 1
    world.beats()
    world.tick(32)
    assert len(attempts) == 2  # still pending: a beat does not cancel the release
    decision = world.gateway.propose(proposal("controller:c1", 32))
    assert decision.accepted is True
    world.tick(33)
    assert len(attempts) == 2  # the new hold is younger than the loss: not released
    assert world.gateway._holding[TAG] is True  # noqa: SLF001


def test_expiry_follows_the_monotonic_clock_not_the_wall_clock() -> None:
    """A wall-clock jump alone loses nothing."""
    world = World()
    world.plant.now_ns = 10**18  # wall clock jumps; the monotonic clock did not move
    world.gateway.tick(world.plant.now_ns)
    assert world.events("controller_lost") == []


def make_service(tmp_path: Path) -> tuple[GatewayService, World]:
    """A service over a World gateway."""
    world = World(hold=False)
    return GatewayService(tmp_path, world.gateway, clock=FakeClock()), world


def beat_args(sender: str = "c1", **over: object) -> dict:
    """Mailbox arguments of a controller beat."""
    return {"kind": "controller", "id": sender, "state": "on", "count": 4, "cycle_s": CYCLE_S,
            "liveness_cycles": 3, "targets": [TAG], **over}


def test_mailbox_beat_and_state_view(tmp_path: Path) -> None:
    """The liveness command is accepted and shows in state.json."""
    service, world = make_service(tmp_path)
    write_command(tmp_path, "l1", {"id": "l1", "cmd": "liveness", "args": beat_args()})
    service.poll_once()
    assert outbox_payload(tmp_path, "l1")["ok"] is True
    row = state_payload(tmp_path)["liveness"]["controllers"]["c1"]
    assert (row["state"], row["count"], row["lost"]) == ("on", 4, False)
    world.mono.t_ns = 100 * S
    service.poll_once()
    assert state_payload(tmp_path)["liveness"]["controllers"]["c1"]["lost"] is True


def test_mailbox_refuses_short_watchdog(tmp_path: Path) -> None:
    """A beat with cycle_s above half the watchdog gets an error reply."""
    service, _world = make_service(tmp_path)
    args = beat_args(cycle_s=40.0)
    write_command(tmp_path, "l2", {"id": "l2", "cmd": "liveness", "args": args})
    service.poll_once()
    assert outbox_payload(tmp_path, "l2")["ok"] is False


def test_beat_of_another_controller_is_refused_and_audited(tmp_path: Path) -> None:
    """svc:controller:c2 cannot beat for c1 (spoofing)."""
    service, world = make_service(tmp_path)
    spoofer = ActorContext(actor="svc:controller:c2", roles=("service",))
    with pytest.raises(CommandError, match="authenticated actor"):
        service._handle_liveness(beat_args("c1"), spoofer)  # noqa: SLF001
    assert "c1" not in world.gateway.liveness_view()["controllers"]
    assert world.reasons("liveness_refused") == ["actor_mismatch:controller:c1"]


def test_beat_of_the_own_actor_is_accepted(tmp_path: Path) -> None:
    """svc:controller:c1 and svc:runtime:runtime may beat for themselves."""
    service, world = make_service(tmp_path)
    own = ActorContext(actor="svc:controller:c1", roles=("service",))
    service._handle_liveness(beat_args("c1"), own)  # noqa: SLF001
    runtime = ActorContext(actor="svc:runtime:runtime", roles=("service",))
    args = beat_args("runtime", kind="runtime", targets=[])
    service._handle_liveness(args, runtime)  # noqa: SLF001
    assert set(world.gateway.liveness_view()["controllers"]) == {"c1"}
    assert world.gateway.liveness_view()["runtime"] is not None


def test_proposal_as_another_controller_is_refused(tmp_path: Path) -> None:
    """A proposal named controller:c1 must come from svc:controller:c1."""
    service, world = make_service(tmp_path)
    spoofer = ActorContext(actor="svc:controller:c2", roles=("service",))
    args = {"target_tag": TAG, "value": 55.0, "proposer": "controller:c1", "t_ns": 0, "reason": "x"}
    with pytest.raises(CommandError, match="authenticated actor"):
        service._handle_propose(args, spoofer)  # noqa: SLF001
    assert world.reasons("liveness_refused") == ["actor_mismatch:controller:c1"]

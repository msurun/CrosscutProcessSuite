"""Liveness of the runtime and its controllers at the gateway (ADR 015, #112)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WriteProposal
from crosscut_gateway.liveness import Beat, LivenessError, parse_beat
from crosscut_gateway.service import GatewayService
from test_gateway_scenarios import POLICY, TAG, S, SimPlant
from test_gateway_service import FakeClock, outbox_payload, state_payload, write_command

CYCLE_S = 2.0  # watchdog_s of POLICY is 5 s: 2 x cycle_s = 4 s <= 5 s, accepted


def beat(state: str = "on", sender: str = "c1", kind: str = "controller", **over: object) -> Beat:
    """A controller beat naming TAG; ``over`` replaces fields."""
    base = Beat(kind, sender, state, 1, CYCLE_S, 3, (TAG,) if kind == "controller" else ())
    return replace(base, **over)  # type: ignore[arg-type]


def make() -> tuple[WriteGateway, SimPlant]:
    """A supervised gateway whose target is held by controller c1."""
    plant = SimPlant()
    gateway = WriteGateway(plant, {TAG: POLICY}, "supervised")  # type: ignore[arg-type]
    gateway.tick(0)
    gateway.record_beat(beat(), 0)
    gateway.propose(WriteProposal(TAG, 55.0, "controller:c1", 0, "test"))
    return gateway, plant


def tick(gateway: WriteGateway, plant: SimPlant, seconds: float) -> None:
    """Move plant time to ``seconds`` and run one gateway cycle."""
    plant.now_ns = int(seconds * S)
    gateway.tick(plant.now_ns)


def events(gateway: WriteGateway, name: str) -> list[dict]:
    """Audit records of one event."""
    return [r for r in gateway.audit_records() if r["event"] == name]


def test_beats_in_time_keep_the_target() -> None:
    """A beat every cycle never releases or audits anything."""
    gateway, plant = make()
    for second in range(1, 4):  # stays inside the 5 s write watchdog
        gateway.record_beat(beat(), second * S)
        tick(gateway, plant, second)
    assert plant.remote is True
    assert events(gateway, "runtime_lost") == []


def test_loss_after_liveness_cycles_releases_and_audits() -> None:
    """Silence beyond 3 x cycle_s (6 s) releases the holder's target once."""
    gateway, plant = make()
    gateway.record_beat(beat(), 0)
    gateway._last_write_t_ns[TAG] = 100 * S  # noqa: SLF001 - keep the write watchdog quiet
    tick(gateway, plant, 6)
    assert plant.remote is True  # exactly at the limit: not yet lost
    tick(gateway, plant, 7)
    assert plant.remote is False
    lost = events(gateway, "runtime_lost")
    assert [r["reason_code"] for r in lost] == ["controller:c1"]
    tick(gateway, plant, 8)
    assert len(events(gateway, "runtime_lost")) == 1
    assert gateway.liveness_view()["controllers"]["c1"]["lost"] is True


def test_new_beat_clears_the_loss_flag() -> None:
    """A beat after a loss shows the controller alive again."""
    gateway, plant = make()
    gateway.record_beat(beat(), 0)
    tick(gateway, plant, 7)
    gateway.record_beat(beat(), 8 * S)
    tick(gateway, plant, 9)
    assert gateway.liveness_view()["controllers"]["c1"]["lost"] is False


def test_controller_not_on_and_holding_nothing_triggers_nothing() -> None:
    """A silent standby controller without a target is no alarm and no audit event."""
    gateway, plant = make()
    gateway.record_beat(beat("standby", "c2"), 0)
    tick(gateway, plant, 30)
    lost = [r["reason_code"] for r in events(gateway, "runtime_lost")]
    assert lost == ["controller:c1"]  # only the holder; the idle c2 raises nothing
    assert gateway.liveness_view()["controllers"]["c2"]["lost"] is False


def test_other_controllers_targets_stay() -> None:
    """Only the targets of the lost controller are released; a live c2 is not touched."""
    gateway, plant = make()
    gateway.record_beat(beat(sender="c1"), 0)
    gateway.record_beat(beat(sender="c2"), 6 * S)
    tick(gateway, plant, 7)
    assert [r["reason_code"] for r in events(gateway, "runtime_lost")] == ["controller:c1"]


def test_lost_runtime_releases_every_controller() -> None:
    """A silent runtime process is lost together with the controllers that were on."""
    gateway, plant = make()
    gateway.record_beat(beat(kind="runtime", sender="runtime", state="running", cycle_s=1.0), 0)
    gateway.record_beat(beat(), 5 * S)  # the controller's own beat is recent
    tick(gateway, plant, 5)
    assert plant.remote is False
    reasons = {r["reason_code"] for r in events(gateway, "runtime_lost")}
    assert reasons == {"runtime", "controller:c1"}


def proposal(proposer: str, t_s: float = 1.0) -> WriteProposal:
    """A proposal for TAG at time ``t_s``."""
    return WriteProposal(TAG, 56.0, proposer, int(t_s * S), "test")


def test_controller_without_beat_is_refused() -> None:
    """No beat, no writes: a controller that never beat gets liveness_missing."""
    gateway, _plant = make()
    decision = gateway.propose(proposal("controller:never"))
    assert (decision.accepted, decision.reason_code) == (False, "liveness_missing")


def test_refused_beat_blocks_the_controllers_writes() -> None:
    """A refused beat (watchdog too short) also drops the earlier valid beat."""
    gateway, _plant = make()
    with pytest.raises(LivenessError):
        gateway.record_beat(beat(cycle_s=3.0), 0)
    assert gateway.propose(proposal("controller:c1")).reason_code == "liveness_missing"


def test_stale_beat_blocks_writes_and_fresh_beat_allows_them() -> None:
    """Writes stop once the beat is older than the window and resume with a new beat."""
    gateway, plant = make()
    gateway._last_write_t_ns[TAG] = 100 * S  # noqa: SLF001 - keep the write watchdog quiet
    tick(gateway, plant, 7)
    assert gateway.propose(proposal("controller:c1", 7)).reason_code == "liveness_missing"
    gateway.record_beat(beat(), 8 * S)
    tick(gateway, plant, 8)
    gateway._last_write_t_ns[TAG] = 0  # noqa: SLF001
    assert gateway.propose(proposal("controller:c1", 8)).accepted is True


def test_other_proposers_need_no_beat() -> None:
    """Supervisors and operators are not controllers: no beat is asked of them."""
    gateway, _plant = make()
    assert gateway.propose(proposal("supervisor:s1")).reason_code != "liveness_missing"


def test_failed_release_is_retried_until_it_works_and_audited_once() -> None:
    """A release that fails stays pending: one audit line, retried on every tick."""
    gateway, plant = make()
    gateway._last_write_t_ns[TAG] = 100 * S  # noqa: SLF001
    attempts = []

    def flaky(tag: str) -> None:
        attempts.append(tag)
        if len(attempts) < 4:
            raise ConnectionError("down")
        plant.remote = False

    plant.release = flaky  # type: ignore[method-assign]
    for second in (7, 8, 9, 10, 11):
        tick(gateway, plant, second)
    assert len(attempts) == 4  # three failures, then success; nothing after
    failed = [r for r in events(gateway, "release") if r["reason_code"] == "release_failed"]
    assert len(failed) == 1
    assert plant.remote is False
    assert len(events(gateway, "runtime_lost")) == 1


def test_runtime_alone_with_nothing_active_is_quiet() -> None:
    """A silent runtime whose controllers are off and hold nothing raises no event."""
    gateway, plant = make()
    gateway.release(TAG)
    gateway._holding[TAG] = False  # noqa: SLF001 - the target was already handed back
    gateway.record_beat(beat(kind="runtime", sender="runtime", state="running", cycle_s=1.0), 0)
    gateway.record_beat(beat("off"), 0)
    tick(gateway, plant, 50)
    assert events(gateway, "runtime_lost") == []


def test_no_dcs_write_besides_the_one_heartbeat() -> None:
    """A beat and a loss add no plant write; only the existing heartbeat path is used."""
    gateway, plant = make()
    writes = len(plant.writes)
    gateway.record_beat(beat(), 0)
    tick(gateway, plant, 7)
    assert len(plant.writes) == writes


def test_watchdog_below_two_cycles_is_refused() -> None:
    """watchdog_s 5 < 2 x cycle_s 3 is refused and audited."""
    gateway, _plant = make()
    with pytest.raises(LivenessError, match="watchdog_s"):
        gateway.record_beat(beat(cycle_s=3.0), 0)
    assert len(events(gateway, "liveness_refused")) == 1
    assert "c1" not in gateway.liveness_view()["controllers"]


@pytest.mark.parametrize("over", [{"cycle_s": 0}, {"liveness_cycles": 1}, {"kind": "other"}])
def test_parse_refuses_bad_values(over: dict) -> None:
    """cycle_s must be positive, liveness_cycles at least 2, kind known."""
    args = {"kind": "controller", "id": "c", "state": "on", "count": 1, "cycle_s": 1.0,
            "liveness_cycles": 3, "targets": []}
    assert parse_beat(args).sender == "c"
    with pytest.raises(LivenessError):
        parse_beat({**args, **over})


def test_mailbox_beat_and_state_view(tmp_path: Path) -> None:
    """The liveness command is accepted, shows in state.json and ages with the clock."""
    gateway, plant = make()
    clock = FakeClock()
    service = GatewayService(tmp_path, gateway, clock=clock)
    args = {"kind": "controller", "id": "c1", "state": "on", "count": 4, "cycle_s": CYCLE_S,
            "liveness_cycles": 3, "targets": [TAG]}
    write_command(tmp_path, "l1", {"id": "l1", "cmd": "liveness", "args": args})
    service.poll_once()
    assert outbox_payload(tmp_path, "l1")["ok"] is True
    row = state_payload(tmp_path)["liveness"]["controllers"]["c1"]
    assert (row["state"], row["count"], row["lost"]) == ("on", 4, False)
    clock.advance(10)
    service.poll_once()
    assert state_payload(tmp_path)["liveness"]["controllers"]["c1"]["lost"] is True


def test_mailbox_refuses_short_watchdog(tmp_path: Path) -> None:
    """A beat with cycle_s above half the watchdog gets an error reply."""
    gateway, _plant = make()
    service = GatewayService(tmp_path, gateway, clock=FakeClock())
    args = {"kind": "controller", "id": "c1", "state": "on", "count": 1, "cycle_s": 30,
            "liveness_cycles": 3, "targets": [TAG]}
    write_command(tmp_path, "l2", {"id": "l2", "cmd": "liveness", "args": args})
    service.poll_once()
    assert outbox_payload(tmp_path, "l2")["ok"] is False

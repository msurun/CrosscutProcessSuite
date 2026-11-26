"""Controller acquisition must track the live setpoint before making a move.

Exercise the real engine with deterministic plant reads, including confirmation races.
"""

from dataclasses import replace

import pytest
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WriteProposal
from crosscut_gateway.policy import proposal_key
from test_gateway_scenarios import POLICY, TAG, S, SimPlant
from test_liveness import beat, runtime_beat


def _gateway(mode: str = "supervised") -> tuple[WriteGateway, SimPlant]:
    """Create a live controller and runtime with a policy sized for their cycle."""
    plant = SimPlant(60)
    gateway = WriteGateway(plant, {TAG: replace(POLICY, watchdog_s=60)}, mode)
    gateway.tick(0)
    gateway.record_beat(runtime_beat())
    gateway.record_beat(beat())
    return gateway, plant


def _proposal(value: float, seconds: int = 0) -> WriteProposal:
    """One controller proposal, uniquely keyed by its cycle time."""
    return WriteProposal(TAG, value, "controller:c1", seconds * S, "test")


def test_controller_start_writes_the_readback_before_any_move() -> None:
    gateway, plant = _gateway()
    decision = gateway.propose(_proposal(58))
    assert decision.accepted and decision.clamped_value == 50
    assert plant.writes == [(0, TAG, 50)]
    assert gateway.propose(_proposal(58, 2)).accepted
    assert plant.writes[-1][2] == 58


def test_a_zero_first_proposal_is_written_and_audited() -> None:
    gateway, plant = _gateway()
    decision = gateway.propose(_proposal(50))
    assert decision.accepted and decision.reason_code == "bumpless_initialisation"
    assert plant.writes == [(0, TAG, 50)]
    assert any(row["event"] == "bumpless_initialisation" for row in gateway.audit_records())


def test_operator_handover_uses_the_operator_value_instead_of_the_old_write() -> None:
    gateway, plant = _gateway()
    gateway.propose(_proposal(58))
    plant.set_setpoint_by_operator(TAG, 75)
    gateway.tick(S)
    gateway.tick(61 * S)
    gateway.re_enable(TAG)
    gateway.record_beat(runtime_beat())
    gateway.record_beat(beat(cycles=3))
    decision = gateway.propose(_proposal(76, 61))
    assert decision.accepted and decision.clamped_value == 75
    assert plant.writes[-1][2] == 75


def test_confirm_reads_the_target_again_at_approval() -> None:
    gateway, plant = _gateway("confirm")
    proposal = _proposal(52)
    gateway.propose(proposal, actor_ctx=ActorContext(actor="svc:controller:c1"))
    plant.values[TAG] = 57
    decision = gateway.approve(proposal_key(proposal), actor_ctx=ActorContext(actor="operator"))
    assert decision.accepted and decision.clamped_value == 57
    assert plant.writes == [(0, TAG, 57)]


def test_bump_limit_refusal_is_audited_without_a_write(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway, plant = _gateway()
    readings = iter((50.0, 35.0))
    monkeypatch.setattr(plant, "read", lambda tag: next(readings))
    decision = gateway.propose(_proposal(58))
    assert not decision.accepted and decision.reason_code == "bumpless_bump_limit"
    assert plant.writes == []
    assert gateway.audit_records()[-1]["reason_code"] == "bumpless_bump_limit"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 101.0])
def test_invalid_final_readback_refuses_acquisition(
    value: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, plant = _gateway()
    readings = iter((50.0, value))
    monkeypatch.setattr(plant, "read", lambda tag: next(readings))
    decision = gateway.propose(_proposal(58))
    assert decision.reason_code == "bumpless_readback_invalid"
    assert plant.writes == []


def test_a_new_switch_on_tracks_even_while_a_previous_hold_remains() -> None:
    gateway, plant = _gateway()
    gateway.propose(_proposal(58))
    gateway.record_beat(beat("standby", cycles=2))
    gateway.record_beat(beat("on", cycles=3))
    decision = gateway.propose(_proposal(55, 2))
    assert decision.accepted and decision.clamped_value == 50
    assert plant.writes[-1][2] == 50


def test_initialisation_does_not_bypass_the_minimum_interval() -> None:
    gateway, plant = _gateway()
    gateway.propose(_proposal(58))
    gateway.record_beat(beat("standby", cycles=2))
    gateway.record_beat(beat("on", cycles=3))
    decision = gateway.propose(_proposal(51))
    assert decision.reason_code == "min_interval"
    assert len(plant.writes) == 1


def test_an_ordinary_beat_does_not_restart_initialisation() -> None:
    gateway, plant = _gateway()
    gateway.propose(_proposal(58))
    gateway.record_beat(beat(cycles=2))
    gateway.propose(_proposal(55, 2))
    assert plant.writes[-1][2] == 55


def test_confirm_refuses_a_short_controller_watchdog_at_approval() -> None:
    gateway, plant = _gateway("confirm")
    proposal = _proposal(52)
    gateway.propose(proposal)
    gateway.record_beat(beat(cycle_s=40, targets=()))
    decision = gateway.approve(proposal_key(proposal))
    assert decision.reason_code == "liveness_watchdog_short"
    assert plant.writes == []


def test_confirm_approval_after_controller_beat_expires_is_refused_as_missing() -> None:
    clock = {"ns": 0}
    plant = SimPlant(60)
    gateway = WriteGateway(
        plant,
        {TAG: replace(POLICY, watchdog_s=60)},
        "confirm",
        monotonic_ns=lambda: clock["ns"],
    )
    gateway.tick(0)
    gateway.record_beat(runtime_beat())
    gateway.record_beat(beat())
    proposal = _proposal(52)
    gateway.propose(proposal)
    clock["ns"] = plant.now_ns = 120 * S
    gateway.tick(plant.now_ns)
    decision = gateway.approve(proposal_key(proposal))
    assert decision.reason_code == "liveness_missing"
    assert plant.writes == []


def _scripted_reads(monkeypatch: pytest.MonkeyPatch, plant: SimPlant, *values: float) -> None:
    """Serve plant reads in order, then keep returning the last value."""
    queue = list(values)
    monkeypatch.setattr(plant, "read", lambda tag: queue.pop(0) if len(queue) > 1 else queue[0])


def test_refused_bump_limit_leaves_target_uninitialised(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway, plant = _gateway()
    _scripted_reads(monkeypatch, plant, 50.0, 35.0, 40.0)
    assert gateway.propose(_proposal(58)).reason_code == "bumpless_bump_limit"
    decision = gateway.propose(_proposal(55, 2))
    assert decision.reason_code == "bumpless_initialisation"
    assert plant.writes[-1][2] == 40.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 101.0])
def test_refused_readback_leaves_target_uninitialised(
    value: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, plant = _gateway()
    _scripted_reads(monkeypatch, plant, 50.0, value, 40.0)
    assert gateway.propose(_proposal(58)).reason_code == "bumpless_readback_invalid"
    decision = gateway.propose(_proposal(55, 2))
    assert decision.reason_code == "bumpless_initialisation"
    assert plant.writes[-1][2] == 40.0

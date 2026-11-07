"""Fail-closed tests for the setpoint path: any plant exception, not only comm errors.

A KeyError, ValueError or RuntimeError from the plant must stop that target, release it,
audit ``plant_error`` (class name only) and never escape propose, approve or tick.
"""

from __future__ import annotations

import pytest
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WriteDecision, WriteProposal
from crosscut_gateway.policy import proposal_key
from test_engine_hardening import FaultPlant, events, make
from test_gateway_scenarios import POLICY, TAG, SimPlant, proposal, run

OTHER = "TIC102.SP"
ERRORS = [KeyError("x"), ValueError("x"), RuntimeError("x")]


class BoomPlant(FaultPlant):
    """FaultPlant that raises ``error`` from the named method."""

    def __init__(self) -> None:
        """No failure armed."""
        super().__init__()
        self.error: Exception | None = None
        self.where = ""
        self.bad_read_tag = ""

    def _maybe(self, name: str) -> None:
        """Raise the armed error when ``name`` is the armed method."""
        if self.error is not None and self.where == name:
            raise self.error

    def write(self, tag: str, value: float) -> bool:
        """Write, or raise the armed error."""
        self._maybe("write")
        return super().write(tag, value)

    def read(self, tag: str) -> float:
        """Read, or raise the armed error."""
        self._maybe("read")
        if tag == self.bad_read_tag:
            raise KeyError(tag)
        return super().read(tag)

    def send_heartbeat(self) -> None:
        """Heartbeat, or raise the armed error."""
        self._maybe("send_heartbeat")
        super().send_heartbeat()

    def loop_mode(self, tag: str) -> str:
        """Loop mode, or raise the armed error."""
        self._maybe("loop_mode")
        return super().loop_mode(tag)

    def release(self, tag: str) -> None:
        """Release, or raise the armed error."""
        self._maybe("release")
        super().release(tag)


def _raise_key_error(tag: str) -> None:
    """A release that fails with a non-comm error."""
    raise KeyError(tag)


def _plant_error_record(gw: WriteGateway) -> dict[str, str]:
    """The single plant_error audit record."""
    found = [r for r in gw.audit_records() if r["event"] == "plant_error"]
    assert found
    return found[-1]


@pytest.mark.parametrize("error", ERRORS)
@pytest.mark.parametrize("where", ["write", "send_heartbeat", "loop_mode"])
def test_propose_plant_exception_fails_closed(error: Exception, where: str) -> None:
    """Any exception at a plant call refuses the proposal and stops the target."""
    plant = BoomPlant()
    plant.error, plant.where = error, where
    gw = make("supervised", plant)
    decision = gw.propose(proposal(55.0))
    assert not decision.accepted
    assert decision.reason_code == "plant_error"
    assert gw.status()[TAG] == "stopped:comm"
    names = [r["value"] for r in gw.audit_records() if r["event"] == "plant_error"]
    assert type(error).__name__ in names


def test_release_failure_during_fail_closed_is_swallowed() -> None:
    """A release that also raises does not escape; the target is still stopped."""
    plant = BoomPlant()
    plant.error, plant.where = RuntimeError("x"), "write"
    gw = make("supervised", plant)
    plant.release = _raise_key_error  # type: ignore[method-assign]
    assert gw.propose(proposal(55.0)).reason_code == "plant_error"
    assert gw.status()[TAG] == "stopped:comm"
    assert "release_failed" in [r["reason_code"] for r in gw.audit_records()]


def test_tick_isolates_a_failing_tag_and_still_heartbeats() -> None:
    """A KeyError for one tag stops only that tag; heartbeat and the other tag still run."""
    plant = BoomPlant()
    plant.values[OTHER] = 50.0
    plant.modes[OTHER] = "CAS"
    gw = WriteGateway(plant, {OTHER: POLICY, TAG: POLICY}, "supervised")
    assert gw.propose(proposal(55.0)).accepted
    assert gw.propose(WriteProposal(OTHER, 55.0, "s", 0, "t")).accepted
    plant.bad_read_tag = TAG
    gw.tick(plant.now_ns)
    assert gw.status()[TAG] == "stopped:comm"
    assert gw.status()[OTHER] == "enabled"
    assert plant.last_hb_ns is not None
    assert _plant_error_record(gw)["tag"] == TAG


def test_tick_heartbeat_exception_stops_holding_targets() -> None:
    """A non-comm heartbeat exception fails closed instead of escaping tick."""
    plant = BoomPlant()
    gw = make("supervised", plant)
    assert gw.propose(proposal(55.0)).accepted
    plant.error, plant.where = RuntimeError("x"), "send_heartbeat"
    gw.tick(plant.now_ns)
    assert gw.status()[TAG] == "stopped:comm"


@pytest.mark.parametrize("error", ERRORS)
def test_approve_never_loses_a_proposal_silently(error: Exception) -> None:
    """Approve with a plant exception returns an audited plant_error decision."""
    plant = BoomPlant()
    gw = make("confirm", plant)
    gw.tick(0)
    queued = proposal(55.0)
    assert gw.propose(queued, actor_ctx=ActorContext(actor="alice")).reason_code == "queued"
    plant.error, plant.where = error, "write"
    decision: WriteDecision = gw.approve(
        proposal_key(queued), actor_ctx=ActorContext(actor="bob")
    )
    assert decision.reason_code == "plant_error"
    assert gw.pending() == [] or all(p.target_tag != TAG for p in gw.pending())
    assert "plant_error" in events(gw)
    assert gw.status()[TAG] == "stopped:comm"


def test_untouched_healthy_path_unchanged() -> None:
    """A normal accepted write still works and holds the target."""
    plant = SimPlant()
    gw = make("supervised", plant)
    assert gw.propose(proposal(55.0)).accepted
    run(gw, plant, 1)
    assert gw.status()[TAG] == "enabled"

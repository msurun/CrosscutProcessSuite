"""Exercise output test trips and restoration using live-read plant doubles.

The double can lose communications during a test, so an open intent is observable.
"""

from dataclasses import replace
from pathlib import Path

import pytest
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WriteDecision
from crosscut_gateway.out_steps import OutputPolicy, OutputRequest
from crosscut_gateway.param_intent_store import ParamIntentRecord

POLICY = OutputPolicy("loop", (0, 100), (10, 90), 2, 10, 0.01)
REQUEST = OutputRequest("test-one", "OUT", 1, 5)
HUMAN = ActorContext(actor="engineer")


class Plant:
    """In-memory DCS whose reads can fail while its output retains the last write."""

    def __init__(self) -> None:
        """Start in MAN with a safe PV and midpoint OUT."""
        self.output = 50.0
        self.mode = "MAN"
        self.pv = 50.0
        self.disconnected = False
        self.writes = []

    def read_out(self, target: str) -> float:
        """Read the output or report a disconnected DCS."""
        if self.disconnected:
            raise ConnectionError("disconnected")
        return self.output

    def read_pv(self, target: str) -> float:
        """Read PV through the same communications fault gate."""
        self.read_out(target)
        return self.pv

    def loop_mode(self, target: str) -> str:
        """Read mode through the same communications fault gate."""
        self.read_out(target)
        return self.mode

    def write_out(self, target: str, value: float) -> bool:
        """Record an accepted write only while connected."""
        self.read_out(target)
        self.output = value
        self.writes.append(value)
        return True


GatewayRig = tuple[Plant, WriteGateway, Path]


@pytest.fixture
def rig(tmp_path: Path) -> GatewayRig:
    """Create a real gateway with a durable output-intent store."""
    plant = Plant()
    gateway = WriteGateway(plant, {}, "confirm", gateway_dir=tmp_path, outputs={"OUT": POLICY})
    gateway.tick(1)
    return plant, gateway, tmp_path


def start(gateway: WriteGateway) -> WriteDecision:
    """Confirm a test as a human engineer."""
    return gateway.start_output(REQUEST, actor_ctx=HUMAN)


@pytest.mark.parametrize("mode", ["off", "advisory", "dry_run", "supervised"])
def test_output_tests_refuse_every_gateway_mode_except_confirm(rig: GatewayRig, mode: str) -> None:
    """Output tests refuse every gateway mode except confirm."""
    plant, gateway, _ = rig
    gateway._mode = mode
    result = start(gateway)
    assert result.reason_code == "out_requires_confirm_mode"
    assert plant.writes == []


def test_output_tests_refuse_a_loop_that_is_not_man(rig: GatewayRig) -> None:
    """Output tests refuse a loop that is not man."""
    plant, gateway, _ = rig
    plant.mode = "AUTO"
    result = start(gateway)
    assert result.reason_code == "loop_not_man"
    assert plant.writes == []


@pytest.mark.parametrize("field,value", [("amplitude", 3), ("duration_s", 11),
                                         ("amplitude", float("nan")), ("duration_s", True)])
def test_output_tests_refuse_invalid_bounds_without_writing(
    rig: GatewayRig, field: str, value: object
) -> None:
    """Output tests refuse invalid bounds without writing."""
    plant, gateway, _ = rig
    result = gateway.start_output(replace(REQUEST, **{field: value}), actor_ctx=HUMAN)
    assert not result.accepted
    assert plant.writes == []


def test_pv_limit_aborts_and_returns_verified_pretest_output(rig: GatewayRig) -> None:
    """Pv limit aborts and returns verified pretest output."""
    plant, gateway, _ = rig
    assert start(gateway).accepted
    plant.pv = POLICY.pv_limits[1]
    gateway.tick(2)
    assert plant.writes == [51, 50]
    assert gateway.status()["OUT"] == "restored"
    assert gateway._outputs.store.load_open() == []


def test_timeout_aborts_and_returns_verified_pretest_output(rig: GatewayRig) -> None:
    """Timeout aborts and returns verified pretest output."""
    plant, gateway, _ = rig
    assert start(gateway).accepted
    gateway.tick(5_000_000_001)
    assert plant.writes == [51, 50]
    assert gateway.status()["OUT"] == "restored"


def test_mode_change_aborts_and_returns_verified_pretest_output(rig: GatewayRig) -> None:
    """Mode change aborts and returns verified pretest output."""
    plant, gateway, _ = rig
    assert start(gateway).accepted
    plant.mode = "AUTO"
    gateway.tick(2)
    assert plant.writes == [51, 50]
    assert plant.mode == "AUTO"


def test_operator_cancel_aborts_and_returns_verified_pretest_output(rig: GatewayRig) -> None:
    """Operator cancel aborts and returns verified pretest output."""
    plant, gateway, _ = rig
    assert start(gateway).accepted
    gateway.cancel_output("OUT", actor_ctx=HUMAN)
    assert plant.writes == [51, 50]
    assert gateway.status()["OUT"] == "restored"


def test_communication_loss_keeps_intent_until_verified_restore_on_reconnect(
    rig: GatewayRig
) -> None:
    """Communication loss keeps intent until verified restore on reconnect."""
    plant, gateway, _ = rig
    assert start(gateway).accepted
    plant.disconnected = True
    gateway.tick(2)
    assert gateway.status()["OUT"] == "reconcile_required"
    assert len(gateway._outputs.store.load_open()) == 1
    plant.disconnected = False
    gateway.tick(3)
    assert plant.writes == [51, 50]
    assert gateway._outputs.store.load_open() == []


def test_crash_midtest_requires_reconciliation_before_another_test(rig: GatewayRig) -> None:
    """Crash midtest requires reconciliation before another test."""
    plant, gateway, directory = rig
    assert start(gateway).accepted
    restarted = WriteGateway(plant, {}, "confirm", gateway_dir=directory, outputs={"OUT": POLICY})
    restarted.tick(2)
    assert start(restarted).reason_code == "reconcile_required"
    assert plant.writes == [51]
    restarted.cancel_output("OUT", actor_ctx=HUMAN)
    assert plant.writes == [51, 50]
    assert restarted._outputs.store.load_open() == []


def test_kill_aborts_and_returns_verified_pretest_output(rig: GatewayRig) -> None:
    """Kill aborts and returns verified pretest output."""
    plant, gateway, _ = rig
    assert start(gateway).accepted
    gateway.kill(actor_ctx=HUMAN)
    gateway.tick(2)
    assert plant.writes == [51, 50]


def test_gateway_mode_change_aborts_and_returns_verified_pretest_output(rig: GatewayRig) -> None:
    """Gateway mode change aborts and returns verified pretest output."""
    plant, gateway, _ = rig
    assert start(gateway).accepted
    gateway._mode = "advisory"
    gateway.tick(2)
    assert plant.writes == [51, 50]


def test_failed_restoration_readback_keeps_the_intent_open(
    rig: GatewayRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An accepted restoration write is insufficient without a matching read-back."""
    plant, gateway, _ = rig
    assert start(gateway).accepted
    monkeypatch.setattr(plant, "read_out", lambda target: 51)
    gateway.cancel_output("OUT", actor_ctx=HUMAN)
    assert gateway.status()["OUT"] == "reconcile_required"
    assert gateway.alarms()["OUT"] == "check_dcs"
    assert len(gateway._outputs.store.load_open()) == 1


def test_intent_storage_failure_prevents_the_first_plant_write(
    rig: GatewayRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persisting the baseline is a prerequisite for any physical output mutation."""
    plant, gateway, _ = rig
    monkeypatch.setattr(gateway._outputs.store, "record_intent", fail_storage)
    assert not start(gateway).accepted
    assert plant.writes == []


def fail_storage(record: ParamIntentRecord) -> None:
    """Represent a full or unavailable intent-storage disk."""
    raise OSError("intent disk unavailable")


def test_abort_reason_and_verified_baseline_are_audited(rig: GatewayRig) -> None:
    """The audit proves both the trip cause and the return value independently read."""
    _, gateway, _ = rig
    assert start(gateway).accepted
    gateway.cancel_output("OUT", actor_ctx=HUMAN)
    events = gateway.audit_records()
    assert any(event["event"] == "out_abort" and
               event["reason_code"] == "operator_cancel" for event in events)
    assert any(event["event"] == "out_write_verified" and
               event["read"] == "50.0" for event in events)

"""L5-OUT: bounded MAN steps through the real OPC UA gateway adapter.

The fixture acts as the DCS operator; the gateway itself never writes loop mode.
Every row asserts the actual OUT read-back after abort, not only gateway status.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.out_steps import OutputPolicy, OutputRequest
from golden import checkout_problem, load_pin, roughersim_dir
from rs_harness import STEP_S, Harness, plant_map_for, rs_server

OUTPUT_TAG = "FIC203.OUT"
OUTPUT_PREFIX = "nsu=urn:roughersim:abb800xa;s=Application/Loop/FIC203/"
OUTPUT_POLICY = OutputPolicy("FIC203", (0, 100), (-1_000_000, 1_000_000), 1, 10, 0.01)
OPERATOR = ActorContext(actor="l5-engineer", roles=("engineer",))
NANOSECONDS_PER_SECOND = 1_000_000_000  # ns per second


def output_map(port: int) -> dict:
    """Extend the pinned plant map with the simulator's manual output and live PV."""
    document = plant_map_for(port)
    document["targets"][OUTPUT_TAG] = {
        "kind": "out_step", "out_node": OUTPUT_PREFIX + "Out",
        "pv_node": OUTPUT_PREFIX + "Pv", "data_type": "Double",
        "mode_node": OUTPUT_PREFIX + "Mode",
        "mode_values": {"MAN": 0, "AUTO": 1, "CAS": 2, "RSP": 3},
    }
    return document


@pytest.fixture(scope="module", autouse=True)
def pinned_checkout() -> None:
    """Run only against the exact checked-in RougherSim release pin."""
    problem = checkout_problem(roughersim_dir(), load_pin())
    if problem:
        pytest.skip(problem)


@pytest.fixture
def output_rig(tmp_path: Path):
    """Put the simulator in MAN as an operator, outside the gateway write path."""
    with rs_server(tmp_path / "output-server.log", None, 1.0) as port:
        harness = Harness(output_map(port), 1.0)
        try:
            harness.wait_ready()
            # Test fixture represents the independent operator's DCS action.
            assert harness.plant._call(harness.plant._take_async(OUTPUT_PREFIX + "Mode", 0))
            harness.advance(2 * STEP_S)  # the DCS applies queued writes on its next plant step
            assert harness.plant.loop_mode(OUTPUT_TAG) == "MAN"
            gateway = WriteGateway(harness.plant, {}, "confirm", gateway_dir=tmp_path,
                                   outputs={OUTPUT_TAG: OUTPUT_POLICY})
            gateway.tick(1)
            yield harness.plant, gateway
        finally:
            harness.close()


@pytest.mark.roughersim
@pytest.mark.parametrize(
    "abort_reason", ["operator_cancel", "timeout", "mode_change", "pv_limit", "comm_loss"]
)
def test_l5_output_step_in_man_aborts_and_restores_readback(
    output_rig, abort_reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An accepted OUT step returns exactly to its independently read pre-test value."""
    plant, gateway = output_rig
    baseline = plant.read_out(OUTPUT_TAG)
    request = OutputRequest("l5-output", OUTPUT_TAG, 1, 5)
    assert gateway.start_output(request, actor_ctx=OPERATOR).accepted
    assert plant.read_out(OUTPUT_TAG) == pytest.approx(baseline + 1, abs=0.01)
    writes = count_out_writes(plant, monkeypatch)
    abort_output(plant, gateway, abort_reason, monkeypatch)
    if abort_reason == "mode_change":
        # The DCS took the loop out of MAN: the gateway must not write OUT and keeps the intent.
        assert writes == []
        assert gateway.status()[OUTPUT_TAG] == "reconcile_required"
        assert len(gateway._outputs.store.load_open()) == 1
        return
    assert plant.read_out(OUTPUT_TAG) == pytest.approx(baseline, abs=0.01)
    assert gateway.status()[OUTPUT_TAG] == "restored"
    assert gateway._outputs.store.load_open() == []


def count_out_writes(plant, patch: pytest.MonkeyPatch) -> list[float]:
    """Record every OUT write the gateway attempts from now on."""
    writes: list[float] = []
    original = plant.write_out

    def counting(tag: str, value: float) -> bool:
        writes.append(value)
        return original(tag, value)

    patch.setattr(plant, "write_out", counting)
    return writes


def abort_output(plant, gateway: WriteGateway, reason: str, patch: pytest.MonkeyPatch) -> None:
    """Inject safety-input faults while keeping actual OUT restoration on OPC UA."""
    if reason == "operator_cancel":
        gateway.cancel_output(OUTPUT_TAG, actor_ctx=OPERATOR)
    elif reason == "timeout":
        gateway.tick(5 * NANOSECONDS_PER_SECOND + 1)
    elif reason == "mode_change":
        assert plant._call(plant._take_async(OUTPUT_PREFIX + "Mode", 1))
        gateway.tick(2)
    elif reason == "pv_limit":
        patch.setattr(plant, "read_pv", lambda target: OUTPUT_POLICY.pv_limits[1])
        gateway.tick(2)
    else:
        with patch.context() as fault:
            fault.setattr(plant, "read_pv", lost_connection)
            fault.setattr(plant, "read_out", lost_connection)
            gateway.tick(2)
            assert gateway.status()[OUTPUT_TAG] == "reconcile_required"
        gateway.tick(3)


def lost_connection(target: str) -> float:
    """Represent unavailable safety/read-back inputs until the transport recovers."""
    raise ConnectionError("injected DCS communications loss")


def test_l5_operator_out_change_is_not_overwritten_by_restore(output_rig) -> None:
    """The DCS operator moves OUT in MAN during the step: restore must keep their value."""
    plant, gateway = output_rig
    baseline = plant.read_out(OUTPUT_TAG)
    request = OutputRequest("l5-op", OUTPUT_TAG, 1, 5)
    assert gateway.start_output(request, actor_ctx=OPERATOR).accepted
    # Test fixture represents the independent operator's own OUT move in the DCS.
    assert plant._call(plant._take_async(OUTPUT_PREFIX + "Out", baseline + 7))
    gateway.cancel_output(OUTPUT_TAG, actor_ctx=OPERATOR)
    assert plant.read_out(OUTPUT_TAG) == pytest.approx(baseline + 7, abs=0.01)
    assert gateway.status()[OUTPUT_TAG] == "reconcile_required"
    assert len(gateway._outputs.store.load_open()) == 1

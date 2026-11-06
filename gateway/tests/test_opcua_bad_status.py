"""Bad status codes and unusable values on node reads fail closed as ConnectionError.

A server answer with a Bad status, or a NaN value, must never escape as a raw
asyncua error from the setpoint, mode, source, acknowledgement or data-type reads.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from asyncua import ua
from asyncua.common.node import Node
from crosscut_gateway.opcua_plant import OpcUaPlant
from test_opcua_plant import (
    RO_TAG,
    TAG,
    PlantFactory,
    ServerControl,
    _close_plant,
    get_free_port,
    make_map,
)


def _set_status(ctrl: ServerControl, name: str, value: Any, status: ua.StatusCodes) -> None:
    """Write ``value`` to a server node together with a non-good status code."""
    code = ua.StatusCode(status)
    variant = ua.Variant(value, ua.VariantType.Double)
    ctrl._run(ctrl.nodes[name].write_value(ua.DataValue(variant, code)))


async def _raise_bad_data_type(*_args: Any, **_kwargs: Any) -> Any:
    """Stand-in for an awaited DataType read that the server answers with a Bad status."""
    raise ua.UaStatusCodeError(ua.StatusCodes.BadAttributeIdInvalid)


@pytest.fixture(scope="module")
def server() -> Iterator[ServerControl]:
    """Start one asyncua server for the module, with its own bad-status nodes."""
    ctrl = ServerControl(get_free_port())
    try:
        try:
            ctrl.start()
        except OSError as error:
            pytest.skip(f"local asyncua server cannot bind: {error}")
        yield ctrl
    finally:
        ctrl.stop()


@pytest.fixture(autouse=True)
def reset_nodes(server: ServerControl) -> None:
    """Restore every node, including its status code, before each test."""
    server.reset()


@pytest.fixture
def make_plant() -> Iterator[PlantFactory]:
    """Yield a plant factory; every plant it made is closed at teardown."""
    plants: list[OpcUaPlant] = []

    def factory(plant_map: Any, timeout_s: float = 2.0) -> OpcUaPlant:
        """Create a plant on the given map and remember it for teardown."""
        plant = OpcUaPlant(plant_map, timeout_s=timeout_s)
        plants.append(plant)
        return plant

    yield factory
    for plant in plants:
        _close_plant(plant)


@pytest.fixture
def plant(server: ServerControl, make_plant: PlantFactory) -> OpcUaPlant:
    """A plant on the test server's map."""
    return make_plant(make_map(server))


def test_setpoint_read_bad_status_raises_connection_error(
    server: ServerControl, plant: OpcUaPlant
) -> None:
    """A readback with a Bad status code fails closed."""
    _set_status(server, "FIC101.PV", 50.0, ua.StatusCodes.BadSensorFailure)
    with pytest.raises(ConnectionError):
        plant.read(TAG)


def test_setpoint_read_nan_raises_connection_error(
    server: ServerControl, plant: OpcUaPlant
) -> None:
    """A NaN readback is an unusable value, not a number to control against."""
    server.set_node("FIC101.PV", float("nan"))
    with pytest.raises(ConnectionError):
        plant.read(TAG)


def test_loop_mode_bad_status_raises_connection_error(
    server: ServerControl, plant: OpcUaPlant
) -> None:
    """A mode node answering with a Bad status raises ConnectionError."""
    _set_status(server, "FIC101.MODE", 2.0, ua.StatusCodes.BadSensorFailure)
    with pytest.raises(ConnectionError):
        plant.loop_mode(TAG)


def test_setpoint_source_bad_status_raises_connection_error(
    server: ServerControl, plant: OpcUaPlant
) -> None:
    """A source node answering with a Bad status raises ConnectionError."""
    _set_status(server, "FIC101.SRC", 1.0, ua.StatusCodes.BadSensorFailure)
    with pytest.raises(ConnectionError):
        plant.setpoint_source(TAG)


def test_heartbeat_ack_bad_status_raises_connection_error(
    server: ServerControl, plant: OpcUaPlant
) -> None:
    """An acknowledgement node answering with a Bad status raises ConnectionError."""
    _set_status(server, "HB_ACK", 1.0, ua.StatusCodes.BadSensorFailure)
    with pytest.raises(ConnectionError):
        plant.heartbeat_seen()


def test_heartbeat_data_type_bad_status_raises_connection_error(
    plant: OpcUaPlant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A heartbeat node whose data type read is refused raises ConnectionError."""
    monkeypatch.setattr(Node, "read_data_type_as_variant_type", _raise_bad_data_type)
    with pytest.raises(ConnectionError):
        plant.send_heartbeat()


def test_release_data_type_bad_status_raises_connection_error(
    plant: OpcUaPlant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source node whose data type read is refused raises ConnectionError on release."""
    monkeypatch.setattr(Node, "read_data_type_as_variant_type", _raise_bad_data_type)
    with pytest.raises(ConnectionError):
        plant.release(TAG)


def test_take_remote_data_type_bad_status_raises_connection_error(
    server: ServerControl, plant: OpcUaPlant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A take-remote node whose data type read is refused raises ConnectionError."""
    monkeypatch.setattr(Node, "read_data_type_as_variant_type", _raise_bad_data_type)
    target = {"take_remote": {"value": 1}, "source_node": server.nid("FIC101.SRC")}
    with pytest.raises(ConnectionError):
        plant._write_take_remote(target)


def test_readback_of_other_tag_still_works(server: ServerControl, plant: OpcUaPlant) -> None:
    """The fail-closed path does not break a healthy read of another target."""
    server.set_node("RO.SP", 42.0)
    assert plant.read(RO_TAG) == pytest.approx(42.0)

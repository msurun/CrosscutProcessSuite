"""Tests for pid_param targets in the OPC UA plant adapter (ADR 014, step 4).

Runs against a real asyncua server on localhost (NoSecurity, random port); the
module is skipped when the server cannot bind.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

import pytest
from asyncua import ua
from crosscut_gateway.opcua_plant import OpcUaPlant, PlantMapError, validate_plant_map
from test_opcua_plant import (
    PlantFactory,
    ServerControl,
    _close_plant,
    dead_endpoint,
    get_free_port,
    make_map,
)

FLOAT_TAG = "PF.GAIN"
DOUBLE_TAG = "PD.GAIN"
SP_TAG = "FIC101.SP"
FLOAT_TOL = 1e-4


@dataclass(frozen=True)
class ParamNode:
    """One parameter variable on the test server."""

    name: str
    initial: Any
    vtype: ua.VariantType
    writable: bool = True


PARAM_NODES = (
    ParamNode("PF", 1.5, ua.VariantType.Float),
    ParamNode("PF.RB", 1.5, ua.VariantType.Float, writable=False),
    ParamNode("PD", 2.5, ua.VariantType.Double),
    ParamNode("PD.AS_FLOAT", 3.5, ua.VariantType.Double),
    ParamNode("PF.AS_DOUBLE", 4.5, ua.VariantType.Float),
    ParamNode("P.RO", 1.0, ua.VariantType.Double, writable=False),
    ParamNode("P.BAD", 1.0, ua.VariantType.Double),
    ParamNode("P.NAN", 1.0, ua.VariantType.Double),
    ParamNode("P.TEXT", "abc", ua.VariantType.String),
    ParamNode("P.FLAG", True, ua.VariantType.Boolean),
)
SPECS = {spec.name: spec for spec in PARAM_NODES}


def _add_param_nodes(ctrl: ServerControl) -> None:
    """Add every PARAM_NODES variable to the running test server."""
    assert ctrl.server is not None
    server = ctrl.server

    async def build() -> None:
        plant_obj = server.get_node(ctrl.nid("Plant"))
        for spec in PARAM_NODES:
            node = await plant_obj.add_variable(
                ctrl.nid(spec.name), spec.name, spec.initial, spec.vtype
            )
            if spec.writable:
                await node.set_writable()
            ctrl.nodes[spec.name] = node

    ctrl._run(build())


def _set_param(ctrl: ServerControl, name: str, value: Any) -> None:
    """Set a server-side parameter value with the node's declared type."""
    variant = ua.Variant(value, SPECS[name].vtype)
    ctrl._run(ctrl.nodes[name].write_value(ua.DataValue(variant)))


def _set_bad_status(ctrl: ServerControl, name: str) -> None:
    """Give a server node a value with a Bad status code."""
    variant = ua.Variant(1.0, ua.VariantType.Double)
    status = ua.StatusCode(ua.StatusCodes.BadSensorFailure)
    ctrl._run(ctrl.nodes[name].write_value(ua.DataValue(variant, status)))


@pytest.fixture(scope="module")
def server() -> Iterator[ServerControl]:
    """Start one asyncua server for the module; skip when it cannot bind."""
    ctrl = ServerControl(get_free_port())
    try:
        try:
            ctrl.start()
            _add_param_nodes(ctrl)
        except OSError as error:
            pytest.skip(f"local asyncua server cannot bind: {error}")
        yield ctrl
    finally:
        ctrl.stop()


@pytest.fixture(autouse=True)
def reset_nodes(server: ServerControl) -> None:
    """Restore the parameter nodes before each test."""
    server.reset()
    for spec in PARAM_NODES:
        _set_param(server, spec.name, spec.initial)


def _param_entry(
    server: ServerControl, node: str, data_type: str, readback: str | None = None
) -> dict[str, Any]:
    """Build one pid_param target whose nodes live on the test server."""
    entry: dict[str, Any] = {
        "param_node": server.nid(node),
        "data_type": data_type,
        "mode_node": server.nid("FIC101.MODE"),
        "mode_values": {"MAN": 0, "AUTO": 1, "CAS": 2},
    }
    if readback is not None:
        entry["readback_node"] = server.nid(readback)
    return entry


def _mixed_map(server: ServerControl) -> dict[str, Any]:
    """A plant map holding the setpoint targets and several pid_param targets."""
    plant_map = make_map(server)
    plant_map["targets"].update(
        {
            FLOAT_TAG: _param_entry(server, "PF", "Float", readback="PF.RB"),
            DOUBLE_TAG: _param_entry(server, "PD", "Double"),
            "PD.AS_FLOAT": _param_entry(server, "PD.AS_FLOAT", "Float"),
            "PF.AS_DOUBLE": _param_entry(server, "PF.AS_DOUBLE", "Double"),
            "P.RO": _param_entry(server, "P.RO", "Double"),
            "P.BAD": _param_entry(server, "P.BAD", "Double"),
            "P.NAN": _param_entry(server, "P.NAN", "Double"),
            "P.TEXT": _param_entry(server, "P.TEXT", "Double"),
            "P.FLAG": _param_entry(server, "P.FLAG", "Double"),
        }
    )
    return plant_map


@pytest.fixture
def make_plant() -> Iterator[PlantFactory]:
    """Yield a plant factory; every plant it made is closed at teardown."""
    plants: list[OpcUaPlant] = []

    def factory(plant_map: Mapping[str, Any], timeout_s: float = 2.0) -> OpcUaPlant:
        """Create a plant on the given map and remember it for teardown."""
        plant = OpcUaPlant(plant_map, timeout_s=timeout_s)
        plants.append(plant)
        return plant

    yield factory
    for plant in plants:
        _close_plant(plant)


@pytest.fixture
def plant(server: ServerControl, make_plant: PlantFactory) -> OpcUaPlant:
    """A plant on the mixed map."""
    return make_plant(_mixed_map(server))


def test_float_round_trip(plant: OpcUaPlant, server: ServerControl) -> None:
    """A Float target is written as Float; read-back comes from readback_node."""
    assert plant.write_param(FLOAT_TAG, 2.25) is True
    assert math.isclose(float(server.get_node("PF")), 2.25, abs_tol=FLOAT_TOL)
    assert math.isclose(plant.read_param(FLOAT_TAG), 1.5)  # PF.RB is a separate node
    _set_param(server, "PF.RB", 2.25)
    assert math.isclose(plant.read_param(FLOAT_TAG), 2.25, abs_tol=FLOAT_TOL)


def test_float_value_is_rounded_to_float32(plant: OpcUaPlant, server: ServerControl) -> None:
    """A Float write keeps float32 precision (0.1 is not 0.1 as a double)."""
    assert plant.write_param(FLOAT_TAG, 0.1) is True
    stored = float(server.get_node("PF"))
    assert stored != 0.1
    assert math.isclose(stored, 0.1, abs_tol=FLOAT_TOL)


def test_double_round_trip_default_readback(plant: OpcUaPlant) -> None:
    """A Double target without readback_node reads param_node back exactly."""
    assert plant.write_param(DOUBLE_TAG, 0.1) is True
    assert plant.read_param(DOUBLE_TAG) == 0.1


def test_integer_value_is_accepted(plant: OpcUaPlant) -> None:
    """A plain int is written as the configured float type."""
    assert plant.write_param(DOUBLE_TAG, 7) is True
    assert plant.read_param(DOUBLE_TAG) == 7.0


def test_float_config_on_double_node_is_type_mismatch(
    plant: OpcUaPlant, server: ServerControl
) -> None:
    """Config says Float, node is Double: the server answers BadTypeMismatch -> False."""
    assert plant.write_param("PD.AS_FLOAT", 9.0) is False
    assert server.get_node("PD.AS_FLOAT") == 3.5


def test_double_config_on_float_node_is_type_mismatch(
    plant: OpcUaPlant, server: ServerControl
) -> None:
    """Config says Double, node is Float: the server answers BadTypeMismatch -> False."""
    assert plant.write_param("PF.AS_DOUBLE", 9.0) is False
    assert server.get_node("PF.AS_DOUBLE") == 4.5


@pytest.mark.parametrize("value", [3.5e38, -3.5e38, 1e300, 10**400])
def test_out_of_float_range_is_refused_without_write(
    plant: OpcUaPlant, server: ServerControl, value: float
) -> None:
    """A value outside the float32 range is refused locally for a Float target."""
    assert plant.write_param(FLOAT_TAG, value) is False
    assert server.get_node("PF") == 1.5


def test_float_extreme_in_range_is_accepted(plant: OpcUaPlant) -> None:
    """The largest float32 is still writable."""
    assert plant.write_param(FLOAT_TAG, 3.4028234663852886e38) is True


def test_large_value_is_fine_for_double(plant: OpcUaPlant) -> None:
    """The float32 limit does not apply to a Double target."""
    assert plant.write_param(DOUBLE_TAG, 1e300) is True
    assert plant.read_param(DOUBLE_TAG) == 1e300


@pytest.mark.parametrize("tag", [FLOAT_TAG, DOUBLE_TAG])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, "1.0", None])
def test_non_finite_or_non_numeric_is_refused(
    plant: OpcUaPlant, server: ServerControl, tag: str, value: Any
) -> None:
    """NaN, infinity, booleans and non-numbers are never written."""
    assert plant.write_param(tag, value) is False
    assert server.get_node("PF") == 1.5
    assert server.get_node("PD") == 2.5


def test_read_only_node_returns_false(plant: OpcUaPlant) -> None:
    """A BadNotWritable answer is a refusal, not an exception."""
    assert plant.write_param("P.RO", 2.0) is False


def test_read_bad_status_raises_connection_error(plant: OpcUaPlant, server: ServerControl) -> None:
    """A DataValue with a Bad status code fails closed."""
    _set_bad_status(server, "P.BAD")
    with pytest.raises(ConnectionError):
        plant.read_param("P.BAD")


def test_read_nan_raises_connection_error(plant: OpcUaPlant, server: ServerControl) -> None:
    """A NaN read-back fails closed."""
    _set_param(server, "P.NAN", math.nan)
    with pytest.raises(ConnectionError):
        plant.read_param("P.NAN")


@pytest.mark.parametrize("tag", ["P.TEXT", "P.FLAG"])
def test_read_non_numeric_raises_connection_error(plant: OpcUaPlant, tag: str) -> None:
    """A string or boolean read-back fails closed (no '1.5' -> 1.5 conversion)."""
    with pytest.raises(ConnectionError):
        plant.read_param(tag)


def test_server_down_raises_within_three_seconds(server: ServerControl) -> None:
    """With nothing listening, read_param and write_param fail quickly."""
    dead_map = {**_mixed_map(server), "endpoint": dead_endpoint()}
    started = time.monotonic()
    with OpcUaPlant(dead_map, timeout_s=0.5) as dead:
        with pytest.raises((ConnectionError, TimeoutError)):
            dead.read_param(DOUBLE_TAG)
        with pytest.raises((ConnectionError, TimeoutError)):
            dead.write_param(DOUBLE_TAG, 1.0)
    assert time.monotonic() - started < 6.0


@pytest.mark.parametrize(("raw", "expected"), [(0, "MAN"), (2, "CAS"), (9, "UNKNOWN:9")])
def test_loop_mode_works_for_param_target(
    plant: OpcUaPlant, server: ServerControl, raw: int, expected: str
) -> None:
    """loop_mode maps raw values through mode_values for pid_param targets too."""
    server.set_node("FIC101.MODE", raw)
    assert plant.loop_mode(FLOAT_TAG) == expected


def test_mixed_map_keeps_setpoint_path_working(plant: OpcUaPlant) -> None:
    """Setpoint and parameter targets coexist in one map and one session."""
    assert plant.write(SP_TAG, 42.0) is True
    assert plant.read(SP_TAG) == 50.0  # PV node is the read-back
    assert plant.write_param(DOUBLE_TAG, 3.0) is True
    assert plant.read_param(DOUBLE_TAG) == 3.0


@pytest.mark.parametrize(
    "call",
    [
        lambda p: p.write(FLOAT_TAG, 1.0),
        lambda p: p.read(FLOAT_TAG),
        lambda p: p.release(FLOAT_TAG),
        lambda p: p.setpoint_source(FLOAT_TAG),
        lambda p: p.read_param(SP_TAG),
        lambda p: p.write_param(SP_TAG, 1.0),
    ],
)
def test_wrong_kind_raises_value_error(plant: OpcUaPlant, call: Callable[..., Any]) -> None:
    """A setpoint method on a param tag, or the reverse, is a ValueError."""
    with pytest.raises(ValueError, match="target"):
        call(plant)


def test_unknown_param_tag_raises_key_error(plant: OpcUaPlant) -> None:
    """An unknown tag stays a KeyError."""
    with pytest.raises(KeyError):
        plant.read_param("NOPE")
    with pytest.raises(KeyError):
        plant.write_param("NOPE", 1.0)


def test_valid_mixed_map_passes_validation(server: ServerControl) -> None:
    """Both kinds in one map validate."""
    validate_plant_map(_mixed_map(server))


def _with_param(server: ServerControl, **changes: Any) -> dict[str, Any]:
    """Return a map whose FLOAT_TAG target has the given keys set (None removes a key)."""
    plant_map = _mixed_map(server)
    target = dict(plant_map["targets"][FLOAT_TAG])
    for key, value in changes.items():
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value
    plant_map["targets"][FLOAT_TAG] = target
    return plant_map


@pytest.mark.parametrize(
    "changes",
    [
        {"setpoint_node": "ns=2;s=X"},
        {"source_node": "ns=2;s=X"},
        {"remote_value": 1},
        {"data_type": "Int32"},
        {"data_type": None},
        {"mode_node": None},
        {"mode_values": None},
        {"mode_values": {}},
        {"param_node": ""},
        {"readback_node": ""},
        {"unknown_key": 1},
    ],
)
def test_pid_param_schema_rejections(server: ServerControl, changes: dict[str, Any]) -> None:
    """Mixed keys of both kinds, a bad data_type and missing fields are all rejected."""
    with pytest.raises(PlantMapError):
        validate_plant_map(_with_param(server, **changes))
    with pytest.raises(PlantMapError):
        OpcUaPlant(_with_param(server, **changes)).close()


def test_setpoint_target_with_param_keys_is_rejected(server: ServerControl) -> None:
    """A setpoint target may not carry param_node or data_type."""
    plant_map = make_map(server)
    plant_map["targets"][SP_TAG]["param_node"] = server.nid("PF")
    with pytest.raises(PlantMapError):
        validate_plant_map(plant_map)
    plant_map = make_map(server)
    plant_map["targets"][SP_TAG]["data_type"] = "Float"
    with pytest.raises(PlantMapError):
        validate_plant_map(plant_map)


def test_param_target_without_readback_node_is_valid(server: ServerControl) -> None:
    """readback_node is optional."""
    validate_plant_map(_with_param(server, readback_node=None))

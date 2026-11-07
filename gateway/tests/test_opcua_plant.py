"""Tests for the OPC UA plant adapter and its gateway integration.

Runs against a real asyncua server on localhost (NoSecurity, random port).
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from asyncua import Server, ua
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WritePolicy, WriteProposal
from crosscut_gateway.opcua_plant import OpcUaPlant, PlantMapError

NAMESPACE_URI = "urn:crosscut:test"
TAG = "FIC101.SP"
RO_TAG = "RO.SP"
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
PlantFactory = Callable[..., OpcUaPlant]


@dataclass(frozen=True)
class NodeSpec:
    """One variable on the test server."""

    name: str
    initial: Any
    vtype: ua.VariantType
    writable: bool = False


NODES = (
    NodeSpec("FIC101.SP", 50.0, ua.VariantType.Double, writable=True),
    NodeSpec("FIC101.PV", 50.0, ua.VariantType.Double),
    NodeSpec("FIC101.MODE", 2, ua.VariantType.Int32, writable=True),
    NodeSpec("FIC101.SRC", 1, ua.VariantType.Int32, writable=True),
    NodeSpec("RO.SP", 50.0, ua.VariantType.Double),
    NodeSpec("HB", 0, ua.VariantType.Int64, writable=True),
    NodeSpec("HB_ACK", True, ua.VariantType.Boolean),
)
SPEC_BY_NAME = {spec.name: spec for spec in NODES}


def get_free_port() -> int:
    """Return a localhost TCP port that was free when asked for."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def dead_endpoint() -> str:
    """Return an OPC UA endpoint URL with nothing listening on it."""
    return f"opc.tcp://127.0.0.1:{get_free_port()}"


class ServerControl:
    """asyncua server running on its own event loop thread."""

    def __init__(self, port: int) -> None:
        self.endpoint = f"opc.tcp://127.0.0.1:{port}"
        self.idx = 0
        self.server: Server | None = None
        self.nodes: dict[str, Any] = {}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="opcua-test-server"
        )
        self._thread.start()

    def _run(self, coro: Any) -> Any:
        """Run a coroutine on the server loop and return its result."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=10)

    def nid(self, name: str) -> str:
        """Return the node id string for a node name in the test namespace."""
        return f"ns={self.idx};s={name}"

    def start(self) -> None:
        """Build the address space and start listening."""
        self._run(self._build())

    async def _build(self) -> None:
        """Create the server, namespace, and every node in NODES."""
        self.server = Server()
        await self.server.init()
        self.server.set_endpoint(self.endpoint)
        self.server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        self.idx = await self.server.register_namespace(NAMESPACE_URI)
        plant_obj = await self.server.nodes.objects.add_object(self.nid("Plant"), "Plant")
        for spec in NODES:
            node = await plant_obj.add_variable(
                self.nid(spec.name), spec.name, spec.initial, spec.vtype
            )
            if spec.writable:
                await node.set_writable()
            self.nodes[spec.name] = node
        await self.server.start()

    def set_node(self, name: str, value: Any) -> None:
        """Set a server-side value, keeping the node's declared VariantType."""
        variant = ua.Variant(value, SPEC_BY_NAME[name].vtype)
        self._run(self.nodes[name].write_value(ua.DataValue(variant)))

    def get_node(self, name: str) -> Any:
        """Read a server-side value."""
        return self._run(self.nodes[name].read_value())

    def reset(self) -> None:
        """Restore every node to its initial value."""
        for spec in NODES:
            self.set_node(spec.name, spec.initial)

    def stop(self) -> None:
        """Stop the server and join its loop thread."""
        if self.server is not None:
            self._run(self.server.stop())
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)
        self._loop.close()


@dataclass(frozen=True)
class Rig:
    """Test server, a valid plant map that points at it, and a plant factory."""

    server: ServerControl
    plant_map: dict[str, Any]
    make_plant: PlantFactory


def _target_entry(server: ServerControl, setpoint: str, readback: str) -> dict[str, Any]:
    """Build one plant-map target whose nodes live on the test server."""
    return {
        "setpoint_node": server.nid(setpoint),
        "readback_node": server.nid(readback),
        "mode_node": server.nid("FIC101.MODE"),
        "source_node": server.nid("FIC101.SRC"),
        "remote_value": 1,
        "local_value": 0,
        "release_value": 0,
        "mode_values": {"MAN": 0, "AUTO": 1, "CAS": 2},
    }


def make_map(server: ServerControl) -> dict[str, Any]:
    """Build a valid plant map whose nodes live on the test server."""
    return {
        "version": 1,
        "endpoint": server.endpoint,
        "heartbeat": {"node": server.nid("HB"), "period_s": 0.1, "ack_node": server.nid("HB_ACK")},
        "targets": {
            TAG: _target_entry(server, "FIC101.SP", "FIC101.PV"),
            RO_TAG: _target_entry(server, "RO.SP", "RO.SP"),
        },
    }


def _patch_target(
    plant_map: Mapping[str, Any],
    changes: Mapping[str, Any],
    drop: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return a copy of the plant map with the TAG target changed or fields dropped."""
    target = {key: val for key, val in plant_map["targets"][TAG].items() if key not in drop}
    target.update(changes)
    return {**plant_map, "targets": {**plant_map["targets"], TAG: target}}


def _proposal(tag: str, value: float, t_ns: int = 0) -> WriteProposal:
    """Build a test proposal."""
    return WriteProposal(tag, value, "test", t_ns, "test")


@pytest.fixture(scope="module")
def server() -> Iterator[ServerControl]:
    """Start one asyncua server for the module and stop it afterwards."""
    ctrl = ServerControl(get_free_port())
    try:
        ctrl.start()
        yield ctrl
    finally:
        ctrl.stop()


@pytest.fixture(autouse=True)
def reset_nodes(server: ServerControl) -> None:
    """Restore the server's nodes before each test."""
    server.reset()


async def _cancel_background_tasks() -> None:
    """Cancel and await every task on the running loop except the caller."""
    current = asyncio.current_task()
    tasks = [task for task in asyncio.all_tasks() if task is not current]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _close_plant(plant: OpcUaPlant) -> None:
    """Drain asyncua's client tasks on the plant's loop, then close the plant.

    asyncua keeps its session supervisor and renew loops alive after disconnect;
    closing the loop with them pending makes them fail with "Event loop is closed".
    """
    if not plant._loop.is_closed():
        asyncio.run_coroutine_threadsafe(_cancel_background_tasks(), plant._loop).result(timeout=5)
    plant.close()


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
def rig(server: ServerControl, make_plant: PlantFactory) -> Rig:
    """Bundle the server, a valid plant map, and the plant factory."""
    return Rig(server, make_map(server), make_plant)


def test_write_then_read_round_trip(rig: Rig) -> None:
    """A write reaches the server and a server-side value is read back."""
    plant = rig.make_plant(rig.plant_map)
    assert plant.write(TAG, 55.0) is True
    assert rig.server.get_node("FIC101.SP") == 55.0
    rig.server.set_node("FIC101.PV", 56.0)
    assert plant.read(TAG) == 56.0


def test_write_to_read_only_node_returns_false(rig: Rig) -> None:
    """A refused write returns False and leaves the server value alone."""
    plant = rig.make_plant(rig.plant_map)
    assert plant.write(RO_TAG, 99.0) is False
    assert rig.server.get_node("RO.SP") == 50.0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(2, "CAS"), (0, "MAN"), (1, "AUTO"), (7, "UNKNOWN:7")],
)
def test_loop_mode_maps_raw_values(rig: Rig, raw: int, expected: str) -> None:
    """Mapped mode values give their names; unmapped values give UNKNOWN:<raw>."""
    rig.server.set_node("FIC101.MODE", raw)
    assert rig.make_plant(rig.plant_map).loop_mode(TAG) == expected


@pytest.mark.parametrize(("raw", "expected"), [(1, "remote"), (0, "local")])
def test_setpoint_source_maps_raw_values(rig: Rig, raw: int, expected: str) -> None:
    """Source node values map to remote or local."""
    rig.server.set_node("FIC101.SRC", raw)
    assert rig.make_plant(rig.plant_map).setpoint_source(TAG) == expected


def test_release_hands_setpoint_back(rig: Rig) -> None:
    """Release writes the release value to the source node."""
    rig.server.set_node("FIC101.SRC", 1)
    rig.make_plant(rig.plant_map).release(TAG)
    assert rig.server.get_node("FIC101.SRC") == 0


def test_heartbeat_counter_is_throttled_by_period(rig: Rig) -> None:
    """A send inside the period leaves the counter alone; after the period it advances."""
    plant = rig.make_plant(rig.plant_map)
    plant.send_heartbeat()
    first = rig.server.get_node("HB")
    plant.send_heartbeat()
    assert rig.server.get_node("HB") == first
    time.sleep(0.15)
    plant.send_heartbeat()
    assert rig.server.get_node("HB") == first + 1


@pytest.mark.parametrize("ack", [True, False])
def test_heartbeat_seen_follows_ack_node(rig: Rig, ack: bool) -> None:
    """heartbeat_seen reports whatever the ack node currently holds."""
    rig.server.set_node("HB_ACK", ack)
    assert rig.make_plant(rig.plant_map).heartbeat_seen() is ack


def test_unknown_tag_raises_key_error(rig: Rig) -> None:
    """Reading a tag that is not in the plant map raises KeyError."""
    plant = rig.make_plant(rig.plant_map)
    with pytest.raises(KeyError):
        plant.read("UNKNOWN")


BAD_MAP_CASES = [
    pytest.param(lambda base: {**base, "extra": 1}, id="extra-top-level-key"),
    pytest.param(lambda base: {**base, "version": 2}, id="wrong-version"),
    pytest.param(
        lambda base: {**base, "endpoint": "http://127.0.0.1:4840"},
        id="bad-endpoint",
    ),
    pytest.param(
        lambda base: {**base, "heartbeat": {**base["heartbeat"], "period_s": 0}},
        id="zero-heartbeat-period",
    ),
    pytest.param(
        lambda base: _patch_target(base, {}, drop=("readback_node",)),
        id="missing-readback",
    ),
    pytest.param(lambda base: _patch_target(base, {"bogus": 1}), id="extra-target-key"),
    pytest.param(lambda base: _patch_target(base, {"mode_values": {}}), id="empty-mode-values"),
    pytest.param(
        lambda base: _patch_target(base, {"take_remote": {"value": 1, "bogus": 2}}),
        id="take-remote-unknown-key",
    ),
    pytest.param(
        lambda base: _patch_target(base, {"take_remote": {}}),
        id="take-remote-missing-value",
    ),
    pytest.param(
        lambda base: _patch_target(base, {"take_remote": {"value": 1, "before_setpoint": "yes"}}),
        id="take-remote-bad-before-setpoint",
    ),
]


@pytest.mark.parametrize("mutate", BAD_MAP_CASES)
def test_schema_failures_raise_plant_map_error(rig: Rig, mutate: Callable[[dict], dict]) -> None:
    """Maps that break the schema are refused before any connection is made."""
    bad_map = mutate(rig.plant_map)
    with pytest.raises(PlantMapError):
        rig.make_plant(bad_map)


@pytest.mark.parametrize("content", ["{not json", "[1, 2]"], ids=["bad-json", "not-an-object"])
def test_from_file_rejects_unreadable_content(tmp_path: Path, content: str) -> None:
    """A file that is not a JSON object raises PlantMapError."""
    path = tmp_path / "map.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(PlantMapError):
        OpcUaPlant.from_file(path)


def test_from_file_rejects_missing_file(tmp_path: Path) -> None:
    """A missing map file raises PlantMapError."""
    with pytest.raises(PlantMapError):
        OpcUaPlant.from_file(tmp_path / "absent.json")


def test_from_file_loads_valid_map(rig: Rig, tmp_path: Path) -> None:
    """A valid map file loads and reads through the server."""
    path = tmp_path / "map.json"
    path.write_text(json.dumps(rig.plant_map), encoding="utf-8")
    with OpcUaPlant.from_file(path) as plant:
        assert plant.read(TAG) == 50.0


def test_server_down_raises_within_three_seconds(rig: Rig) -> None:
    """With nothing listening, a read fails with a connection or timeout error quickly."""
    dead_map = {**rig.plant_map, "endpoint": dead_endpoint()}
    started = time.monotonic()
    with pytest.raises((ConnectionError, TimeoutError)):
        with OpcUaPlant(dead_map, timeout_s=0.5) as plant:
            plant.read(TAG)
    assert time.monotonic() - started < 3.0


def _gateway(plant: OpcUaPlant, tag: str = TAG) -> WriteGateway:
    """Build a supervised gateway with the shared policy for one tag."""
    return WriteGateway(plant, {tag: POLICY}, "supervised")


def test_e2e_propose_writes_setpoint_and_is_enabled(rig: Rig) -> None:
    """An accepted proposal writes the setpoint while remote and is enabled after readback.

    The gateway never changes the setpoint source: remote ownership is a precondition
    set by the operator, so the source must be left untouched by a proposal.
    """
    gw = _gateway(rig.make_plant(rig.plant_map))
    decision = gw.propose(_proposal(TAG, 55.0))
    assert decision.accepted
    assert rig.server.get_node("FIC101.SP") == 55.0
    assert rig.server.get_node("FIC101.SRC") == 1
    rig.server.set_node("FIC101.PV", 55.0)
    gw.tick(1)
    assert gw.status()[TAG] == "enabled"


def test_e2e_operator_takeover_gives_hold_off(rig: Rig) -> None:
    """When the operator moves the source back to local, the next tick holds off."""
    gw = _gateway(rig.make_plant(rig.plant_map))
    gw.propose(_proposal(TAG, 55.0))
    rig.server.set_node("FIC101.SRC", 0)
    gw.tick(1)
    assert gw.status()[TAG] == "hold_off"


def test_e2e_read_only_tag_is_refused(rig: Rig) -> None:
    """A proposal to a read-only setpoint is refused and the server value is unchanged."""
    gw = _gateway(rig.make_plant(rig.plant_map), RO_TAG)
    decision = gw.propose(_proposal(RO_TAG, 55.0))
    assert not decision.accepted
    assert rig.server.get_node("RO.SP") == 50.0


def test_e2e_kill_then_tick_releases_setpoint(rig: Rig) -> None:
    """After the kill switch, the next tick hands the setpoint back to local."""
    gw = _gateway(rig.make_plant(rig.plant_map))
    gw.propose(_proposal(TAG, 55.0))
    gw.kill()
    gw.tick(1)
    assert rig.server.get_node("FIC101.SRC") == 0


def test_e2e_dead_server_fails_closed(rig: Rig) -> None:
    """With the server down, a proposal is refused and the target is not enabled."""
    dead_map = {**rig.plant_map, "endpoint": dead_endpoint()}
    gw = _gateway(rig.make_plant(dead_map, timeout_s=0.5))
    decision = gw.propose(_proposal(TAG, 55.0))
    assert not decision.accepted
    assert gw.status()[TAG] != "enabled"


def test_take_remote_writes_source_before_setpoint(rig: Rig) -> None:
    """A take_remote entry puts the source into remote, so the setpoint write succeeds."""
    rig.server.set_node("FIC101.SRC", 0)
    plant = rig.make_plant(_patch_target(rig.plant_map, {"take_remote": {"value": 1}}))
    assert plant.write(TAG, 55.0) is True
    assert rig.server.get_node("FIC101.SRC") == 1
    assert plant.setpoint_source(TAG) == "remote"


def test_e2e_take_remote_gives_enabled(rig: Rig) -> None:
    """With take_remote the engine sees remote ownership and the proposal is enabled."""
    rig.server.set_node("FIC101.SRC", 0)
    plant = rig.make_plant(_patch_target(rig.plant_map, {"take_remote": {"value": 1}}))
    gw = _gateway(plant)
    assert gw.propose(_proposal(TAG, 55.0)).accepted
    rig.server.set_node("FIC101.PV", 55.0)
    gw.tick(1)
    assert gw.status()[TAG] == "enabled"


def test_e2e_without_take_remote_gives_hold_off(rig: Rig) -> None:
    """Without take_remote the source stays local, so the engine holds off."""
    rig.server.set_node("FIC101.SRC", 0)
    gw = _gateway(rig.make_plant(rig.plant_map))
    gw.propose(_proposal(TAG, 55.0))
    rig.server.set_node("FIC101.PV", 55.0)
    gw.tick(1)
    assert gw.status()[TAG] == "hold_off"


def test_take_remote_refused_blocks_setpoint(rig: Rig) -> None:
    """A refused take_remote write returns False and the setpoint is not written."""
    take = {"node": rig.server.nid(RO_TAG), "value": 1}
    plant = rig.make_plant(_patch_target(rig.plant_map, {"take_remote": take}))
    assert plant.write(TAG, 55.0) is False
    assert rig.server.get_node("FIC101.SP") == 50.0


def test_take_remote_after_setpoint_writes_both(rig: Rig) -> None:
    """With before_setpoint false the setpoint and the source are both written."""
    rig.server.set_node("FIC101.SRC", 0)
    take = {"value": 1, "before_setpoint": False}
    plant = rig.make_plant(_patch_target(rig.plant_map, {"take_remote": take}))
    assert plant.write(TAG, 55.0) is True
    assert rig.server.get_node("FIC101.SP") == 55.0
    assert rig.server.get_node("FIC101.SRC") == 1


def test_take_remote_after_setpoint_refused_restores_setpoint(rig: Rig) -> None:
    """With before_setpoint false a refused take restores the previous setpoint."""
    take = {"node": rig.server.nid(RO_TAG), "value": 1, "before_setpoint": False}
    plant = rig.make_plant(_patch_target(rig.plant_map, {"take_remote": take}))
    assert plant.write(TAG, 55.0) is False
    assert rig.server.get_node("FIC101.SP") == 50.0


def test_take_remote_after_setpoint_restore_failure_is_state_unknown(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the take is refused and the restore fails too, the write state is unknown."""
    take = {"node": rig.server.nid(RO_TAG), "value": 1, "before_setpoint": False}
    plant = rig.make_plant(_patch_target(rig.plant_map, {"take_remote": take}))
    calls: list[float] = []
    original = plant._write_setpoint

    def flaky(target: Mapping[str, Any], value: float) -> bool:
        calls.append(value)
        if len(calls) > 1:
            raise ConnectionError("down")
        return original(target, value)

    monkeypatch.setattr(plant, "_write_setpoint", flaky)
    with pytest.raises(ConnectionError, match="write_state_unknown"):
        plant.write(TAG, 55.0)
    assert rig.server.get_node("FIC101.SP") == 55.0


def test_take_remote_after_setpoint_restore_refused_is_state_unknown(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restore the server refuses (False) also raises write_state_unknown."""
    take = {"node": rig.server.nid(RO_TAG), "value": 1, "before_setpoint": False}
    plant = rig.make_plant(_patch_target(rig.plant_map, {"take_remote": take}))
    original = plant._write_setpoint
    seen: list[float] = []

    def refusing(target: Mapping[str, Any], value: float) -> bool:
        seen.append(value)
        return original(target, value) if len(seen) == 1 else False

    monkeypatch.setattr(plant, "_write_setpoint", refusing)
    with pytest.raises(ConnectionError, match="write_state_unknown"):
        plant.write(TAG, 55.0)


def test_take_remote_before_setpoint_unchanged_when_take_refused(rig: Rig) -> None:
    """With before_setpoint true a refused take writes nothing and needs no restore."""
    take = {"node": rig.server.nid(RO_TAG), "value": 1, "before_setpoint": True}
    plant = rig.make_plant(_patch_target(rig.plant_map, {"take_remote": take}))
    assert plant.write(TAG, 55.0) is False
    assert rig.server.get_node("FIC101.SP") == 50.0


def test_strict_compare_rejects_bool_for_int_remote_value(rig: Rig) -> None:
    """An integer remote_value never matches a boolean source value, and vice versa."""
    source = rig.server.nid("HB_ACK")
    as_int = rig.make_plant(
        _patch_target(rig.plant_map, {"source_node": source, "remote_value": 1})
    )
    as_bool = rig.make_plant(
        _patch_target(rig.plant_map, {"source_node": source, "remote_value": True})
    )
    assert as_int.setpoint_source(TAG) == "local"
    assert as_bool.setpoint_source(TAG) == "remote"


def test_loop_mode_rejects_bool_for_int_mode_value(rig: Rig) -> None:
    """A boolean raw mode value does not match an integer mode_values entry."""
    changes = {"mode_node": rig.server.nid("HB_ACK"), "mode_values": {"ON": 1, "OFF": 0}}
    plant = rig.make_plant(_patch_target(rig.plant_map, changes))
    assert plant.loop_mode(TAG).startswith("UNKNOWN")


def test_take_remote_settle_waits_before_setpoint(rig: Rig) -> None:
    """settle_s delays the setpoint write after the take, and the write still succeeds."""
    take = {"value": 1, "settle_s": 0.3}
    plant = rig.make_plant(_patch_target(rig.plant_map, {"take_remote": take}))
    started = time.monotonic()
    assert plant.write(TAG, 55.0) is True
    assert time.monotonic() - started >= 0.3
    assert rig.server.get_node("FIC101.SP") == 55.0


def test_take_remote_negative_settle_is_a_schema_error(rig: Rig) -> None:
    """A negative settle_s is refused by the plant-map schema."""
    take = {"value": 1, "settle_s": -1}
    with pytest.raises(PlantMapError):
        rig.make_plant(_patch_target(rig.plant_map, {"take_remote": take}))

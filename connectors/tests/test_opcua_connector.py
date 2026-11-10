"""Tests for the OPC UA connector adapter against PlantServer (Phase 1, #43).

Verifies connect, hierarchical browsing, and live sampling against an active test server.
Runs the simulated PlantServer in a dedicated background thread so synchronous
connector client operations can talk to it over TCP without deadlock.
"""

from __future__ import annotations

import asyncio
import socket
import threading

import pytest
from crosscut_connectors.base import CAP_BROWSE, CAP_METADATA, CAP_READ_LIVE, LiveValue
from crosscut_connectors.opcua_connector import OpcUaConnector
from crosscut_opcua.server import PlantServer, ServerConfig
from crosscut_sim.plants.wood_berry import WoodBerryPlant
from crosscut_sim.scenarios import Scenario

from tests import OPCUA_SERVER_START_TIMEOUT_S

SERVER_TIMEOUT_S = 10.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def opcua_server():
    port = _free_port()
    server = PlantServer(
        WoodBerryPlant(),
        Scenario(measurement_noise=0.1),
        ServerConfig(
            seed=42,
            host="127.0.0.1",
            port=port,
            speed=20.0,
            tick_s=0.05,
            heartbeat_timeout_s=SERVER_TIMEOUT_S,
        ),
    )
    endpoint = f"opc.tcp://127.0.0.1:{port}"

    loop = asyncio.new_event_loop()
    ready_evt = threading.Event()
    stop_evt = threading.Event()

    def _server_thread() -> None:
        asyncio.set_event_loop(loop)

        async def _runner() -> None:
            async with server:
                ready_evt.set()
                while not stop_evt.is_set():
                    await asyncio.sleep(0.05)

        loop.run_until_complete(_runner())
        loop.close()

    t = threading.Thread(target=_server_thread, daemon=True)
    t.start()
    assert ready_evt.wait(timeout=OPCUA_SERVER_START_TIMEOUT_S), (
        "PlantServer failed to start in time"
    )

    try:
        yield server, endpoint
    finally:
        stop_evt.set()
        t.join(timeout=5.0)


def test_opcua_connector_browse_and_read_live(opcua_server: tuple[PlantServer, str]) -> None:
    _server, endpoint = opcua_server
    conn = OpcUaConnector(endpoint)
    caps = conn.capabilities()
    assert {CAP_BROWSE, CAP_METADATA, CAP_READ_LIVE} <= caps

    # 1. Browse root / objects
    root_nodes = conn.browse()
    assert len(root_nodes) > 0
    # PlantServer creates 'Plant' object under Objects
    plant_node = next(
        (n for n in root_nodes if "Plant" in n.name or "Objects" in n.name),
        root_nodes[0],
    )

    # Browse child nodes under Objects/Plant
    children = conn.browse(node_id=plant_node.id)
    assert len(children) > 0

    # 2. Read live tags
    var_nodes = [n for n in children if n.node_type == "variable"]
    if not var_nodes:
        # Browse one level deeper if plant_node was Objects
        deeper = conn.browse(node_id=children[0].id)
        var_nodes = [n for n in deeper if n.node_type == "variable"]

    assert len(var_nodes) > 0
    target_ids = [var_nodes[0].id]
    live_data = conn.read_live(target_ids)
    assert target_ids[0] in live_data
    live_val = live_data[target_ids[0]]
    assert isinstance(live_val, LiveValue)
    assert live_val.value is not None
    assert live_val.quality == 0  # GOOD
    assert live_val.timestamp_utc.endswith("Z") or "+" in live_val.timestamp_utc

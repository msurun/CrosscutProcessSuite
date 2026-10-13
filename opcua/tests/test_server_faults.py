"""A DCS client sees the effect of a plant fault over OPC UA, never the fault itself."""

from __future__ import annotations

import asyncio

from asyncua import Client
from crosscut_opcua.server import NAMESPACE_URI, PlantServer, ServerConfig
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario

PRESS = "sim.mc.hpgr_press"
PRESS_SP = "sim.mc.hpgr_press_sp"
SETPOINT_STEP = 1.0
SPEED = 200.0


def _stiction_server() -> PlantServer:
    scenario = build_scenario("mill_circuit", "stiction", duration_s=24 * 3600.0)
    config = ServerConfig(seed=1, port=_free_port(), speed=SPEED, tick_s=0.05)
    return PlantServer(MillCircuitPlant(), scenario, config)


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _step_the_setpoint_and_read_the_press() -> tuple[float, float, list[str]]:
    async with _stiction_server() as server, Client(server.endpoint) as client:
        idx = await client.get_namespace_index(NAMESPACE_URI)
        press = client.get_node(f"ns={idx};s={PRESS}")
        setpoint = client.get_node(f"ns={idx};s={PRESS_SP}")
        before = await press.read_value()
        await setpoint.write_value(before + SETPOINT_STEP)
        await asyncio.sleep(1.5)
        after = await press.read_value()
        children = await client.get_node(f"ns={idx};s=Plant").get_children()
        return before, after, [child.nodeid.Identifier for child in children]


def test_the_loop_reacts_to_a_setpoint_step_on_a_plant_with_stiction() -> None:
    before, after, _ = asyncio.run(asyncio.wait_for(_step_the_setpoint_and_read_the_press(), 30))
    assert after != before


def test_the_ground_truth_of_the_fault_is_not_visible_to_the_client() -> None:
    *_, node_ids = asyncio.run(asyncio.wait_for(_step_the_setpoint_and_read_the_press(), 30))
    assert not [node_id for node_id in node_ids if "stiction" in str(node_id)]

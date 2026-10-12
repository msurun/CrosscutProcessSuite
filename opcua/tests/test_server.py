"""Integration tests for the OPC UA test server that exposes a simulated plant."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from asyncua import Client
from crosscut_opcua.server import (
    HEARTBEAT_OK_TAG,
    HEARTBEAT_TAG,
    NAMESPACE_URI,
    TIME_TAG,
    PlantServer,
)
from crosscut_sim.core import AUTO, CAS, Scenario
from crosscut_sim.plants.wood_berry import NOMINAL, WoodBerryPlant

TOP, TOP_SP, TOP_RSP, TOP_MODE = (
    "sim.wb.top_comp",
    "sim.wb.top_comp_sp",
    "sim.wb.top_comp_rsp",
    "sim.wb.top_comp_mode",
)
REFLUX = "sim.wb.reflux"


def free_port() -> int:
    """Return a port number that is currently free on localhost."""
    with socket.socket() as probe_socket:
        probe_socket.bind(("127.0.0.1", 0))
        return int(probe_socket.getsockname()[1])


def serve(
    body: Callable[[PlantServer, Client, Callable[[str], Any]], Awaitable[None]],
    *,
    heartbeat_timeout_s: float = 5.0,
    speed: float = 100.0,
) -> None:
    """Run ``body(server, client, node)`` against a started server; ``node(tag)`` gets a node."""

    asyncio.run(asyncio.wait_for(_serve_async(body, heartbeat_timeout_s, speed), timeout=30))


def _make_server(heartbeat_timeout_s: float, speed: float) -> PlantServer:
    """Build an unstarted ``PlantServer`` bound to a free localhost port."""

    plant = WoodBerryPlant()
    return PlantServer(
        plant,
        Scenario(measurement_noise=0.0),
        seed=1,
        host="127.0.0.1",
        port=free_port(),
        speed=speed,
        tick_s=0.05,
        heartbeat_timeout_s=heartbeat_timeout_s,
    )


async def _serve_async(
    body: Callable[[PlantServer, Client, Callable[[str], Any]], Awaitable[None]],
    heartbeat_timeout_s: float,
    speed: float,
) -> None:
    """Start the server and client, then hand both plus ``node`` to ``body``."""

    server = _make_server(heartbeat_timeout_s, speed)
    async with server:
        async with Client(server.endpoint) as client:
            node = await _make_node_factory(client)
            await body(server, client, node)


async def _make_node_factory(client: Client) -> Callable[[str], Any]:
    """Return ``node(tag)`` resolving ``tag`` against the client's namespace index."""

    idx = await client.get_namespace_index(NAMESPACE_URI)

    def node(tag: str) -> Any:
        """Return the OPC UA node with the given string identifier from this namespace."""
        return client.get_node(f"ns={idx};s={tag}")

    return node


def test_all_tags_are_exposed_with_initial_values() -> None:
    async def body(server: PlantServer, client: Client, node: Callable[[str], Any]) -> None:
        """Check every tag is readable and key plant values match the expected state."""
        for tag_id in server.plant.tags.ids():
            value = await node(tag_id).read_value()
            assert isinstance(value, float)
        assert await node(TOP).read_value() == pytest.approx(NOMINAL["top_comp"], abs=0.01)
        assert await node(HEARTBEAT_TAG).read_value() == 0
        assert await node(HEARTBEAT_OK_TAG).read_value() is True
        assert await node(TIME_TAG).read_value() >= 0.0

    serve(body)


def test_simulation_advances_faster_than_real_time() -> None:
    async def body(server: PlantServer, client: Client, node: Callable[[str], Any]) -> None:
        """Check the plant clock advances about 60 s while the test sleeps 0.6 s."""
        t0 = await node(TIME_TAG).read_value()
        await asyncio.sleep(0.6)
        t1 = await node(TIME_TAG).read_value()
        assert t1 - t0 > 10.0  # speed 100x -> about 60 s of plant time
        assert server.plant.time_s >= t1

    serve(body)


def test_writing_a_setpoint_reaches_the_plant() -> None:
    async def body(server: PlantServer, client: Client, node: Callable[[str], Any]) -> None:
        """Write 97.25 to TOP_SP and check both sides read it back."""
        await node(TOP_SP).write_value(97.25)
        await asyncio.sleep(0.3)
        assert server.plant.read(TOP_SP)[0] == pytest.approx(97.25)
        assert await node(TOP_SP).read_value() == pytest.approx(97.25)

    serve(body)


def test_read_only_tags_cannot_be_written() -> None:
    async def body(server: PlantServer, client: Client, node: Callable[[str], Any]) -> None:
        """Verify that the top and heartbeat nodes reject writes from this client."""
        with pytest.raises(Exception):  # noqa: B017 - asyncua raises UaStatusCodeError (BadNotWritable)
            await node(TOP).write_value(90.0)
        with pytest.raises(Exception):  # noqa: B017
            await node(HEARTBEAT_OK_TAG).write_value(False)

    serve(body)


def test_writes_rejected_by_the_plant_are_reverted() -> None:
    async def body(server: PlantServer, client: Client, node: Callable[[str], Any]) -> None:
        """Check that a node in AUTO mode cannot override a value written in MAN mode."""
        # the output can only be written in MAN; the loop is in AUTO
        await node(REFLUX).write_value(3.0)
        await asyncio.sleep(0.3)
        assert server.plant.read(REFLUX)[0] != pytest.approx(3.0)
        assert await node(REFLUX).read_value() == pytest.approx(
            server.plant.read(REFLUX)[0], abs=0.2
        )

    serve(body)


def test_heartbeat_keeps_cascade_alive_and_its_loss_returns_control_to_the_dcs() -> None:
    async def body(server: PlantServer, client: Client, node: Callable[[str], Any]) -> None:
        """Drive the watchdog through healthy heartbeats, a lost counter, and recovery."""
        await _drive_healthy_heartbeats_into_cascade(node, server)

        await asyncio.sleep(1.2)  # the counter stops
        assert await node(HEARTBEAT_OK_TAG).read_value() is False
        assert server.plant.read(TOP_MODE)[0] == AUTO  # DCS took the loop back
        sp_after_loss = server.plant.read(TOP_SP)[0]
        await node(TOP_RSP).write_value(95.0)  # the remote setpoint is ignored now
        await asyncio.sleep(0.3)
        assert server.plant.read(TOP_SP)[0] == pytest.approx(sp_after_loss)

        await node(HEARTBEAT_TAG).write_value(99)  # a moving counter restores the status
        await asyncio.sleep(0.2)
        assert await node(HEARTBEAT_OK_TAG).read_value() is True

    serve(body, heartbeat_timeout_s=0.6)


async def _drive_healthy_heartbeats_into_cascade(
    node: Callable[[str], Any], server: PlantServer
) -> None:
    """Put the loop in cascade and feed heartbeats faster than the 0.6 s timeout."""
    await node(TOP_RSP).write_value(97.0)
    await node(TOP_MODE).write_value(float(CAS))
    for k in range(1, 11):  # 1.0 s of healthy heartbeats, longer than the 0.6 s timeout
        await node(HEARTBEAT_TAG).write_value(k)
        await asyncio.sleep(0.1)
    assert await node(HEARTBEAT_OK_TAG).read_value() is True
    assert server.plant.read(TOP_MODE)[0] == CAS
    assert server.plant.read(TOP_SP)[0] == pytest.approx(97.0)


def test_server_stops_cleanly() -> None:
    async def main() -> None:
        """Start a plant server on a free port; clients cannot connect after it stops."""
        port = free_port()
        server = PlantServer(
            WoodBerryPlant(),
            Scenario(),
            seed=1,
            host="127.0.0.1",
            port=port,
            speed=10.0,
            tick_s=0.05,
            heartbeat_timeout_s=5.0,
        )
        async with server:
            assert server.endpoint.endswith(f":{port}")
        with pytest.raises(Exception):  # noqa: B017
            async with Client(server.endpoint, timeout=1):
                pass

    asyncio.run(asyncio.wait_for(main(), timeout=30))

"""OPC UA connector cycle snapshot: one batch read, reused session, comm loss and recovery.

The plant test server runs in a background thread so it can be stopped and restarted on the same
port while the connector keeps its session object.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from asyncua import Client
from crosscut_connectors.base import Snapshot, SnapshotConnector
from crosscut_connectors.opcua_connector import OpcUaConnector
from crosscut_opcua.server import NAMESPACE_URI
from test_opcua_import import TAG_Y1, free_port, make_server

OPCUA_SERVER_START_TIMEOUT_S = 30.0
TAG = f"nsu={NAMESPACE_URI};s={TAG_Y1}"
MISSING_TAG = "nsu=urn:not-there;s=Nothing"
BACKOFF_S = 10.0


@dataclass
class ServerHandle:
    """A plant server in a thread that can be stopped (once) from the test."""

    port: int
    stop_evt: threading.Event = field(default_factory=threading.Event)
    ready_evt: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the server and wait until it accepts connections."""
        self.stop_evt.clear()
        self.ready_evt.clear()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        assert self.ready_evt.wait(OPCUA_SERVER_START_TIMEOUT_S), "server did not start"

    def stop(self) -> None:
        """Stop the server and wait for its thread."""
        self.stop_evt.set()
        if self.thread is not None:
            self.thread.join(timeout=10.0)

    def _serve(self) -> None:
        async def runner() -> None:
            async with make_server(self.port):
                self.ready_evt.set()
                while not self.stop_evt.is_set():
                    await asyncio.sleep(0.05)

        asyncio.run(runner())


class FakeClock:
    """A manually advanced clock for the reconnect back-off."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def server() -> Iterator[ServerHandle]:
    handle = ServerHandle(free_port())
    handle.start()
    try:
        yield handle
    finally:
        handle.stop()


def _connector(server: ServerHandle, clock: FakeClock) -> OpcUaConnector:
    endpoint = f"opc.tcp://127.0.0.1:{server.port}"
    return OpcUaConnector(endpoint, reconnect_min_s=BACKOFF_S, clock=clock)


def test_snapshot_is_good_with_one_cycle_time(server: ServerHandle) -> None:
    with _connector(server, FakeClock()) as conn:
        assert isinstance(conn, SnapshotConnector)
        snap = conn.read_snapshot([TAG, MISSING_TAG])
    assert isinstance(snap, Snapshot)
    assert snap.comm_ok and snap.reason is None
    assert snap.values[TAG].quality == 0 and snap.values[TAG].value is not None
    assert snap.values[MISSING_TAG].quality == 2 and snap.values[MISSING_TAG].value is None
    assert snap.values[MISSING_TAG].timestamp_utc == snap.cycle_utc


def test_one_batch_read_per_snapshot(server: ServerHandle, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    original = Client.read_attributes

    async def spy(self: Client, nodes, attr=None):  # type: ignore[no-untyped-def]
        calls.append(len(list(nodes)))
        return await original(self, nodes, attr) if attr else await original(self, nodes)

    monkeypatch.setattr(Client, "read_attributes", spy)
    with _connector(server, FakeClock()) as conn:
        conn.read_snapshot([TAG, TAG.replace(TAG_Y1, "y2")])
        conn.read_snapshot([TAG])
    assert len(calls) == 2


def test_session_is_reused_across_snapshots(
    server: ServerHandle, monkeypatch: pytest.MonkeyPatch
) -> None:
    connects: list[int] = []
    original = Client.connect

    async def spy(self: Client):  # type: ignore[no-untyped-def]
        connects.append(1)
        return await original(self)

    monkeypatch.setattr(Client, "connect", spy)
    with _connector(server, FakeClock()) as conn:
        first = conn.read_snapshot([TAG])
        second = conn.read_snapshot([TAG])
    assert first.comm_ok and second.comm_ok
    assert len(connects) == 1


def test_comm_loss_does_not_raise_and_recovers_after_backoff(server: ServerHandle) -> None:
    clock = FakeClock()
    with _connector(server, clock) as conn:
        assert conn.read_snapshot([TAG]).comm_ok
        server.stop()
        lost = conn.read_snapshot([TAG])
        assert not lost.comm_ok and lost.reason == "comm_loss"
        assert lost.values[TAG].quality == 2
        server.start()
        assert not conn.read_snapshot([TAG]).comm_ok  # still inside the back-off window
        clock.now += BACKOFF_S + 1.0
        recovered = conn.read_snapshot([TAG])
    assert recovered.comm_ok and recovered.values[TAG].quality == 0


def test_to_live_value_keeps_uncertain_quality() -> None:
    """An Uncertain StatusCode stays quality 1 in a snapshot, as in read_live."""
    from asyncua import ua
    from crosscut_connectors.opcua_session import to_live_value

    data_value = ua.DataValue(
        ua.Variant(1.5, ua.VariantType.Double), ua.StatusCode(ua.StatusCodes.UncertainLastUsableValue)
    )
    assert to_live_value(data_value, "2026-11-10T00:00:00+00:00").quality == 1

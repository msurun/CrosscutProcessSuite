"""Adapt an existing async OPC UA session to the read connector boundary.

The async extension retains native DataValues for legacy quality policies and the
collector's atomic clock-and-tags batch; it never exposes a write operation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Protocol

from asyncua import Client, ua
from asyncua.common.node import Node

from crosscut_connectors.base import LiveValue, NotSupportedError
from crosscut_connectors.opcua_connector import TIMEOUT_S, OpcUaConnector


class AsyncOpcUaReads(Protocol):
    """Optional native reads for acquisition running on an existing event loop."""

    async def read_raw(self, node_id: str) -> ua.DataValue:
        """Read one native value without changing its timestamp or quality."""
        ...

    async def read_raw_batch(self, nodes: Sequence[Node]) -> list[ua.DataValue]:
        """Read a consistent group of native values in one server request."""
        ...


class OpcUaSessionConnector(OpcUaConnector):
    """Read connector bound to the caller's connected asyncua session and loop."""

    def __init__(self, client: Client) -> None:
        """Reuse a client without opening another connection or event loop."""
        super().__init__(str(getattr(client, "server_url", "")))
        self.session = client
        self._session_loop = asyncio.get_running_loop()

    async def connect_async(self) -> None:
        """Open the session, preserving the legacy connection exception contract."""
        try:
            await self.session.connect()
        except (TimeoutError, OSError, ua.UaError, ua.UaStatusCodeError) as error:
            message = f"could not connect to {self.session.server_url}: {error}"
            raise ConnectionError(message) from error

    async def disconnect_async(self) -> None:
        """Close the session, tolerating transport failures during cleanup."""
        try:
            await self.session.disconnect()
        except (OSError, ua.UaError):
            pass

    def read_live(self, tag_ids: Sequence[str]) -> dict[str, LiveValue]:
        """Read from another thread; async callers must await ``read_live_async``."""
        try:
            caller_loop = asyncio.get_running_loop()
        except RuntimeError:
            caller_loop = None
        if caller_loop is self._session_loop:
            raise NotSupportedError("On the session loop, await read_live_async(tag_ids) instead")
        future = asyncio.run_coroutine_threadsafe(self.read_live_async(tag_ids), self._session_loop)
        return future.result(TIMEOUT_S)

    async def read_live_async(self, tag_ids: Sequence[str]) -> dict[str, LiveValue]:
        """Read live values on the bound session without opening another client."""
        from crosscut_connectors.opcua_session import now_iso, to_live_value

        return {tag: to_live_value(await self.read_raw(tag), now_iso()) for tag in tag_ids}

    async def read_raw(self, node_id: str) -> ua.DataValue:
        """Read one native DataValue for the caller's existing quality policy."""
        return await self.session.get_node(node_id).read_data_value()

    async def read_raw_batch(self, nodes: Sequence[Node]) -> list[ua.DataValue]:
        """Read all values atomically, preserving input order and native qualities."""
        return await self.session.read_attributes(list(nodes), ua.AttributeIds.Value)

    async def browse_nodes(self, parent: Node | None = None) -> list[Node]:
        """Browse root objects or the variables under an existing parent node."""
        if parent is None:
            return await self.session.nodes.objects.get_children()
        return await self.browse_variables(parent)

    @staticmethod
    async def browse_variables(parent: Node) -> list[Node]:
        """Browse variable children through the same read-only session boundary."""
        return await parent.get_children(nodeclassmask=ua.NodeClass.Variable)

    async def subscribe_nodes(self, node_ids: Sequence[str], settings: tuple[int, Any]) -> Any:
        """Subscribe to native changes using a publishing period in milliseconds."""
        period_ms, handler = settings
        subscription = await self.session.create_subscription(period_ms, handler)
        await subscription.subscribe_data_change([self.session.get_node(tag) for tag in node_ids])
        return subscription

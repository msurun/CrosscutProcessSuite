"""OPC UA industrial protocol connector adapter (Phase 1, #43).

Provides live node sampling, hierarchical address-space browsing, and subscription handling.
HistoryRead is not supported and writing to control systems is strictly forbidden (ADR 012).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from asyncua import Client, ua

from crosscut_connectors.base import (
    CAP_BROWSE,
    CAP_METADATA,
    CAP_READ_LIVE,
    CAP_SUBSCRIBE,
    Connector,
    LiveValue,
    NodeInfo,
    NotSupportedError,
    Snapshot,
    SourceConnectionError,
    TagMetadata,
)
from crosscut_connectors.opcua_import import quality_from_status, resolve_node_id
from crosscut_connectors.opcua_session import LoopThread, bad_value, now_iso, snapshot_async

TIMEOUT_S = 5.0


class OpcUaConnector(Connector):
    """OPC UA read-only client adapter."""

    def __init__(
        self,
        endpoint: str,
        options: Mapping[str, Any] | None = None,
        reconnect_min_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.endpoint = endpoint
        self.options = dict(options or {})
        self._reconnect_min_s = reconnect_min_s
        self._clock = clock
        self._next_attempt = 0.0
        self._loop: LoopThread | None = None
        self._client: Client | None = None

    def __enter__(self) -> OpcUaConnector:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the persistent session and stop its event-loop thread."""
        if self._loop is None:
            return
        self._drop_session()
        self._loop.stop()
        self._loop = None

    def read_snapshot(self, tag_ids: Sequence[str]) -> Snapshot:
        """Sample all tags in one batch on a reused session; comm loss never raises."""
        cycle = now_iso()
        tags = list(tag_ids)
        if self._clock() < self._next_attempt:
            return _comm_loss(tags, cycle)
        try:
            values = self._ensure_loop().run(self._snapshot(tags, cycle), 2 * TIMEOUT_S)
        except (OSError, ua.UaError, TimeoutError, SourceConnectionError):
            self._drop_session()
            self._next_attempt = self._clock() + self._reconnect_min_s
            return _comm_loss(tags, cycle)
        return Snapshot(cycle_utc=cycle, values=values, comm_ok=True)

    def _ensure_loop(self) -> LoopThread:
        """Start the session event-loop thread on first use."""
        if self._loop is None:
            self._loop = LoopThread()
        return self._loop

    async def _snapshot(self, tags: list[str], cycle: str) -> dict[str, LiveValue]:
        """Connect lazily, then batch-read the tags."""
        if self._client is None:
            client = Client(url=self.endpoint, timeout=TIMEOUT_S)
            await client.connect()
            self._client = client
        return await snapshot_async(self._client, tags, cycle)

    def _drop_session(self) -> None:
        """Forget the session (best-effort disconnect) so the next call reconnects."""
        client, self._client = self._client, None
        if client is None or self._loop is None:
            return
        try:
            self._loop.run(_safe_disconnect(client), TIMEOUT_S)
        except (OSError, ua.UaError, TimeoutError):
            pass

    def capabilities(self) -> set[str]:
        """Declare supported capabilities."""
        return {CAP_BROWSE, CAP_METADATA, CAP_READ_LIVE, CAP_SUBSCRIBE}

    def browse(self, node_id: str | None = None) -> list[NodeInfo]:
        """Browse address space nodes starting at Objects or given parent."""
        return _run_sync(self._browse_async(node_id))

    async def _browse_async(self, node_id: str | None) -> list[NodeInfo]:
        """Connect and inspect child nodes in the OPC UA address space."""
        client = Client(url=self.endpoint, timeout=TIMEOUT_S)
        try:
            await client.connect()
            target = client.nodes.objects if not node_id else client.get_node(node_id)
            children = await target.get_children()
            return [await _node_to_info(child) for child in children]
        except (OSError, ua.UaError) as error:
            raise SourceConnectionError(f"OPC UA browse failed: {error}") from error
        finally:
            await _safe_disconnect(client)

    def metadata(self, tag_ids: Sequence[str]) -> list[TagMetadata]:
        """Fetch engineering descriptions and units for node identifiers."""
        return [TagMetadata(id=tag) for tag in tag_ids]

    def history(
        self,
        tag_ids: Sequence[str],
        start_utc: str,
        end_utc: str,
        period_s: float | None = None,
    ) -> Mapping[str, Any]:
        """OPC UA servers do not expose HistoryRead without specialised configuration."""
        raise NotSupportedError("OPC UA connector does not support HistoryRead")

    def read_live(self, tag_ids: Sequence[str]) -> dict[str, LiveValue]:
        """Sample current node values and OPC UA status codes."""
        return _run_sync(self._read_live_async(tag_ids))

    async def _read_live_async(self, tag_ids: Sequence[str]) -> dict[str, LiveValue]:
        """Connect and read live DataValues for all requested tags."""
        client = Client(url=self.endpoint, timeout=TIMEOUT_S)
        try:
            await client.connect()
            result: dict[str, LiveValue] = {}
            for tag in tag_ids:
                result[tag] = await _sample_single_node(client, tag)
            return result
        except (OSError, ua.UaError) as error:
            raise SourceConnectionError(f"OPC UA live read failed: {error}") from error
        finally:
            await _safe_disconnect(client)


def _comm_loss(tags: Sequence[str], cycle: str) -> Snapshot:
    """Snapshot for an unreachable source: every value bad."""
    values = {tag: bad_value(cycle) for tag in tags}
    return Snapshot(cycle_utc=cycle, values=values, comm_ok=False, reason="comm_loss")


async def _node_to_info(node: Any) -> NodeInfo:
    """Extract browse name and classification from an asyncua node."""
    bname = await node.read_browse_name()
    nclass = await node.read_node_class()
    is_var = nclass == ua.NodeClass.Variable
    node_type = "variable" if is_var else "object"
    node_id_str = node.nodeid.to_string() if hasattr(node.nodeid, "to_string") else str(node.nodeid)
    return NodeInfo(
        id=node_id_str,
        name=bname.Name,
        node_type=node_type,
        has_children=not is_var,
    )


async def _sample_single_node(client: Client, tag: str) -> LiveValue:
    """Read a single DataValue, translate status to quality, and return LiveValue."""
    try:
        node_id = await resolve_node_id(client, tag)
        dv = await client.get_node(node_id).read_data_value()
        val = float(dv.Value.Value) if isinstance(dv.Value.Value, (int, float)) else None
        qual = quality_from_status(dv.StatusCode)
        ts = dv.SourceTimestamp.isoformat() if dv.SourceTimestamp else datetime.now(UTC).isoformat()
        return LiveValue(value=val, quality=qual, timestamp_utc=ts)
    except Exception:
        now = datetime.now(UTC).isoformat()
        return LiveValue(value=None, quality=2, timestamp_utc=now)


async def _safe_disconnect(client: Client) -> None:
    """Disconnect client silently, suppressing network socket closure errors."""
    try:
        await client.disconnect()
    except (OSError, ua.UaError):
        pass


def _run_sync(coroutine: Any) -> Any:
    """Execute an async coroutine synchronously, supporting invocation inside running loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()

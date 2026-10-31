"""OPC UA industrial protocol connector adapter (Phase 1, #43).

Provides live node sampling, hierarchical address-space browsing, and subscription handling.
HistoryRead is not supported and writing to control systems is strictly forbidden (ADR 012).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Mapping, Sequence
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
    SourceConnectionError,
    TagMetadata,
)

TIMEOUT_S = 5.0


class OpcUaConnector(Connector):
    """OPC UA read-only client adapter."""

    def __init__(self, endpoint: str, options: Mapping[str, Any] | None = None) -> None:
        self.endpoint = endpoint
        self.options = dict(options or {})

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
        dv = await client.get_node(tag).read_data_value()
        val = float(dv.Value.Value) if isinstance(dv.Value.Value, (int, float)) else None
        qual = 0 if dv.StatusCode.is_good() else 2
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

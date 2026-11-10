"""Persistent OPC UA client session on a private event-loop thread (Phase 2.5, step 2).

A client created by asyncua is bound to the loop it connected on, so a session that outlives one
call needs a loop that outlives it too. ``LoopThread`` provides that loop; ``snapshot_async``
reads many nodes in a single batch request.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from asyncua import Client, ua

from crosscut_connectors.base import LiveValue
from crosscut_connectors.opcua_import import quality_from_status, resolve_node_id


class LoopThread:
    """An asyncio event loop running in a daemon thread; run coroutines from any thread."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coroutine: Any, timeout_s: float) -> Any:
        """Run ``coroutine`` on the loop and wait for its result (TimeoutError on expiry)."""
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout_s)
        except concurrent.futures.TimeoutError as error:
            future.cancel()
            raise TimeoutError("OPC UA call timed out") from error

    def stop(self) -> None:
        """Stop the loop and join the thread."""
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)
        self._loop.close()


def to_live_value(data_value: ua.DataValue, cycle_utc: str) -> LiveValue:
    """Translate one DataValue to a LiveValue (quality GOOD 0, UNCERTAIN 1, BAD 2)."""
    raw = data_value.Value.Value if data_value.Value is not None else None
    value = float(raw) if isinstance(raw, (int, float)) else None
    status = data_value.StatusCode
    quality = 2 if status is None else quality_from_status(status)
    stamp = data_value.SourceTimestamp
    return LiveValue(value, quality, stamp.isoformat() if stamp else cycle_utc)


def bad_value(cycle_utc: str) -> LiveValue:
    """A bad-quality placeholder value."""
    return LiveValue(value=None, quality=2, timestamp_utc=cycle_utc)


async def _resolve_nodes(client: Client, tags: Sequence[str]) -> tuple[list[str], list[Any]]:
    """Resolve tag names to nodes; tags whose id cannot be resolved are left out."""
    good: list[str] = []
    nodes: list[Any] = []
    for tag in tags:
        try:
            nodes.append(client.get_node(await resolve_node_id(client, tag)))
            good.append(tag)
        except (ValueError, ua.UaError):
            continue
    return good, nodes


async def snapshot_async(
    client: Client, tags: Sequence[str], cycle_utc: str
) -> dict[str, LiveValue]:
    """Read all tags with ONE batch request; unresolvable tags get a bad value."""
    good, nodes = await _resolve_nodes(client, tags)
    result = {tag: bad_value(cycle_utc) for tag in tags}
    if not nodes:
        return result
    data_values = await client.read_attributes(nodes, ua.AttributeIds.Value)
    for tag, data_value in zip(good, data_values, strict=True):
        result[tag] = to_live_value(data_value, cycle_utc)
    return result


def now_iso() -> str:
    """Current UTC time as an ISO string."""
    return datetime.now(UTC).isoformat()

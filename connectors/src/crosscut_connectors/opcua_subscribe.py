"""Import a dataset from OPC UA by data-change subscription instead of polling.

The server pushes a notification when a value changes, the importer records
them and resamples to a regular grid with sample-and-hold, so slow tags cost no
traffic. A subscription only ever reads: nothing is written back to the server.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from asyncua import Client, ua
from crosscut_sim.core import BAD, GOOD
from crosscut_sim.dataset import Samples, write_dataset

from crosscut_connectors.csv_import import _sanitize_tag_name
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.opcua_import import (
    CONNECT_TIMEOUT_S,
    OpcUaImportReport,
    PollPlan,
    _check_identifier_uniqueness,
    _connect,
    _dataset_info,
    _disconnect,
    _is_status_good,
    _make_report,
    _validate_arguments,
    resolve_node_id,
)

INITIAL_VALUE_POLL_S = 0.05  # wait between two checks for the first notifications, seconds
MS_PER_S = 1000
PUBLISHES_PER_GRID_PERIOD = 2  # publishes per grid period, so no grid instant is missed
NS_PER_S = 1_000_000_000
FIRST_EVENT = 1  # a node has one event as soon as the server has sent its initial value


class _ChangeCollector:
    """Subscription handler that records every data-change notification per node.

    ``node_ids`` is the resolved node id list, passed as ``nodes_list`` to
    ``subscribe_data_change`` so ``node.nodeid.to_string()`` compares to it.
    Every node pushes its current value right after subscribing, so a node with
    a wrong id simply never appears in ``events_by_node``.
    """

    def __init__(self, node_ids: list[str]) -> None:
        """Create one empty event list per node, in the same order as ``node_ids``."""
        # ``events_by_node[i]`` holds (ts_ns, value, quality) of node ``node_ids[i]``,
        # appended in arrival order, which the server keeps increasing in time.
        self.node_ids = node_ids
        # The server reports ids in canonical form ('i=2258'), a configuration may say
        # 'ns=0;i=2258': compare in canonical form and keep the configured spelling as key.
        self._configured_by_canonical = {_canonical_id(node_id): node_id for node_id in node_ids}
        self.events_by_node: dict[str, list[tuple[int, float, int]]] = {
            node_id: [] for node_id in node_ids
        }

    def datachange_notification(self, node: Any, val: Any, data: Any) -> None:
        """Record one pushed value; a broken payload becomes NaN with BAD quality.

        Never raises: one malformed notification must not stop the subscription.
        """
        node_id = self._configured_by_canonical.get(node.nodeid.to_string())
        if node_id is None:
            return
        quality = _quality_of(data)
        value = _numeric_value(val) if quality == GOOD else float("nan")
        self.events_by_node[node_id].append((time.time_ns(), value, quality))

    def events_for(self, node_ids: list[str]) -> list[list[tuple[int, float, int]]]:
        """Return the events in ``node_ids`` order, so rows match the tag order."""
        return [self.events_by_node[node_id] for node_id in node_ids]

    def has_event_for_every_node(self) -> bool:
        """True once every node has received at least its initial value."""
        return all(len(events) >= FIRST_EVENT for events in self.events_by_node.values())


def _canonical_id(node_id: str) -> str:
    """The node id in the server's own string form, or unchanged when it cannot be parsed."""
    try:
        return str(ua.NodeId.from_string(node_id).to_string())
    except (ValueError, ua.UaError):
        return node_id


def _quality_of(data: Any) -> int:
    """Translate the StatusCode of a notification into GOOD or BAD.

    A missing payload or a bad status code means the value cannot be trusted.
    """
    try:
        status_code = data.monitored_item.Value.StatusCode
    except AttributeError:
        return BAD
    return GOOD if _is_status_good(status_code) else BAD


def _numeric_value(val: Any) -> float:
    """Convert a notification payload to a finite float, or NaN when unusable.

    The payload is an OPC UA variant: it may be a structured or array value, a
    non-numeric type, or a NaN/infinity that would poison later aggregations.
    """
    try:
        value = float(val)
    except (TypeError, ValueError):
        return float("nan")
    return value if np.isfinite(value) else float("nan")


def hold_resample(
    events: Sequence[Sequence[tuple[int, float, int]]],
    grid_ns: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Resample per-node event lists onto ``grid_ns`` with sample-and-hold.

    ``events[i]`` is the list of (ts_ns, value, quality) notifications of node
    ``i``, sorted by ts_ns and possibly empty. The value held at a grid time ``g``
    is the value of the last event with ``ts_ns <= g``: that is what the sensor
    reported most recently, so slow tags keep their last reading. A grid instant
    before a node's first event, or a node without events, is NaN with BAD.

    Returns:
        (values float64, qualities uint8), each shaped
        (len(events), len(grid_ns)).
    """
    values = np.full((len(events), len(grid_ns)), np.nan, dtype=np.float64)
    qualities = np.full((len(events), len(grid_ns)), BAD, dtype=np.uint8)
    for row, node_events in enumerate(events):
        _fill_row(node_events, grid_ns, values[row], qualities[row])
    return values, qualities


def _fill_row(
    node_events: Sequence[tuple[int, float, int]],
    grid_ns: np.ndarray,
    values: np.ndarray,
    qualities: np.ndarray,
) -> None:
    """Write one node's held values and qualities into its pre-filled output row."""
    if not node_events:
        return
    # The stamps are local wall-clock times, which can step back (NTP); searchsorted needs order.
    node_events = sorted(node_events, key=lambda event: event[0])
    event_ts = np.array([ts_ns for ts_ns, _, _ in node_events], dtype=np.int64)
    event_values = np.array([value for _, value, _ in node_events], dtype=np.float64)
    event_qualities = np.array([quality for _, _, quality in node_events], dtype=np.uint8)
    # `side='right'` puts a grid time equal to an event time just after that event,
    # so the event applies to its own instant. Index -1 means "before the first event".
    last_event = np.searchsorted(event_ts, grid_ns, side="right") - 1
    known = last_event >= 0
    values[known] = event_values[last_event[known]]
    qualities[known] = event_qualities[last_event[known]]


def import_opcua_subscription(
    endpoint: str,
    nodes: Mapping[str, str],
    target: ImportTarget,
    plan: PollPlan = PollPlan(),  # noqa: B008 - frozen dataclass, safe as a shared default
) -> OpcUaImportReport:
    """Subscribe to the given OPC UA nodes, resample the pushed changes, write a dataset.

    Same contract as ``import_opcua``, but the server pushes values instead of
    this client reading them on a timer. Notifications are recorded with their
    arrival time, then resampled onto a grid of ``plan.n_samples`` instants
    ``plan.period_s`` apart with sample-and-hold.

    Parameters
    ----------
    endpoint: str
        OPC UA endpoint URL of the server to subscribe to.
    nodes: Mapping[str, str]
        Mapping of output tag name to OPC UA node id string.
    target: ImportTarget
        Output directory and dataset id (its timezone is unused: samples are
        stamped from the local clock in UTC).
    plan: PollPlan
        Grid period and number of grid instants.

    Returns
    -------
    OpcUaImportReport
        Summary of the import operation.

    Raises
    ------
    ValueError
        If ``nodes`` is empty, or ``plan.n_samples`` is not positive, or
        ``plan.period_s`` is not strictly positive.
    ConnectionError
        If the endpoint cannot be reached, or the connection times out.
    """
    _validate_arguments(nodes, plan)
    tag_ids = _check_identifier_uniqueness(nodes, [_sanitize_tag_name(tag) for tag in nodes])
    node_ids = [nodes[tag] for tag in nodes]

    grid_ns, events = asyncio.run(_collect_events(endpoint, node_ids, plan))
    values, qualities = hold_resample(events, grid_ns)

    info = dataclasses.replace(
        _dataset_info(target.dataset_id, endpoint, grid_ns, (tag_ids, node_ids)),
        source={"kind": "opcua_subscription", "endpoint": endpoint},
    )
    write_dataset(target.out_dir, Samples(grid_ns, tag_ids, values, qualities), info)

    return _make_report(values, len(tag_ids))


async def _collect_events(
    endpoint: str,
    node_ids: list[str],
    plan: PollPlan,
) -> tuple[np.ndarray, list[list[tuple[int, float, int]]]]:
    """Subscribe, record the pushed changes over the grid, then unsubscribe.

    Returns the grid timestamps ``(n_samples,)`` and, per node in ``node_ids``
    order, the list of (ts_ns, value, quality) notifications received during the
    subscription; events that arrived before the grid start are kept, since they
    are the value held at the first grid instant.
    """
    client = Client(url=endpoint, timeout=CONNECT_TIMEOUT_S)
    try:
        await _connect(client)
        resolved = [await resolve_node_id(client, node_id) for node_id in node_ids]
        collector, subscription = await _open_subscription(client, resolved, plan)
        grid_ns = await _wait_for_grid(collector, plan)
        await _verify_session_alive(client, resolved[0])
    finally:
        # Close the session even if the wait or a notification raised.
        await _disconnect(client)
    return grid_ns, collector.events_for(resolved)


async def _verify_session_alive(client: Client, node_id: str) -> None:
    """Raise ConnectionError if the session died during the recording.

    A dead session sends no notifications, and sample-and-hold would carry the last value to
    the end of the grid as GOOD: flat, healthy-looking data. One read at the end tells the
    difference; the polling importer notices the same thing through its failed reads.
    """
    try:
        await client.get_node(node_id).read_data_value()
    except ua.UaStatusCodeError:
        return  # the server answered (even with a bad status), so the session is alive
    except (OSError, TimeoutError, ua.UaError) as error:
        raise ConnectionError("the OPC UA session was lost during the recording") from error


async def _open_subscription(
    client: Client,
    resolved_node_ids: list[str],
    plan: PollPlan,
) -> tuple[_ChangeCollector, Any]:
    """Create the subscription, subscribe every node and wait for its first value.

    The publishing period is half the grid period, so a change is never held
    back for a whole grid step. The initial value of each node arrives only
    after subscribing, so this waits for it before the grid starts.
    """
    collector = _ChangeCollector(resolved_node_ids)
    period_ms = max(1, int(plan.period_s * MS_PER_S / PUBLISHES_PER_GRID_PERIOD))
    subscription = await client.create_subscription(period_ms, collector)
    await subscription.subscribe_data_change([client.get_node(n) for n in resolved_node_ids])
    await _wait_for_first_events(collector)
    return collector, subscription


async def _wait_for_first_events(collector: _ChangeCollector) -> None:
    """Wait until every node has one event, or ``CONNECT_TIMEOUT_S`` has passed.

    A node with a wrong id never reports anything; waiting forever would hang
    the import, so the timeout ends the wait with that node still BAD.
    """
    deadline_s = time.monotonic() + CONNECT_TIMEOUT_S
    while not collector.has_event_for_every_node() and time.monotonic() < deadline_s:
        await asyncio.sleep(INITIAL_VALUE_POLL_S)


async def _wait_for_grid(collector: _ChangeCollector, plan: PollPlan) -> np.ndarray:
    """Mark the grid start, sleep past its last instant plus one publishing interval.

    Returns the grid timestamps in nanoseconds since the epoch. Sleeping one
    extra publishing interval lets the server deliver the notification of the
    last grid instant before the events are read.
    """
    t0_ns = time.time_ns()
    period_ns = int(plan.period_s * NS_PER_S)
    grid_ns = t0_ns + np.arange(plan.n_samples, dtype=np.int64) * period_ns
    publish_ns = period_ns // PUBLISHES_PER_GRID_PERIOD
    wait_s = (int(grid_ns[-1]) + publish_ns - time.time_ns()) / NS_PER_S
    if wait_s > 0:
        await asyncio.sleep(wait_s)
    return grid_ns

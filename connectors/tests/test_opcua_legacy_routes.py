"""Check OPC UA datasets against the former direct asyncua transport paths.

A deterministic session supplies identical values and clocks to both paths, so
routing changes cannot hide differences behind live server timing or noise.
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from asyncua import ua
from crosscut_connectors import opcua_import, opcua_subscribe
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.opcua_import import PollPlan
from crosscut_connectors.opcua_session_connector import OpcUaSessionConnector
from crosscut_opcua import collector
from crosscut_opcua.server import PLANT_OBJECT_NAME, TIME_TAG
from crosscut_sim.dataset import DatasetInfo, Samples, read_dataset, write_dataset

START_NS = 1_767_225_600_000_000_000  # UTC nanoseconds, 2026-01-01.
TAG_ID = "ns=2;s=temperature"


class FixedNode:
    """A deterministic native node, including the collector's plant hierarchy."""

    def __init__(self, identifier: str) -> None:
        """Keep the canonical OPC UA identifier used in notifications."""
        self.nodeid = ua.NodeId.from_string(identifier)

    async def read_data_value(self) -> ua.DataValue:
        """Return an unchanged numeric measurement with good quality."""
        return ua.DataValue(ua.Variant(12.5))

    async def read_browse_name(self) -> Any:
        """Name the synthetic plant folder as the production collector expects."""
        return SimpleNamespace(Name=PLANT_OBJECT_NAME)

    async def get_children(self, **options: Any) -> list[FixedNode]:
        """Return the plant clock followed by one measured tag."""
        return [FixedNode(f"ns=2;s={TIME_TAG}"), FixedNode(TAG_ID)]


class FixedSession:
    """An asyncua-shaped read session with a repeatable simulation clock."""

    def __init__(self, url: str, **options: Any) -> None:
        """Start every recording from the same plant time in seconds."""
        self.server_url = url
        self.plant_time_s = 0
        self.nodes = SimpleNamespace(objects=self)

    async def __aenter__(self) -> FixedSession:
        """Return this already configured session."""
        return self

    async def __aexit__(self, *errors: Any) -> None:
        """Close this in-memory session without external side effects."""

    async def connect(self) -> None:
        """Open this in-memory session without external side effects."""

    async def disconnect(self) -> None:
        """Close this in-memory session without external side effects."""

    async def get_namespace_index(self, uri: str) -> int:
        """Return the fixed namespace index of the synthetic plant."""
        return 2

    def get_node(self, identifier: str) -> FixedNode:
        """Return a fixed node matching the requested identifier."""
        return FixedNode(identifier)

    async def get_children(self) -> list[FixedNode]:
        """Return the synthetic plant object at the root."""
        return [FixedNode("ns=2;s=plant")]

    async def read_attributes(self, nodes: list[FixedNode], attribute: Any) -> list[ua.DataValue]:
        """Advance one plant second per atomic clock-and-measurement read."""
        clock = ua.DataValue(ua.Variant(float(self.plant_time_s)))
        self.plant_time_s += 1
        return [clock, await nodes[1].read_data_value()]

    async def create_subscription(self, period_ms: int, handler: Any) -> Any:
        """Return a subscription that pushes its initial value immediately."""
        return FixedSubscription(handler)


class FixedSubscription:
    """Send the same initial notification for each requested native node."""

    def __init__(self, handler: Any) -> None:
        """Keep the callback that receives native data-change notifications."""
        self.handler = handler

    async def subscribe_data_change(self, nodes: list[FixedNode]) -> None:
        """Push a good value at the deterministic local arrival time."""
        notification = SimpleNamespace(monitored_item=SimpleNamespace(Value=ua.DataValue()))
        for node in nodes:
            self.handler.datachange_notification(node, 12.5, notification)


@pytest.fixture
def fixed_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace external I/O and the wall clock while retaining acquisition logic."""
    monkeypatch.setattr(opcua_import, "Client", FixedSession)
    monkeypatch.setattr(opcua_subscribe, "Client", FixedSession)
    monkeypatch.setattr(collector, "Client", FixedSession)
    monkeypatch.setattr(opcua_import.time, "time_ns", lambda: START_NS)


async def _direct_read(connector: OpcUaSessionConnector, node_id: str) -> ua.DataValue:
    """Former transport: ask the native node for its DataValue directly."""
    return await connector.session.get_node(node_id).read_data_value()


async def _direct_subscribe(
    connector: OpcUaSessionConnector, node_ids: list[str], settings: tuple[int, Any]
) -> Any:
    """Former transport: create the subscription and register the native nodes."""
    period_ms, handler = settings
    subscription = await connector.session.create_subscription(period_ms, handler)
    await subscription.subscribe_data_change([connector.session.get_node(tag) for tag in node_ids])
    return subscription


async def _direct_batch(
    connector: OpcUaSessionConnector, nodes: list[FixedNode]
) -> list[ua.DataValue]:
    """Former collector transport: read the clock and all tags in one native call."""
    return await connector.session.read_attributes(nodes, ua.AttributeIds.Value)


def _track_reads(monkeypatch: pytest.MonkeyPatch, method: str) -> list[bool]:
    """Record whether acquisition actually traverses the connector transport boundary."""
    calls: list[bool] = []
    original = getattr(OpcUaSessionConnector, method)

    async def tracked(connector: OpcUaSessionConnector, *arguments: Any) -> Any:
        """Record one connector call and run its real transport implementation."""
        calls.append(True)
        return await original(connector, *arguments)

    monkeypatch.setattr(OpcUaSessionConnector, method, tracked)
    return calls


def test_polling_matches_the_legacy_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_transport: None
) -> None:
    """Polling keeps timestamps, values, quality, tag sanitization and its report."""
    calls = _track_reads(monkeypatch, "read_raw")
    nodes, plan = {"Plant Temperature": TAG_ID}, PollPlan(0.001, 2)
    actual = opcua_import.import_opcua(
        "fixed", nodes, ImportTarget(tmp_path / "actual", "same"), plan
    )
    monkeypatch.setattr(OpcUaSessionConnector, "read_raw", _direct_read)
    expected = _legacy_import(
        "fixed", nodes, ImportTarget(tmp_path / "legacy", "same"), plan
    )
    assert calls
    assert actual == expected
    assert read_dataset(tmp_path / "actual").equals(read_dataset(tmp_path / "legacy"))


def test_subscription_matches_the_legacy_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_transport: None
) -> None:
    """Subscription preserves arrival timestamps and sample-and-hold quality."""
    calls = _track_reads(monkeypatch, "subscribe_nodes")
    nodes, plan = {"Plant Temperature": TAG_ID}, PollPlan(0.001, 2)
    actual = opcua_subscribe.import_opcua_subscription(
        "fixed", nodes, ImportTarget(tmp_path / "actual", "same"), plan
    )
    monkeypatch.setattr(OpcUaSessionConnector, "subscribe_nodes", _direct_subscribe)
    expected = _legacy_subscription(
        "fixed", nodes, ImportTarget(tmp_path / "legacy", "same"), plan
    )
    assert calls
    assert actual == expected
    assert read_dataset(tmp_path / "actual").equals(read_dataset(tmp_path / "legacy"))


def test_collector_matches_the_legacy_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_transport: None
) -> None:
    """Plant-clock batching retains the legacy dataset and provenance exactly."""
    calls = _track_reads(monkeypatch, "read_raw_batch")
    config = collector.CollectorConfig(2.0, 1.0, "same", "synthetic", poll_s=0)
    actual = asyncio.run(collector.collect("fixed", tmp_path / "actual", config))
    monkeypatch.setattr(OpcUaSessionConnector, "read_raw_batch", _direct_batch)
    expected = asyncio.run(_legacy_collect("fixed", tmp_path / "legacy", config))
    assert calls
    assert actual["source"] == expected["source"]
    assert actual["data_sha256"] == expected["data_sha256"]
    assert read_dataset(tmp_path / "actual").equals(read_dataset(tmp_path / "legacy"))


def _legacy_import(endpoint: str, nodes: dict, target: ImportTarget, plan: PollPlan) -> Any:
    """Frozen polling entrypoint before routing; use the original native transport."""
    opcua_import._validate_arguments(nodes, plan)
    tag_ids = opcua_import._check_identifier_uniqueness(
        [opcua_import._sanitize_tag_name(tag) for tag in nodes]
    )
    node_ids = list(nodes.values())
    timestamps, values, qualities = asyncio.run(
        opcua_import._collect_samples(endpoint, node_ids, plan)
    )
    info = opcua_import._dataset_info(target.dataset_id, endpoint, timestamps, (tag_ids, node_ids))
    write_dataset(target.out_dir, Samples(timestamps, tag_ids, values, qualities), info)
    return opcua_import._make_report(values, len(tag_ids))


def _legacy_subscription(endpoint: str, nodes: dict, target: ImportTarget, plan: PollPlan) -> Any:
    """Frozen subscription entrypoint before routing, including its source kind."""
    opcua_import._validate_arguments(nodes, plan)
    tag_ids = opcua_import._check_identifier_uniqueness(
        [opcua_import._sanitize_tag_name(tag) for tag in nodes]
    )
    node_ids = list(nodes.values())
    grid, events = asyncio.run(opcua_subscribe._collect_events(endpoint, node_ids, plan))
    values, qualities = opcua_subscribe.hold_resample(events, grid)
    info = dataclasses.replace(
        opcua_import._dataset_info(target.dataset_id, endpoint, grid, (tag_ids, node_ids)),
        source={"kind": "opcua_subscription", "endpoint": endpoint},
    )
    write_dataset(target.out_dir, Samples(grid, tag_ids, values, qualities), info)
    return opcua_import._make_report(values, len(tag_ids))


async def _legacy_collect(endpoint: str, out_dir: Path, config: collector.CollectorConfig) -> dict:
    """Frozen plant collector entrypoint, retaining its original native batch read."""
    recording = collector._Recording(collector._utc_to_ns(config.start_utc), config.sample_period_s)
    async with FixedSession(endpoint) as client:
        index = await client.get_namespace_index(collector.NAMESPACE_URI)
        clock, nodes, tags = await collector._discover_plant_nodes(client, index)
        await collector._poll_until_done(client, [clock, *nodes], config, recording)
    samples = Samples(
        np.asarray(recording.ts_ns, dtype=np.int64), tags,
        np.asarray(recording.rows, dtype=np.float64),
        np.asarray(recording.quality_rows, dtype=np.uint8),
    )
    info = DatasetInfo(
        dataset_id=config.dataset_id, source=collector._build_source(config),
        start_utc=config.start_utc, tags_document=collector._build_tags_document(tags, index),
        git_commit=config.git_commit,
    )
    return write_dataset(out_dir, samples, info)

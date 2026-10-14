"""Unit tests for the sample-and-hold resampling and integration tests for the
subscription importer, run against the real plant test server."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.compute as pc
import pytest
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.opcua_import import OpcUaImportReport, PollPlan
from crosscut_connectors.opcua_subscribe import hold_resample, import_opcua_subscription
from crosscut_opcua.server import PlantServer, ServerConfig
from crosscut_sim.core import BAD, GOOD, Scenario
from crosscut_sim.dataset import read_dataset, to_wide
from crosscut_sim.plants.wood_berry import WoodBerryPlant

SERVER_TIMEOUT_S = 60.0
TAG_Y1 = "sim.wb.top_comp"
UNKNOWN_TAG = "sim.wb.does_not_exist"
SOURCE_KIND = "opcua_subscription"
GRID_PERIOD_S = 0.2
GRID_SAMPLES = 8
# Nanoseconds in one second, used to convert plan periods to a nanosecond grid.
NS_PER_S = 1_000_000_000


def free_port() -> int:
    """Return a currently unused TCP port on the loopback interface."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def make_server(port: int) -> PlantServer:
    """Return the plant test server matching the collector test configuration."""
    return PlantServer(
        WoodBerryPlant(),
        Scenario(measurement_noise=1.0),
        ServerConfig(
            seed=3,
            host="127.0.0.1",
            port=port,
            speed=50.0,
            tick_s=0.02,
            heartbeat_timeout_s=SERVER_TIMEOUT_S,
        ),
    )


def run_against_server(
    server: PlantServer,
    call: Callable[[str], OpcUaImportReport],
    *,
    timeout_s: float = SERVER_TIMEOUT_S,
) -> OpcUaImportReport:
    """Start the async server, run the sync `call` against its endpoint, stop the server."""

    async def main() -> OpcUaImportReport:
        """Run the OPC UA import against the server and return the resulting report."""
        async with server:
            return await asyncio.to_thread(call, server.endpoint)

    return asyncio.run(asyncio.wait_for(main(), timeout=timeout_s))


def import_y1(tmp_path: Path, nodes: dict[str, str], **plan_options: Any) -> OpcUaImportReport:
    """Run import_opcua_subscription for the given nodes against a fresh plant server."""
    out_dir = tmp_path / "ds"
    port = free_port()
    server = make_server(port)
    call = lambda endpoint: import_opcua_subscription(  # noqa: E731 - tiny endpoint adapter
        endpoint, nodes, ImportTarget(out_dir, SOURCE_KIND), PollPlan(**plan_options)
    )
    return run_against_server(server, call)


def read_column(out_dir: Path, tag: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (timestamps, values, quality) for one tag read back from the written dataset."""
    table = read_dataset(out_dir)
    timestamps, wide = to_wide(table)
    # Select in Arrow: converting the nanosecond timestamps to Python objects fails on Linux
    # clocks, whose readings are not whole microseconds.
    rows = table.filter(pc.equal(table["tag_id"], tag)).sort_by("ts")
    quality = rows["quality"].to_numpy()
    return timestamps, wide[tag], quality


def test_a_value_is_held_between_events() -> None:
    events = [[(0, 1.0, GOOD), (30, 2.0, GOOD)]]
    values, qualities = hold_resample(events, np.array([0, 10, 20, 30, 40], dtype=np.int64))
    assert list(values[0]) == [1.0, 1.0, 1.0, 2.0, 2.0]
    assert list(qualities[0]) == [GOOD, GOOD, GOOD, GOOD, GOOD]


def test_before_the_first_event_the_sample_is_bad_and_nan() -> None:
    events = [[(20, 5.0, GOOD)]]
    values, qualities = hold_resample(events, np.array([0, 10, 30], dtype=np.int64))
    assert np.isnan(values[0, :2]).all()
    assert list(qualities[0, :2]) == [BAD, BAD]
    assert values[0, 2] == 5.0


def test_a_node_without_events_is_all_nan_and_bad() -> None:
    events: list[list[tuple[int, float, int]]] = [[]]
    values, qualities = hold_resample(events, np.array([0, 10, 20], dtype=np.int64))
    assert np.isnan(values[0]).all()
    assert list(qualities[0]) == [BAD, BAD, BAD]


def test_a_bad_event_propagates_nan_and_bad_until_a_good_one() -> None:
    events = [[(0, float("nan"), BAD), (20, 3.0, GOOD)]]
    values, qualities = hold_resample(events, np.array([0, 10, 20], dtype=np.int64))
    assert np.isnan(values[0, :2]).all()
    assert list(qualities[0, :2]) == [BAD, BAD]
    assert values[0, 2] == 3.0


def test_an_event_exactly_on_a_grid_instant_is_used() -> None:
    events = [[(50, 7.0, GOOD)]]
    values, qualities = hold_resample(events, np.array([50], dtype=np.int64))
    assert values[0, 0] == 7.0
    assert qualities[0, 0] == GOOD


def test_two_nodes_are_independent() -> None:
    events = [[(0, 1.0, GOOD)], [(0, 9.0, GOOD), (10, 8.0, GOOD)]]
    values, _ = hold_resample(events, np.array([0, 10], dtype=np.int64))
    assert list(values[0]) == [1.0, 1.0]
    assert list(values[1]) == [9.0, 8.0]


def test_the_subscription_import_writes_a_regular_grid(tmp_path: Path) -> None:
    report = import_y1(
        tmp_path, {"y1": f"ns=2;s={TAG_Y1}"}, n_samples=GRID_SAMPLES, period_s=GRID_PERIOD_S
    )
    assert (report.n_rows, report.n_tags, report.n_bad_values) == (GRID_SAMPLES, 1, 0)
    timestamps, values, _ = read_column(tmp_path / "ds", "y1")
    assert np.all(np.isfinite(values))
    steps_s = np.diff(timestamps.astype(np.int64)) / NS_PER_S
    assert np.allclose(steps_s, GRID_PERIOD_S, atol=0.005)


def test_an_unknown_node_id_gives_an_all_nan_bad_column(tmp_path: Path) -> None:
    report = import_y1(
        tmp_path,
        {"ghost": f"ns=2;s={UNKNOWN_TAG}"},
        n_samples=GRID_SAMPLES,
        period_s=GRID_PERIOD_S,
    )
    assert report.n_bad_values == GRID_SAMPLES
    _, values, quality = read_column(tmp_path / "ds", "ghost")
    assert np.all(np.isnan(values))
    assert np.all(quality == BAD)


def test_an_empty_node_map_is_rejected(tmp_path: Path) -> None:
    server = make_server(free_port())
    with pytest.raises(ValueError):
        run_against_server(
            server,
            lambda endpoint: import_opcua_subscription(
                endpoint, {}, ImportTarget(tmp_path / "ds", SOURCE_KIND)
            ),
        )


def test_a_non_positive_period_is_rejected(tmp_path: Path) -> None:
    server = make_server(free_port())
    with pytest.raises(ValueError):
        run_against_server(
            server,
            lambda endpoint: import_opcua_subscription(
                endpoint,
                {"y1": f"ns=2;s={TAG_Y1}"},
                ImportTarget(tmp_path / "ds", SOURCE_KIND),
                PollPlan(period_s=0.0),
            ),
        )

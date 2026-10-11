# connectors/tests/test_opcua_import.py
"""Integration tests for crosscut_connectors.opcua_import against the real test server."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pyarrow.compute as pc
import pytest
from crosscut_connectors.opcua_import import OpcUaImportReport, import_opcua
from crosscut_opcua.server import PlantServer
from crosscut_sim.core import BAD, GOOD, Scenario
from crosscut_sim.dataset import read_dataset, to_wide
from crosscut_sim.plants.wood_berry import NOMINAL, WoodBerryPlant

SERVER_TIMEOUT_S = 60.0
TAG_Y1 = "sim.wb.top_comp"
UNKNOWN_TAG = "sim.wb.does_not_exist"


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
        seed=3,
        host="127.0.0.1",
        port=port,
        speed=50.0,
        tick_s=0.02,
        heartbeat_timeout_s=SERVER_TIMEOUT_S,
    )


def run_against_server(
    server: PlantServer,
    call: Callable[[str], OpcUaImportReport],
    *,
    timeout_s: float = SERVER_TIMEOUT_S,
) -> OpcUaImportReport:
    """Start the async server, run the sync `call` against its endpoint, stop the server."""

    async def main() -> OpcUaImportReport:
        async with server:
            return await asyncio.to_thread(call, server.endpoint)

    return asyncio.run(asyncio.wait_for(main(), timeout=timeout_s))


def import_y1(tmp_path: Path, nodes: dict[str, str], **kwargs: object) -> OpcUaImportReport:
    """Run import_opcua for the given nodes against a freshly started plant server."""
    out_dir = tmp_path / "ds"
    port = free_port()
    server = make_server(port)
    call = lambda endpoint: import_opcua(  # noqa: E731 - tiny adapter to pass the live endpoint
        endpoint, nodes, out_dir, dataset_id="opcua", **kwargs
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


def test_import_returns_the_requested_number_of_rows_and_tags(tmp_path: Path) -> None:
    report = import_y1(tmp_path, {"y1": f"ns=2;s={TAG_Y1}"}, n_samples=5, period_s=0.05)
    assert isinstance(report, OpcUaImportReport)
    assert report.n_rows == 5
    assert report.n_tags == 1
    assert report.n_bad_values == 0


def test_imported_values_are_finite_and_plausible_for_y1(tmp_path: Path) -> None:
    report = import_y1(tmp_path, {"y1": f"ns=2;s={TAG_Y1}"}, n_samples=5, period_s=0.05)
    assert report.n_bad_values == 0
    _, values, _ = read_column(tmp_path / "ds", "y1")
    assert np.all(np.isfinite(values))
    assert float(np.mean(values)) == pytest.approx(NOMINAL["top_comp"], abs=0.5)


def test_imported_timestamps_are_strictly_increasing(tmp_path: Path) -> None:
    import_y1(tmp_path, {"y1": f"ns=2;s={TAG_Y1}"}, n_samples=5, period_s=0.05)
    timestamps, _, _ = read_column(tmp_path / "ds", "y1")
    assert len(timestamps) == 5
    assert np.all(np.diff(timestamps.astype(np.int64)) > 0)


def test_an_unknown_node_id_gives_an_all_nan_bad_column(tmp_path: Path) -> None:
    report = import_y1(tmp_path, {"ghost": f"ns=2;s={UNKNOWN_TAG}"}, n_samples=4, period_s=0.05)
    assert report.n_bad_values == 4
    _, values, quality = read_column(tmp_path / "ds", "ghost")
    assert np.all(np.isnan(values))
    assert np.all(quality == BAD)


def test_a_good_node_has_good_quality(tmp_path: Path) -> None:
    import_y1(tmp_path, {"y1": f"ns=2;s={TAG_Y1}"}, n_samples=3, period_s=0.05)
    _, _, quality = read_column(tmp_path / "ds", "y1")
    assert np.all(quality == GOOD)


def test_import_does_not_write_to_the_plant(tmp_path: Path) -> None:
    server = make_server(free_port())
    client_writes: list[tuple[str, float]] = []
    original_on_client_write = server._on_client_write

    def recording_on_client_write(tag_id: str, value: float) -> None:
        client_writes.append((tag_id, value))
        original_on_client_write(tag_id, value)

    server._on_client_write = recording_on_client_write
    nodes = {"y1": f"ns=2;s={TAG_Y1}"}
    run_against_server(
        server,
        lambda endpoint: import_opcua(
            endpoint, nodes, tmp_path / "ds", dataset_id="opcua", n_samples=3, period_s=0.05
        ),
    )
    assert client_writes == []


def test_an_empty_node_map_is_rejected(tmp_path: Path) -> None:
    port = free_port()
    server = make_server(port)
    with pytest.raises(ValueError):
        run_against_server(
            server,
            lambda endpoint: import_opcua(endpoint, {}, tmp_path / "ds", dataset_id="opcua"),
        )


def test_zero_samples_is_rejected(tmp_path: Path) -> None:
    port = free_port()
    server = make_server(port)
    with pytest.raises(ValueError):
        run_against_server(
            server,
            lambda endpoint: import_opcua(
                endpoint,
                {"y1": f"ns=2;s={TAG_Y1}"},
                tmp_path / "ds",
                dataset_id="opcua",
                n_samples=0,
            ),
        )


def test_a_non_positive_period_is_rejected(tmp_path: Path) -> None:
    port = free_port()
    server = make_server(port)
    with pytest.raises(ValueError):
        run_against_server(
            server,
            lambda endpoint: import_opcua(
                endpoint,
                {"y1": f"ns=2;s={TAG_Y1}"},
                tmp_path / "ds",
                dataset_id="opcua",
                period_s=0.0,
            ),
        )


def test_an_unreachable_endpoint_raises_connection_error(tmp_path: Path) -> None:
    endpoint = f"opc.tcp://127.0.0.1:{free_port()}"
    nodes = {"y1": f"ns=2;s={TAG_Y1}"}
    with pytest.raises(ConnectionError):
        import_opcua(
            endpoint, nodes, tmp_path / "ds", dataset_id="opcua", n_samples=1, period_s=0.05
        )


def test_the_written_dataset_is_readable_in_wide_form(tmp_path: Path) -> None:
    import_y1(tmp_path, {"y1": f"ns=2;s={TAG_Y1}"}, n_samples=3, period_s=0.05)
    table = read_dataset(tmp_path / "ds")
    timestamps, wide = to_wide(table)
    assert "y1" in wide
    assert len(timestamps) == 3
    assert len(wide["y1"]) == 3

"""Tests for source connector HTTP endpoints (Phase 1, #43).

Verifies GET /sources, POST /sources/{id}/test, GET /sources/{id}/browse,
and POST /sources/{id}/read-live across CSV and OPC UA simulated sources.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from pathlib import Path

import pytest
from crosscut_connectors.site import save_site
from crosscut_opcua.server import PlantServer, ServerConfig
from crosscut_sim.plants.wood_berry import WoodBerryPlant
from crosscut_sim.scenarios import Scenario
from fastapi.testclient import TestClient
from open_app import create_app_without_auth


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def opcua_server():
    port = _free_port()
    server = PlantServer(
        WoodBerryPlant(),
        Scenario(measurement_noise=0.1),
        ServerConfig(seed=42, host="127.0.0.1", port=port, speed=20.0, tick_s=0.05),
    )
    endpoint = f"opc.tcp://127.0.0.1:{port}"
    loop = asyncio.new_event_loop()
    ready_evt = threading.Event()
    stop_evt = threading.Event()

    def _server_thread() -> None:
        asyncio.set_event_loop(loop)

        async def _runner() -> None:
            async with server:
                ready_evt.set()
                while not stop_evt.is_set():
                    await asyncio.sleep(0.05)

        loop.run_until_complete(_runner())
        loop.close()

    t = threading.Thread(target=_server_thread, daemon=True)
    t.start()
    assert ready_evt.wait(timeout=10.0), "PlantServer failed to start"

    try:
        yield endpoint
    finally:
        stop_evt.set()
        t.join(timeout=5.0)


@pytest.fixture
def site_with_sources(tmp_path: Path, opcua_server: str) -> tuple[TestClient, Path]:
    csv_file = tmp_path / "historian.csv"
    csv_content = "timestamp,FIC_101.PV,FIC_101.SP\n2026-01-01T00:00:00Z,50.0,50.0\n"
    csv_file.write_text(csv_content, encoding="utf-8")

    site_doc = {
        "schema_version": 1,
        "site": {"name": "Test Plant"},
        "tags": [
            {"id": "FIC_101.PV", "unit": "kg/h", "source": "csv_src"},
            {"id": "FIC_101.SP", "unit": "kg/h", "source": "csv_src"},
        ],
        "sources": [
            {"id": "csv_src", "driver": "csv", "endpoint": str(csv_file)},
            {"id": "opcua_src", "driver": "opcua", "endpoint": opcua_server},
        ],
    }
    save_site(tmp_path, site_doc)
    client = TestClient(create_app_without_auth(tmp_path))
    return client, tmp_path


def test_list_sources(site_with_sources: tuple[TestClient, Path]) -> None:
    client, _ = site_with_sources
    res = client.get("/sources")
    assert res.status_code == 200
    sources = res.json()["sources"]
    assert len(sources) == 2
    assert {s["id"] for s in sources} == {"csv_src", "opcua_src"}


def test_test_source_endpoints(site_with_sources: tuple[TestClient, Path]) -> None:
    client, _ = site_with_sources
    csv_res = client.post("/sources/csv_src/test")
    assert csv_res.status_code == 200
    assert csv_res.json()["status"] == "ok"
    assert "history" in csv_res.json()["capabilities"]

    opc_res = client.post("/sources/opcua_src/test")
    assert opc_res.status_code == 200
    assert "read_live" in opc_res.json()["capabilities"]


def test_browse_source_opcua(site_with_sources: tuple[TestClient, Path]) -> None:
    client, _ = site_with_sources
    res = client.get("/sources/opcua_src/browse")
    assert res.status_code == 200
    nodes = res.json()["nodes"]
    assert len(nodes) > 0

    # Live read on unsupported driver (CSV) returns 400
    csv_live = client.post("/sources/csv_src/read-live", json={"tags": ["FIC_101.PV"]})
    assert csv_live.status_code == 400


def test_read_live_opcua(site_with_sources: tuple[TestClient, Path]) -> None:
    client, _ = site_with_sources
    # Browse first to find a valid variable node
    browse_res = client.get("/sources/opcua_src/browse")
    nodes = browse_res.json()["nodes"]
    plant_node = next(
        (n for n in nodes if "Plant" in n["name"] or "Objects" in n["name"]),
        nodes[0],
    )

    children_res = client.get(f"/sources/opcua_src/browse?node_id={plant_node['id']}")
    children = children_res.json()["nodes"]
    var_nodes = [n for n in children if n["node_type"] == "variable"]
    if not var_nodes:
        deeper_res = client.get(f"/sources/opcua_src/browse?node_id={children[0]['id']}")
        var_nodes = [n for n in deeper_res.json()["nodes"] if n["node_type"] == "variable"]

    assert len(var_nodes) > 0
    target_id = var_nodes[0]["id"]

    live_res = client.post("/sources/opcua_src/read-live", json={"tags": [target_id]})
    assert live_res.status_code == 200
    values = live_res.json()["values"]
    assert target_id in values
    assert values[target_id]["quality"] == 0
    assert values[target_id]["value"] is not None


def test_source_not_found(site_with_sources: tuple[TestClient, Path]) -> None:
    client, _ = site_with_sources
    res = client.post("/sources/non_existent/test")
    assert res.status_code == 404

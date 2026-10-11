"""Integration tests for the OPC UA collector that records a running plant server."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from crosscut_opcua.collector import collect
from crosscut_opcua.server import HEARTBEAT_OK_TAG, HEARTBEAT_TAG, TIME_TAG, PlantServer
from crosscut_sim.core import Scenario
from crosscut_sim.dataset import compute_data_sha256, read_dataset, to_wide
from crosscut_sim.plants.wood_berry import NOMINAL, WoodBerryPlant
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run_collection(out_dir: Path, sim_duration_s: float) -> dict[str, object]:
    async def main() -> dict[str, object]:
        server = PlantServer(
            WoodBerryPlant(),
            Scenario(measurement_noise=1.0),
            seed=3,
            host="127.0.0.1",
            port=free_port(),
            speed=50.0,
            tick_s=0.02,
            heartbeat_timeout_s=60.0,
        )
        async with server:
            return await collect(
                server.endpoint,
                out_dir,
                sim_duration_s=sim_duration_s,
                sample_period_s=1.0,
                dataset_id="wb_opcua_test",
                plant_name="wood_berry",
                scenario_name="nominal",
                seed=3,
                timeout_s=30.0,
            )

    return asyncio.run(asyncio.wait_for(main(), timeout=60))


def test_collector_records_a_valid_dataset(tmp_path: Path) -> None:
    doc = run_collection(tmp_path, sim_duration_s=200.0)
    schema = json.loads((REPO_ROOT / "schemas" / "dataset.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(doc))
    assert errors == [], [e.message for e in errors]
    assert json.loads((tmp_path / "dataset.json").read_text(encoding="utf-8")) == doc
    assert doc["source"] == {
        "kind": "opcua",
        "plant": "wood_berry",
        "scenario": "nominal",
        "seed": 3,
    }

    plant_tags = set(WoodBerryPlant().tags.ids())
    assert set(doc["tags"]) == plant_tags  # type: ignore[call-overload]
    assert not {HEARTBEAT_TAG, HEARTBEAT_OK_TAG, TIME_TAG} & set(doc["tags"])  # type: ignore[call-overload]

    table = read_dataset(tmp_path)
    assert compute_data_sha256(table) == doc["data_sha256"]
    ts, wide = to_wide(table)
    assert set(wide) == plant_tags
    n = len(ts)
    assert 100 <= n <= 202
    assert doc["row_count"] == n * len(plant_tags)
    steps = np.diff(ts).astype("timedelta64[s]").astype(int)
    assert steps.min() >= 1
    assert ts[0] == np.datetime64("2026-01-01T00:00:00", "ns")
    assert float(np.mean(wide["sim.wb.top_comp"])) == pytest.approx(NOMINAL["top_comp"], abs=0.2)
    assert float(np.std(wide["sim.wb.top_comp"])) > 0.0  # measurement noise is on


def test_command_line_entry_points_print_help() -> None:
    entry_points = (
        ("crosscut_opcua.server", "--plant"),
        ("crosscut_opcua.collector", "--endpoint"),
    )
    for module, option in entry_points:
        result = subprocess.run(
            [sys.executable, "-m", module, "--help"], capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0
        assert option in result.stdout

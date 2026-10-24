"""Anomaly routes report tags that hold a long exact linear ramp (an interpolated archive gap).

A 16 h simulation gets an 8 h straight line written into one tag; fit and scan must name that tag.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from crosscut_api.app import create_app
from crosscut_sim.run import main as run_simulation
from fastapi.testclient import TestClient

PREFIX = "sim.mc."
TAGS = ["mill_power", "p80", "mill_feed", "hpgr_power", "feed_moisture"]
RAMP_TAG = PREFIX + "p80"
CONFIG: dict[str, Any] = {
    "schema_version": "1.0.0",
    "id": "mc",
    "tags": [PREFIX + tag for tag in TAGS],
    "mode": "advisory",
    "sample_period_s": 20,
}
RAMP_FROM_H, RAMP_TO_H = 3.0, 11.0


def _simulate(root: Path) -> None:
    """Write a 16 h mill_circuit simulation (10 s samples) under root."""
    argv = ["--plant", "mill_circuit", "--duration", "16h", "--sample-period", "10"]
    assert run_simulation([*argv, "--out", str(root)]) == 0


def _write_ramp(root: Path) -> None:
    """Replace the RAMP_TAG samples between RAMP_FROM_H and RAMP_TO_H by a straight line."""
    path = next(root.rglob("part-*.parquet"))
    table = pq.read_table(path)
    values = table["value"].to_numpy().copy()
    hit = np.array([tag == RAMP_TAG for tag in table["tag_id"].to_pylist()])
    ts_ns = table["ts"].cast(pa.int64()).to_numpy()
    hours = (ts_ns - ts_ns[0]) / 3.6e12
    inside = hit & (hours >= RAMP_FROM_H) & (hours < RAMP_TO_H)
    values[inside] = np.linspace(1.0, 2.0, int(inside.sum()))
    index = table.schema.get_field_index("value")
    pq.write_table(table.set_column(index, "value", pa.array(values)), path)


def _client(root: Path, ramp: bool) -> tuple[TestClient, str]:
    """A client on the simulation (with the ramp when asked) and the dataset id."""
    _simulate(root)
    if ramp:
        _write_ramp(root)
    client = TestClient(create_app(root))
    assert client.put("/anomaly/mc", json=CONFIG).status_code == 200
    return client, client.get("/datasets").json()[0]["id"]


@pytest.mark.parametrize("route", ["fit", "scan"])
def test_anomaly_ramp_routes_name_the_ramp_tag(tmp_path: Path, route: str) -> None:
    client, dataset = _client(tmp_path, ramp=True)
    assert client.post(f"/datasets/{dataset}/anomaly/mc/fit", json={}).status_code == 200
    body = client.post(f"/datasets/{dataset}/anomaly/mc/{route}", json={}).json()
    assert list(body["unreliable_tags"]) == [RAMP_TAG]
    assert 0.35 < body["unreliable_tags"][RAMP_TAG] < 0.65


@pytest.mark.parametrize("route", ["fit", "scan"])
def test_anomaly_ramp_routes_report_nothing_without_a_ramp(tmp_path: Path, route: str) -> None:
    client, dataset = _client(tmp_path, ramp=False)
    assert client.post(f"/datasets/{dataset}/anomaly/mc/fit", json={}).status_code == 200
    body = client.post(f"/datasets/{dataset}/anomaly/mc/{route}", json={}).json()
    assert body["unreliable_tags"] == {}

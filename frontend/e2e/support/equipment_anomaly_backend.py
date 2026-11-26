"""Serve an isolated synthetic pump dataset for the equipment-anomaly browser tests.

The real API owns learning, event replay and feedback; no shared e2e catalogue is changed.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import numpy as np
import uvicorn
from crosscut_api.app import create_app
from crosscut_connectors.site import save_site
from crosscut_sim.dataset import DatasetInfo, Samples, write_dataset

DATASET_ID = "equipment-pump-data"
START_UTC = "2026-01-01T00:00:00Z"
START_NS = 1767225600000000000  # Unix epoch nanoseconds.
SAMPLE_COUNT = 300  # One-second samples, sufficient for the four-variable PCA model.
TAGS = ["flow", "target", "speed", "mode", "current"]


def write_pump_dataset(root: Path) -> None:
    """Write reproducible, aligned good-quality pump signals in engineering units."""
    random = np.random.default_rng(215)
    speed = random.uniform(20, 80, SAMPLE_COUNT)
    # Rows are one-second observations; columns follow TAGS. Current follows motor load.
    values = np.column_stack((speed + random.normal(0, .2, SAMPLE_COUNT), speed, speed,
                              np.ones(SAMPLE_COUNT),
                              2 * speed + random.normal(0, .1, SAMPLE_COUNT)))
    samples = Samples(START_NS + np.arange(SAMPLE_COUNT) * 10**9, TAGS, values,
                      np.zeros_like(values, dtype=np.uint8))
    tags = {"schema_version": "1.0.0", "tags": [
        {"id": tag, "name": tag, "unit": "", "type": "float", "role": "other"}
        for tag in TAGS]}
    info = DatasetInfo(DATASET_ID, {"kind": "sim", "plant": "pump", "seed": 215},
                       START_UTC, tags)
    write_dataset(root / DATASET_ID, samples, info)


def write_pump_catalogue(root: Path) -> None:
    """Attach a pump and its loop to an area with explicit failure criticality."""
    site = {"schema_version": 1, "site": {"name": "Equipment browser fixture"},
            "sources": [{"id": "source", "driver": "opcua", "endpoint": "opc.tcp://test"}],
            "tags": [{"id": tag} for tag in TAGS],
            "equipment": [{"id": "plant", "name": "Plant", "level": "site"},
                          {"id": "grinding", "name": "Grinding", "level": "area",
                           "parent": "plant"},
                          {"id": "pump", "name": "Feed pump", "level": "equipment",
                           "parent": "grinding", "criticality": "high", "loops": ["flow-loop"],
                           "signals": [{"tag": "current", "kind": "current", "confirmed": True}]}],
            "loops": [{"id": "flow-loop", "pv": "flow", "sp": "target", "out": "speed",
                       "mode": "mode", "out_limits": {"min": 0, "max": 100}}]}
    save_site(root, site)


def write_pump_events(root: Path) -> None:
    """Seed one closed and one open event using the runtime's public JSON shape."""
    event = {"equipment": "pump", "opened_utc": "2026-01-01T00:04:00+00:00",
             "closed_utc": None, "peak": 2.0, "contributions": [
                 {"tag": "current", "share": .7}, {"tag": "speed", "share": .3}],
             "residuals": [{"tag": "current", "z": 3.2, "trend": 1}],
             "loops_affected": ["flow-loop"]}
    closed = {**event, "opened_utc": "2026-01-01T00:01:00+00:00",
              "closed_utc": "2026-01-01T00:02:00+00:00"}
    runtime = root / "_runtime"
    runtime.mkdir()
    (runtime / "equipment_events.jsonl").write_text(
        json.dumps(closed) + "\n" + json.dumps(event) + "\n", encoding="utf-8")
    (runtime / "state.json").write_text(json.dumps({"jobs": {"scan": {"equipment": {
        "pump": {"status": "anomaly", "open_event": event}}}}}), encoding="utf-8")


def serve_fixture(root: Path) -> None:
    """Prepare the fixture and print the chosen address before serving the real API."""
    write_pump_dataset(root)
    write_pump_catalogue(root)
    write_pump_events(root)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        print(json.dumps({"address": address}), flush=True)
        server = uvicorn.Server(uvicorn.Config(create_app(root, auth_enabled=False),
                                               log_level="warning"))
        server.run(sockets=[listener])


if __name__ == "__main__":
    serve_fixture(Path(sys.argv[1]))

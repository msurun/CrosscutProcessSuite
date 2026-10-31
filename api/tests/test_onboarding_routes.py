"""Tests for dataset onboarding and readiness HTTP endpoint (Phase 1, #39).

Verifies GET /datasets/{id}/readiness against clean synthetic data,
missing loop OUT tags, and missing soft sensor targets.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from crosscut_api.app import create_app
from crosscut_connectors.site import save_site
from crosscut_sim.dataset import DatasetInfo, Samples, write_dataset
from fastapi.testclient import TestClient


@pytest.fixture
def clean_dataset_client(tmp_path: Path) -> tuple[TestClient, Path]:
    ds_dir = tmp_path / "synthetic_ds"
    ds_dir.mkdir(parents=True)
    t_s = np.arange(0.0, 30 * 3600.0, 10.0)
    timestamps = (t_s * 1e9).astype(np.int64)

    rng = np.random.default_rng(42)
    tag_names = [
        "FIC101.PV",
        "FIC101.SP",
        "FIC101.OUT",
        "FIC101.MODE",
        "FEED_RATE",
        "DENSITY",
        "PRODUCT_CONC",
    ]
    series_data = [
        50.0 + rng.normal(0, 0.1, len(t_s)),
        np.full(len(t_s), 50.0),
        45.0 + rng.normal(0, 0.2, len(t_s)),
        np.full(len(t_s), 1.0),
        100.0 + rng.normal(0, 0.5, len(t_s)),
        1.4 + rng.normal(0, 0.02, len(t_s)),
        80.0 + rng.normal(0, 0.3, len(t_s)),
    ]
    values = np.column_stack(series_data)
    qualities = np.zeros(values.shape, dtype=np.uint8)
    samples = Samples(ts_ns=timestamps, tag_ids=tag_names, values=values, qualities=qualities)
    info = DatasetInfo(
        dataset_id="synthetic_ds",
        source={"kind": "simulated"},
        start_utc="2026-01-01T00:00:00Z",
        tags_document={
            "schema_version": "0.1.0",
            "tags": [{"id": t, "name": t, "unit": "", "role": "other"} for t in tag_names],
        },
    )
    write_dataset(ds_dir, samples, info)

    site_doc = {
        "schema_version": 1,
        "site": {"name": "Synthetic Clean Plant"},
        "tags": [{"id": k} for k in tag_names],
        "signals": [
            {"tag": "FIC101.PV", "role": "pv", "loop": "FIC101"},
            {"tag": "FIC101.SP", "role": "sp", "loop": "FIC101"},
            {"tag": "FIC101.OUT", "role": "out", "loop": "FIC101"},
            {"tag": "FIC101.MODE", "role": "mode", "loop": "FIC101"},
            {"tag": "FEED_RATE", "role": "input"},
            {"tag": "DENSITY", "role": "input"},
            {"tag": "PRODUCT_CONC", "role": "target"},
        ],
        "loops": [
            {
                "id": "FIC101",
                "pv": "FIC101.PV",
                "sp": "FIC101.SP",
                "out": "FIC101.OUT",
                "mode": "FIC101.MODE",
            }
        ],
        "labs": [
            {
                "id": "LAB01",
                "variable": "PRODUCT_CONC",
                "tag": "PRODUCT_CONC",
                "stamp": {"meaning": "end"},
            }
        ],
    }
    save_site(tmp_path, site_doc)
    return TestClient(create_app(tmp_path)), tmp_path


def test_clean_dataset_readiness_endpoint(clean_dataset_client: tuple[TestClient, Path]) -> None:
    client, _ = clean_dataset_client
    res = client.get("/datasets/synthetic_ds/readiness")
    assert res.status_code == 200
    data = res.json()
    assert data["dataset_id"] == "synthetic_ds"
    assert data["verdict"] == "ok"
    assert data["modules"]["loops"]["status"] == "ok"
    assert data["modules"]["anomaly"]["status"] == "ok"
    assert data["modules"]["softsensor"]["status"] == "ok"


def test_missing_out_reports_loop_amber_endpoint(
    clean_dataset_client: tuple[TestClient, Path],
) -> None:
    client, root = clean_dataset_client
    site_file = root / "_site" / "site.json"
    doc = json.loads(site_file.read_text(encoding="utf-8"))
    # Remove out tag mapping from loop
    doc["loops"][0]["out"] = ""
    site_file.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    res = client.get("/datasets/synthetic_ds/readiness")
    assert res.status_code == 200
    data = res.json()
    assert data["modules"]["loops"]["status"] == "warning"
    assert any("no OUT tag mapped" in r for r in data["modules"]["loops"]["reasons"])
    assert data["verdict"] == "warning"


def test_missing_target_reports_softsensor_red_endpoint(
    clean_dataset_client: tuple[TestClient, Path],
) -> None:
    client, root = clean_dataset_client
    site_file = root / "_site" / "site.json"
    doc = json.loads(site_file.read_text(encoding="utf-8"))
    # Remove target role
    doc["signals"] = [s for s in doc["signals"] if s.get("role") != "target"]
    site_file.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    res = client.get("/datasets/synthetic_ds/readiness")
    assert res.status_code == 200
    data = res.json()
    assert data["modules"]["softsensor"]["status"] == "not_ready"
    assert any("No target tag mapped" in r for r in data["modules"]["softsensor"]["reasons"])
    assert data["verdict"] == "not_ready"

"""Tests of the soft sensor routes: config, lab CSV, fit, model summary and run on a simulation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from crosscut_api.app import DatasetStore, create_app
from crosscut_sim.run import main as run_simulation
from fastapi.testclient import TestClient

PREFIX = "sim.mc."
INPUTS = [PREFIX + "mill_power", PREFIX + "p80", PREFIX + "mill_feed"]
CONFIG: dict[str, Any] = {
    "schema_version": "1.0.0",
    "id": "p80lab",
    "target_tag": PREFIX + "p80",
    "input_tags": INPUTS,
    "mode": "advisory",
    "lags_s": [0, 20],
    "lab_delay_s": 120,
    "sample_period_s": 20,
    "max_components": 3,
    "cv_blocks": 3,
}
GOOD_CSV = "sample_time;value\n0;1,5\n60;2,5\n"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A data root holding a fresh 1-hour mill_circuit simulation."""
    argv = ["--plant", "mill_circuit", "--duration", "1h", "--sample-period", "10"]
    assert run_simulation([*argv, "--out", str(tmp_path)]) == 0
    return tmp_path


@pytest.fixture
def client(root: Path) -> TestClient:
    """A client on the simulated data root."""
    return TestClient(create_app(root))


def _dataset_id(client: TestClient) -> str:
    """The id of the one simulated dataset."""
    return client.get("/datasets").json()[0]["id"]


def _lab_csv(root: Path, dataset_id: str) -> str:
    """Lab results every 40 s: a known linear function of the bin means plus small noise."""
    _, columns = DatasetStore(root).load_seconds(dataset_id)
    bins = {tag: columns[tag][:360].reshape(-1, 2).mean(axis=1) for tag in INPUTS}
    truth = 3.0 * bins[INPUTS[0]] - 2.0 * bins[INPUTS[1]] + 0.5 * bins[INPUTS[2]]
    noise = np.random.default_rng(1).normal(0.0, 0.05 * truth.std(), len(truth))
    lines = [f"{20.0 * i},{float(truth[i] + noise[i])!r}" for i in range(0, len(truth), 2)]
    return "sample_time,value\n" + "\n".join(lines) + "\n"


def _fitted(client: TestClient, root: Path) -> str:
    """Save config and labs, fit on the whole record; return the dataset id."""
    dataset = _dataset_id(client)
    assert client.put("/softsensor/p80lab", json=CONFIG).status_code == 200
    body = {"csv_text": _lab_csv(root, dataset)}
    assert client.post("/softsensor/p80lab/lab", json=body).status_code == 200
    response = client.post(f"/datasets/{dataset}/softsensor/p80lab/fit", json={})
    assert response.status_code == 200, response.text
    return dataset


def _refuse_constant(name: str) -> float:
    """json.loads hook: NaN and Infinity must not appear in a response."""
    raise AssertionError(f"non-finite JSON constant {name}")


def test_config_round_trip_and_listing(client: TestClient) -> None:
    assert client.get("/softsensor").json() == []
    assert client.put("/softsensor/p80lab", json=CONFIG).json() == CONFIG
    assert client.get("/softsensor/p80lab").json() == CONFIG
    assert client.get("/softsensor").json() == ["p80lab"]
    assert client.get("/softsensor/nope").status_code == 404


def test_bad_configs_are_422_with_the_message(client: TestClient) -> None:
    response = client.put("/softsensor/p80lab", json={**CONFIG, "mode": "closed_loop"})
    assert response.status_code == 422 and "mode" in response.json()["detail"]
    assert client.put("/softsensor/other", json=CONFIG).status_code == 422
    assert client.get("/softsensor").json() == []


@pytest.mark.parametrize("sid", ["..", "a.b", "a b", "x" * 65, "..%2Fevil", "%2E%2E", "a%5Cevil"])
def test_unsafe_ids_are_refused_and_write_nothing(
    client: TestClient, root: Path, sid: str
) -> None:
    response = client.put(f"/softsensor/{sid}", json={**CONFIG, "id": sid})
    assert response.status_code in {404, 422}
    assert not list(root.glob("**/evil*"))
    assert client.get("/softsensor").json() == []


def test_lab_upload_is_normalised_and_read_back(client: TestClient, root: Path) -> None:
    assert client.put("/softsensor/p80lab", json=CONFIG).status_code == 200
    text = "﻿" + GOOD_CSV
    body = client.post("/softsensor/p80lab/lab", json={"csv_text": text}).json()
    assert body["count"] == 2 and body["rows"][0] == {"t_s": 0.0, "value": 1.5}
    again = client.get("/softsensor/p80lab/lab").json()
    assert again["first_s"] == 0.0 and again["last_s"] == 60.0 and again["count"] == 2
    stored = (root / "_softsensor" / "p80lab.lab.csv").read_text(encoding="utf-8")
    assert stored.startswith("sample_time,value\n")


def test_lab_iso_times_need_and_use_the_origin(client: TestClient) -> None:
    assert client.put("/softsensor/p80lab", json=CONFIG).status_code == 200
    csv_text = "sample_time,value\n2026-01-01T00:01:00Z,4\n"
    assert client.post("/softsensor/p80lab/lab", json={"csv_text": csv_text}).status_code == 422
    body = {"csv_text": csv_text, "origin_iso": "2026-01-01T00:00:00Z"}
    assert client.post("/softsensor/p80lab/lab", json=body).json()["rows"][0]["t_s"] == 60.0


@pytest.mark.parametrize(
    "text",
    ["", "a,b\n1,2\n", "sample_time,value\n", "sample_time,value\n1,x\n",
     "sample_time,value\nx,1\n", "sample_time,value\n1\n", "sample_time,value\n1,nan\n"],
)
def test_bad_lab_csv_is_422(client: TestClient, text: str) -> None:
    assert client.put("/softsensor/p80lab", json=CONFIG).status_code == 200
    assert client.post("/softsensor/p80lab/lab", json={"csv_text": text}).status_code == 422
    assert client.get("/softsensor/p80lab/lab").status_code == 404


def test_oversized_lab_csv_is_422(client: TestClient) -> None:
    assert client.put("/softsensor/p80lab", json=CONFIG).status_code == 200
    text = "sample_time,value\n" + "1,2\n" * 300_000
    assert client.post("/softsensor/p80lab/lab", json={"csv_text": text}).status_code == 422


def test_lab_of_an_unknown_sensor_is_404(client: TestClient) -> None:
    assert client.post("/softsensor/zzz/lab", json={"csv_text": GOOD_CSV}).status_code == 404
    assert client.get("/softsensor/zzz/lab").status_code == 404


def test_fit_stores_model_and_manifest_and_the_summary_matches(
    client: TestClient, root: Path
) -> None:
    dataset = _fitted(client, root)
    summary = client.get("/softsensor/p80lab/model").json()
    assert 1 <= summary["chosen_components"] <= summary["n_components"] <= 3
    assert len(summary["cv_rmse"]) == 3 and summary["cv_sigma"] > 0
    assert summary["n_train"] >= 10 and summary["r2_train"] > 0.9
    assert summary["dataset_id"] == dataset and len(summary["sha256"]) == 64
    manifest = json.loads((root / "_softsensor" / "p80lab.manifest.json").read_text("utf-8"))
    assert manifest["kind"] == "softsensor_pls" and manifest["model_sha256"] == summary["sha256"]


def test_fit_respects_train_end_and_reports_errors(client: TestClient, root: Path) -> None:
    dataset = _dataset_id(client)
    url = f"/datasets/{dataset}/softsensor/p80lab/fit"
    assert client.post(url, json={}).status_code == 404
    assert client.put("/softsensor/p80lab", json=CONFIG).status_code == 200
    assert client.post(url, json={}).status_code == 404
    client.post("/softsensor/p80lab/lab", json={"csv_text": _lab_csv(root, dataset)})
    assert client.post(url, json={"train_end_s": 1500}).json()["window"]["end_s"] == 1500
    assert client.post(url, json={"train_end_s": -5}).status_code == 422
    assert client.post(url, json={"train_end_s": 200}).status_code == 422
    assert client.post("/datasets/nope/softsensor/p80lab/fit", json={}).status_code == 404


def test_fit_and_run_name_an_unknown_tag(client: TestClient, root: Path) -> None:
    dataset = _dataset_id(client)
    bad = {**CONFIG, "input_tags": [*INPUTS, "no.such.tag"]}
    assert client.put("/softsensor/p80lab", json=bad).status_code == 200
    client.post("/softsensor/p80lab/lab", json={"csv_text": _lab_csv(root, dataset)})
    response = client.post(f"/datasets/{dataset}/softsensor/p80lab/fit", json={})
    assert response.status_code == 422 and "no.such.tag" in response.json()["detail"]


def test_model_and_run_before_fit_are_404(client: TestClient) -> None:
    assert client.put("/softsensor/p80lab", json=CONFIG).status_code == 200
    assert client.get("/softsensor/p80lab/model").status_code == 404
    response = client.post(f"/datasets/{_dataset_id(client)}/softsensor/p80lab/run", json={})
    assert response.status_code == 404 and "not fitted" in response.json()["detail"]


def test_run_reports_validity_and_no_drift_on_stable_data(
    client: TestClient, root: Path
) -> None:
    dataset = _fitted(client, root)
    response = client.post(
        f"/datasets/{dataset}/softsensor/p80lab/run", json={"max_points": 50}
    )
    body = json.loads(response.text, parse_constant=_refuse_constant)
    counts = body["validity_counts"]
    assert set(counts) == {"ok", "missing_input", "out_of_range", "extrapolation"}
    assert sum(counts.values()) == 180 and counts["ok"] > 100 and counts["missing_input"] >= 1
    assert body["drift_episodes"] == [] and not body["latest"]["drift"]
    series = body["series"]
    assert len(series["t_s"]) <= 50 and len(series["estimate"]) == len(series["t_s"])
    assert body["n_lab_used"] > 10 and body["lab_points"]
    assert body["latest"]["bias"] is not None


def test_run_with_changed_inputs_is_stale(client: TestClient, root: Path) -> None:
    dataset = _fitted(client, root)
    changed = {**CONFIG, "input_tags": INPUTS[:2]}
    assert client.put("/softsensor/p80lab", json=changed).status_code == 200
    response = client.post(f"/datasets/{dataset}/softsensor/p80lab/run", json={})
    assert response.status_code == 422 and "stale" in response.json()["detail"]


def test_writes_stay_under_the_softsensor_folder(client: TestClient, root: Path) -> None:
    before = {p for p in root.rglob("*") if p.is_file()}
    _fitted(client, root)
    new = {p for p in root.rglob("*") if p.is_file()} - before
    assert new and all((root / "_softsensor") in p.parents for p in new)

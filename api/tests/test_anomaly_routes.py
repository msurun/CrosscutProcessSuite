"""Tests of the anomaly routes: config storage, fit, model summary and scan on a simulation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from crosscut_api.app import create_app
from crosscut_sim.run import main as run_simulation
from fastapi.testclient import TestClient

PREFIX = "sim.mc."
TAGS = ["mill_power", "p80", "mill_feed", "hpgr_power", "feed_moisture"]
CONFIG: dict[str, Any] = {
    "schema_version": "1.0.0",
    "id": "mc",
    "tags": [PREFIX + tag for tag in TAGS],
    "mode": "advisory",
    "sample_period_s": 20,
}
SHIFTED_TAG = PREFIX + "p80"
SHIFT_FROM_S = 2400.0


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


def _fitted(client: TestClient) -> str:
    """Save the standard config and fit it on the whole record; return the dataset id."""
    assert client.put("/anomaly/mc", json=CONFIG).status_code == 200
    dataset = _dataset_id(client)
    assert client.post(f"/datasets/{dataset}/anomaly/mc/fit", json={}).status_code == 200
    return dataset


def _shift_tag(root: Path) -> None:
    """Add eight standard deviations to one tag from SHIFT_FROM_S on (edits the parquet)."""
    path = next(root.rglob("part-*.parquet"))
    table = pq.read_table(path)
    tags, values = table["tag_id"].to_pylist(), table["value"].to_numpy().copy()
    ts = table["ts"].cast(pa.int64()).to_numpy()
    hit = [t == SHIFTED_TAG for t in tags]
    own = values[hit]
    after = (ts[hit] - ts[0]) / 1e9 >= SHIFT_FROM_S
    own[after] += 8 * own.std()
    values[hit] = own
    index = table.schema.get_field_index("value")
    pq.write_table(table.set_column(index, "value", pa.array(values)), path)


def test_config_round_trip_and_listing(client: TestClient) -> None:
    assert client.get("/anomaly").json() == []
    assert client.put("/anomaly/mc", json=CONFIG).json() == CONFIG
    assert client.get("/anomaly/mc").json() == CONFIG
    assert client.get("/anomaly").json() == ["mc"]
    assert client.get("/anomaly/nope").status_code == 404


def test_bad_configs_are_422_with_the_message(client: TestClient) -> None:
    response = client.put("/anomaly/mc", json={**CONFIG, "mode": "closed_loop"})
    assert response.status_code == 422 and "mode" in response.json()["detail"]
    assert client.put("/anomaly/other", json=CONFIG).status_code == 422
    assert client.put("/anomaly/mc", json={**CONFIG, "tags": ["a", "b"]}).status_code == 422
    assert client.get("/anomaly").json() == []


@pytest.mark.parametrize("aid", ["..", "a.b", "a b", "x" * 65, "..%2Fevil", "%2E%2E", "a%5Cevil"])
def test_unsafe_ids_are_refused_and_write_nothing(
    client: TestClient, root: Path, aid: str
) -> None:
    response = client.put(f"/anomaly/{aid}", json={**CONFIG, "id": aid})
    assert response.status_code in {404, 422}
    assert not list(root.glob("**/evil*"))
    assert client.get("/anomaly").json() == []


def test_fit_stores_model_and_manifest_and_the_summary_matches(
    client: TestClient, root: Path
) -> None:
    dataset = _fitted(client)
    summary = client.get("/anomaly/mc/model").json()
    assert 1 <= summary["k"] <= len(TAGS) and summary["n_train"] > 50
    assert summary["cumulative_variance"][-1] == pytest.approx(1.0)
    assert summary["t2_limit"] > 0 and summary["spe_limit"] > 0
    assert summary["dataset_id"] == dataset and len(summary["sha256"]) == 64
    manifest = json.loads((root / "_anomaly" / "mc.manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "anomaly_pca" and manifest["model_sha256"] == summary["sha256"]
    assert summary["window"]["start_s"] == 0.0


def test_fit_with_a_window_and_with_bad_input(client: TestClient) -> None:
    assert client.put("/anomaly/mc", json=CONFIG).status_code == 200
    url = f"/datasets/{_dataset_id(client)}/anomaly/mc/fit"
    assert client.post(url, json={"start_s": 600, "end_s": 3000}).json()["window"]["start_s"] == 600
    assert client.post(url, json={"start_s": 9, "end_s": 1}).status_code == 422
    assert client.post(url, json={"start_s": 1e9}).status_code == 422
    assert client.post("/datasets/nope/anomaly/mc/fit", json={}).status_code == 404


def test_fit_names_a_missing_tag(client: TestClient) -> None:
    bad = {**CONFIG, "tags": [*CONFIG["tags"], "no.such.tag"]}
    assert client.put("/anomaly/mc", json=bad).status_code == 200
    response = client.post(f"/datasets/{_dataset_id(client)}/anomaly/mc/fit", json={})
    assert response.status_code == 404 and "no.such.tag" in response.json()["detail"]


def test_model_and_scan_before_fit_are_404(client: TestClient) -> None:
    assert client.put("/anomaly/mc", json=CONFIG).status_code == 200
    assert client.get("/anomaly/mc/model").status_code == 404
    scan_url = f"/datasets/{_dataset_id(client)}/anomaly/mc/scan"
    response = client.post(scan_url, json={})
    assert response.status_code == 404 and "not fitted" in response.json()["detail"]


def test_scan_of_the_training_record_is_quiet_and_json_is_finite(client: TestClient) -> None:
    dataset = _fitted(client)
    response = client.post(f"/datasets/{dataset}/anomaly/mc/scan", json={"max_points": 50})
    body = json.loads(response.text, parse_constant=_refuse_constant)
    assert len(body["events"]) <= 1 and body["n_valid"] > 50
    series = body["series"]
    assert len(series["t_s"]) <= 50
    assert len(series["t2"]) == len(series["spe"]) == len(series["t_s"])


def _refuse_constant(name: str) -> float:
    """json.loads hook: NaN and Infinity must not appear in a response."""
    raise AssertionError(f"non-finite JSON constant {name}")


def test_scan_finds_a_shifted_tag(root: Path) -> None:
    dataset = _fitted(TestClient(create_app(root)))
    _shift_tag(root)
    client = TestClient(create_app(root))
    body = client.post(f"/datasets/{dataset}/anomaly/mc/scan", json={}).json()
    assert body["events"], "the shift produced no event"
    event = body["events"][-1]
    assert event["start_s"] >= SHIFT_FROM_S - 200
    assert event["top_spe_tags"][0] == event["top_t2_tags"][0] == SHIFTED_TAG
    assert max(body["series"]["spe"]) > body["series"]["spe_limit"]
    contribution = event["contributions"]["spe"]
    assert max(contribution, key=lambda tag: contribution[tag]) == SHIFTED_TAG


def test_bad_quality_samples_are_skipped_not_imputed(root: Path) -> None:
    dataset = _fitted(TestClient(create_app(root)))
    path = next(root.rglob("part-*.parquet"))
    table = pq.read_table(path)
    quality = table["quality"].to_numpy().copy()
    quality[: 6 * len(TAGS) * 20] = 2
    index = table.schema.get_field_index("quality")
    pq.write_table(table.set_column(index, "quality", pa.array(quality)), path)
    body = TestClient(create_app(root)).post(
        f"/datasets/{dataset}/anomaly/mc/scan", json={}
    ).json()
    assert body["n_skipped"] >= 5 and body["skipped_reasons"]["nan"] >= 5

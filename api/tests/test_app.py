"""Tests for the read-only dataset API (FastAPI, driven through TestClient)."""

from __future__ import annotations

from pathlib import Path

import pytest
from crosscut_api.app import create_app
from crosscut_sim.run import main as run_simulation
from fastapi.testclient import TestClient

TOP = "sim.wb.top_comp"


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("datasets")
    code = run_simulation(
        ["--plant", "wood_berry", "--scenario", "nominal", "--duration", "10m", "--out", str(root)]
    )
    assert code == 0
    return root


@pytest.fixture(scope="module")
def client(data_root: Path) -> TestClient:
    return TestClient(create_app(data_root))


DATASET = "wood_berry_nominal_seed42"


def test_health_reports_ok(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_datasets_lists_recorded_datasets(client: TestClient) -> None:
    body = client.get("/datasets").json()
    assert [d["id"] for d in body] == [DATASET]
    assert body[0]["n_tags"] > 0 and body[0]["n_samples"] == 600


def test_tags_returns_the_tag_catalog(client: TestClient) -> None:
    tags = client.get(f"/datasets/{DATASET}/tags").json()
    assert TOP in {t["id"] for t in tags}


def test_series_returns_raw_points_when_the_window_is_small(client: TestClient) -> None:
    resp = client.get(f"/datasets/{DATASET}/series", params={"tag": TOP, "max_points": 1000})
    series = resp.json()["series"][0]
    assert series["tag"] == TOP and series["downsampled"] is False
    assert len(series["t"]) == 600
    assert series["min"] == series["max"] == series["mean"]


def test_series_downsamples_when_the_window_is_large(client: TestClient) -> None:
    resp = client.get(f"/datasets/{DATASET}/series", params={"tag": TOP, "max_points": 50})
    series = resp.json()["series"][0]
    assert series["downsampled"] is True and len(series["t"]) <= 50


def test_series_supports_several_tags_and_a_time_window(client: TestClient) -> None:
    all_t = client.get(
        f"/datasets/{DATASET}/series", params={"tag": TOP, "max_points": 1000}
    ).json()["series"][0]["t"]
    resp = client.get(
        f"/datasets/{DATASET}/series",
        params={
            "tag": [TOP, "sim.wb.bottom_comp"],
            "start": all_t[100],
            "end": all_t[199],
            "max_points": 1000,
        },
    )
    series = resp.json()["series"]
    assert [s["tag"] for s in series] == [TOP, "sim.wb.bottom_comp"]
    assert series[0]["t"] == all_t[100:200]


def test_unknown_dataset_and_unknown_tag_give_404(client: TestClient) -> None:
    assert client.get("/datasets/nope/tags").status_code == 404
    resp = client.get(f"/datasets/{DATASET}/series", params={"tag": "no.such.tag"})
    assert resp.status_code == 404


def test_dataset_id_cannot_escape_the_data_root(client: TestClient) -> None:
    assert client.get("/datasets/..%2F..%2Fetc/tags").status_code in (400, 404)


def test_invalid_max_points_gives_422(client: TestClient) -> None:
    resp = client.get(f"/datasets/{DATASET}/series", params={"tag": TOP, "max_points": 1})
    assert resp.status_code == 422


def test_series_without_tag_gives_422(client: TestClient) -> None:
    assert client.get(f"/datasets/{DATASET}/series").status_code == 422


def test_nan_values_are_serialised_as_null() -> None:
    import numpy as np
    from crosscut_api.app import _json_floats

    assert _json_floats(np.array([1.0, np.nan])) == [1.0, None]


def test_a_dotdot_dataset_id_is_not_found(data_root: Path) -> None:
    from crosscut_api.app import _dataset_dir
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as err:
        _dataset_dir(data_root, "..")
    assert err.value.status_code == 404

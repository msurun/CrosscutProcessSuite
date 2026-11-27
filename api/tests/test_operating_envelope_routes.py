"""Operating-envelope route: descriptive per-mode quantiles, stopped samples, permission."""

import json
from pathlib import Path

import numpy as np
import pytest
from crosscut_api.auth.route_permissions import ROUTE_PERMISSIONS
from crosscut_sim.dataset import DatasetInfo, Samples, write_dataset
from fastapi.testclient import TestClient
from open_app import create_app_without_auth

START_NS = 1767225600000000000  # 2026-01-01T00:00:00Z, Unix nanoseconds
TAGS = ["rec", "feed", "run"]
URL = "/datasets/mill/operating-envelope"
N = 600


def _site() -> dict:
    """Catalogue with two modes by feed and a stopped mode by the run flag."""
    clause = lambda op, value, tag="feed": {"tag": tag, "op": op, "value": value}  # noqa: E731
    mode = lambda name, *clauses: {"id": name, "condition": {"clauses": list(clauses)}}  # noqa: E731
    return {"schema_version": 1, "site": {"id": "t", "name": "T"},
            "tags": [{"id": tag} for tag in TAGS],
            "modes": [mode("stopped", clause("<", 0.5, "run")), mode("low", clause("<", 50)),
                      mode("high", clause(">=", 50))]}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Dataset where recovery peaks near feed 30 (low mode) and 70 (high mode)."""
    rng = np.random.default_rng(3)
    feed = rng.uniform(0, 100, N)
    peak = np.where(feed < 50, 30.0, 70.0)
    rec = 90 - 0.01 * (feed - peak) ** 2 + rng.normal(0, 0.3, N)
    run = np.ones(N)
    run[:60] = 0
    rec[:60] = 1e5
    values = np.column_stack((rec, feed, run))
    samples = Samples(START_NS + np.arange(N) * 10**9, TAGS, values,
                      np.zeros_like(values, dtype=np.uint8))
    tags = {"schema_version": "1.0.0", "tags": [
        {"id": tag, "name": tag, "unit": "", "type": "float", "role": "other"} for tag in TAGS]}
    info = DatasetInfo("mill", {"kind": "sim", "plant": "mill", "seed": 3},
                       "2026-01-01T00:00:00Z", tags)
    write_dataset(tmp_path / "mill", samples, info)
    (tmp_path / "_site").mkdir()
    (tmp_path / "_site" / "site.json").write_text(json.dumps(_site()), encoding="utf-8")
    return tmp_path


def test_envelope_per_mode_with_window_and_definitions(root: Path) -> None:
    """Modes, coverage, window and the mode definitions come back; stopped data is excluded."""
    response = TestClient(create_app_without_auth(root)).get(
        URL, params={"outcome": "rec", "x": "feed", "bins": 5, "min_count": 10})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["modes"]) == {"low", "high"}
    assert body["excluded_stopped"] == 60
    assert body["window"]["start_utc"] == "2026-01-01T00:00:00Z"
    assert body["window"]["end_utc"] == "2026-01-01T00:09:59Z"
    assert {m["id"] for m in body["mode_definitions"]} == {"stopped", "low", "high"}
    assert max(c["p90"] for m in body["modes"].values() for c in m["cells"] if c["p90"]) < 100


def test_errors_and_validation(root: Path) -> None:
    """An unknown tag is 422 with a message; an out-of-range option is rejected."""
    client = TestClient(create_app_without_auth(root))
    assert client.get(URL, params={"outcome": "nope", "x": "feed"}).status_code == 422
    assert client.get(URL, params={"outcome": "rec", "x": "feed", "bins": 1}).status_code == 422
    assert client.get("/datasets/absent/operating-envelope",
                      params={"outcome": "rec", "x": "feed"}).status_code == 404


def test_without_catalogue_modes_everything_is_one_mode(root: Path) -> None:
    """No modes in the catalogue: one mode called all."""
    (root / "_site" / "site.json").unlink()
    body = TestClient(create_app_without_auth(root)).get(
        URL, params={"outcome": "rec", "x": "feed"}).json()
    assert list(body["modes"]) == ["all"]


def test_route_needs_analysis_run() -> None:
    """The route is mapped to analysis.run like the other analysis routes."""
    assert ROUTE_PERMISSIONS[("GET", "/datasets/{dataset_id}/operating-envelope")] == "analysis.run"

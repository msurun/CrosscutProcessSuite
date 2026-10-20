"""Tests for the read-only dataset API (FastAPI, driven through TestClient)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from crosscut_api.app import create_app
from crosscut_sim.run import main as run_simulation
from fastapi.testclient import TestClient

TOP = "sim.wb.top_comp"


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a temporary folder holding datasets from a nominal 10-minute simulation."""
    root = tmp_path_factory.mktemp("datasets")
    code = run_simulation(
        ["--plant", "wood_berry", "--scenario", "nominal", "--duration", "10m", "--out", str(root)]
    )
    assert code == 0
    return root


@pytest.fixture(scope="module")
def client(data_root: Path) -> TestClient:
    """Create a test HTTP client backed by an app rooted at the given data directory."""
    return TestClient(create_app(data_root))


DATASET = "wood_berry_nominal_seed42"


def test_health_reports_ok(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_datasets_lists_recorded_datasets(client: TestClient) -> None:
    """The /datasets endpoint lists the recorded dataset with its tag and sample counts."""
    datasets = client.get("/datasets").json()
    assert [dataset["id"] for dataset in datasets] == [DATASET]
    assert datasets[0]["n_tags"] > 0 and datasets[0]["n_samples"] == 600


def test_tags_returns_the_tag_catalog(client: TestClient) -> None:
    """The tags endpoint returns the catalog containing the top tag."""
    tags = client.get(f"/datasets/{DATASET}/tags").json()
    assert TOP in {tag["id"] for tag in tags}


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
    assert [one_series["tag"] for one_series in series] == [TOP, "sim.wb.bottom_comp"]
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


@pytest.fixture(scope="module")
def loops_client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    """Run a short mill circuit simulation and return a test client reading its results."""
    root = tmp_path_factory.mktemp("mill")
    argv = [
        "--plant",
        "mill_circuit",
        "--duration",
        "1h",
        "--sample-period",
        "10",
        "--out",
        str(root),
    ]
    assert run_simulation(argv) == 0
    return TestClient(create_app(root))


def test_loops_endpoint_reports_each_discovered_loop_as_json(loops_client: TestClient) -> None:
    dataset = loops_client.get("/datasets").json()[0]["id"]
    body = loops_client.get(f"/datasets/{dataset}/loops").json()
    assert body["dataset_id"] == dataset
    assert [loop["name"] for loop in body["loops"]] == ["hpgr_press", "mill_feed", "cyc_water"]
    first = body["loops"][0]
    assert {"name", "status", "health_percent", "findings", "sparkline", "pv", "mode"} <= set(first)
    assert first["status"] in {"ok", "warning", "problem", "unused", "not_assessed"}


def test_loops_endpoint_returns_404_for_an_unknown_dataset(client: TestClient) -> None:
    assert client.get("/datasets/nope/loops").status_code == 404


def test_loops_endpoint_uses_the_project_file_with_its_names_and_settings(
    data_root: Path, client: TestClient
) -> None:
    project = _build_loops_project()
    project_file = _write_project_file(data_root, project)
    try:
        loops = _fetch_loops(client)
    finally:
        project_file.unlink()
    assert [loop["name"] for loop in loops] == ["Top composition"]
    assert loops[0]["out"] == "sim.wb.reflux"


def _build_loops_project() -> dict:
    """Return the project payload with a single loop definition, as stored on disk."""
    return {
        "loops": [
            {
                "id": "top",
                "name": "Top composition",
                "pv": "sim.wb.top_comp",
                "sp": "sim.wb.top_comp_sp",
                "out": "sim.wb.reflux",
                "mode": "sim.wb.top_comp_mode",
                "delay_s": 1.0,
                "ultimate_period_s": 6.0,
            }
        ]
    }


def _write_project_file(data_root: Path, project: dict) -> Path:
    """Write the project payload to the dataset's project.json and return its path."""
    project_file = data_root / DATASET / "project.json"
    project_file.write_text(json.dumps(project))
    return project_file


def _fetch_loops(client: TestClient) -> list:
    """Return the loops the endpoint reports for the dataset."""
    return client.get(f"/datasets/{DATASET}/loops").json()["loops"]


@pytest.fixture(scope="module")
def step_test_client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    """Run the step-test simulation into a temp folder and return a client for its data."""
    root = tmp_path_factory.mktemp("steps")
    argv = ["--plant", "mill_circuit", "--scenario", "step_test", "--duration", "3h"]
    assert run_simulation([*argv, "--sample-period", "5", "--out", str(root)]) == 0
    return TestClient(create_app(root))


def test_tuning_endpoint_finds_the_step_window_and_proposes_settings(
    step_test_client: TestClient,
) -> None:
    dataset = step_test_client.get("/datasets").json()[0]["id"]
    body = step_test_client.get(f"/datasets/{dataset}/loops/hpgr_press/tuning").json()
    assert body["windows"] and body["window"]["manual_percent"] == 100
    assert body["model"]["gain"] > 0 and body["fit"]["verdict"] in {"good", "fair"}
    assert body["settings"]["simc"]["kc"] > 0 and body["blocked_code"] is None
    assert len(body["step"]["t_s"]) == len(body["step"]["pv"]) and "# " in body["markdown"]


def test_tuning_endpoint_is_slower_but_calmer_with_more_robustness(
    step_test_client: TestClient,
) -> None:
    dataset = step_test_client.get("/datasets").json()[0]["id"]
    url = f"/datasets/{dataset}/loops/mill_feed/tuning"
    fast = step_test_client.get(url, params={"robustness": 0.0}).json()["settings"]["simc"]
    robust = step_test_client.get(url, params={"robustness": 1.0}).json()["settings"]["simc"]
    assert robust["kc"] < fast["kc"]


def test_tuning_endpoint_returns_404_for_an_unknown_loop(step_test_client: TestClient) -> None:
    dataset = step_test_client.get("/datasets").json()[0]["id"]
    assert step_test_client.get(f"/datasets/{dataset}/loops/nope/tuning").status_code == 404


def test_benefit_endpoint_returns_estimate_assumptions_and_curves(
    step_test_client: TestClient,
) -> None:
    dataset = step_test_client.get("/datasets").json()[0]["id"]
    url = f"/datasets/{dataset}/loops/mill_feed/benefit"
    body = step_test_client.get(url, params={"value_per_unit_h": 100.0}).json()
    assert body["assumptions"]["limit_is_default"] is True
    assert body["estimate"]["std_target"] < body["estimate"]["std_now"]
    assert body["estimate"]["value_per_h"] >= 0.0 and "no_value" not in body["notes"]
    curves = body["curves"]
    assert len(curves["x"]) == len(curves["now"]) == len(curves["after"])


def test_benefit_endpoint_uses_the_given_limit_and_flags_a_missing_value(
    step_test_client: TestClient,
) -> None:
    dataset = step_test_client.get("/datasets").json()[0]["id"]
    url = f"/datasets/{dataset}/loops/mill_feed/benefit"
    body = step_test_client.get(url, params={"limit": 400.0}).json()
    assert body["assumptions"]["limit"] == 400.0
    assert body["assumptions"]["limit_is_default"] is False
    assert "no_value" in body["notes"]


def test_benefit_endpoint_rejects_an_impossible_reduction(step_test_client: TestClient) -> None:
    dataset = step_test_client.get("/datasets").json()[0]["id"]
    url = f"/datasets/{dataset}/loops/mill_feed/benefit"
    assert step_test_client.get(url, params={"std_reduction": 1.5}).status_code == 422
    assert step_test_client.get(f"/datasets/{dataset}/loops/nope/benefit").status_code == 404


def test_benefit_endpoint_takes_the_variability_cut_from_a_measured_retune(
    step_test_client: TestClient,
) -> None:
    dataset = step_test_client.get("/datasets").json()[0]["id"]
    url = f"/datasets/{dataset}/loops/mill_feed/benefit"
    body = step_test_client.get(url, params={"std_before": 2.0, "std_after": 1.0}).json()
    assert body["assumptions"]["std_reduction_source"] == "retune_measured"
    assert body["assumptions"]["std_reduction"] == 0.5
    default = step_test_client.get(url).json()
    assert default["assumptions"]["std_reduction_source"] == "assumed"


def test_benefit_endpoint_rejects_a_zero_spread_before_the_retune(
    step_test_client: TestClient,
) -> None:
    dataset = step_test_client.get("/datasets").json()[0]["id"]
    url = f"/datasets/{dataset}/loops/mill_feed/benefit"
    response = step_test_client.get(url, params={"std_before": 0.0, "std_after": 1.0})
    assert response.status_code == 422


@pytest.fixture(scope="module")
def fresh_wood_berry_client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    """Record a Wood-Berry run into its own folder so its project file stays intact."""
    root = tmp_path_factory.mktemp("wood_berry_fresh")
    argv = ["--plant", "wood_berry", "--scenario", "nominal", "--duration", "10m"]
    assert run_simulation([*argv, "--out", str(root)]) == 0
    return TestClient(create_app(root))


def test_a_wood_berry_run_reports_both_composition_loops_with_a_health_value_or_none(
    fresh_wood_berry_client: TestClient,
) -> None:
    loops = _fetch_loops(fresh_wood_berry_client)
    assert [loop["name"] for loop in loops] == ["Top composition", "Bottom composition"]
    # None means "not scored" (no Harris index on a 10-minute run), never an imputed number.
    healths = [loop["health_percent"] for loop in loops]
    assert all(health is None or 0 <= health <= 100 for health in healths)

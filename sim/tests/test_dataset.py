"""Tests for recording a plant run into a Parquet dataset and reading it back."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from crosscut_sim.core import Scenario
from crosscut_sim.dataset import (
    DEFAULT_START_UTC,
    RunInfo,
    compute_data_sha256,
    read_dataset,
    record,
    to_wide,
)
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.plants.wood_berry import NOMINAL, WoodBerryPlant
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
TOP = "sim.wb.top_comp"
N_TAGS = 11


def schema(name: str) -> dict[str, Any]:
    """Load the JSON schema file with this name from the schemas directory."""
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def rec(
    out: Path,
    scenario: Scenario,
    seed: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    """Record a WoodBerryPlant run for the given scenario and return the recording result."""
    run = RunInfo(
        seed=seed,
        dataset_id=f"wb_test_seed{seed}",
        plant_name="wood_berry",
        scenario_name="test",
        **kwargs,
    )
    return record(WoodBerryPlant(), scenario, out, run)


def test_layout_schema_and_contents(tmp_path: Path) -> None:
    doc = rec(tmp_path, Scenario(duration_s=600.0, measurement_noise=0.0), git_commit="abc1234")
    _assert_layout_files_exist(tmp_path)
    _assert_dataset_json_matches(tmp_path, doc)
    _assert_metadata_fields(doc)

    table = read_dataset(tmp_path)
    _assert_table_matches_doc(table, doc)
    _assert_timestamp_column(table, doc)


def _assert_layout_files_exist(tmp_path: Path) -> None:
    """Assert the dataset, tags and partitioned parquet files were written."""
    assert (tmp_path / "dataset.json").is_file()
    assert (tmp_path / "tags.json").is_file()
    assert _partition_directory_names(tmp_path) == ["date=2026-01-01"]
    assert (tmp_path / "data" / "date=2026-01-01" / "part-0.parquet").is_file()


def _partition_directory_names(tmp_path: Path) -> list[str]:
    """Return the sorted names of the partitions written under the data directory."""
    return sorted(partition_path.name for partition_path in (tmp_path / "data").iterdir())


def _assert_dataset_json_matches(tmp_path: Path, doc: dict) -> None:
    """Assert dataset.json round-trips and validates against its schema."""
    on_disk = json.loads((tmp_path / "dataset.json").read_text(encoding="utf-8"))
    assert on_disk == doc
    errors = list(Draft202012Validator(schema("dataset.schema.json")).iter_errors(on_disk))
    assert errors == [], [validation_error.message for validation_error in errors]
    tags_doc = json.loads((tmp_path / "tags.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema("tags.schema.json")).iter_errors(tags_doc)) == []


def _assert_metadata_fields(doc: dict) -> None:
    """Assert the metadata describes the sim scenario, storage layout and time range."""
    assert doc["source"] == {"kind": "sim", "plant": "wood_berry", "scenario": "test", "seed": 1}
    assert doc["storage"] == {
        "format": "parquet",
        "layout": "long",
        "partitioning": "daily",
        "path": "data",
    }
    assert doc["code"] == {"git_commit": "abc1234"}
    assert doc["row_count"] == 600 * N_TAGS
    assert doc["time_range"] == {"start_utc": DEFAULT_START_UTC, "end_utc": "2026-01-01T00:09:59Z"}
    assert len(doc["tags"]) == N_TAGS


def _assert_table_matches_doc(table: pa.Table, doc: dict) -> None:
    """Assert the parquet table row count and column types match the metadata."""
    assert table.num_rows == doc["row_count"]
    assert table.schema.field("ts").type == pa.timestamp("ns", tz="UTC")
    assert table.schema.field("tag_id").type == pa.string()
    assert table.schema.field("value").type == pa.float64()
    assert table.schema.field("quality").type == pa.uint8()


def _assert_timestamp_column(table: pa.Table, doc: dict) -> None:
    """Assert the ts column is sorted, starts at DEFAULT_START_UTC and hashes as recorded."""
    ts = table["ts"].cast(pa.int64()).to_numpy()
    assert np.all(np.diff(ts) >= 0)
    assert ts[0] == np.datetime64(DEFAULT_START_UTC.removesuffix("Z"), "ns").astype(np.int64)
    assert compute_data_sha256(table) == doc["data_sha256"]


def test_git_commit_is_optional(tmp_path: Path) -> None:
    doc = rec(tmp_path, Scenario(duration_s=10.0))
    assert "code" not in doc
    assert list(Draft202012Validator(schema("dataset.schema.json")).iter_errors(doc)) == []


def test_same_seed_gives_identical_data_and_different_seed_does_not(tmp_path: Path) -> None:
    scenario = Scenario(duration_s=300.0, measurement_noise=1.0, disturbance_sigma=0.02)
    recording_with_first_seed = rec(tmp_path / "a", scenario, seed=5)
    recording_with_same_seed = rec(tmp_path / "b", scenario, seed=5)
    recording_with_other_seed = rec(tmp_path / "c", scenario, seed=6)
    assert recording_with_first_seed["data_sha256"] == recording_with_same_seed["data_sha256"]
    assert recording_with_first_seed["data_sha256"] != recording_with_other_seed["data_sha256"]


def test_daily_partitions(tmp_path: Path) -> None:
    scenario = Scenario(duration_s=26 * 3600.0, dt_s=60.0, measurement_noise=0.0)
    doc = rec(tmp_path, scenario)
    partition_names = sorted(partition.name for partition in (tmp_path / "data").iterdir())
    assert partition_names == ["date=2026-01-01", "date=2026-01-02"]
    first_day = pq.read_table(tmp_path / "data" / "date=2026-01-01" / "part-0.parquet")
    second_day = pq.read_table(tmp_path / "data" / "date=2026-01-02" / "part-0.parquet")
    assert first_day.num_rows == 1440 * N_TAGS
    assert second_day.num_rows == 120 * N_TAGS
    assert doc["row_count"] == 1560 * N_TAGS
    assert read_dataset(tmp_path).num_rows == doc["row_count"]


def test_sample_period_must_be_a_multiple_of_the_step(tmp_path: Path) -> None:
    doc = rec(tmp_path / "ok", Scenario(duration_s=600.0), sample_period_s=10.0)
    assert doc["row_count"] == 60 * N_TAGS
    with pytest.raises(ValueError):
        rec(tmp_path / "bad1", Scenario(duration_s=600.0), sample_period_s=2.5)
    with pytest.raises(ValueError):
        rec(tmp_path / "bad2", Scenario(duration_s=600.0), sample_period_s=0.5)


def test_to_wide_matches_manual_stepping_sampled_before_each_step(tmp_path: Path) -> None:
    scenario = Scenario(duration_s=120.0, measurement_noise=1.0, disturbance_sigma=0.02)
    rec(tmp_path, scenario, seed=9)
    ts, wide = to_wide(read_dataset(tmp_path))
    assert ts.shape == (120,)
    assert set(wide) == set(WoodBerryPlant().tags.ids())

    plant = WoodBerryPlant()
    plant.reset(seed=9, scenario=scenario)
    for k in range(120):
        for tag_id in wide:
            assert wide[tag_id][k] == pytest.approx(plant.read(tag_id)[0], abs=1e-12)
        plant.step()
    assert wide[TOP][0] == pytest.approx(NOMINAL["top_comp"])
    assert (ts[1] - ts[0]) == np.timedelta64(1, "s")


def test_a_plant_with_injected_faults_stores_its_ground_truth(tmp_path: Path) -> None:
    scenario = Scenario(
        duration_s=60.0,
        params=(("stiction_band_hpgr_press", 2.0), ("stiction_jump_hpgr_press", 1.0)),
    )
    run = RunInfo(seed=1, dataset_id="mill_fault", plant_name="mill_circuit")
    doc = record(MillCircuitPlant(), scenario, tmp_path, run)
    expected = {"hpgr_press": {"stiction_band": 2.0, "stiction_jump": 1.0}}
    assert doc["source"]["ground_truth"] == expected
    assert list(Draft202012Validator(schema("dataset.schema.json")).iter_errors(doc)) == []


def test_a_healthy_plant_stores_no_ground_truth(tmp_path: Path) -> None:
    doc = record(
        MillCircuitPlant(), Scenario(duration_s=60.0), tmp_path,
        RunInfo(seed=1, dataset_id="mill_ok", plant_name="mill_circuit"),
    )
    assert "ground_truth" not in doc["source"]

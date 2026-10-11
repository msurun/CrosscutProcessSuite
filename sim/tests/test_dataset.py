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
    compute_data_sha256,
    read_dataset,
    record,
    to_wide,
)
from crosscut_sim.plants.wood_berry import NOMINAL, WoodBerryPlant
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
TOP = "sim.wb.top_comp"
N_TAGS = 11


def schema(name: str) -> dict[str, Any]:
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def rec(
    out: Path,
    scenario: Scenario,
    seed: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    return record(
        WoodBerryPlant(),
        scenario,
        out,
        seed=seed,
        dataset_id=f"wb_test_seed{seed}",
        plant_name="wood_berry",
        scenario_name="test",
        **kwargs,
    )


def test_layout_schema_and_contents(tmp_path: Path) -> None:
    doc = rec(tmp_path, Scenario(duration_s=600.0, measurement_noise=0.0), git_commit="abc1234")
    assert (tmp_path / "dataset.json").is_file()
    assert (tmp_path / "tags.json").is_file()
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == ["date=2026-01-01"]
    assert (tmp_path / "data" / "date=2026-01-01" / "part-0.parquet").is_file()

    on_disk = json.loads((tmp_path / "dataset.json").read_text(encoding="utf-8"))
    assert on_disk == doc
    errors = list(Draft202012Validator(schema("dataset.schema.json")).iter_errors(on_disk))
    assert errors == [], [e.message for e in errors]
    tags_doc = json.loads((tmp_path / "tags.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema("tags.schema.json")).iter_errors(tags_doc)) == []

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

    table = read_dataset(tmp_path)
    assert table.num_rows == doc["row_count"]
    assert table.schema.field("ts").type == pa.timestamp("ns", tz="UTC")
    assert table.schema.field("tag_id").type == pa.string()
    assert table.schema.field("value").type == pa.float64()
    assert table.schema.field("quality").type == pa.uint8()
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
    a = rec(tmp_path / "a", scenario, seed=5)
    b = rec(tmp_path / "b", scenario, seed=5)
    c = rec(tmp_path / "c", scenario, seed=6)
    assert a["data_sha256"] == b["data_sha256"]
    assert a["data_sha256"] != c["data_sha256"]


def test_daily_partitions(tmp_path: Path) -> None:
    scenario = Scenario(duration_s=26 * 3600.0, dt_s=60.0, measurement_noise=0.0)
    doc = rec(tmp_path, scenario)
    parts = sorted(p.name for p in (tmp_path / "data").iterdir())
    assert parts == ["date=2026-01-01", "date=2026-01-02"]
    day1 = pq.read_table(tmp_path / "data" / "date=2026-01-01" / "part-0.parquet")
    day2 = pq.read_table(tmp_path / "data" / "date=2026-01-02" / "part-0.parquet")
    assert day1.num_rows == 1440 * N_TAGS
    assert day2.num_rows == 120 * N_TAGS
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

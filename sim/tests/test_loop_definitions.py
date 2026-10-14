"""Tests for the explicit control-loop definitions of each plant and their export.

A loop definition records the tag ids a controller needs: the process value, its
set-point, the actuator it writes and the auto/manual mode flag. These tests pin
the exact ids and the catalog, and check that the dataset writer and the CLI
runner export them as ``project.json`` next to the generated data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from crosscut_sim.loop_definitions import loop_definitions, write_project_file
from crosscut_sim.run import PLANTS, main

WOOD_BERRY_LOOPS = ["top", "bottom"]
MILL_CIRCUIT_LOOPS = ["hpgr_press", "mill_feed", "cyc_water"]
EXPECTED_KEYS = {"id", "name", "pv", "sp", "out", "mode"}
RUN_DURATION = "10m"
DEFAULT_SEED = 42


def _catalog_ids(plant_name: str) -> set[str]:
    """Return every tag id in the catalog of the plant built from :data:`PLANTS`."""
    plant = PLANTS[plant_name]()
    return {spec.id for spec in plant.tags}


def _loop_ids(plant_name: str) -> list[str]:
    """Return the loop ids of a plant in the order the module lists them."""
    return [definition["id"] for definition in loop_definitions(plant_name)]


def test_wood_berry_lists_its_two_loops_in_order() -> None:
    assert _loop_ids("wood_berry") == WOOD_BERRY_LOOPS


def test_mill_circuit_lists_its_three_loops_in_order() -> None:
    assert _loop_ids("mill_circuit") == MILL_CIRCUIT_LOOPS


def test_an_unknown_plant_name_is_refused() -> None:
    with pytest.raises(ValueError):
        loop_definitions("no_such_plant")


@pytest.mark.parametrize("plant_name", ["wood_berry", "mill_circuit"])
def test_every_referenced_tag_id_exists_in_the_plant_catalog(plant_name: str) -> None:
    available = _catalog_ids(plant_name)
    for definition in loop_definitions(plant_name):
        for field in ("pv", "sp", "out", "mode"):
            assert definition[field] in available


@pytest.mark.parametrize("plant_name", ["wood_berry", "mill_circuit"])
def test_every_loop_has_exactly_the_expected_keys_and_a_name(plant_name: str) -> None:
    for definition in loop_definitions(plant_name):
        assert set(definition) == EXPECTED_KEYS
        assert definition["name"]


def test_write_project_file_writes_the_json_and_returns_its_path(tmp_path: Path) -> None:
    path = write_project_file(tmp_path, "wood_berry")
    assert path == tmp_path / "project.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"loops": loop_definitions("wood_berry")}


def test_the_runner_exports_the_project_file_into_the_dataset_directory(tmp_path: Path) -> None:
    exit_code = main(
        ["--plant", "wood_berry", "--scenario", "nominal", "--duration", RUN_DURATION,
         "--out", str(tmp_path)]
    )
    dataset_dir = tmp_path / f"wood_berry_nominal_seed{DEFAULT_SEED}"
    written = json.loads((dataset_dir / "project.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert written == {"loops": loop_definitions("wood_berry")}

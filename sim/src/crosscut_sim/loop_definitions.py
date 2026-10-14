"""Explicit control-loop definitions of the simulated plants, written as a project.json.

The loop-monitoring code can guess loops from the tag naming convention, but Wood-Berry does not
follow it. A project file names the pv, sp, out and mode tag of every loop instead, so any plant
can be analysed the same way and the simulator can state which loops exist.
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_FILE = "project.json"

# Wood-Berry: each composition loop is closed by one manipulated flow.
_WOOD_BERRY_LOOPS = (
    ("top", "Top composition", "top_comp", "reflux"),
    ("bottom", "Bottom composition", "bottom_comp", "steam"),
)
_MILL_LOOPS = ("hpgr_press", "mill_feed", "cyc_water")


def loop_definitions(plant_name: str) -> list[dict[str, str]]:
    """Return the loops of a plant as dicts with id, name and the pv, sp, out and mode tag ids.

    Raises ValueError for a plant without definitions.
    """
    if plant_name == "wood_berry":
        return [_wood_berry_loop(*entry) for entry in _WOOD_BERRY_LOOPS]
    if plant_name == "mill_circuit":
        return [_mill_loop(loop_id) for loop_id in _MILL_LOOPS]
    raise ValueError(f"no loop definitions for plant {plant_name!r}")


def _wood_berry_loop(loop_id: str, name: str, controlled: str, manipulated: str) -> dict[str, str]:
    """Build one Wood-Berry loop: the controlled composition and the flow that moves it."""
    prefix = "sim.wb."
    return {
        "id": loop_id,
        "name": name,
        "pv": f"{prefix}{controlled}",
        "sp": f"{prefix}{controlled}_sp",
        "out": f"{prefix}{manipulated}",
        "mode": f"{prefix}{controlled}_mode",
    }


def _mill_loop(loop_id: str) -> dict[str, str]:
    """Build one mill-circuit loop; its tags follow the pv, _sp, _out, _mode convention.

    The name equals the id because the API addresses a loop (e.g. its tuning) by this name.
    """
    base = f"sim.mc.{loop_id}"
    return {
        "id": loop_id,
        "name": loop_id,
        "pv": base,
        "sp": f"{base}_sp",
        "out": f"{base}_out",
        "mode": f"{base}_mode",
    }


def write_project_file(dataset_dir: Path, plant_name: str) -> Path:
    """Write ``project.json`` with the plant's loops next to its dataset and return its path."""
    path = dataset_dir / PROJECT_FILE
    path.write_text(json.dumps({"loops": loop_definitions(plant_name)}), encoding="utf-8")
    return path

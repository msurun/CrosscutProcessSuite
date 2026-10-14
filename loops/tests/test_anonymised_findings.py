"""An anonymised export must give the same loop findings and stiction verdict as the original.

This is the promise of the customer kit: names, scales and absolute time are hidden but the dynamics
the analysis looks at are kept. The test runs the stiction scenario of the mill-circuit simulator,
anonymises the recording and compares the loop analysis of both.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from crosscut_connectors.anonymise import AnonymisedData, anonymise
from crosscut_loops.overview import LoopTags, analyze_dataset
from crosscut_sim.core import Event
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario

LOOP = "hpgr_press"
BASE = f"sim.mc.{LOOP}"
SAMPLE_EVERY_STEPS = 10  # 10 s samples: slower sampling hides stiction
DURATION_S = 6 * 3600.0
STICTION_BAND_PERCENT = 12.0  # a clearly sticking valve, found reliably even with full noise
SETPOINT_STEP = 1.0
STEP_TIME_S = 1800.0
SEED = 1


def _recording() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Simulate a sticking HPGR valve and sample PV, SP, OUT and MODE every 10 s."""
    scenario = build_scenario("mill_circuit", "stiction", duration_s=DURATION_S)
    params = dict(scenario.params)
    params[f"stiction_band_{LOOP}"] = STICTION_BAND_PERCENT
    params[f"stiction_jump_{LOOP}"] = STICTION_BAND_PERCENT / 2.0
    plant = MillCircuitPlant()
    plant.reset(SEED, dataclasses.replace(scenario, params=tuple(params.items())))
    setpoint = plant.read(f"{BASE}_sp")[0] + SETPOINT_STEP
    step = Event(t_s=STEP_TIME_S, tag_id=f"{BASE}_sp", value=setpoint)
    plant.reset(SEED, dataclasses.replace(scenario, params=tuple(params.items()), events=(step,)))
    names = {"pv": BASE, "sp": f"{BASE}_sp", "out": f"{BASE}_out", "mode": f"{BASE}_mode"}
    rows: dict[str, list[float]] = {key: [] for key in names}
    times: list[float] = []
    for index in range(int(DURATION_S)):
        if index % SAMPLE_EVERY_STEPS == 0:
            times.append(float(plant.time_s))
            for key, tag_id in names.items():
                rows[key].append(float(plant.read(tag_id)[0]))
        plant.step()
    return np.array(times), {names[key]: np.array(values) for key, values in rows.items()}


def _loop(names: dict[str, str], eng: dict[str, tuple[float, float]]) -> LoopTags:
    """The tag description of the HPGR loop under the given tag names and engineering ranges."""
    return LoopTags(
        LOOP, names["pv"], names["sp"], names["out"], names["mode"], "N/mm2",
        eng["pv"][0], eng["pv"][1], out_low=eng["out"][0], out_high=eng["out"][1],
    )  # fmt: skip


Range = tuple[float, float]
Rows = tuple[dict, dict]  # analysis row of the original and of the anonymised recording


def _scaled(data: AnonymisedData, new_name: str, low_high: Range) -> Range:
    """Engineering range of an anonymised tag: the same affine map as its values."""
    scale, offset = data.transforms[new_name]
    return scale * low_high[0] + offset, scale * low_high[1] + offset


@pytest.fixture(scope="module")
def both_rows() -> Rows:
    """Analysis rows of the original and the anonymised recording."""
    t_s, columns = _recording()
    suffixes = dict(pv="", sp="_sp", out="_out", mode="_mode")
    originals = {key: f"{BASE}{suffix}" for key, suffix in suffixes.items()}
    eng = {"pv": (0.0, 6.0), "out": (0.0, 100.0)}
    [original] = analyze_dataset(t_s, columns, [_loop(originals, eng)])
    anon = anonymise(
        t_s, columns, linked_groups=[[originals["pv"], originals["sp"]]],
        keep_values=[originals["mode"]], seed=7,
    )  # fmt: skip
    renamed = {key: anon.tag_map[name] for key, name in originals.items()}
    scaled = {
        "pv": _scaled(anon, renamed["pv"], eng["pv"]),
        "out": _scaled(anon, renamed["out"], eng["out"]),
    }
    [hidden] = analyze_dataset(anon.t_s, anon.columns, [_loop(renamed, scaled)])
    return original, hidden


def test_the_anonymised_export_gives_the_same_stiction_verdict(both_rows: Rows) -> None:
    """The stiction verdict depends on the shape of OUT, which survives a scale and offset."""
    original, hidden = both_rows
    assert hidden["stiction_verdict"] == original["stiction_verdict"]


def test_the_anonymised_export_gives_the_same_findings(both_rows: Rows) -> None:
    """The codes of the findings are the same in the original and the anonymised analysis."""
    original, hidden = both_rows
    codes = [[finding["code"] for finding in row["findings"]] for row in both_rows]
    assert codes[0] == codes[1]
    assert abs(original["health_percent"] - hidden["health_percent"]) <= 2

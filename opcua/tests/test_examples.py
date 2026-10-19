"""Tests for the pure helpers of the live OPC UA demo scripts.

The demo scripts live in ``opcua/examples`` and import heavy simulation packages, but their
pure helpers (scenario tweaking, recording, loop tags, error integrals) can be exercised
without starting a server. The examples folder is put on the import path so the scripts can
be imported by module name.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from crosscut_sim.scenarios import build_scenario

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))

import live_demo
import retune_demo


@pytest.fixture
def nominal_scenario():
    """A short nominal mill-circuit scenario used as a base by several tests."""
    return build_scenario("mill_circuit", "nominal", duration_s=600.0)


def test_a_valve_band_adds_the_band_and_its_slip_jump(nominal_scenario):
    """A band of 12 % becomes band 12.0 and jump 6.0 (half the band) for the demo loop."""
    tuned = live_demo.with_valve_band(nominal_scenario, 12.0)
    params = dict(tuned.params)
    assert params["stiction_band_hpgr_press"] == 12.0
    assert params["stiction_jump_hpgr_press"] == 6.0


def test_a_valve_band_keeps_the_existing_scenario_params(nominal_scenario):
    """Setting a band keeps every parameter the base scenario already carried."""
    tuned = live_demo.with_valve_band(nominal_scenario, 12.0)
    params = dict(tuned.params)
    for key, value in dict(nominal_scenario.params).items():
        assert params[key] == value


def test_a_zero_valve_band_returns_the_same_scenario_object(nominal_scenario):
    """A band of 0 leaves the scenario untouched, so the same object comes back."""
    assert live_demo.with_valve_band(nominal_scenario, 0.0) is nominal_scenario


def test_new_gains_replace_the_demo_loop_gains(nominal_scenario):
    """New gains set kc and Ti of the demo loop to the requested values."""
    tuned = retune_demo.with_gains(nominal_scenario, 3.0, 40.0)
    params = dict(tuned.params)
    assert params["kc_hpgr_press"] == 3.0
    assert params["ti_s_hpgr_press"] == 40.0


def test_new_gains_keep_the_other_scenario_params(nominal_scenario):
    """Applying new gains keeps every other parameter of the base scenario."""
    tuned = retune_demo.with_gains(nominal_scenario, 3.0, 40.0)
    params = dict(tuned.params)
    for key, value in dict(nominal_scenario.params).items():
        if key in ("kc_hpgr_press", "ti_s_hpgr_press"):
            continue
        assert params[key] == value


def test_applying_new_gains_does_not_mutate_the_original_scenario(nominal_scenario):
    """Gain tuning returns a new scenario and leaves the original params unchanged."""
    original_params = dict(nominal_scenario.params)
    retune_demo.with_gains(nominal_scenario, 3.0, 40.0)
    assert dict(nominal_scenario.params) == original_params


def test_a_recording_stores_the_time_and_the_four_values():
    """Adding one sample stores the time and the pv, sp, out and mode values."""
    recording = live_demo.Recording()
    recording.add(12.5, {"pv": 1.0, "sp": 1.5, "out": 2.0, "mode": 1.0})
    assert recording.t_s == [12.5]
    assert recording.values == {"pv": [1.0], "sp": [1.5], "out": [2.0], "mode": [1.0]}


def test_error_integral_counts_only_samples_from_the_setpoint_step():
    """Only samples at or after the step count: two errors of 2 and one of 1 give 5 * dt."""
    recording = live_demo.Recording()
    recording.t_s = [0.0, 600.0, 605.0, 610.0]
    recording.values = {
        "pv": [9.0, 9.0, 9.0, 9.0],
        "sp": [10.0, 10.0, 11.0, 11.0],
        "out": [0.0, 0.0, 0.0, 0.0],
        "mode": [0.0, 0.0, 0.0, 0.0],
    }
    assert retune_demo.error_integral(recording) == pytest.approx(5.0 * retune_demo.SAMPLE_S)


def test_the_loop_tags_point_at_the_demo_loop_nodes():
    """The tag description names the pv, sp, out and mode nodes of the demo loop."""
    tags = live_demo.loop_tags()
    assert tags.pv == "sim.mc.hpgr_press"
    assert tags.sp == "sim.mc.hpgr_press_sp"
    assert tags.out == "sim.mc.hpgr_press_out"
    assert tags.mode == "sim.mc.hpgr_press_mode"

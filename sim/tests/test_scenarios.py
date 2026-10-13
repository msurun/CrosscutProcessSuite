"""Tests for named scenarios and random-binary excitation events."""

from __future__ import annotations

import pytest
from crosscut_sim.core import Scenario
from crosscut_sim.plants.wood_berry import NOMINAL, WoodBerryPlant
from crosscut_sim.scenarios import (
    BinarySignal,
    available_scenarios,
    build_scenario,
    random_binary_events,
)

TOP_SP = "sim.wb.top_comp_sp"
BOT_SP = "sim.wb.bottom_comp_sp"
FEED = "sim.wb.feed_rate"
DAY = 6 * 3600.0


def test_available_scenarios() -> None:
    assert available_scenarios("wood_berry") == ("nominal", "noisy_feed", "feed_step", "excited")


def test_unknown_plant_or_scenario() -> None:
    with pytest.raises(ValueError):
        available_scenarios("no_such_plant")
    with pytest.raises(ValueError):
        build_scenario("no_such_plant", "nominal")
    with pytest.raises(ValueError):
        build_scenario("wood_berry", "no_such_scenario")


def test_nominal_and_noisy_feed() -> None:
    nominal = build_scenario("wood_berry", "nominal", duration_s=DAY)
    assert nominal.name == "nominal"
    assert nominal.duration_s == DAY
    assert nominal.measurement_noise == 1.0
    assert nominal.disturbance_sigma == 0.0
    assert nominal.events == ()
    noisy = build_scenario("wood_berry", "noisy_feed", duration_s=DAY)
    assert noisy.name == "noisy_feed"
    assert noisy.disturbance_sigma > 0.0
    assert noisy.events == ()


def test_feed_step_has_one_event_at_a_quarter_of_the_run() -> None:
    scenario = build_scenario("wood_berry", "feed_step", duration_s=DAY)
    assert len(scenario.events) == 1
    event = scenario.events[0]
    assert event.tag_id == FEED
    assert event.t_s == pytest.approx(DAY / 4)
    assert event.value == pytest.approx(NOMINAL["feed_rate"] + 0.1)


def test_random_binary_events_are_deterministic_and_binary() -> None:
    """Same seed gives same events; a different seed diverges; values stay binary."""
    signal = BinarySignal(center=10.0, amplitude=1.0, switch_period_s=100.0, duration_s=10000.0)
    same_seed_events = random_binary_events("x", signal, seed=1)
    repeated_same_seed_events = random_binary_events("x", signal, seed=1)
    other_seed_events = random_binary_events("x", signal, seed=2)
    assert same_seed_events == repeated_same_seed_events
    assert same_seed_events != other_seed_events
    assert len(same_seed_events) == 100
    assert [event.t_s for event in same_seed_events] == [100.0 * k for k in range(100)]
    assert {event.tag_id for event in same_seed_events} == {"x"}
    assert {event.value for event in same_seed_events} == {9.0, 11.0}


def test_excited_scenario_perturbs_both_setpoints() -> None:
    scenario = build_scenario("wood_berry", "excited", duration_s=DAY)
    tags = {event.tag_id for event in scenario.events}
    assert tags == {TOP_SP, BOT_SP}
    assert all(0.0 <= event.t_s < DAY for event in scenario.events)
    top_values = {event.value for event in scenario.events if event.tag_id == TOP_SP}
    assert top_values == {NOMINAL["top_comp"] - 0.5, NOMINAL["top_comp"] + 0.5}
    bottom_values = {event.value for event in scenario.events if event.tag_id == BOT_SP}
    assert bottom_values == {NOMINAL["bottom_comp"] - 0.1, NOMINAL["bottom_comp"] + 0.1}
    assert scenario.events == build_scenario("wood_berry", "excited", duration_s=DAY).events


def test_excited_scenario_runs_and_moves_the_process() -> None:
    scenario = build_scenario("wood_berry", "excited", duration_s=3600.0)
    plant = WoodBerryPlant()
    plant.reset(seed=1, scenario=scenario)
    top_comp_trace = simulate_top_comp_trace(plant, steps=3600)
    assert max(top_comp_trace) - min(top_comp_trace) > 0.3
    assert max(abs(top_comp - NOMINAL["top_comp"]) for top_comp in top_comp_trace) < 5.0


def simulate_top_comp_trace(plant, steps: int) -> list[float]:
    """Return the top composition recorded at every simulated step.

    `plant` is advanced `steps` times, one step at a time, so the trace keeps
    the exact per-step order of the original loop. Returns one float per step.
    """
    top_comp_trace = []
    for _ in range(steps):
        plant.step()
        top_comp_trace.append(plant.read("sim.wb.top_comp")[0])
    return top_comp_trace


MC_PRESS_SP, MC_FEED_SP, MC_WATER_SP = (
    "sim.mc.hpgr_press_sp",
    "sim.mc.mill_feed_sp",
    "sim.mc.cyc_water_sp",
)
QUIET_PARAMS = ("operator", "inner_noise", "process_noise", "hardness_sigma", "moisture_sigma")


def test_mill_circuit_scenarios() -> None:
    names = ("nominal", "observational", "excited", "quiet", "hardness_shift", "step_test", "stiction")
    assert available_scenarios("mill_circuit") == names

    assert_baseline_scenarios()

    shift = build_scenario("mill_circuit", "hardness_shift", duration_s=DAY)
    assert_hardness_shift_scenario(shift)

    excited = build_scenario("mill_circuit", "excited", duration_s=DAY)
    assert_excited_scenario(excited)


def assert_baseline_scenarios() -> None:
    """Check the nominal, observational and quiet scenarios share the baseline parameters."""
    nominal = build_scenario("mill_circuit", "nominal", duration_s=DAY)
    assert nominal.param("operator", 1.0) == 0.0
    assert nominal.measurement_noise == 1.0
    assert nominal.events == ()

    observational = build_scenario("mill_circuit", "observational", duration_s=DAY)
    assert observational.param("operator", 0.0) == 1.0
    assert observational.events == ()

    quiet = build_scenario("mill_circuit", "quiet", duration_s=DAY)
    assert quiet.measurement_noise == 0.0
    assert all(quiet.param(name, 1.0) == 0.0 for name in QUIET_PARAMS)


def assert_hardness_shift_scenario(shift: Scenario) -> None:
    """Check the hardness_shift scenario keeps the operator level and schedules one mid-day step."""
    assert shift.param("operator", 1.0) == 0.0
    assert len(shift.events) == 1
    assert shift.events[0].tag_id == "sim.mc.hardness_mean"
    assert shift.events[0].t_s == pytest.approx(DAY / 2)
    assert shift.events[0].value == pytest.approx(16.0)


def assert_excited_scenario(excited: Scenario) -> None:
    """Excited scenario moves three setpoints off baseline and stays reproducible."""
    assert excited.param("operator", 1.0) == 0.0
    assert {event.tag_id for event in excited.events} == {MC_PRESS_SP, MC_FEED_SP, MC_WATER_SP}

    levels = _excited_levels_per_tag(excited)
    assert levels[MC_PRESS_SP] == {3.5 - 0.3, 3.5 + 0.3}
    assert levels[MC_FEED_SP] == {150.0 - 8.0, 150.0 + 8.0}
    assert levels[MC_WATER_SP] == {100.0 - 5.0, 100.0 + 5.0}
    assert all(0.0 <= event.t_s < DAY for event in excited.events)
    assert excited.events == build_scenario("mill_circuit", "excited", duration_s=DAY).events


def _excited_levels_per_tag(excited: Scenario) -> dict[str, set[float]]:
    """Return, per setpoint tag, the distinct event values seen in the excited scenario."""
    return {
        tag: _distinct_event_values_for_tag(excited, tag)
        for tag in (MC_PRESS_SP, MC_FEED_SP, MC_WATER_SP)
    }


def _distinct_event_values_for_tag(scenario: Scenario, tag: str) -> set[float]:
    """Return the distinct event values in the scenario whose tag matches the given setpoint tag."""
    return {event.value for event in scenario.events if event.tag_id == tag}


def test_mill_step_test_scenario_puts_loops_in_manual_and_steps_each_output_in_turn() -> None:
    """Check the mill step test puts control loops in manual and steps each output in turn."""
    scenario = build_scenario("mill_circuit", "step_test", duration_s=3 * 3600.0)
    mode_events = [event for event in scenario.events if event.tag_id.endswith("_mode")]
    assert len(mode_events) == 3 and all(event.value == 0.0 for event in mode_events)
    output_events = [event for event in scenario.events if event.tag_id.endswith("_out")]
    assert len(output_events) == 6
    assert [event.tag_id for event in output_events[::2]] == [
        "sim.mc.hpgr_press_out",
        "sim.mc.mill_feed_out",
        "sim.mc.cyc_water_out",
    ]
    times = [event.t_s for event in scenario.events]
    assert times == sorted(times)


def test_mill_stiction_scenario_sticks_the_hpgr_valve_and_keeps_the_rest_of_nominal() -> None:
    scenario = build_scenario("mill_circuit", "stiction", duration_s=DAY)
    params = dict(scenario.params)
    assert params["stiction_band_hpgr_press"] > params["stiction_jump_hpgr_press"] > 0
    assert params["operator"] == 0.0
    assert not any(key.startswith("stiction") and "mill_feed" in key for key in params)

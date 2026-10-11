"""Tests for named scenarios and random-binary excitation events."""

from __future__ import annotations

import pytest
from crosscut_sim.plants.wood_berry import NOMINAL, WoodBerryPlant
from crosscut_sim.scenarios import available_scenarios, build_scenario, random_binary_events

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
    a = random_binary_events("x", center=10.0, amplitude=1.0, switch_period_s=100.0,
                             duration_s=10000.0, seed=1)  # fmt: skip
    b = random_binary_events("x", center=10.0, amplitude=1.0, switch_period_s=100.0,
                             duration_s=10000.0, seed=1)  # fmt: skip
    c = random_binary_events("x", center=10.0, amplitude=1.0, switch_period_s=100.0,
                             duration_s=10000.0, seed=2)  # fmt: skip
    assert a == b
    assert a != c
    assert len(a) == 100
    assert [e.t_s for e in a] == [100.0 * k for k in range(100)]
    assert {e.tag_id for e in a} == {"x"}
    assert {e.value for e in a} == {9.0, 11.0}


def test_excited_scenario_perturbs_both_setpoints() -> None:
    scenario = build_scenario("wood_berry", "excited", duration_s=DAY)
    tags = {e.tag_id for e in scenario.events}
    assert tags == {TOP_SP, BOT_SP}
    assert all(0.0 <= e.t_s < DAY for e in scenario.events)
    top_values = {e.value for e in scenario.events if e.tag_id == TOP_SP}
    assert top_values == {NOMINAL["top_comp"] - 0.5, NOMINAL["top_comp"] + 0.5}
    bottom_values = {e.value for e in scenario.events if e.tag_id == BOT_SP}
    assert bottom_values == {NOMINAL["bottom_comp"] - 0.1, NOMINAL["bottom_comp"] + 0.1}
    assert scenario.events == build_scenario("wood_berry", "excited", duration_s=DAY).events


def test_excited_scenario_runs_and_moves_the_process() -> None:
    scenario = build_scenario("wood_berry", "excited", duration_s=3600.0)
    plant = WoodBerryPlant()
    plant.reset(seed=1, scenario=scenario)
    values = []
    for _ in range(3600):
        plant.step()
        values.append(plant.read("sim.wb.top_comp")[0])
    assert max(values) - min(values) > 0.3
    assert max(abs(v - NOMINAL["top_comp"]) for v in values) < 5.0

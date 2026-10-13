"""Tests for the stiction valve model and its use as a fault in the mill circuit."""

from __future__ import annotations

import pytest
from crosscut_sim.core import Scenario
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.valve import StictionSpec, StictionValve

LOOP = "hpgr_press"


def test_a_valve_without_deadband_follows_the_command_exactly() -> None:
    valve = StictionValve(StictionSpec(), position=50.0)
    assert [valve.move(command) for command in (50.2, 49.0, 60.0)] == [50.2, 49.0, 60.0]


def test_small_command_changes_inside_the_deadband_do_not_move_the_valve() -> None:
    valve = StictionValve(StictionSpec(deadband=1.0, jump=0.5), position=50.0)
    assert valve.move(50.9) == 50.0 and valve.move(49.1) == 50.0


def test_the_valve_slips_when_the_gap_exceeds_the_deadband() -> None:
    valve = StictionValve(StictionSpec(deadband=1.0, jump=0.4), position=50.0)
    assert valve.move(51.5) == pytest.approx(51.5 - 0.6)


def test_a_reversal_needs_a_new_build_up_before_the_valve_moves() -> None:
    valve = StictionValve(StictionSpec(deadband=1.0, jump=0.4), position=50.0)
    valve.move(51.5)
    assert valve.move(51.0) == pytest.approx(50.9)


def test_a_jump_larger_than_the_deadband_is_refused() -> None:
    with pytest.raises(ValueError):
        StictionSpec(deadband=0.5, jump=0.6)


def _plant(**params: float) -> MillCircuitPlant:
    # inner_noise=0 removes the fast random wobble, so only stiction makes the output stair-step.
    scenario = Scenario(
        duration_s=3600.0, measurement_noise=0.0, params=(("inner_noise", 0.0), *params.items())
    )
    plant = MillCircuitPlant()
    plant.reset(1, scenario)
    return plant


def test_ground_truth_lists_only_the_loops_with_stiction() -> None:
    plant = _plant(**{f"stiction_band_{LOOP}": 2.0, f"stiction_jump_{LOOP}": 1.0})
    assert plant.ground_truth() == {LOOP: {"stiction_band": 2.0, "stiction_jump": 1.0}}


def test_a_healthy_plant_has_an_empty_ground_truth() -> None:
    assert _plant().ground_truth() == {}


def test_a_sticky_valve_makes_the_actuator_move_in_fewer_distinct_steps() -> None:
    def distinct_positions(plant: MillCircuitPlant) -> int:
        """Count the different actuator readings over half an hour after a set-point step."""
        # A set-point step makes the controller move its output, so the valve has to follow.
        plant.write(f"sim.mc.{LOOP}_sp", 3.8)
        seen = set()
        for _ in range(1800):
            plant.step()
            seen.add(round(plant.read(f"sim.mc.{LOOP}")[0], 6))
        return len(seen)

    sticky = _plant(**{f"stiction_band_{LOOP}": 3.0, f"stiction_jump_{LOOP}": 1.5})
    assert distinct_positions(sticky) < distinct_positions(_plant())

"""Tests for the fault-injection wrapper that corrupts what a client reads from a plant."""

from __future__ import annotations

import math

import pytest
from crosscut_sim.core import BAD, GOOD, Scenario
from crosscut_sim.faults import Fault, FaultyPlant
from crosscut_sim.plants.wood_berry import TOP, WoodBerryPlant

SCENARIO = Scenario(duration_s=3600.0, measurement_noise=1.0)


def run(faults: list[Fault], steps: int, seed: int = 5) -> list[tuple[float, int]]:
    """Return the (value, quality) readings of TOP after each of ``steps`` steps."""
    plant = FaultyPlant(WoodBerryPlant(), faults)
    plant.reset(seed, SCENARIO)
    readings = []
    for _ in range(steps):
        plant.step()
        readings.append(plant.read(TOP))
    return readings


def clean(steps: int, seed: int = 5) -> list[tuple[float, int]]:
    return run([], steps, seed)


def test_without_faults_the_wrapper_is_transparent() -> None:
    assert run([], 60) == clean(60)


def test_wrapper_exposes_tags_and_time_of_the_wrapped_plant() -> None:
    plant = FaultyPlant(WoodBerryPlant(), [])
    plant.reset(1, SCENARIO)
    plant.step()
    assert plant.time_s == 1.0
    assert TOP in plant.tags


def test_freeze_holds_the_last_good_value_and_keeps_quality_good() -> None:
    readings = run([Fault("freeze", TOP, start_s=20.0, end_s=40.0)], 60)
    frozen = {readings[i] for i in range(21, 39)}
    assert len(frozen) == 1
    assert next(iter(frozen))[1] == GOOD


def test_readings_outside_the_fault_window_are_unchanged() -> None:
    readings = run([Fault("freeze", TOP, start_s=20.0, end_s=40.0)], 60)
    reference = clean(60)
    assert readings[:19] == reference[:19]
    assert readings[45:] == reference[45:]


def test_drift_grows_linearly_with_time_inside_the_window() -> None:
    fault = Fault("drift", TOP, start_s=10.0, end_s=50.0, magnitude=3600.0)  # units per hour
    readings = run([fault], 40)
    reference = clean(40)
    offset_a = readings[19][0] - reference[19][0]
    offset_b = readings[29][0] - reference[29][0]
    assert offset_b - offset_a == pytest.approx(10.0, rel=1e-6)


def test_spike_adds_plus_or_minus_magnitude_to_the_reading() -> None:
    fault = Fault("spike", TOP, start_s=0.0, end_s=60.0, magnitude=7.0, probability=1.0)
    readings = run([fault], 30)
    reference = clean(30)
    for (value, _), (ref, _) in zip(readings, reference, strict=True):
        assert abs(value - ref) == pytest.approx(7.0)


def test_spike_with_zero_probability_changes_nothing() -> None:
    fault = Fault("spike", TOP, start_s=0.0, end_s=60.0, magnitude=7.0, probability=0.0)
    assert run([fault], 30) == clean(30)


def test_bad_quality_marks_samples_bad_but_keeps_the_value() -> None:
    readings = run([Fault("bad_quality", TOP, start_s=10.0, end_s=20.0)], 30)
    reference = clean(30)
    assert readings[14] == (reference[14][0], BAD)
    assert readings[25] == reference[25]


def test_dropout_returns_nan_with_bad_quality() -> None:
    readings = run([Fault("dropout", TOP, start_s=10.0, end_s=20.0)], 30)
    value, quality = readings[14]
    assert math.isnan(value) and quality == BAD


def test_snapshot_applies_the_same_faults_as_read() -> None:
    plant = FaultyPlant(WoodBerryPlant(), [Fault("dropout", TOP, start_s=0.0, end_s=100.0)])
    plant.reset(2, SCENARIO)
    plant.step()
    assert math.isnan(plant.snapshot()[TOP][0])


def test_faults_are_deterministic_for_a_seed_and_differ_between_seeds() -> None:
    fault = Fault("spike", TOP, start_s=0.0, end_s=60.0, magnitude=5.0, probability=0.5)
    assert run([fault], 60, seed=1) == run([fault], 60, seed=1)
    assert run([fault], 60, seed=1) != run([fault], 60, seed=2)


def test_unknown_fault_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="kind"):
        Fault("melt", TOP, start_s=0.0, end_s=1.0)


def test_fault_on_an_unknown_tag_is_rejected_by_the_wrapper() -> None:
    with pytest.raises(KeyError):
        FaultyPlant(WoodBerryPlant(), [Fault("freeze", "no.such.tag", 0.0, 1.0)])


def test_window_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="end_s"):
        Fault("freeze", TOP, start_s=10.0, end_s=5.0)


def test_writes_pass_through_to_the_wrapped_plant() -> None:
    plant = FaultyPlant(WoodBerryPlant(), [])
    plant.reset(1, SCENARIO)
    with pytest.raises(PermissionError):
        plant.write(TOP, 1.0)  # PV is never writable

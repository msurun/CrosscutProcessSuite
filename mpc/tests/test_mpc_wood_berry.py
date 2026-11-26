"""Close the reference MPC around the independent Wood-Berry simulator.

Published coefficients and the nominal point come from the real sim package, not a copy.
"""

import numpy as np
import pytest
from crosscut_mpc import Controller, CycleInputs, FopdtModel, Limits, Settings, cycle, initialise
from crosscut_sim.core import MAN, Scenario
from crosscut_sim.plants.wood_berry import (
    BOT,
    BOT_MODE,
    DEAD_TIME_MATRIX_MIN,
    GAIN_MATRIX,
    NOMINAL,
    REFLUX,
    STEAM,
    TIME_CONSTANT_MATRIX_MIN,
    TOP,
    TOP_MODE,
    WoodBerryPlant,
)

SECONDS_PER_MINUTE = 60.0  # Convert published minute-based dynamics to controller seconds.
NOMINAL_MVS = np.array([NOMINAL["reflux"], NOMINAL["steam"]])
NOMINAL_CVS = np.array([NOMINAL["top_comp"], NOMINAL["bottom_comp"]])


def wood_berry_controller() -> Controller:
    """Build the published 2x2 model with a one-minute reference-engine cycle."""
    model = FopdtModel(GAIN_MATRIX, np.array(TIME_CONSTANT_MATRIX_MIN) * SECONDS_PER_MINUTE,
                       np.array(DEAD_TIME_MATRIX_MIN) * SECONDS_PER_MINUTE, SECONDS_PER_MINUTE)
    limits = Limits(-NOMINAL_MVS, 5.0 - NOMINAL_MVS, -NOMINAL_CVS, 100.0 - NOMINAL_CVS,
                    np.array([0, 1]), np.full(2, 0.05), np.full(2, 0.05 / SECONDS_PER_MINUTE),
                    np.full(2, 0.05 / SECONDS_PER_MINUTE), np.full(2, 2.0), np.full(2, 0.2))
    return Controller(model, limits, Settings(75, 8, 1.0))


def run_wood_berry() -> tuple[np.ndarray, np.ndarray, np.ndarray, list]:
    """Apply proposals to manual simulator actuators and return the closed-loop record."""
    plant = WoodBerryPlant()
    plant.reset(0, Scenario(dt_s=SECONDS_PER_MINUTE, measurement_noise=0.0))
    plant.write(TOP_MODE, MAN)
    plant.write(BOT_MODE, MAN)
    controller = wood_berry_controller()
    targets = np.array([0.75, 0.3])
    inputs = CycleInputs(np.zeros(2), np.zeros(2), targets)
    state = initialise(controller, inputs)
    measurements, positions, results = [], [], []
    for _ in range(160):
        result, state = cycle(controller, state, inputs)
        plant.write(REFLUX, result.moves[0] + NOMINAL_MVS[0])
        plant.write(STEAM, result.moves[1] + NOMINAL_MVS[1])
        plant.step()
        measured = np.array([plant.read(TOP)[0], plant.read(BOT)[0]])
        actual = np.array([plant.read(REFLUX)[0], plant.read(STEAM)[0]])
        inputs = CycleInputs(measured - NOMINAL_CVS, actual - NOMINAL_MVS, targets)
        measurements.append(measured)
        positions.append(actual)
        results.append(result)
    return measured, np.array(measurements), np.array(positions), results


def test_wood_berry_reaches_both_targets_without_violating_limits() -> None:
    measured, measurements, positions, results = run_wood_berry()
    assert measured == pytest.approx(NOMINAL_CVS + [0.75, 0.3], abs=0.015)
    assert np.all((measurements >= 0.0) & (measurements <= 100.0))
    assert np.all((positions >= 0.0) & (positions <= 5.0))
    assert np.max(np.abs(np.diff(positions, axis=0))) <= 0.05 + 2e-5
    assert {result.status for result in results} <= {"initialised", "solved", "relaxed"}

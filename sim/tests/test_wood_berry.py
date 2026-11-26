"""Tests for the Wood-Berry distillation column plant with its two PID loops."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from crosscut_sim.core import AUTO, CAS, GOOD, MAN, Event, Scenario
from crosscut_sim.plants.wood_berry import (
    DEAD_TIME_MATRIX_MIN,
    DISTURBANCE_DEAD_TIMES_MIN,
    DISTURBANCE_GAINS,
    DISTURBANCE_TIME_CONSTANTS_MIN,
    GAIN_MATRIX,
    NOMINAL,
    TIME_CONSTANT_MATRIX_MIN,
    WoodBerryPlant,
)
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]

TOP, TOP_SP, TOP_RSP, TOP_MODE, REFLUX = (
    "sim.wb.top_comp",
    "sim.wb.top_comp_sp",
    "sim.wb.top_comp_rsp",
    "sim.wb.top_comp_mode",
    "sim.wb.reflux",
)
BOT, BOT_SP, BOT_RSP, BOT_MODE, STEAM = (
    "sim.wb.bottom_comp",
    "sim.wb.bottom_comp_sp",
    "sim.wb.bottom_comp_rsp",
    "sim.wb.bottom_comp_mode",
    "sim.wb.steam",
)
FEED = "sim.wb.feed_rate"


def make(
    seed: int = 1,
    noise: float = 0.0,
    sigma: float = 0.0,
    events: tuple[Event, ...] = (),
) -> WoodBerryPlant:
    """Build a WoodBerryPlant configured with the given seed, noise, disturbance and events."""
    plant = WoodBerryPlant()
    plant.reset(
        seed=seed,
        scenario=Scenario(measurement_noise=noise, disturbance_sigma=sigma, events=events),
    )
    return plant


def run(plant: WoodBerryPlant, minutes: float) -> None:
    """Advance the plant simulation by the given number of minutes."""
    for _ in range(round(minutes * 60)):
        plant.step()


def val(plant: WoodBerryPlant, tag: str) -> float:
    """Return the first value recorded for the given tag on the plant."""
    return plant.read(tag)[0]


def to_manual(plant: WoodBerryPlant) -> None:
    """Switch every boiler of the plant to manual mode."""
    plant.write(TOP_MODE, MAN)
    plant.write(BOT_MODE, MAN)


INPUT_TAGS = {"reflux": REFLUX, "steam": STEAM, "feed_rate": FEED}
OUTPUT_TAGS = {"top_comp": TOP, "bottom_comp": BOT}
STEP_SIZE = 0.1  # lb/min, small enough to stay in the linear range of the model

# One row per channel: input name, output name, gain (wt% per lb/min), tau (min), dead time
# (min). The MV matrix rows follow the published output order and columns the input order;
# the feed-rate cases are the disturbance column.
CHANNEL_CASES = (
    ("reflux", "top_comp", GAIN_MATRIX[0][0], TIME_CONSTANT_MATRIX_MIN[0][0],
     DEAD_TIME_MATRIX_MIN[0][0]),
    ("reflux", "bottom_comp", GAIN_MATRIX[1][0], TIME_CONSTANT_MATRIX_MIN[1][0],
     DEAD_TIME_MATRIX_MIN[1][0]),
    ("steam", "top_comp", GAIN_MATRIX[0][1], TIME_CONSTANT_MATRIX_MIN[0][1],
     DEAD_TIME_MATRIX_MIN[0][1]),
    ("steam", "bottom_comp", GAIN_MATRIX[1][1], TIME_CONSTANT_MATRIX_MIN[1][1],
     DEAD_TIME_MATRIX_MIN[1][1]),
    ("feed_rate", "top_comp", DISTURBANCE_GAINS[0], DISTURBANCE_TIME_CONSTANTS_MIN[0],
     DISTURBANCE_DEAD_TIMES_MIN[0]),
    ("feed_rate", "bottom_comp", DISTURBANCE_GAINS[1], DISTURBANCE_TIME_CONSTANTS_MIN[1],
     DISTURBANCE_DEAD_TIMES_MIN[1]),
)


def apply_open_loop_step(plant: WoodBerryPlant, input_name: str) -> None:
    """Put both loops in MAN and raise one input by STEP_SIZE above its nominal."""
    to_manual(plant)
    plant.write(INPUT_TAGS[input_name], NOMINAL[input_name] + STEP_SIZE)


def output_deviation(plant: WoodBerryPlant, output_name: str) -> float:
    """Return the measured output minus its nominal value, in wt%."""
    return val(plant, OUTPUT_TAGS[output_name]) - NOMINAL[output_name]


def analytic_step_response(
    gain: float, tau_s: float, delay_s: float, elapsed_s: float, input_step: float
) -> float:
    """Return the continuous FOPDT step response K*du*(1 - exp(-(t - theta)/tau))."""
    if elapsed_s <= delay_s:
        return 0.0
    return gain * input_step * (1.0 - math.exp(-(elapsed_s - delay_s) / tau_s))


def run_steps(plant: WoodBerryPlant, steps: int) -> None:
    """Advance the plant by an exact number of one-second steps."""
    for _ in range(steps):
        plant.step()


def test_catalog_is_valid_and_complete() -> None:
    plant = make()
    schema = json.loads((REPO_ROOT / "schemas" / "tags.schema.json").read_text(encoding="utf-8"))
    validation_errors = list(Draft202012Validator(schema).iter_errors(plant.tags.to_document()))
    assert validation_errors == [], [error.message for error in validation_errors]
    expected = {
        TOP, TOP_SP, TOP_RSP, TOP_MODE, REFLUX, BOT, BOT_SP, BOT_RSP, BOT_MODE, STEAM, FEED,
    }  # fmt: skip
    assert set(plant.tags.ids()) == expected
    assert set(plant.snapshot()) == expected


def test_nominal_steady_state_is_held_without_noise() -> None:
    plant = make()
    assert plant.time_s == 0.0
    run(plant, 60)
    assert plant.time_s == pytest.approx(3600.0)
    assert val(plant, TOP) == pytest.approx(NOMINAL["top_comp"], abs=1e-9)
    assert val(plant, BOT) == pytest.approx(NOMINAL["bottom_comp"], abs=1e-9)
    assert val(plant, REFLUX) == pytest.approx(NOMINAL["reflux"], abs=1e-9)
    assert val(plant, STEAM) == pytest.approx(NOMINAL["steam"], abs=1e-9)
    assert val(plant, TOP_MODE) == AUTO
    assert plant.read(TOP)[1] == GOOD


def test_open_loop_static_gains_of_reflux_step() -> None:
    plant = make()
    to_manual(plant)
    plant.write(REFLUX, NOMINAL["reflux"] + 0.1)
    run(plant, 180)
    assert val(plant, TOP) - NOMINAL["top_comp"] == pytest.approx(12.8 * 0.1, abs=0.02)
    assert val(plant, BOT) - NOMINAL["bottom_comp"] == pytest.approx(6.6 * 0.1, abs=0.02)


def test_open_loop_static_gains_of_steam_step() -> None:
    plant = make()
    to_manual(plant)
    plant.write(STEAM, NOMINAL["steam"] + 0.1)
    run(plant, 180)
    assert val(plant, TOP) - NOMINAL["top_comp"] == pytest.approx(-18.9 * 0.1, abs=0.02)
    assert val(plant, BOT) - NOMINAL["bottom_comp"] == pytest.approx(-19.4 * 0.1, abs=0.02)


def test_open_loop_feed_disturbance_gains() -> None:
    plant = make()
    to_manual(plant)
    plant.write(FEED, NOMINAL["feed_rate"] + 0.1)
    run(plant, 180)
    assert val(plant, TOP) - NOMINAL["top_comp"] == pytest.approx(3.8 * 0.1, abs=0.02)
    assert val(plant, BOT) - NOMINAL["bottom_comp"] == pytest.approx(4.9 * 0.1, abs=0.02)


def test_published_gain_matrix_matches_wood_berry_1973() -> None:
    """The ground-truth matrices are the published Wood-Berry coefficients."""
    assert GAIN_MATRIX == ((12.8, -18.9), (6.6, -19.4))
    assert DISTURBANCE_GAINS == (3.8, 4.9)


@pytest.mark.parametrize(
    ("input_name", "output_name", "gain", "tau_min", "delay_min"), CHANNEL_CASES
)
def test_steady_state_gain_equals_its_matrix_entry(
    input_name: str, output_name: str, gain: float, tau_min: float, delay_min: float
) -> None:
    """A 0.1 lb/min input step settles at the matrix gain times the step size."""
    plant = make()
    apply_open_loop_step(plant, input_name)
    run(plant, 200)
    assert output_deviation(plant, output_name) == pytest.approx(gain * STEP_SIZE, abs=0.01)


@pytest.mark.parametrize(
    ("input_name", "output_name", "gain", "tau_min", "delay_min"), CHANNEL_CASES
)
def test_dead_time_delays_each_channel(
    input_name: str, output_name: str, gain: float, tau_min: float, delay_min: float
) -> None:
    """The output stays at nominal until the channel dead time, then moves with the gain sign."""
    plant = make()
    apply_open_loop_step(plant, input_name)
    run_steps(plant, round(delay_min * 60.0))
    assert output_deviation(plant, output_name) == pytest.approx(0.0, abs=1e-12)
    plant.step()
    assert output_deviation(plant, output_name) * math.copysign(1.0, gain) > 0.0


@pytest.mark.parametrize(
    ("input_name", "output_name", "gain", "tau_min", "delay_min"), CHANNEL_CASES
)
def test_step_response_matches_the_analytic_fopdt_curve(
    input_name: str, output_name: str, gain: float, tau_min: float, delay_min: float
) -> None:
    """At one hour, each channel equals K*du*(1 - exp(-(t - theta)/tau)) to round-off."""
    plant = make()
    apply_open_loop_step(plant, input_name)
    elapsed_s = 3600
    run_steps(plant, elapsed_s)
    expected = analytic_step_response(
        gain, tau_min * 60.0, delay_min * 60.0, elapsed_s, STEP_SIZE
    )
    assert output_deviation(plant, output_name) == pytest.approx(expected, abs=1e-9)


def test_model_coefficients_expose_the_published_matrices() -> None:
    """The test bed publishes the coefficients an identification result is checked against."""
    coefficients = make().model_coefficients()
    assert coefficients["gain_matrix"] == GAIN_MATRIX
    assert coefficients["time_constant_matrix_min"] == TIME_CONSTANT_MATRIX_MIN
    assert coefficients["dead_time_matrix_min"] == DEAD_TIME_MATRIX_MIN
    assert coefficients["disturbance_gains"] == DISTURBANCE_GAINS


def test_dead_time_delays_the_first_response() -> None:
    plant = make()
    to_manual(plant)
    plant.write(REFLUX, NOMINAL["reflux"] + 0.1)
    run(plant, 0.9)  # shorter than the 1 min dead time of G11
    assert val(plant, TOP) == pytest.approx(NOMINAL["top_comp"], abs=1e-9)
    run(plant, 5)
    assert val(plant, TOP) > NOMINAL["top_comp"] + 0.05


def test_closed_loop_tracks_setpoint_step_and_keeps_other_loop_regulated() -> None:
    plant = make()
    plant.write(TOP_SP, NOMINAL["top_comp"] + 1.0)
    worst = 0.0
    for _ in range(240 * 60):
        plant.step()
        worst = max(worst, abs(val(plant, TOP) - NOMINAL["top_comp"]), abs(val(plant, BOT) - 0.5))
    assert worst < 5.0  # stable, no runaway
    assert val(plant, TOP) == pytest.approx(NOMINAL["top_comp"] + 1.0, abs=0.15)
    assert val(plant, BOT) == pytest.approx(NOMINAL["bottom_comp"], abs=0.1)


def test_closed_loop_rejects_feed_step_via_event() -> None:
    event = Event(t_s=600.0, tag_id=FEED, value=NOMINAL["feed_rate"] + 0.1)
    plant = make(events=(event,))
    run(plant, 9.5)
    assert val(plant, FEED) == pytest.approx(NOMINAL["feed_rate"])
    run(plant, 1.0)
    assert val(plant, FEED) == pytest.approx(NOMINAL["feed_rate"] + 0.1)
    run(plant, 240)
    assert val(plant, TOP) == pytest.approx(NOMINAL["top_comp"], abs=0.15)
    assert val(plant, BOT) == pytest.approx(NOMINAL["bottom_comp"], abs=0.1)


def test_cascade_mode_follows_remote_setpoint_and_rejects_local_writes() -> None:
    plant = make()
    plant.write(TOP_MODE, CAS)
    plant.write(TOP_RSP, NOMINAL["top_comp"] + 0.5)
    run(plant, 1)
    assert val(plant, TOP_SP) == pytest.approx(NOMINAL["top_comp"] + 0.5)
    with pytest.raises(PermissionError):
        plant.write(TOP_SP, 90.0)
    run(plant, 240)
    assert val(plant, TOP) == pytest.approx(NOMINAL["top_comp"] + 0.5, abs=0.15)


def test_write_permissions_and_validation() -> None:
    plant = make()
    with pytest.raises(KeyError):
        plant.write("sim.wb.unknown", 1.0)
    with pytest.raises(KeyError):
        plant.read("sim.wb.unknown")
    with pytest.raises(PermissionError):
        plant.write(TOP, 90.0)  # measurement is read-only
    with pytest.raises(PermissionError):
        plant.write(REFLUX, 2.0)  # OUT can only be written in MAN
    with pytest.raises(ValueError):
        plant.write(TOP_MODE, 5)
    plant.write(TOP_MODE, MAN)
    plant.write(REFLUX, 2.0)  # allowed now
    assert val(plant, TOP_MODE) == MAN


def test_manual_switch_is_bumpless() -> None:
    plant = make()
    run(plant, 10)
    before = val(plant, REFLUX)
    plant.write(TOP_MODE, MAN)
    run(plant, 1)
    assert val(plant, REFLUX) == pytest.approx(before, abs=1e-9)
    plant.write(TOP_MODE, AUTO)
    run(plant, 1)
    assert val(plant, REFLUX) == pytest.approx(before, abs=1e-6)


def test_determinism_and_seed_sensitivity_with_noise_and_disturbance() -> None:
    def trace(seed: int) -> list[float]:
        """Record the value at the top of a freshly made plant over 1800 steps."""
        plant = make(seed=seed, noise=1.0, sigma=0.02)
        out = []
        for _ in range(1800):
            plant.step()
            out.append(val(plant, TOP))
        return out

    assert trace(5) == trace(5)
    assert trace(5) != trace(6)


def test_measurement_noise_appears_only_when_enabled() -> None:
    quiet = make(noise=0.0)
    noisy = make(noise=1.0)
    quiet_values, noisy_values = [], []
    for _ in range(600):
        quiet.step()
        noisy.step()
        quiet_values.append(val(quiet, TOP))
        noisy_values.append(val(noisy, TOP))
    assert max(quiet_values) - min(quiet_values) < 1e-9
    assert max(noisy_values) - min(noisy_values) > 1e-3

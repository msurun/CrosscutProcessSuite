"""Tests for the Wood-Berry distillation column plant with its two PID loops."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from crosscut_sim.core import AUTO, CAS, GOOD, MAN, Event, Scenario
from crosscut_sim.plants.wood_berry import NOMINAL, WoodBerryPlant
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

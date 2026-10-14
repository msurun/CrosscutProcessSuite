"""Tests for the grinding-circuit plant (HPGR + ball mill + cyclone) with known ground truth."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from crosscut_sim.core import AUTO, CAS, GOOD, MAN, Scenario
from crosscut_sim.plants.mill_circuit import NOMINAL, MillCircuitPlant
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]

PRESS, PRESS_SP, PRESS_RSP, PRESS_MODE, PRESS_OUT = (
    "sim.mc.hpgr_press",
    "sim.mc.hpgr_press_sp",
    "sim.mc.hpgr_press_rsp",
    "sim.mc.hpgr_press_mode",
    "sim.mc.hpgr_press_out",
)
FEED, FEED_SP, FEED_RSP, FEED_MODE, FEED_OUT = (
    "sim.mc.mill_feed",
    "sim.mc.mill_feed_sp",
    "sim.mc.mill_feed_rsp",
    "sim.mc.mill_feed_mode",
    "sim.mc.mill_feed_out",
)
WATER, WATER_SP, WATER_RSP, WATER_MODE, WATER_OUT = (
    "sim.mc.cyc_water",
    "sim.mc.cyc_water_sp",
    "sim.mc.cyc_water_rsp",
    "sim.mc.cyc_water_mode",
    "sim.mc.cyc_water_out",
)
HARD_EST, MOIST, HARD_MEAN = (
    "sim.mc.ore_hardness_est",
    "sim.mc.feed_moisture",
    "sim.mc.hardness_mean",
)
P80, MILL_POWER, HPGR_POWER = "sim.mc.p80", "sim.mc.mill_power", "sim.mc.hpgr_power"

ALL_TAGS = {
    PRESS, PRESS_SP, PRESS_RSP, PRESS_MODE, PRESS_OUT,
    FEED, FEED_SP, FEED_RSP, FEED_MODE, FEED_OUT,
    WATER, WATER_SP, WATER_RSP, WATER_MODE, WATER_OUT,
    HARD_EST, MOIST, HARD_MEAN, P80, MILL_POWER, HPGR_POWER,
}  # fmt: skip
MODES = (PRESS_MODE, FEED_MODE, WATER_MODE)

QUIET = (
    ("operator", 0.0),
    ("inner_noise", 0.0),
    ("process_noise", 0.0),
    ("hardness_sigma", 0.0),
    ("moisture_sigma", 0.0),
)


def make(
    seed: int = 1,
    params: tuple[tuple[str, float], ...] = QUIET,
    noise: float = 0.0,
    dt_s: float = 1.0,
) -> MillCircuitPlant:
    """Return a reset mill circuit plant built from the given seed, noise and time step."""
    plant = MillCircuitPlant()
    plant.reset(seed=seed, scenario=Scenario(dt_s=dt_s, measurement_noise=noise, params=params))
    return plant


def run(plant: MillCircuitPlant, minutes: float) -> None:
    """Advance the plant simulation by the given number of minutes."""
    for _ in range(round(minutes * 60 / plant_dt(plant))):
        plant.step()


def plant_dt(plant: MillCircuitPlant) -> float:
    """Return the plant sampling interval in seconds."""
    return plant.dt_s


def val(plant: MillCircuitPlant, tag: str) -> float:
    """Return the current numeric value of the plant tag's most recent reading."""
    return plant.read(tag)[0]


def to_manual(plant: MillCircuitPlant) -> None:
    """Set every operating mode of the given plant to manual."""
    for mode in MODES:
        plant.write(mode, MAN)


def test_catalog_is_valid_and_complete() -> None:
    plant = make()
    schema = json.loads((REPO_ROOT / "schemas" / "tags.schema.json").read_text(encoding="utf-8"))
    validation_errors = list(Draft202012Validator(schema).iter_errors(plant.tags.to_document()))
    assert validation_errors == [], [
        validation_error.message for validation_error in validation_errors
    ]
    assert set(plant.tags.ids()) == ALL_TAGS
    assert set(plant.snapshot()) == ALL_TAGS
    assert not any("true" in tag_id for tag_id in plant.tags.ids())  # hidden state stays hidden


def test_quiet_nominal_steady_state_is_held() -> None:
    plant = make()
    run(plant, 60)
    assert plant.time_s == pytest.approx(3600.0)
    assert val(plant, PRESS) == pytest.approx(NOMINAL["hpgr_press"], abs=1e-6)
    assert val(plant, FEED) == pytest.approx(NOMINAL["mill_feed"], abs=1e-6)
    assert val(plant, WATER) == pytest.approx(NOMINAL["cyc_water"], abs=1e-6)
    assert val(plant, P80) == pytest.approx(NOMINAL["p80"], abs=1e-6)
    assert val(plant, MILL_POWER) == pytest.approx(NOMINAL["mill_power"], abs=1e-6)
    assert val(plant, HPGR_POWER) == pytest.approx(NOMINAL["hpgr_power"], abs=1e-6)
    assert val(plant, HARD_EST) == pytest.approx(NOMINAL["ore_hardness"], abs=1e-6)
    assert val(plant, MOIST) == pytest.approx(NOMINAL["feed_moisture"], abs=1e-6)
    assert val(plant, PRESS_OUT) == pytest.approx(50.0, abs=1e-6)
    assert val(plant, PRESS_MODE) == AUTO
    assert plant.read(P80)[1] == GOOD
    assert plant.true_hardness == pytest.approx(14.0)


@pytest.mark.parametrize(
    ("out_tag", "dp80", "dmill", "dhpgr"),
    [
        # actuator gains: press 0.07 N/mm2 per %, feed 3 t/h per %, water 2 m3/h per %
        (PRESS_OUT, -20.0 * 0.7, -150.0 * 0.7, 250.0 * 0.7),
        (FEED_OUT, 0.45 * 30.0, 10.0 * 30.0, 0.0),
        (WATER_OUT, -0.6 * 20.0, 1.0 * 20.0, 0.0),
    ],
)
def test_open_loop_gains_match_ground_truth_at_nominal_hardness(
    out_tag: str, dp80: float, dmill: float, dhpgr: float
) -> None:
    delta_out = 10.0  # percentage-point OUT step applied to the loop under test
    plant = make()
    to_manual(plant)
    plant.write(out_tag, 50.0 + delta_out)
    run(plant, 180)
    assert val(plant, P80) - NOMINAL["p80"] == pytest.approx(dp80, abs=0.25)
    assert val(plant, MILL_POWER) - NOMINAL["mill_power"] == pytest.approx(dmill, abs=3.0)
    assert val(plant, HPGR_POWER) - NOMINAL["hpgr_power"] == pytest.approx(dhpgr, abs=3.0)


def test_press_effect_is_stronger_for_harder_ore() -> None:
    plant = make()
    to_manual(plant)
    plant.write(HARD_MEAN, 17.0)
    run(plant, 180)
    base = val(plant, P80)
    assert base == pytest.approx(NOMINAL["p80"] + 6.0 * 3.0, abs=0.3)  # direct hardness effect
    assert val(plant, HARD_EST) == pytest.approx(17.0, abs=1e-6)
    plant.write(PRESS_OUT, 60.0)
    run(plant, 180)
    delta = val(plant, P80) - base
    assert delta == pytest.approx(-20.0 * (1 + 0.08 * 3.0) * 0.7, abs=0.3)
    assert abs(delta) > 1.2 * 14.0


def test_true_gain_api() -> None:
    plant = make()
    assert plant.true_gain("hpgr_press", "p80", 14.0) == pytest.approx(-20.0)
    assert plant.true_gain("hpgr_press", "p80", 17.0) == pytest.approx(-20.0 * 1.24)
    assert plant.true_gain("mill_feed", "p80", 14.0) == pytest.approx(0.45)
    assert plant.true_gain("mill_feed", "p80", 24.0) == pytest.approx(0.45 * 2.0)
    assert plant.true_gain("cyc_water", "p80", 20.0) == pytest.approx(-0.6)
    assert plant.true_gain("ore_hardness", "p80", 20.0) == pytest.approx(6.0)
    assert plant.true_gain("hpgr_press", "hpgr_power", 14.0) == pytest.approx(250.0)
    assert plant.true_gain("mill_feed", "hpgr_power", 14.0) == 0.0
    assert plant.true_gain("hpgr_press", "mill_power", 14.0) == pytest.approx(-150.0)
    assert plant.true_gain("hpgr_press", "p80") == pytest.approx(-20.0)  # default: current hardness
    with pytest.raises(KeyError):
        plant.true_gain("nope", "p80", 14.0)
    with pytest.raises(KeyError):
        plant.true_gain("hpgr_press", "nope", 14.0)


def test_inner_loops_track_setpoints() -> None:
    plant = make()
    plant.write(PRESS_SP, 3.8)
    plant.write(FEED_SP, 160.0)
    plant.write(WATER_SP, 95.0)
    run(plant, 30)
    assert val(plant, PRESS) == pytest.approx(3.8, abs=0.02)
    assert val(plant, FEED) == pytest.approx(160.0, abs=0.5)
    assert val(plant, WATER) == pytest.approx(95.0, abs=0.3)


def test_cascade_and_write_permissions() -> None:
    plant = make()
    _assert_cascade_value_is_tracked(plant)
    _assert_protected_tags_reject_writes(plant)
    _assert_unknown_tags_are_rejected(plant)
    _assert_manual_mode_allows_writes(plant)


def _assert_cascade_value_is_tracked(plant: MillCircuitPlant) -> None:
    """Assert that a cascade setpoint drives the process value it controls."""
    plant.write(PRESS_MODE, CAS)
    plant.write(PRESS_RSP, 3.7)
    run(plant, 1)
    assert val(plant, PRESS_SP) == pytest.approx(3.7)


def _assert_protected_tags_reject_writes(plant: MillCircuitPlant) -> None:
    """Assert that internal setpoints and read-only measurements refuse writes."""
    with pytest.raises(PermissionError):
        plant.write(PRESS_SP, 3.0)
    with pytest.raises(PermissionError):
        plant.write(PRESS_OUT, 55.0)
    for read_only in (PRESS, P80, MILL_POWER, HPGR_POWER, HARD_EST, MOIST):
        with pytest.raises(PermissionError):
            plant.write(read_only, 1.0)


def _assert_unknown_tags_are_rejected(plant: MillCircuitPlant) -> None:
    """Assert that invalid modes and unknown tags raise instead of silently failing."""
    with pytest.raises(ValueError):
        plant.write(FEED_MODE, 7)
    with pytest.raises(KeyError):
        plant.write("sim.mc.unknown", 1.0)
    with pytest.raises(KeyError):
        plant.read("sim.mc.unknown")


def _assert_manual_mode_allows_writes(plant: MillCircuitPlant) -> None:
    """Assert that manual mode lets the operator drive the output tag."""
    plant.write(FEED_MODE, MAN)
    plant.write(FEED_OUT, 55.0)
    assert val(plant, FEED_OUT) == pytest.approx(55.0)


def test_manual_switch_is_bumpless() -> None:
    plant = make()
    run(plant, 5)
    before = val(plant, PRESS_OUT)
    plant.write(PRESS_MODE, MAN)
    run(plant, 1)
    assert val(plant, PRESS_OUT) == pytest.approx(before, abs=1e-9)
    plant.write(PRESS_MODE, AUTO)
    run(plant, 1)
    assert val(plant, PRESS_OUT) == pytest.approx(before, abs=1e-6)


NOISY = (("operator", 1.0),)


def test_determinism_and_seed_sensitivity_with_all_noise_sources() -> None:
    def trace(seed: int) -> list[tuple[float, float, float]]:
        """Run one hour and record P80, pressure and pressure setpoint at each step."""
        plant = make(seed=seed, params=NOISY, noise=1.0)
        out = []
        for _ in range(3600):
            plant.step()
            out.append((val(plant, P80), val(plant, PRESS), val(plant, PRESS_SP)))
        return out

    assert trace(4) == trace(4)
    assert trace(4) != trace(5)


def test_process_has_noise_driven_variation_even_with_constant_setpoints() -> None:
    plant = make(params=(("operator", 0.0),), noise=1.0)
    press, p80, out = [], [], []
    for _ in range(3600 * 3):
        plant.step()
        press.append(val(plant, PRESS))
        p80.append(val(plant, P80))
        out.append(val(plant, PRESS_OUT))
    assert np.std(press[600:]) > 0.005
    assert np.std(p80[600:]) > 0.3
    assert np.std(out[600:]) > 0.05
    assert abs(np.mean(press[600:]) - NOMINAL["hpgr_press"]) < 0.1  # loop keeps it near SP


def _correlations_with_hardness(seed: int) -> tuple[float, float]:
    """Run one 24 h simulation; return hardness/pressure and hardness/feed correlations."""
    scenario = Scenario(dt_s=10.0, params=(("operator", 1.0),), measurement_noise=1.0)
    plant = MillCircuitPlant()
    plant.reset(seed=seed, scenario=scenario)
    hardness_samples, pressure_setpoints, feed_setpoints = [], [], []
    for step in range(24 * 360):  # 24 h at 10 s
        plant.step()
        if (step + 1) % 180 == 0:  # sample every 30 min
            hardness_samples.append(plant.true_hardness)
            pressure_setpoints.append(val(plant, PRESS_SP))
            feed_setpoints.append(val(plant, FEED_SP))
    return (
        np.corrcoef(hardness_samples, pressure_setpoints)[0, 1],
        np.corrcoef(hardness_samples, feed_setpoints)[0, 1],
    )


def test_operator_confounds_setpoints_with_hardness() -> None:
    """With the operator on, setpoints follow the (partly unobserved) ore hardness."""
    pressure_correlations, feed_correlations = [], []
    for seed in (1, 2, 3):
        pressure_corr, feed_corr = _correlations_with_hardness(seed)
        pressure_correlations.append(pressure_corr)
        feed_correlations.append(feed_corr)
    assert all(corr > 0 for corr in pressure_correlations) and np.mean(pressure_correlations) > 0.5
    assert all(corr < 0 for corr in feed_correlations) and np.mean(feed_correlations) < -0.5


def test_operator_off_leaves_setpoints_alone() -> None:
    plant = make(params=(("operator", 0.0), ("hardness_sigma", 1.5)), noise=1.0, dt_s=10.0)
    for _ in range(12 * 360):
        plant.step()
    assert val(plant, PRESS_SP) == NOMINAL["hpgr_press"]
    assert val(plant, FEED_SP) == NOMINAL["mill_feed"]
    assert val(plant, WATER_SP) == NOMINAL["cyc_water"]


def test_operator_only_acts_on_loops_in_auto() -> None:
    plant = make(params=(("operator", 1.0),), dt_s=10.0)
    plant.write(PRESS_MODE, MAN)
    plant.write(FEED_MODE, CAS)
    for _ in range(3 * 360):
        plant.step()
    assert val(plant, PRESS_SP) == NOMINAL["hpgr_press"]
    assert val(plant, FEED_SP) == pytest.approx(val(plant, FEED_RSP))
    assert val(plant, WATER_SP) != NOMINAL["cyc_water"]  # the operator did touch this one


def test_dataset_recording_works_for_this_plant(tmp_path: Path) -> None:
    from crosscut_sim.dataset import RunInfo, read_dataset, record

    doc = record(
        MillCircuitPlant(),
        Scenario(duration_s=300.0, params=NOISY, measurement_noise=1.0),
        tmp_path,
        RunInfo(seed=2, dataset_id="mc_test", plant_name="mill_circuit"),
    )
    assert doc["row_count"] == 300 * len(ALL_TAGS)
    assert read_dataset(tmp_path).num_rows == doc["row_count"]

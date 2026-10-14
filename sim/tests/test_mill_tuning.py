"""Tests for the PID gains of the mill-circuit loops becoming scenario params.

The gains belong to the closed-loop controller of each loop, so these tests check the
plant's pid objects directly and, for the tuned behaviour, the integrated error after a
set-point step. They are written before the implementation and fail on the missing keys.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_sim.core import Event, Scenario
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import available_scenarios, build_scenario

LOOPS = ("hpgr_press", "mill_feed", "cyc_water")

# Today's defaults, the loop spec value per loop and a common integral time in seconds.
DEFAULT_KC = {"hpgr_press": 7.0, "mill_feed": 0.17, "cyc_water": 0.25}
DEFAULT_TI_S = 60.0

DETUNED_KC_FACTOR = 0.25
DETUNED_TI_S = 300.0


def _plant(params: dict[str, float], *, seed: int = 1) -> MillCircuitPlant:
    """Reset a mill plant with the given extra params and the inner noise switched off."""
    pairs = tuple(("inner_noise", 0.0) for _ in ()) + tuple(params.items())
    scenario = Scenario(duration_s=3600.0, measurement_noise=0.0, params=pairs)
    plant = MillCircuitPlant()
    plant.reset(seed, scenario)
    return plant


def test_a_plant_without_tuning_params_uses_todays_default_gains() -> None:
    plant = _plant({})
    for loop in LOOPS:
        assert plant._loops[loop].pid.kc == pytest.approx(DEFAULT_KC[loop])
        assert plant._loops[loop].pid.ti_s == pytest.approx(DEFAULT_TI_S)


def test_params_override_only_the_loop_they_name() -> None:
    plant = _plant({"kc_hpgr_press": 3.5, "ti_s_hpgr_press": 120.0})

    assert plant._loops["hpgr_press"].pid.kc == pytest.approx(3.5)
    assert plant._loops["hpgr_press"].pid.ti_s == pytest.approx(120.0)

    for loop in ("mill_feed", "cyc_water"):
        assert plant._loops[loop].pid.kc == pytest.approx(DEFAULT_KC[loop])
        assert plant._loops[loop].pid.ti_s == pytest.approx(DEFAULT_TI_S)


def _pv_series(params: dict[str, float], steps: int = 600) -> np.ndarray:
    """Return the hpgr_press PV for the first `steps` after reset, noise left on."""
    scenario = Scenario(duration_s=3600.0, measurement_noise=0.0, params=tuple(params.items()))
    plant = MillCircuitPlant()
    plant.reset(1, scenario)
    values = []
    for _ in range(steps):
        plant.step()
        values.append(plant.read("sim.mc.hpgr_press")[0])
    return np.array(values)


def test_explicit_params_equal_to_defaults_reproduce_the_untuned_series() -> None:
    explicit = {f"kc_{loop}": DEFAULT_KC[loop] for loop in LOOPS}
    explicit.update({f"ti_s_{loop}": DEFAULT_TI_S for loop in LOOPS})

    assert np.array_equal(_pv_series({}), _pv_series(explicit))


def test_detuned_is_listed_and_scales_the_gains_down() -> None:
    assert "detuned" in available_scenarios("mill_circuit")

    scenario = build_scenario("mill_circuit", "detuned", duration_s=3600.0)

    assert scenario.param("kc_hpgr_press", -1.0) == pytest.approx(
        DETUNED_KC_FACTOR * DEFAULT_KC["hpgr_press"]
    )
    assert scenario.param("ti_s_hpgr_press", -1.0) == pytest.approx(DETUNED_TI_S)


def _quiet_params(tuning: dict[str, float]) -> dict[str, float]:
    """Return the params with every noise source off, then the given tuning applied on top."""
    base_params = {
        "operator": 0.0,
        "inner_noise": 0.0,
        "process_noise": 0.0,
        "hardness_sigma": 0.0,
        "moisture_sigma": 0.0,
    }
    base_params.update(tuning)
    return base_params


def _quiet_scenario(params: dict[str, float], events: tuple[Event, ...] = ()) -> Scenario:
    """Return a one-hour scenario with measurement noise off and the given params and events."""
    return Scenario(
        duration_s=3600.0,
        measurement_noise=0.0,
        params=tuple(params.items()),
        events=events,
    )


def _sum_abs_setpoint_error(plant: MillCircuitPlant, steps: int) -> float:
    """Sum |setpoint - PV| of the hpgr_press loop over the given number of plant steps."""
    iae = 0.0
    for _ in range(steps):
        plant.step()
        pv = plant.read("sim.mc.hpgr_press")[0]
        sp = plant.read("sim.mc.hpgr_press_sp")[0]
        iae += abs(sp - pv)
    return iae


def _iae_after_setpoint_step(tuning: dict[str, float], *, seed: int = 1) -> float:
    """Sum |setpoint - PV| for one hour after a small step, with the plant noise off.

    The step is applied at t=60 s on the loop's own setpoint; the error is accumulated on
    the hpgr_press loop in percent, so the unit of the result is percent * seconds.
    """
    params = _quiet_params(tuning)
    plant = MillCircuitPlant()
    plant.reset(seed, _quiet_scenario(params))
    nominal_sp = plant.read("sim.mc.hpgr_press_sp")[0]

    step = Event(t_s=60.0, tag_id="sim.mc.hpgr_press_sp", value=nominal_sp + 0.5)
    plant.reset(seed, _quiet_scenario(params, events=(step,)))
    return _sum_abs_setpoint_error(plant, steps=3600)


def test_a_detuned_loop_integrates_more_error_than_the_default_loop() -> None:
    detuned = {
        f"kc_{loop}": DETUNED_KC_FACTOR * DEFAULT_KC[loop] for loop in LOOPS
    }
    detuned.update({f"ti_s_{loop}": DETUNED_TI_S for loop in LOOPS})

    assert _iae_after_setpoint_step(detuned) > _iae_after_setpoint_step({})

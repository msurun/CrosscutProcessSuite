"""Experiment cases for the stiction validation: valve, noise, tuning and forcing of one run.

A positive case has a sticking valve (band > 0); the negative cases keep the valve healthy and
make the loop oscillate for another reason, so that false alarms can be counted per cause.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

import exp01
import numpy as np
from crosscut_sim.core import Event
from crosscut_sim.plants.mill_circuit import DEFAULT_KC, MillCircuitPlant

LOOP = "hpgr_press"
FORCING_START_S = 1800.0  # the setpoint is disturbed from 30 min on, as in exp01
FORCING_UPDATE_S = 60.0  # the forced setpoint is rewritten every minute
FORCING_AMPLITUDE = 1.0  # same size as the setpoint step, engineering units
AGGRESSIVE_KC_FACTOR = 3.0  # a loop with 3 x the gain and a third of the integral time rings
AGGRESSIVE_TI_FACTOR = 1.0 / 3.0
DEFAULT_TI_S = 60.0
FORCINGS = ("step", "sine", "square")
TUNINGS = ("default", "aggressive")


@dataclass(frozen=True)
class Case:
    """One experiment condition; ``forcing`` is how the setpoint is moved after the first 30 min."""

    band_percent: float
    noise: str
    tuning: str = "default"
    forcing: str = "step"
    period_s: float = 1200.0


def forcing_events(case: Case, nominal_setpoint: float, duration_s: float) -> tuple[Event, ...]:
    """Setpoint events: one step, or a sine / square wave of period ``case.period_s``."""
    if case.forcing == "step":
        return (Event(FORCING_START_S, exp01.SETPOINT_TAG, nominal_setpoint + FORCING_AMPLITUDE),)
    times = np.arange(FORCING_START_S, duration_s, FORCING_UPDATE_S)
    return tuple(
        Event(float(time_s), exp01.SETPOINT_TAG, nominal_setpoint + _wave(case, float(time_s)))
        for time_s in times
    )


def _wave(case: Case, time_s: float) -> float:
    """Setpoint offset at ``time_s``: a sine, or its sign for the square wave."""
    phase = math.sin(2.0 * math.pi * (time_s - FORCING_START_S) / case.period_s)
    if case.forcing == "sine":
        return FORCING_AMPLITUDE * phase
    if case.forcing == "square":
        return FORCING_AMPLITUDE * (1.0 if phase >= 0.0 else -1.0)
    raise ValueError(f"unknown forcing {case.forcing!r}; expected one of {FORCINGS}")


Params = tuple[tuple[str, float], ...]


def _tuned_params(case: Case, params: Params) -> Params:
    """Add the aggressive gains of the case to the scenario params (default tuning adds none)."""
    if case.tuning == "default":
        return params
    if case.tuning != "aggressive":
        raise ValueError(f"unknown tuning {case.tuning!r}; expected one of {TUNINGS}")
    gains = {
        f"kc_{LOOP}": DEFAULT_KC[LOOP] * AGGRESSIVE_KC_FACTOR,
        f"ti_s_{LOOP}": DEFAULT_TI_S * AGGRESSIVE_TI_FACTOR,
    }
    return exp01._override(params, **gains)


def simulate_case(case: Case, seed: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Run one case and return (pv, out, dt_s) of the HPGR pressure loop, every step recorded."""
    scenario = exp01._configure_scenario(case.band_percent, case.noise)
    plant = MillCircuitPlant()
    plant.reset(seed, scenario)
    nominal_setpoint = plant.read(exp01.SETPOINT_TAG)[0]
    events = forcing_events(case, nominal_setpoint, scenario.duration_s)
    params = _tuned_params(case, scenario.params)
    scenario = dataclasses.replace(scenario, events=events, params=params)
    plant.reset(seed, scenario)
    steps = int(round(scenario.duration_s / scenario.dt_s))
    pv = np.empty(steps)
    out = np.empty(steps)
    for step in range(steps):
        pv[step] = plant.read(exp01.PV_TAG)[0]
        out[step] = plant.read(exp01.OUT_TAG)[0]
        plant.step()
    return pv, out, scenario.dt_s

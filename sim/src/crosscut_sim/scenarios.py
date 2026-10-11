# sim/src/crosscut_sim/scenarios.py
"""Scenario definitions and utilities for the Crosscut simulation suite.

The public API consists of:

* :func:`random_binary_events` – generate a deterministic binary disturbance series.
* :func:`available_scenarios` – list scenario names for a given plant.
* :func:`build_scenario` – construct a :class:`~crosscut_sim.core.Scenario` instance.

Only the ``wood_berry`` plant is currently supported, but the implementation is
extensible via a registry mapping plant identifiers to builder callables.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping

import numpy as np

from .core import Event, Scenario
from .plants.mill_circuit import NOMINAL as MILL_NOMINAL
from .plants.wood_berry import NOMINAL

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #


def random_binary_events(
    tag_id: str,
    *,
    center: float,
    amplitude: float,
    switch_period_s: float,
    duration_s: float,
    seed: int,
) -> tuple[Event, ...]:
    """Return a deterministic series of binary ``Event`` objects.

    Parameters
    ----------
    tag_id:
        Identifier of the tag that the events target.
    center:
        Mid‑point of the binary values.
    amplitude:
        Distance from ``center`` to each extreme value. Must be non‑negative.
    switch_period_s:
        Time interval between successive events; must be positive.
    duration_s:
        Total duration of the series; must be positive.
    seed:
        Seed for the random number generator; ensures reproducibility.

    Returns
    -------
    tuple[Event, ...]
        A tuple of events at times ``k * switch_period_s`` for
        ``k = 0 .. event_count‑1`` where
        ``event_count = ceil(duration_s / switch_period_s)``.
        The value of each event is either ``center - amplitude`` or
        ``center + amplitude`` depending on a random binary draw.

    Raises
    ------
    ValueError
        If ``switch_period_s`` or ``duration_s`` is not positive, or if
        ``amplitude`` is negative.
    """
    if switch_period_s <= 0:
        raise ValueError("switch_period_s must be positive")
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    if amplitude < 0:
        raise ValueError("amplitude must be non‑negative")

    event_count = int(math.ceil(duration_s / switch_period_s))
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, 2, size=event_count)

    events = []
    low_value = center - amplitude
    high_value = center + amplitude
    for index, draw in enumerate(draws):
        event_time_s = index * switch_period_s
        value = low_value if draw == 0 else high_value
        events.append(Event(t_s=event_time_s, tag_id=tag_id, value=value))

    return tuple(events)


# --------------------------------------------------------------------------- #
# Plant‑specific scenario registries
# --------------------------------------------------------------------------- #


def _build_wood_berry_scenario(scenario_name: str, duration_s: float) -> Scenario:
    """Create a :class:`Scenario` for the Wood‑Berry plant.

    Supported ``scenario_name`` values are:

    * ``"nominal"``
    * ``"noisy_feed"``
    * ``"feed_step"``
    * ``"excited"``
    """
    dt = 1.0
    if scenario_name == "nominal":
        return _build_wood_berry_nominal(duration_s, dt)
    if scenario_name == "noisy_feed":
        return _build_wood_berry_noisy_feed(duration_s, dt)
    if scenario_name == "feed_step":
        return _build_wood_berry_feed_step(duration_s, dt)
    if scenario_name == "excited":
        return _build_wood_berry_excited(duration_s, dt)
    raise ValueError(f"unknown scenario for wood_berry: {scenario_name!r}")

def _build_wood_berry_nominal(duration_s: float, dt: float) -> Scenario:
    """Return the nominal Wood‑Berry scenario: no disturbance, no events."""
    return Scenario(
        name="nominal",
        duration_s=duration_s,
        dt_s=dt,
        measurement_noise=1.0,
        disturbance_sigma=0.0,
        events=(),
    )

def _build_wood_berry_noisy_feed(duration_s: float, dt: float) -> Scenario:
    """Return the Wood‑Berry scenario with a correlated feed disturbance."""
    return Scenario(
        name="noisy_feed",
        duration_s=duration_s,
        dt_s=dt,
        measurement_noise=1.0,
        disturbance_sigma=0.02,
        disturbance_tau_s=1800.0,
        events=(),
    )

def _build_wood_berry_feed_step(duration_s: float, dt: float) -> Scenario:
    """Return the Wood‑Berry scenario with a single feed rate step."""
    step_event = Event(
        t_s=duration_s / 4.0,
        tag_id="sim.wb.feed_rate",
        value=NOMINAL["feed_rate"] + 0.1,
    )
    return Scenario(
        name="feed_step",
        duration_s=duration_s,
        dt_s=dt,
        measurement_noise=1.0,
        events=(step_event,),
    )

def _build_wood_berry_excited(duration_s: float, dt: float) -> Scenario:
    """Return the Wood‑Berry scenario with binary setpoint excitation on both compositions."""
    merged = _build_wood_berry_excitation_events(duration_s)
    return Scenario(
        name="excited",
        duration_s=duration_s,
        dt_s=dt,
        measurement_noise=1.0,
        events=merged,
    )

def _build_wood_berry_excitation_events(duration_s: float) -> tuple[Event, ...]:
    """Return the merged, time-sorted excitation events for the excited scenario."""
    top_events = random_binary_events(
        "sim.wb.top_comp_sp",
        center=NOMINAL["top_comp"],
        amplitude=0.5,
        switch_period_s=600.0,
        duration_s=duration_s,
        seed=101,
    )
    bot_events = random_binary_events(
        "sim.wb.bottom_comp_sp",
        center=NOMINAL["bottom_comp"],
        amplitude=0.1,
        switch_period_s=900.0,
        duration_s=duration_s,
        seed=202,
    )
    return tuple(sorted(top_events + bot_events, key=lambda event: event.t_s))


def _build_mill_circuit_scenario(scenario_name: str, duration_s: float) -> Scenario:
    """Create a :class:`Scenario` for the grinding-circuit plant.

    Supported ``scenario_name`` values are ``"nominal"``, ``"observational"``, ``"excited"``,
    ``"quiet"``, ``"hardness_shift"`` and ``"step_test"`` (open-loop OUT steps for identification).

    Raises:
        ValueError: if ``scenario_name`` is not one of the supported names.
    """
    dt = 1.0
    if scenario_name == "nominal":
        return Scenario(
            name=scenario_name,
            duration_s=duration_s,
            dt_s=dt,
            measurement_noise=1.0,
            params=(("operator", 0.0),),
        )
    if scenario_name == "observational":
        return Scenario(
            name=scenario_name,
            duration_s=duration_s,
            dt_s=dt,
            measurement_noise=1.0,
            params=(("operator", 1.0),),
        )
    if scenario_name == "quiet":
        return Scenario(
            name=scenario_name,
            duration_s=duration_s,
            dt_s=dt,
            measurement_noise=0.0,
            params=(
                ("operator", 0.0),
                ("inner_noise", 0.0),
                ("process_noise", 0.0),
                ("hardness_sigma", 0.0),
                ("moisture_sigma", 0.0),
            ),
        )
    if scenario_name == "hardness_shift":
        # The step lands halfway through the run so the first half stays at nominal hardness.
        shift_event = Event(
            t_s=duration_s / 2.0,
            tag_id="sim.mc.hardness_mean",
            value=16.0,
        )
        return Scenario(
            name=scenario_name,
            duration_s=duration_s,
            dt_s=dt,
            measurement_noise=1.0,
            params=(("operator", 0.0),),
            events=(shift_event,),
        )
    if scenario_name == "excited":
        # Three independent binary dithers at different periods keep the inputs persistently
        # excited, which is what the identification step needs.
        press_events = random_binary_events(
            "sim.mc.hpgr_press_sp",
            center=MILL_NOMINAL["hpgr_press"],
            amplitude=0.3,
            switch_period_s=600.0,
            duration_s=duration_s,
            seed=301,
        )
        feed_events = random_binary_events(
            "sim.mc.mill_feed_sp",
            center=MILL_NOMINAL["mill_feed"],
            amplitude=8.0,
            switch_period_s=900.0,
            duration_s=duration_s,
            seed=302,
        )
        water_events = random_binary_events(
            "sim.mc.cyc_water_sp",
            center=MILL_NOMINAL["cyc_water"],
            amplitude=5.0,
            switch_period_s=1200.0,
            duration_s=duration_s,
            seed=303,
        )
        merged = tuple(
            sorted(press_events + feed_events + water_events, key=lambda event: event.t_s)
        )
        return Scenario(
            name=scenario_name,
            duration_s=duration_s,
            dt_s=dt,
            measurement_noise=1.0,
            params=(("operator", 0.0),),
            events=merged,
        )
    if scenario_name == "step_test":
        return Scenario(
            name=scenario_name,
            duration_s=duration_s,
            dt_s=dt,
            measurement_noise=1.0,
            params=(("operator", 0.0),),
            events=_mill_step_test_events(),
        )
    raise ValueError(f"unknown scenario for mill_circuit: {scenario_name!r}")


# Open-loop step test of the three mill loops, one after the other so that they do not disturb
# each other's response: all go to MAN, then each OUT steps up and back after a hold.
STEP_TEST_MAN_AT_S = 300.0
STEP_TEST_FIRST_STEP_S = 900.0
STEP_TEST_HOLD_S = 1200.0
STEP_TEST_BASE_OUT = 50.0
STEP_TEST_SIZE_PCT = 8.0
MILL_LOOP_NAMES = ("hpgr_press", "mill_feed", "cyc_water")


def _mill_step_test_events() -> tuple[Event, ...]:
    """Events of the ``step_test`` scenario: MAN for all loops, then staggered OUT steps."""
    events = [Event(STEP_TEST_MAN_AT_S, f"sim.mc.{name}_mode", 0.0) for name in MILL_LOOP_NAMES]
    for index, name in enumerate(MILL_LOOP_NAMES):
        start = STEP_TEST_FIRST_STEP_S + 2 * index * STEP_TEST_HOLD_S
        out_tag = f"sim.mc.{name}_out"
        events.append(Event(start, out_tag, STEP_TEST_BASE_OUT + STEP_TEST_SIZE_PCT))
        events.append(Event(start + STEP_TEST_HOLD_S, out_tag, STEP_TEST_BASE_OUT))
    return tuple(sorted(events, key=lambda event: event.t_s))


# Registry mapping plant identifiers to their builder functions.
_PLANT_BUILDERS: Mapping[str, Callable[[str, float], Scenario]] = {
    "wood_berry": _build_wood_berry_scenario,
    "mill_circuit": _build_mill_circuit_scenario,
}


def available_scenarios(plant_name: str) -> tuple[str, ...]:
    """Return the tuple of scenario names available for ``plant_name``.

    Raises
    ------
    ValueError
        If ``plant_name`` is not recognised.
    """
    if plant_name not in _PLANT_BUILDERS:
        raise ValueError(f"unknown plant: {plant_name!r}")
    if plant_name == "wood_berry":
        return ("nominal", "noisy_feed", "feed_step", "excited")
    if plant_name == "mill_circuit":
        return ("nominal", "observational", "excited", "quiet", "hardness_shift", "step_test")
    # Future plants can add their own static tuples here.
    raise ValueError(f"scenario list not defined for plant: {plant_name!r}")


def build_scenario(
    plant_name: str,
    scenario_name: str,
    *,
    duration_s: float = 6 * 3600.0,
) -> Scenario:
    """Construct a :class:`Scenario` instance for a given plant and scenario.

    Parameters
    ----------
    plant_name:
        Identifier of the plant (e.g. ``"wood_berry"``).
    scenario_name:
        Name of the scenario to build.
    duration_s:
        Desired simulation duration; defaults to six hours.

    Returns
    -------
    Scenario
        Fully populated scenario object.

    Raises
    ------
    ValueError
        If either the plant or the scenario name is unknown.
    """
    builder = _PLANT_BUILDERS.get(plant_name)
    if builder is None:
        raise ValueError(f"unknown plant: {plant_name!r}")
    if scenario_name not in available_scenarios(plant_name):
        raise ValueError(f"unknown scenario {scenario_name!r} for plant {plant_name!r}")
    return builder(scenario_name, duration_s)

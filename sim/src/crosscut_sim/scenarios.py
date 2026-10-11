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
        ``k = 0 .. n‑1`` where ``n = ceil(duration_s / switch_period_s)``.
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

    n = int(math.ceil(duration_s / switch_period_s))
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, 2, size=n)

    events = []
    low = center - amplitude
    high = center + amplitude
    for k, draw in enumerate(draws):
        t = k * switch_period_s
        value = low if draw == 0 else high
        events.append(Event(t_s=t, tag_id=tag_id, value=value))

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
        return Scenario(
            name=scenario_name,
            duration_s=duration_s,
            dt_s=dt,
            measurement_noise=1.0,
            disturbance_sigma=0.0,
            events=(),
        )
    if scenario_name == "noisy_feed":
        return Scenario(
            name=scenario_name,
            duration_s=duration_s,
            dt_s=dt,
            measurement_noise=1.0,
            disturbance_sigma=0.02,
            disturbance_tau_s=1800.0,
            events=(),
        )
    if scenario_name == "feed_step":
        step_event = Event(
            t_s=duration_s / 4.0,
            tag_id="sim.wb.feed_rate",
            value=NOMINAL["feed_rate"] + 0.1,
        )
        return Scenario(
            name=scenario_name,
            duration_s=duration_s,
            dt_s=dt,
            measurement_noise=1.0,
            events=(step_event,),
        )
    if scenario_name == "excited":
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
        merged = tuple(sorted(top_events + bot_events, key=lambda e: e.t_s))
        return Scenario(
            name=scenario_name,
            duration_s=duration_s,
            dt_s=dt,
            measurement_noise=1.0,
            events=merged,
        )
    raise ValueError(f"unknown scenario for wood_berry: {scenario_name!r}")


# Registry mapping plant identifiers to their builder functions.
_PLANT_BUILDERS: Mapping[str, Callable[[str, float], Scenario]] = {
    "wood_berry": _build_wood_berry_scenario,
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

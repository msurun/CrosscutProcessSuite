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
from dataclasses import dataclass
from typing import Any

import numpy as np

from .core import Event, Scenario
from .plants.mill_circuit import NOMINAL as MILL_NOMINAL
from .plants.wood_berry import NOMINAL

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BinarySignal:
    """Shape of a two-level random signal: levels ``center -/+ amplitude``, one draw per period.

    ``center`` and ``amplitude`` share the unit of the tag; ``switch_period_s`` and
    ``duration_s`` are in seconds.
    """

    center: float
    amplitude: float
    switch_period_s: float
    duration_s: float

    def __post_init__(self) -> None:
        """Reject shapes that cannot produce a sensible series."""
        if self.switch_period_s <= 0:
            raise ValueError("switch_period_s must be positive")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be positive")
        if self.amplitude < 0:
            raise ValueError("amplitude must be non‑negative")


def random_binary_events(tag_id: str, signal: BinarySignal, seed: int) -> tuple[Event, ...]:
    """Return a deterministic series of binary ``Event`` objects.

    Models a two-state ("binary") signal sampled at a fixed period: at each
    sample the signal sits at one of two values, chosen at random, like a
    coin flipped once per period.

    Parameters
    ----------
    tag_id:
        Identifier of the tag that the events target.
    signal:
        Mid‑point (``center``), half-distance between the two values (``amplitude``,
        non‑negative), time between successive events (``switch_period_s``, positive) and
        total duration (``duration_s``, positive).
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

    Notes
    -----
    The events form a square wave whose two levels sit symmetrically around
    ``center``. Reproducibility holds because the whole draw is generated from
    one seeded generator, so the same seed always yields the same sequence.
    """
    # Number of sample slots in the series. The ceiling rounds up so that a
    # duration that is not an exact multiple of the period still gets a final
    # partial slot. Unit: count of events.
    event_count = int(math.ceil(signal.duration_s / signal.switch_period_s))
    # A dedicated generator (not the global NumPy state) makes the outcome
    # depend only on `seed`, so runs are reproducible and isolated.
    rng = np.random.default_rng(seed)
    # `size` is an int, so this returns a 1-D array of `event_count` integers,
    # each 0 or 1 (uniformly drawn) — the coin flip per sample slot.
    draws = rng.integers(0, 2, size=event_count)

    # The two possible signal levels: the low and high rails of the square
    # wave, placed `amplitude` on either side of `center`. Unit: same unit as
    # `center` and `amplitude`.
    events = []
    low_value = signal.center - signal.amplitude
    high_value = signal.center + signal.amplitude
    # One event per sample slot, walked in time order. `index` is the slot
    # number k, so the timestamps are exactly k * switch_period_s (seconds).
    for index, draw in enumerate(draws):
        event_time_s = index * signal.switch_period_s
        value = low_value if draw == 0 else high_value
        events.append(Event(t_s=event_time_s, tag_id=tag_id, value=value))

    # Return an immutable tuple so callers cannot mutate the series in place.
    return tuple(events)


# --------------------------------------------------------------------------- #
# Plant‑specific scenario registries
# --------------------------------------------------------------------------- #


def _build_wood_berry_scenario(scenario_name: str, duration_s: float) -> Scenario:
    """Create a :class:`Scenario` for the Wood‑Berry plant.

    The Wood–Berry plant is a classic benchmark model of a binary distillation
    column: a feed entering a column is split into a distillate and a bottoms
    product, and the dynamics describe how composition and holdup evolve.

    Supported ``scenario_name`` values are:

    * ``"nominal"`` — steady conditions, used as the baseline.
    * ``"noisy_feed"`` — feed measurement carries noise, for filter tests.
    * ``"feed_step"`` — a step change in the feed, for tracking tests.
    * ``"excited"`` — a driving signal rich in frequencies, for identification.

    ``duration_s`` is the simulated time span in seconds. Every scenario uses the
    same sampling period ``dt`` (seconds) so they can be compared directly.

    Returns:
        A :class:`Scenario` configured for the requested case.

    Raises:
        ValueError: if ``scenario_name`` is not one of the names above.
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
    """Return the nominal Wood‑Berry scenario: no disturbance, no events.

    The Wood–Berry model is a small compartmental model used to benchmark
    state estimators: a reactor is fed by a stream whose composition can
    drift, and the estimator must recover the states from noisy measurements.

    Arguments:
        duration_s: how long the simulation runs, in seconds.
        dt: simulation step, in seconds.

    Returns:
        A Scenario with idealised settings: white measurement noise only,
        no process disturbance and no scheduled events.
    """
    return Scenario(
        name="nominal",
        duration_s=duration_s,
        dt_s=dt,
        # Standard deviation of the measurement noise, in the units of the
        # measured variables: 1.0 unit gives a signal-to-noise ratio of about
        # 10:1 against the nominal state magnitudes of this model.
        measurement_noise=1.0,
        # Standard deviation of the process disturbance, same units: 0.0 means
        # the states evolve exactly as the (unknown to the estimator) model
        # predicts, so any error the estimator makes is its own.
        disturbance_sigma=0.0,
        # Empty tuple: no time-scheduled interventions (e.g. a step change in
        # the feed) happen during the run.
        events=(),
    )


def _build_wood_berry_noisy_feed(duration_s: float, dt: float) -> Scenario:
    """Return the Wood-Berry scenario with a correlated feed disturbance.

    The Wood-Berry model is the classic 2x2 distillation control benchmark: two
    manipulated inputs (reflux and reboiler steam) drive two outputs (top and
    bottom composition). "Noisy feed" means the disturbance entering the plant
    is not white noise but a slowly wandering signal, which is what a real feed
    stream looks like.

    Parameters:
        duration_s: simulated horizon in seconds.
        dt: integration/sampling step in seconds.

    Returns:
        A Scenario with the disturbance parameters below and no scheduled events.
    """
    return Scenario(
        name="noisy_feed",
        duration_s=duration_s,
        dt_s=dt,
        # Standard deviation of the measurement noise added to the outputs:
        # unit is mole-fraction of the measured composition.
        measurement_noise=1.0,
        # The disturbance is modelled as an Ornstein-Uhlenbeck process
        # (mean-reverting random walk): disturbance_sigma is its stationary
        # standard deviation in the same unit as the feed disturbance, and
        # disturbance_tau_s is its time constant in seconds (time for a deviation
        # to decay to about 37% of its initial value).
        disturbance_sigma=0.02,
        disturbance_tau_s=1800.0,
        events=(),
    )


def _build_wood_berry_feed_step(duration_s: float, dt: float) -> Scenario:
    """Return the Wood‑Berry scenario with a single feed rate step.

    The Wood-Berry model is a well-known 2x2 distillation column benchmark
    (Wood & Berry, 1973) used to compare controller tuning. It maps two
    manipulated inputs (reflux, reboiler steam) to two controlled outputs
    (top and bottom compositions). This scenario keeps the plant at its
    nominal operating point and then applies ONE step change to the feed
    rate, so a controller's disturbance rejection can be observed.
    """
    # A feed rate step is a DISTURBANCE: it shifts the plant away from its
    # nominal steady state and the controller must bring the outputs back.
    # The step fires at one quarter of the run, leaving the remaining three
    # quarters for the transient to settle and be measured.
    step_event = Event(
        # Time of the step, in seconds from the start of the run.
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
    """Return the Wood‑Berry scenario with binary setpoint excitation on both compositions.

    Wood and Berry is a classic binary distillation column benchmark model: the two
    controlled variables (top and bottom compositions) respond slowly and with strong
    coupling, which makes it the standard test case for identification and control.

    A good identification data set must contain enough variation in the inputs, or the
    fitted model is ill-conditioned. This scenario adds "binary setpoint excitation":
    the composition setpoints are stepped repeatedly between two levels so that both
    outputs are driven through a wide range of operating points.

    Parameters
    ----------
    duration_s : float
        Simulated time span in seconds.
    dt : float
        Simulation time step in seconds.

    Returns
    -------
    Scenario
        Scenario named "excited" carrying the merged excitation events.
    """
    merged = _build_wood_berry_excitation_events(duration_s)
    return Scenario(
        name="excited",
        duration_s=duration_s,
        dt_s=dt,
        # Standard deviation of the added measurement noise, in the unit of the
        # measured composition.
        measurement_noise=1.0,
        events=merged,
    )


def _build_wood_berry_excitation_events(duration_s: float) -> tuple[Event, ...]:
    """Return the merged, time-sorted excitation events for the excited scenario.

    The Wood-Berry distillation column has two manipulated compositions: the
    top (distillate) and bottom (bottoms) composition setpoints. In the excited
    scenario both setpoints are driven by independent random binary signals, so
    each signal is built separately and the resulting events are merged.

    Args:
        duration_s: Length of the simulated window in seconds.

    Returns:
        A tuple of events ordered by ``t_s`` (ascending), ready to be replayed
        by the simulator.
    """
    # Top composition: amplitude 0.5, a new random draw every 600 s.
    top_events = random_binary_events(
        "sim.wb.top_comp_sp",
        BinarySignal(NOMINAL["top_comp"], 0.5, 600.0, duration_s),
        seed=101,
    )
    # Bottom composition: same construction, switch period 900 s and a smaller amplitude (0.1).
    bot_events = random_binary_events(
        "sim.wb.bottom_comp_sp",
        BinarySignal(NOMINAL["bottom_comp"], 0.1, 900.0, duration_s),
        seed=202,
    )
    # Merge the two event tuples and sort by simulation time so the simulator
    # can consume them in chronological order.
    return tuple(sorted(top_events + bot_events, key=lambda event: event.t_s))


def _mill_scenario(scenario_name: str, duration_s: float, **overrides: Any) -> Scenario:
    """Build a mill-circuit Scenario from the shared defaults, replacing the given fields.

    Defaults: 1 s step, unit sensor noise, operator parameter off.
    """
    fields: dict[str, Any] = {
        "name": scenario_name,
        "duration_s": duration_s,
        "dt_s": 1.0,
        "measurement_noise": 1.0,
        "params": (("operator", 0.0),),
    }
    fields.update(overrides)
    return Scenario(**fields)


def _mill_excitation_events(duration_s: float) -> tuple[Event, ...]:
    """Merged, time-sorted random binary setpoint moves on the three mill loops."""
    loops = (
        ("sim.mc.hpgr_press_sp", "hpgr_press", 0.3, 600.0, 301),
        ("sim.mc.mill_feed_sp", "mill_feed", 8.0, 900.0, 302),
        ("sim.mc.cyc_water_sp", "cyc_water", 5.0, 1200.0, 303),
    )
    events: tuple[Event, ...] = ()
    for tag_id, nominal_key, amplitude, period_s, seed in loops:
        signal = BinarySignal(MILL_NOMINAL[nominal_key], amplitude, period_s, duration_s)
        events += random_binary_events(tag_id, signal, seed=seed)
    return tuple(sorted(events, key=lambda event: event.t_s))


def _build_mill_circuit_scenario(scenario_name: str, duration_s: float) -> Scenario:
    """Create a :class:`Scenario` for the grinding-circuit plant.

    A grinding circuit crushes ore: a high-pressure grinding roll (HPGR) presses the feed,
    the mill grinds it, and a cyclone separates fine product from coarse material that is
    recirculated. A scenario is one named experiment on that plant, describing how long it
    runs, the sampling interval, how much sensor noise is added, which model parameters
    (``params``) are overridden, and which scheduled setpoint changes (``events``) occur.

    Supported ``scenario_name`` values are ``"nominal"``, ``"observational"``, ``"excited"``,
    ``"quiet"``, ``"hardness_shift"`` and ``"step_test"`` (open-loop OUT steps for identification) and ``"stiction"`` (sticking HPGR valve).

    Args:
        scenario_name: Which experiment to build; must be one of the supported names.
        duration_s: Simulated length of the run, in seconds.

    Returns:
        The configured :class:`Scenario`.

    Raises:
        ValueError: if ``scenario_name`` is not one of the supported names.
    """
    if scenario_name == "nominal":
        return _mill_scenario(scenario_name, duration_s)
    if scenario_name == "observational":
        return _mill_scenario(scenario_name, duration_s, params=(("operator", 1.0),))
    if scenario_name == "quiet":
        return _mill_scenario(
            scenario_name, duration_s, measurement_noise=0.0, params=_QUIET_PARAMS
        )
    if scenario_name == "hardness_shift":
        shift_event = Event(t_s=duration_s / 2.0, tag_id="sim.mc.hardness_mean", value=16.0)
        return _mill_scenario(scenario_name, duration_s, events=(shift_event,))
    if scenario_name == "excited":
        return _mill_scenario(scenario_name, duration_s, events=_mill_excitation_events(duration_s))
    if scenario_name == "step_test":
        return _mill_scenario(scenario_name, duration_s, events=_mill_step_test_events())
    if scenario_name == "stiction":
        return _mill_scenario(scenario_name, duration_s, params=_STICTION_PARAMS)
    raise ValueError(f"unknown scenario for mill_circuit: {scenario_name!r}")


# The "stiction" scenario sticks the HPGR pressure valve: a 3 % deadband and a 1.5 % slip jump
# (both in % of valve travel) make its loop swing in the stick-slip cycle a detector must find.
_STICTION_PARAMS = (
    ("operator", 0.0),
    ("stiction_band_hpgr_press", 3.0),
    ("stiction_jump_hpgr_press", 1.5),
)

# The "quiet" scenario switches every noise source off (operator included).
_QUIET_PARAMS = (
    ("operator", 0.0),
    ("inner_noise", 0.0),
    ("process_noise", 0.0),
    ("hardness_sigma", 0.0),
    ("moisture_sigma", 0.0),
)


STEP_TEST_MAN_AT_S = 300.0
STEP_TEST_FIRST_STEP_S = 900.0
STEP_TEST_HOLD_S = 1200.0
STEP_TEST_BASE_OUT = 50.0
STEP_TEST_SIZE_PCT = 8.0
MILL_LOOP_NAMES = ("hpgr_press", "mill_feed", "cyc_water")


def _mill_step_test_events() -> tuple[Event, ...]:
    """Events of the ``step_test`` scenario: MAN for all loops, then staggered OUT steps.

    The scenario mimics an operator pressing the manual (MAN) button on every mill loop, then
    applying a step change to each loop's OUT (controller output) one after another.

    Each loop stays in MAN for the whole scenario. The OUT steps are *staggered*: loop 0 starts
    at STEP_TEST_FIRST_STEP_S, loop 1 two hold-periods later, and so on. Staggering matters
    because a simultaneous step on every loop would superimpose all responses at once, making
    it impossible to attribute a change in the mill to a single loop.

    An ``Event`` carries a simulation time ``t_s`` (seconds), a tag, and a value. Two events are
    emitted per loop: one that raises OUT, and one hold-period later that restores it. Every loop
    is put into MAN before any step happens, so the steps start from a steady, manual baseline.

    Returns:
        All events sorted by increasing simulation time; the simulation engine consumes them in
        this order.
    """
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

    A *scenario* is a named, fixed set of simulation conditions used to
    exercise one plant model: "nominal" means no disturbance at all, while
    the other names inject a specific perturbation (noisy feed, step in a
    setpoint, excitation signal, plant shut down, and so on).  Callers look
    scenarios up by name, so this function is the authoritative catalogue
    of what may be requested.

    Parameters
    ----------
    plant_name : str
        Key of a plant registered in ``_PLANT_BUILDERS``.

    Returns
    -------
    tuple[str, ...]
        The scenario names this plant supports.

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
        return ("nominal", "observational", "excited", "quiet", "hardness_shift", "step_test", "stiction")
    raise ValueError(f"scenario list not defined for plant: {plant_name!r}")


def build_scenario(
    plant_name: str,
    scenario_name: str,
    *,
    duration_s: float = 6 * 3600.0,
) -> Scenario:
    """Construct a :class:`Scenario` instance for a given plant and scenario.

    A plant is a physical site (a biomass plant, a gas turbine, ...) and a
    scenario is one way of running it (normal day, blackout, ...). Each plant
    ships its own builder, so this function only dispatches: it looks up the
    builder registered for ``plant_name`` and hands the remaining arguments
    over to it.

    Parameters
    ----------
    plant_name:
        Identifier of the plant (e.g. ``"wood_berry"``).
    scenario_name:
        Name of the scenario to build.
    duration_s:
        Desired simulation duration, in seconds; defaults to six hours
        (``6 * 3600.0``). Keyword-only, so callers must name it.

    Returns
    -------
    Scenario
        Fully populated scenario object.

    Raises
    ------
    ValueError
        If either the plant or the scenario name is unknown.
    """
    # Look up the scenario builder for the requested plant; unknown plants fail
    # with the same error as ``available_scenarios``.
    builder = _PLANT_BUILDERS.get(plant_name)
    if builder is None:
        raise ValueError(f"unknown plant: {plant_name!r}")
    # Validate ``scenario_name`` before calling the builder so the error is
    # raised here with both names in the message.
    if scenario_name not in available_scenarios(plant_name):
        raise ValueError(f"unknown scenario {scenario_name!r} for plant {plant_name!r}")
    return builder(scenario_name, duration_s)

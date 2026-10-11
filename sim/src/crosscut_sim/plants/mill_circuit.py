"""Grinding-circuit simulation (HPGR, ball mill and hydrocyclone) with known ground truth.

The model is deliberately simplified and is NOT physically accurate. Its purpose is to provide
synthetic data with known causal gains, ore-hardness dependent (heterogeneous) gains, and an
operator whose setpoint changes are confounded by the ore hardness. Times are in seconds.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from crosscut_sim.core import AUTO, CAS, GOOD, MAN, Event, Fopdt, Scenario, TagCatalog, TagSpec
from crosscut_sim.disturbances import OrnsteinUhlenbeck
from crosscut_sim.pid import PID

NOMINAL: dict[str, float] = {
    "hpgr_press": 3.5,
    "mill_feed": 150.0,
    "cyc_water": 100.0,
    "ore_hardness": 14.0,
    "feed_moisture": 4.0,
    "p80": 150.0,
    "mill_power": 3000.0,
    "hpgr_power": 1800.0,
}

NOMINAL_OUT = 50.0
REFERENCE_HARDNESS = 14.0
OPERATOR_PERIOD_S = 1800.0
ESTIMATE_PERIOD_S = 1800.0
_EPS = 1e-9

DRIVERS = ("hpgr_press", "mill_feed", "cyc_water", "ore_hardness", "feed_moisture")
CVS = ("p80", "mill_power", "hpgr_power")

HARD_MEAN = "sim.mc.hardness_mean"
HARD_EST = "sim.mc.ore_hardness_est"
MOIST = "sim.mc.feed_moisture"
CV_TAGS: dict[str, str] = {cv: f"sim.mc.{cv}" for cv in CVS}

_CV_UNITS = {"p80": "um", "mill_power": "kW", "hpgr_power": "kW"}
_CV_ENG_MAX = {"p80": 500.0, "mill_power": 6000.0, "hpgr_power": 4000.0}
_CV_DESCRIPTIONS = {
    "p80": "P80 of the ground product (measured)",
    "mill_power": "Ball mill drive power (measured)",
    "hpgr_power": "HPGR drive power (measured)",
}
_CV_PROCESS_SIGMA = {"p80": 1.0, "mill_power": 40.0, "hpgr_power": 20.0}
_CV_MEAS_SD = {"p80": 0.5, "mill_power": 15.0, "hpgr_power": 8.0}

# (driver, cv) -> (g0 per unit of driver, relative hardness slope s, tau in min, delay in min)
_PATHS: dict[tuple[str, str], tuple[float, float, float, float]] = {
    ("hpgr_press", "p80"): (-20.0, 0.08, 4.0, 1.0),
    ("mill_feed", "p80"): (0.45, 0.10, 8.0, 2.0),
    ("cyc_water", "p80"): (-0.6, 0.0, 3.0, 0.5),
    ("ore_hardness", "p80"): (6.0, 0.0, 10.0, 1.0),
    ("feed_moisture", "p80"): (2.0, 0.0, 6.0, 0.5),
    ("hpgr_press", "mill_power"): (-150.0, 0.05, 5.0, 1.0),
    ("mill_feed", "mill_power"): (10.0, 0.04, 6.0, 1.0),
    ("cyc_water", "mill_power"): (1.0, 0.0, 3.0, 0.5),
    ("ore_hardness", "mill_power"): (80.0, 0.0, 8.0, 1.0),
    ("feed_moisture", "mill_power"): (-20.0, 0.0, 4.0, 0.5),
    ("hpgr_press", "hpgr_power"): (250.0, 0.05, 1.0, 0.1667),
    ("ore_hardness", "hpgr_power"): (60.0, 0.0, 6.0, 1.0),
}


@dataclass(frozen=True)
class _LoopSpec:
    """Static description of one actuator loop (PV, SP, RSP, MODE and OUT tags)."""

    name: str
    unit: str
    eng_min: float
    eng_max: float
    description: str
    kc: float
    actuator_gain: float
    actuator_tau_s: float
    inner_sigma: float
    meas_sd: float

    @property
    def tag(self) -> str:
        """Return the simulator's tag as a Monte Carlo identifier built from its name."""
        return f"sim.mc.{self.name}"


LOOPS: tuple[_LoopSpec, ...] = (
    _LoopSpec(
        name="hpgr_press",
        unit="N/mm2",
        eng_min=0.0,
        eng_max=6.0,
        description="HPGR specific roll pressure",
        kc=7.0,
        actuator_gain=0.07,
        actuator_tau_s=30.0,
        inner_sigma=0.08,
        meas_sd=0.01,
    ),
    _LoopSpec(
        name="mill_feed",
        unit="t/h",
        eng_min=0.0,
        eng_max=300.0,
        description="Ball mill fresh feed rate",
        kc=0.17,
        actuator_gain=3.0,
        actuator_tau_s=20.0,
        inner_sigma=3.0,
        meas_sd=0.5,
    ),
    _LoopSpec(
        name="cyc_water",
        unit="m3/h",
        eng_min=0.0,
        eng_max=200.0,
        description="Hydrocyclone dilution water flow",
        kc=0.25,
        actuator_gain=2.0,
        actuator_tau_s=15.0,
        inner_sigma=2.0,
        meas_sd=0.3,
    ),
)

_LOOP_KINDS: tuple[tuple[str, str], ...] = (
    ("pv", ""),
    ("sp", "_sp"),
    ("rsp", "_rsp"),
    ("mode", "_mode"),
    ("out", "_out"),
)


def _gain(base_gain: float, sensitivity: float, hardness: float) -> float:
    """Return the driver-to-CV gain at the given ore hardness."""
    return base_gain * (1.0 + sensitivity * (hardness - REFERENCE_HARDNESS))


def _build_tag_catalog() -> TagCatalog:
    specs: list[TagSpec] = []
    for loop in LOOPS:
        specs.extend(_tag_specs_for_loop(loop))
    specs.extend(_tag_specs_for_disturbances())
    for cv in CVS:
        specs.append(_tag_spec_for_cv(cv))
    return TagCatalog(specs)


def _tag_specs_for_loop(loop: _LoopSpec) -> list[TagSpec]:
    """Return the five tags describing one control loop, PV first."""
    return [
        _loop_pv_spec(loop),
        _loop_sp_spec(loop, suffix="_sp", description_suffix="active setpoint"),
        _loop_sp_spec(loop, suffix="_rsp", description_suffix="remote setpoint"),
        _loop_mode_spec(loop),
        _loop_out_spec(loop),
    ]


def _loop_pv_spec(loop: _LoopSpec) -> TagSpec:
    """Return the measured process variable tag of a loop."""
    return TagSpec(
        id=loop.tag,
        unit=loop.unit,
        role="PV",
        type="float",
        description=f"{loop.description} (measured)",
        eng_min=loop.eng_min,
        eng_max=loop.eng_max,
        writable=False,
    )


def _loop_sp_spec(loop: _LoopSpec, suffix: str, description_suffix: str) -> TagSpec:
    """Return a setpoint tag of a loop; `suffix` distinguishes active from remote."""
    return TagSpec(
        id=f"{loop.tag}{suffix}",
        unit=loop.unit,
        role="SP",
        type="float",
        description=f"{loop.description} {description_suffix}",
        eng_min=loop.eng_min,
        eng_max=loop.eng_max,
        writable=True,
    )


def _loop_mode_spec(loop: _LoopSpec) -> TagSpec:
    """Return the operating mode tag of a loop, 0=MAN, 1=AUTO, 2=CAS."""
    return TagSpec(
        id=f"{loop.tag}_mode",
        unit="",
        role="MODE",
        type="enum",
        description=f"{loop.description} loop mode (0=MAN, 1=AUTO, 2=CAS)",
        eng_min=0.0,
        eng_max=2.0,
        writable=True,
    )


def _loop_out_spec(loop: _LoopSpec) -> TagSpec:
    """Return the controller output tag of a loop, in percent."""
    return TagSpec(
        id=f"{loop.tag}_out",
        unit="%",
        role="OUT",
        type="float",
        description=f"{loop.description} controller output",
        eng_min=0.0,
        eng_max=100.0,
        writable=True,
    )


def _tag_specs_for_disturbances() -> list[TagSpec]:
    """Return the hardness and moisture tags that drive the simulation."""
    return [
        _hard_mean_spec(),
        _hard_est_spec(),
        _moist_spec(),
    ]


def _hard_mean_spec() -> TagSpec:
    """Return the writable tag carrying the true ore hardness mean."""
    return TagSpec(
        id=HARD_MEAN,
        unit="kWh/t",
        role="other",
        type="float",
        description="Mean of the true ore hardness (writable simulation driver)",
        eng_min=5.0,
        eng_max=30.0,
        writable=True,
    )


def _hard_est_spec() -> TagSpec:
    """Return the ore hardness estimate tag, sampled every 30 min."""
    return TagSpec(
        id=HARD_EST,
        unit="kWh/t",
        role="DV",
        type="float",
        description="Ore hardness estimate, sample-and-hold every 30 min",
    )


def _moist_spec() -> TagSpec:
    """Return the feed moisture tag, measured every step."""
    return TagSpec(
        id=MOIST,
        unit="%",
        role="DV",
        type="float",
        description="Feed moisture (measured every step)",
    )


def _tag_spec_for_cv(cv: str) -> TagSpec:
    """Return the controlled variable tag for one `cv` key."""
    return TagSpec(
        id=CV_TAGS[cv],
        unit=_CV_UNITS[cv],
        role="CV",
        type="float",
        description=_CV_DESCRIPTIONS[cv],
        eng_min=0.0,
        eng_max=_CV_ENG_MAX[cv],
        writable=False,
    )


class _Loop:
    """Mutable state of one actuator loop: PID, actuator lag, inner disturbance and setpoints."""

    def __init__(
        self, spec: _LoopSpec, dt_s: float, inner_scale: float, rng: np.random.Generator
    ) -> None:
        self.spec = spec
        self.pid = self._build_pid(spec, dt_s)
        nominal = NOMINAL[spec.name]
        self.actuator = self._build_actuator(spec, dt_s)
        self.inner = self._build_inner(spec, inner_scale, dt_s, rng)
        self._init_signals(nominal)

    def _build_pid(self, spec: _LoopSpec, dt_s: float) -> PID:
        """Build the PID with the spec gains and seed it in manual at the nominal operating
        point."""
        pid = PID(kc=spec.kc, ti_s=60.0, dt_s=dt_s, out_min=0.0, out_max=100.0, direct=False)
        nominal = NOMINAL[spec.name]
        pid.update(nominal, nominal, "MAN", man_out=NOMINAL_OUT)
        return pid

    def _build_actuator(self, spec: _LoopSpec, dt_s: float) -> Fopdt:
        """Build the actuator model; the delay is already folded into the spec gains, so it is
        zero here."""
        return Fopdt(gain=spec.actuator_gain, tau_s=spec.actuator_tau_s, delay_s=0.0, dt_s=dt_s)

    def _build_inner(
        self, spec: _LoopSpec, inner_scale: float, dt_s: float, rng: np.random.Generator
    ) -> OrnsteinUhlenbeck:
        """Build the inner disturbance; inner_scale scales the spec sigma for faster scenario
        sweeps."""
        return OrnsteinUhlenbeck(
            mean=0.0,
            sigma=spec.inner_sigma * inner_scale,
            tau_s=120.0,
            dt_s=dt_s,
            rng=rng,
        )

    def _init_signals(self, nominal: float) -> None:
        """Start the loop in auto, with setpoint, manual output and PV all at the nominal."""
        self.mode = AUTO
        self.local_sp = nominal
        self.rsp = nominal
        self.manual_out = NOMINAL_OUT
        self.out = NOMINAL_OUT
        self.pv = nominal


class MillCircuitPlant:
    """HPGR, ball mill and cyclone plant: three actuator loops and a hidden ore hardness."""

    tags: TagCatalog
    time_s: float
    dt_s: float

    def __init__(self) -> None:
        self.tags = _build_tag_catalog()
        self.time_s = 0.0
        self.dt_s = 1.0
        self._loop_tags: dict[str, tuple[str, str]] = {}
        for loop in LOOPS:
            for kind, suffix in _LOOP_KINDS:
                self._loop_tags[f"{loop.tag}{suffix}"] = (loop.name, kind)
        self.reset(seed=0)

    @property
    def true_hardness(self) -> float:
        """Hidden true ore hardness in kWh/t (not a tag)."""
        return self._hard_mean + self._hard_ou.value

    @property
    def true_moisture(self) -> float:
        """Hidden true feed moisture in percent (not a tag)."""
        return NOMINAL["feed_moisture"] + self._moist_ou.value

    def true_gain(self, driver: str, cv: str, hardness: float | None = None) -> float:
        """Return the true steady-state gain from ``driver`` to ``cv``.

        Args:
            driver: One of ``DRIVERS``.
            cv: One of ``CVS``.
            hardness: Ore hardness to evaluate at; defaults to the current true hardness.

        Returns:
            The gain (0.0 for driver/CV pairs without a causal path).

        Raises:
            KeyError: If the driver or the CV is unknown.
        """
        if driver not in DRIVERS:
            raise KeyError(f"unknown driver: {driver!r}")
        if cv not in CVS:
            raise KeyError(f"unknown cv: {cv!r}")
        path = _PATHS.get((driver, cv))
        if path is None:
            return 0.0
        evaluated_hardness = self.true_hardness if hardness is None else hardness
        reference_gain, hardness_sensitivity, _, _ = path
        return _gain(reference_gain, hardness_sensitivity, evaluated_hardness)

    def reset(self, seed: int, scenario: Scenario | None = None) -> None:
        """Restore the nominal steady state at time 0 and seed all random generators."""
        self._scenario = scenario if scenario is not None else Scenario()
        dt_s = self._scenario.dt_s
        self.dt_s = dt_s
        self.time_s = 0.0
        rngs = self._spawn_rngs(seed)
        self._assign_fixed_rngs(rngs)
        self._init_loops(dt_s, rngs)
        self._init_ore_and_moisture(dt_s, rngs)
        self._init_process_noise(dt_s, rngs)
        self._init_paths(dt_s)
        self._init_cv_states()
        self._init_operator()
        self._init_events()

    def _spawn_rngs(self, seed: int) -> list[np.random.Generator]:
        """Create ten independent random generators from the given seed."""
        children = np.random.SeedSequence(seed).spawn(10)
        return [np.random.default_rng(child) for child in children]

    def _assign_fixed_rngs(self, rngs: list[np.random.Generator]) -> None:
        """Store the measurement and operator RNGs.

        Fixed assignment: 0 measurements, 1-3 inner disturbances, 4 hardness, 5 moisture,
        6-8 process noise per CV, 9 operator.
        """
        self._meas_rng = rngs[0]
        self._op_rng = rngs[9]

    def _init_loops(self, dt_s: float, rngs: list[np.random.Generator]) -> None:
        """Build the control loops with their inner-noise RNGs."""
        inner_scale = self._scenario.param("inner_noise", 1.0)
        self._loops: dict[str, _Loop] = {
            loop.name: _Loop(loop, dt_s, inner_scale, rngs[1 + i]) for i, loop in enumerate(LOOPS)
        }

    def _init_ore_and_moisture(self, dt_s: float, rngs: list[np.random.Generator]) -> None:
        """Set up ore hardness and moisture Ornstein-Uhlenbeck processes, estimates and
        measurements."""
        self._hard_mean = NOMINAL["ore_hardness"]
        self._hard_ou = OrnsteinUhlenbeck(
            mean=0.0,
            sigma=self._scenario.param("hardness_sigma", 1.5),
            tau_s=14400.0,
            dt_s=dt_s,
            rng=rngs[4],
        )
        self._moist_ou = OrnsteinUhlenbeck(
            mean=0.0,
            sigma=self._scenario.param("moisture_sigma", 0.4),
            tau_s=7200.0,
            dt_s=dt_s,
            rng=rngs[5],
        )
        self._hard_est = NOMINAL["ore_hardness"]
        self._next_est_s = 0.0
        self._moist_meas = NOMINAL["feed_moisture"]

    def _init_process_noise(self, dt_s: float, rngs: list[np.random.Generator]) -> None:
        """Create the per-CV Ornstein-Uhlenbeck process-noise generators."""
        process_scale = self._scenario.param("process_noise", 1.0)
        self._process_ou: dict[str, OrnsteinUhlenbeck] = {
            cv: OrnsteinUhlenbeck(
                mean=0.0,
                sigma=_CV_PROCESS_SIGMA[cv] * process_scale,
                tau_s=300.0,
                dt_s=dt_s,
                rng=rngs[6 + i],
            )
            for i, cv in enumerate(CVS)
        }

    def _init_paths(self, dt_s: float) -> None:
        """Build the first-order-plus-dead-time models for every driver-CV path."""
        self._paths: list[tuple[str, str, float, float, Fopdt]] = [
            (
                driver,
                cv,
                gain_initial,
                variance,
                Fopdt(
                    gain=1.0,
                    tau_s=tau_minutes * 60.0,
                    delay_s=delay_minutes * 60.0,
                    dt_s=dt_s,
                ),
            )
            for (driver, cv), (gain_initial, variance, tau_minutes, delay_minutes) in _PATHS.items()
        ]

    def _init_cv_states(self) -> None:
        """Set the true and measured controlled-variable values to their nominal values."""
        self._cv_true: dict[str, float] = {cv: NOMINAL[cv] for cv in CVS}
        self._cv_meas: dict[str, float] = {cv: NOMINAL[cv] for cv in CVS}

    def _init_operator(self) -> None:
        """Configure the operator state, noise level and next action time."""
        self._operator_on = self._scenario.param("operator", 1.0) > 0.0
        self._operator_noise = self._scenario.param("operator_noise", 1.0)
        self._next_op_s = OPERATOR_PERIOD_S

    def _init_events(self) -> None:
        """Validate scenario event tags and store events sorted by their start time."""
        events: Sequence[Event] = self._scenario.events
        for event in events:
            if event.tag_id not in self.tags:
                raise KeyError(f"Unknown tag in scenario event: {event.tag_id}")
        self._events: list[Event] = sorted(events, key=lambda event: event.t_s)
        self._event_idx = 0

    def step(self) -> None:
        """Advance the simulation by scenario.dt_s."""
        self._apply_due_events()
        self._maybe_apply_operator_action()
        hardness = self._update_process_drivers()
        self._update_controllers()
        actual = self._update_actuators()
        self._update_controlled_variables(actual, hardness)
        self.time_s += self.dt_s

    def _apply_due_events(self) -> None:
        """Write every scenario event due at or before the current time."""
        # Events bypass permission checks: a scenario is an authoritative input.
        while self._event_idx < len(self._events):
            ev = self._events[self._event_idx]
            if ev.t_s > self.time_s:
                break
            self._write(ev.tag_id, ev.value, enforce=False)
            self._event_idx += 1

    def _maybe_apply_operator_action(self) -> None:
        """Fire an operator setpoint change when its period has elapsed."""
        if self._operator_on and self.time_s >= self._next_op_s - _EPS:
            self._next_op_s += OPERATOR_PERIOD_S
            self._operator_act()

    def _update_process_drivers(self) -> float:
        """Update hardness and moisture signals; return the true hardness."""
        self._hard_ou.update()
        self._moist_ou.update()
        hardness = self.true_hardness
        if self.time_s >= self._next_est_s - _EPS:
            self._hard_est = hardness + self._noise(0.5)
            self._next_est_s += ESTIMATE_PERIOD_S
        self._moist_meas = self.true_moisture + self._noise(0.1)
        return hardness

    def _update_controllers(self) -> None:
        """Compute each loop output; the active setpoint is RSP in CAS, local SP otherwise."""
        for loop in self._loops.values():
            if loop.mode == CAS:
                loop.local_sp = loop.rsp
            loop.out = loop.pid.update(
                pv=loop.pv,
                sp=loop.local_sp,
                mode="MAN" if loop.mode == MAN else "AUTO",
                man_out=loop.manual_out,
            )

    def _update_actuators(self) -> dict[str, float]:
        """Advance actuators and return the measured actuator values by name."""
        actual: dict[str, float] = {}
        for name, loop in self._loops.items():
            deviation = loop.actuator.update(loop.out - NOMINAL_OUT)
            actual[name] = NOMINAL[name] + deviation + loop.inner.update()
            loop.pv = actual[name] + self._noise(loop.spec.meas_sd)
        return actual

    def _update_controlled_variables(self, actual: dict[str, float], hardness: float) -> None:
        """Update the true and measured controlled variables from the causal paths."""
        drivers: dict[str, float] = {
            "hpgr_press": actual["hpgr_press"] - NOMINAL["hpgr_press"],
            "mill_feed": actual["mill_feed"] - NOMINAL["mill_feed"],
            "cyc_water": actual["cyc_water"] - NOMINAL["cyc_water"],
            "ore_hardness": hardness - NOMINAL["ore_hardness"],
            "feed_moisture": self.true_moisture - NOMINAL["feed_moisture"],
        }
        contributions = {cv: 0.0 for cv in CVS}
        for driver, cv, gain0, gain_response, path in self._paths:
            driver_deviation = path.update(drivers[driver])
            contributions[cv] += _gain(gain0, gain_response, hardness) * driver_deviation
        for cv in CVS:
            self._cv_true[cv] = NOMINAL[cv] + contributions[cv] + self._process_ou[cv].update()
            self._cv_meas[cv] = self._cv_true[cv] + self._noise(_CV_MEAS_SD[cv])

    def read(self, tag_id: str) -> tuple[float, int]:
        """Return (value, quality); raise KeyError for unknown tags."""
        if tag_id not in self.tags:
            raise KeyError(f"Unknown tag: {tag_id}")
        if tag_id == HARD_MEAN:
            return self._hard_mean, GOOD
        if tag_id == HARD_EST:
            return self._hard_est, GOOD
        if tag_id == MOIST:
            return self._moist_meas, GOOD
        for cv, cv_tag in CV_TAGS.items():
            if tag_id == cv_tag:
                return self._cv_meas[cv], GOOD

        name, kind = self._loop_tags[tag_id]
        loop = self._loops[name]
        return self._read_loop_field(loop, kind), GOOD

    def _read_loop_field(self, loop: _Loop, kind: str) -> float:
        """Return the loop attribute named by kind, in the order read() documents."""
        if kind == "pv":
            return loop.pv
        if kind == "sp":
            return loop.local_sp
        if kind == "rsp":
            return loop.rsp
        if kind == "mode":
            return float(loop.mode)
        return loop.out

    def write(self, tag_id: str, value: float) -> None:
        """Write a tag value adhering to loop permissions and validation rules."""
        self._write(tag_id, value, enforce=True)

    def snapshot(self) -> dict[str, tuple[float, int]]:
        """Return {tag_id: (value, quality)} for every tag in catalog order."""
        return {tag_id: self.read(tag_id) for tag_id in self.tags.ids()}

    def _write(self, tag_id: str, value: float, *, enforce: bool) -> None:
        """Write a tag; with ``enforce`` False (scenario events) permission checks are skipped."""
        if tag_id not in self.tags:
            raise KeyError(f"Unknown tag: {tag_id}")
        if enforce and not self.tags[tag_id].writable:
            raise PermissionError(f"Tag {tag_id} is read-only")

        if tag_id == HARD_MEAN:
            self._hard_mean = float(value)
            return
        if tag_id not in self._loop_tags:
            return  # read-only measured tag reached by an event: nothing to write

        name, kind = self._loop_tags[tag_id]
        loop = self._loops[name]
        if kind == "out":
            if enforce and loop.mode != MAN:
                raise PermissionError(f"Cannot write {tag_id} unless the loop is in MAN mode")
            clamped = float(np.clip(value, 0.0, 100.0))
            loop.manual_out = clamped
            loop.out = clamped
        elif kind == "sp":
            if enforce and loop.mode == CAS:
                raise PermissionError(f"Cannot write {tag_id} while the loop is in CAS mode")
            loop.local_sp = float(value)
        elif kind == "rsp":
            loop.rsp = float(value)
        elif kind == "mode":
            if value not in (MAN, AUTO, CAS):
                raise ValueError(f"Invalid mode value: {value}")
            new_mode = int(value)
            if new_mode == MAN:
                loop.manual_out = loop.out
            loop.mode = new_mode

    def _noise(self, sd: float) -> float:
        """Return measurement noise with standard deviation ``sd`` scaled by the scenario."""
        scale = self._scenario.measurement_noise
        if scale <= 0.0:
            return 0.0
        return sd * scale * float(self._meas_rng.standard_normal())

    def _operator_draw(self, sd: float) -> float:
        """Return operator noise N(0, sd * operator_noise)."""
        return sd * self._operator_noise * float(self._op_rng.standard_normal())

    def _operator_act(self) -> None:
        """Operator writes local setpoints of AUTO loops based on the observed ore hardness."""
        h_obs = self.true_hardness + self._operator_draw(0.3)
        press = self._loops["hpgr_press"]
        if press.mode == AUTO:
            sp = 3.5 + 0.12 * (h_obs - 14.0) + self._operator_draw(0.1)
            press.local_sp = float(np.clip(sp, 2.5, 4.5))
        feed = self._loops["mill_feed"]
        if feed.mode == AUTO:
            sp = 150.0 - 4.0 * (h_obs - 14.0) + self._operator_draw(3.0)
            feed.local_sp = float(np.clip(sp, 100.0, 200.0))
        water = self._loops["cyc_water"]
        if water.mode == AUTO:
            sp = 100.0 + 0.5 * (self._cv_meas["p80"] - 150.0) + self._operator_draw(2.0)
            water.local_sp = float(np.clip(sp, 70.0, 130.0))

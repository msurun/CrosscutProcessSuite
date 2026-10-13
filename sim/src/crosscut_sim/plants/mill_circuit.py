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
from crosscut_sim.disturbances import OrnsteinUhlenbeck, OuShape
from crosscut_sim.pid import PID, OutputLimits, PidTuning

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
    """Assemble the full catalog of PI tag definitions the rest of the app queries.

    A "tag" is one named time series in the plant historian (PI); a TagSpec describes one tag:
    its name, data type and unit. This function produces the single catalog all callers share,
    by gathering every tag family and concatenating them in a fixed order.

    Returns:
        TagCatalog: immutable catalog holding every TagSpec, in the order added below:
        loop tags, then disturbance tags, then CV tags.
    """
    # Built up in three blocks because the tag families have different shapes:
    # loops come from a table of processes, disturbances and CVs are flat config lists.
    specs: list[TagSpec] = []

    # Every process loop contributes a fixed bundle of tags (flow, pressure, controller setpoint,
    # and so on); _tag_specs_for_loop returns that whole bundle as a list, so extend flattens it
    # into specs instead of appending a nested list.
    for loop in LOOPS:
        specs.extend(_tag_specs_for_loop(loop))

    # Disturbances are plant-wide (feed composition, ambient temperature), not owned by a loop,
    # so they arrive as their own pre-built list.
    specs.extend(_tag_specs_for_disturbances())

    # Controlled variables are one tag per CV, not a bundle, hence append (one spec, not a list).
    # Order is preserved: CV tags are appended after loop and disturbance tags.
    for cv in CVS:
        specs.append(_tag_spec_for_cv(cv))

    return TagCatalog(specs)


def _tag_specs_for_loop(loop: _LoopSpec) -> list[TagSpec]:
    """Return the five tags describing one control loop, PV first.

    A control loop is one controller (a PLC block or a DCS faceplate) that keeps
    one process variable (PV) at a target setpoint by driving one output. Each
    role in that picture is exposed to the historian as its own tag, so one loop
    becomes five tags. The list order matters: downstream code writes the PV
    sample first, and a recorder that drops the tail of a batch still keeps the
    PV.

    Returns:
        The PV tag, the two setpoint tags, the mode tag and the output tag, in
        that order.
    """
    return [
        # The process variable: the measured value the loop is trying to hold.
        _loop_pv_spec(loop),
        # Two setpoints coexist rather than one, because a loop can be under
        # local or remote control at any moment and operators compare both:
        # "_sp" is the setpoint the loop is actually using right now,
        # "_rsp" is the value pushed in from a supervisory system (the remote
        # setpoint). When the loop runs locally the two diverge.
        _loop_sp_spec(loop, suffix="_sp", description_suffix="active setpoint"),
        _loop_sp_spec(loop, suffix="_rsp", description_suffix="remote setpoint"),
        # The mode tag says which source is in charge (auto, manual, cascade...).
        # It is what makes the other four tags readable: a sp that looks wrong
        # often just means the loop was in manual at the time.
        _loop_mode_spec(loop),
        # The controller output: what the loop commands its final element to do
        # (valve position, motor speed), i.e. the PV's manipulated variable.
        _loop_out_spec(loop),
    ]


def _loop_pv_spec(loop: _LoopSpec) -> TagSpec:
    """Return the measured process variable tag of a loop.

    In process control, a "loop" is a single controller plus the sensor and
    actuator it drives. The loop's process variable (PV) is the value the
    controller measures and tries to hold at its setpoint (SP) by moving its
    output (OP). This function builds the tag descriptor for that measured
    value so it can be exposed to the tag model.

    Returns a TagSpec: read-only, floating point, tagged with role "PV".
    """
    # Read-only float measured value; engineering range is copied so the tag can be
    # scaled and displayed without consulting the loop again.
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
    """Return a setpoint tag of a loop; `suffix` distinguishes active from remote.

    A "tag" is a named process variable that a control system can read or write, and a
    setpoint (role "SP") is the target value the controller tries to reach. One physical
    loop exposes several setpoint tags, so the caller passes a `suffix` to give each tag a
    unique id and a `description_suffix` to make its human-readable text unique as well.

    `eng_min` and `eng_max` are the engineering-range limits in `loop.unit` (for example
    0.0 to 100.0 degrees Celsius): the setpoint written through this tag must stay inside
    them. `type="float"` means the value travels as a floating-point number.
    """
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
    """Return the operating mode tag of a loop, 0=MAN, 1=AUTO, 2=CAS.

    A control loop (PID controller) runs in exactly one operating mode at a time:
    MAN (0) = manual, the operator sets the output directly;
    AUTO (1) = automatic, the controller computes the output from the setpoint;
    CAS  (2) = cascade, the setpoint comes from another (master) controller.
    The tag is writable so an operator can switch modes from the HMI.
    """
    return TagSpec(
        id=f"{loop.tag}_mode",
        # Dimensionless tag (enum), so no engineering unit.
        unit="",
        # Role tells the HMI to render this as a mode selector, not a numeric field.
        role="MODE",
        type="enum",
        description=f"{loop.description} loop mode (0=MAN, 1=AUTO, 2=CAS)",
        # Engineering range spans the three mode codes 0..2 (see docstring above).
        eng_min=0.0,
        eng_max=2.0,
        writable=True,
    )


def _loop_out_spec(loop: _LoopSpec) -> TagSpec:
    """Return the controller output tag of a loop, in percent.

    The output tag is the value a PID controller writes to command its final control
    element (a valve, a damper, a variable-speed drive). It is expressed as a
    percentage of the actuator's full travel, so the engineering range is fixed at
    0-100 % and never depends on the process variable's own range.
    """
    return TagSpec(
        id=f"{loop.tag}_out",
        unit="%",
        role="OUT",
        type="float",
        description=f"{loop.description} controller output",
        # A controller output is always a percentage of actuator travel: 0.0 % is
        # fully closed, 100.0 % is fully open. These bounds are the same for every
        # loop and are unrelated to the process variable's engineering range.
        eng_min=0.0,
        eng_max=100.0,
        # The controller owns this value, but an operator may override it, so the tag
        # accepts writes from the control system and from the operator station.
        writable=True,
    )


def _tag_specs_for_disturbances() -> list[TagSpec]:
    """Return the hardness and moisture tags that drive the simulation.

    Each TagSpec describes one simulated plant tag: how to generate its raw
    sensor values, its unit, and its expected range. Hardness and moisture both
    shift the ore quality and therefore act as disturbances on the process, so
    they are grouped here and refreshed once per simulation step.

    Returns:
        A list of TagSpec, one per disturbance tag, in a fixed order so that
        callers can index by position.
    """
    return [
        # Mean of the hardness tag: the slow-moving trend, in kWh/t, around which
        # the faster estimate fluctuates.
        _hard_mean_spec(),
        # Instantaneous hardness estimate: sample-and-hold reading in kWh/t,
        # updated every 30 min and used by the controllers.
        _hard_est_spec(),
        # Moisture content of the ore feed, in % by mass.
        _moist_spec(),
    ]


def _hard_mean_spec() -> TagSpec:
    """Return the writable tag carrying the true ore hardness mean.

    A TagSpec is the metadata for one process tag: its id, engineering unit,
    role, value type, human description and engineering range. This spec
    describes the "true" hardness of the ore fed to the grinding circuit, as
    opposed to hardness estimated by a soft sensor or model. Because the tag
    is writable it acts as a simulation driver: whoever writes to it sets
    the ground truth that the rest of the simulation must track.

    Returns:
        TagSpec for HARD_MEAN, a float in kWh/t, writable, spanning 5.0-30.0.
    """
    return TagSpec(
        id=HARD_MEAN,
        # Unit is specific grinding energy in kWh/t, the convention used for ore
        # hardness in this model.
        unit="kWh/t",
        role="other",
        type="float",
        description="Mean of the true ore hardness (writable simulation driver)",
        # Engineering range in kWh/t: 5.0 to 30.0, used to clamp or validate any
        # value written to this tag.
        eng_min=5.0,
        eng_max=30.0,
        writable=True,
    )


def _hard_est_spec() -> TagSpec:
    """Return the ore hardness estimate tag, sampled every 30 min.

    Ore hardness is a physical property of the rock being milled. It cannot be
    measured online, so it is estimated by a soft sensor and published as a
    single number that the control loop treats as a measured variable.

    Returns:
        TagSpec: metadata for the hardness estimate tag. The unit is specific
        energy in kilowatt-hours per tonne of ore (kWh/t); higher values mean
        harder ore that needs more grinding energy per tonne.
    """
    # role="DV" marks this tag as a Dependent (or Disturbance) Variable: an
    # input the controller must accept as given rather than manipulate.
    # type="float" says values are continuous, not categorical, so downstream
    # code may interpolate or difference them.
    return TagSpec(
        id=HARD_EST,
        unit="kWh/t",
        role="DV",
        type="float",
        description="Ore hardness estimate, sample-and-hold every 30 min",
    )


def _moist_spec() -> TagSpec:
    """Return the feed moisture tag, measured every step.

    The tag is part of the plant-wide tag table that MPC (model predictive
    control) tooling reads. Its fields tell that tooling how to treat the
    signal:

    * ``unit`` is the physical unit of the value, here mass percent water in
      the feed (%, 0-100).
    * ``role="DV"`` marks the tag as a *disturbance variable*: a measured
      input that the controller cannot move, but whose current value shifts
      the predicted trajectories. Contrast with "MV" (manipulated variable,
      an output the controller steers) and "CV" (controlled variable, an
      output that must be held near its setpoint).
    * ``type="float"`` is the expected Python type of the sampled value, so
      the reader can allocate the right buffer and detect a mis-wired tag.
    """
    return TagSpec(
        id=MOIST,
        unit="%",
        role="DV",
        type="float",
        description="Feed moisture (measured every step)",
    )


def _tag_spec_for_cv(cv: str) -> TagSpec:
    """Return the controlled variable tag for one `cv` key.

    A "tag" is the metadata record that tells the rest of the system (OPC UA,
    historian, HMI) everything it needs about one signal: its identifier, its
    engineering unit, its allowed range, and whether a client may write to it.

    A "CV" (controlled variable) is an output of the process that a controller
    drives towards a setpoint, as opposed to a manipulated variable (MV) or a
    disturbance. Every CV key in the four `_CV_*` lookup tables below must be
    present in all of them; that is the invariant this function relies on.

    Returns:
        A `TagSpec` for the given `cv`, built only from lookups (no computation).

    Raises:
        KeyError: if `cv` is missing from any of the four lookup tables.
    """
    return TagSpec(
        # Stable external identifier of the signal, e.g. "sim.mc.p80".
        id=CV_TAGS[cv],
        # Engineering unit the raw value is expressed in, e.g. "um".
        unit=_CV_UNITS[cv],
        # Role in the control loop: a measured process output, never an actuator.
        role="CV",
        # All CVs are analogue measurements, so they travel as 64-bit floats.
        type="float",
        # Human-readable label shown on the operator screen.
        description=_CV_DESCRIPTIONS[cv],
        # Engineering range of the signal, in `unit`. The minimum is 0.0 for
        # every CV by project convention (all CVs are non-negative physical
        # quantities), hence the literal instead of another table lookup.
        eng_min=0.0,
        # Upper end of the engineering range, in `unit`, per-signal.
        eng_max=_CV_ENG_MAX[cv],
        # CVs are read-only for clients: only the control loop may update them.
        writable=False,
    )


class _Loop:
    """Mutable state of one actuator loop: PID, actuator lag, inner disturbance and setpoints."""

    def __init__(
        self, spec: _LoopSpec, dt_s: float, inner_scale: float, rng: np.random.Generator
    ) -> None:
        """Assemble one closed-loop simulation from its specification.

        Builds the three blocks that make up the loop -- outer PID controller,
        actuator, and inner fast dynamics -- then seeds the signal state from
        the loop's nominal operating point.

        Args:
            spec: Which loop to simulate; selects the nominal point and gains.
            dt_s: Outer-loop sample time in seconds.
            inner_scale: Number of inner dynamics steps per outer control step.
            rng: Random source for measurement noise; shared so runs reproduce.
        """
        self.spec = spec
        # Outer loop: the PID the actuator and inner dynamics are commanded by.
        self.pid = self._build_pid(spec, dt_s)
        # Nominal operating point (the linearisation point) for this loop. Used
        # below to initialise every signal, so the loop starts already trimmed
        # instead of drifting toward the trim point over the first seconds.
        nominal = NOMINAL[spec.name]
        # Actuator turns the PID's command into a physical input, with its own
        # gain, rate limit and dead time. Runs at the outer sample time dt_s.
        self.actuator = self._build_actuator(spec, dt_s)
        # Inner loop: the fast dynamics between actuator and plant output.
        # inner_scale sets how many inner steps happen per outer step, so the
        # inner block is integrated at dt_s / inner_scale to stay stable.
        self.inner = self._build_inner(spec, inner_scale, dt_s, rng)
        # Place all state variables (errors, integrator, filtered measurements)
        # at their nominal values, which also zeroes the accumulated integrals.
        self._init_signals(nominal)

    def _build_pid(self, spec: _LoopSpec, dt_s: float) -> PID:
        """Build the PID with the spec gains and seed it in manual at the nominal operating
        point.

        Returns a controller that is already tracking the nominal process value while its
        output is held at NOMINAL_OUT, so the first automatic scan starts without a bump.
        """
        # Build the controller from the loop spec.
        #   kc       - proportional gain, dimensionless
        #   ti_s=60  - integral (reset) time in SECONDS; 60 s means the integral term repeats
        #              the proportional action once per minute (the classic reset-time form)
        #   dt_s     - scan period in SECONDS, supplied by the caller
        #   out_min/out_max - output clamps in PERCENT (0..100), the controller's 0-100% range
        #   direct=False    - reverse acting: the output falls when the measurement rises
        #                     above setpoint, the usual convention for a heating loop
        pid = PID(PidTuning(kc=spec.kc, ti_s=60.0), dt_s=dt_s, limits=OutputLimits(0.0, 100.0))
        # Nominal steady-state operating point for this loop: measurement and setpoint in
        # engineering units (whatever quantity the loop controls).
        nominal = NOMINAL[spec.name]
        # First scan in MANUAL mode. Passing the process value as both PV and SP keeps the
        # error at zero, and man_out pins the output at the running value (PERCENT), so the
        # integral term cannot wind up before the loop is taken to automatic.
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
        sweeps.

        The inner disturbance is a zero-mean Ornstein-Uhlenbeck process: a mean-reverting
        Gaussian noise, the continuous-time analogue of an AR(1). The spec fixes its intended
        volatility; inner_scale is a dimensionless multiplier applied on top so a sweep can
        temporarily inflate or damp the disturbance without rewriting the spec.

        Returns an OrnsteinUhlenbeck already parameterised for the current simulation step.
        """
        # sigma is the stationary standard deviation of the process (same unit as the
        # disturbed quantity); scaling it scales the whole noise amplitude linearly.
        shape = OuShape(mean=0.0, sigma=spec.inner_sigma * inner_scale, tau_s=120.0)
        # dt_s is the integration step in seconds; the process is sampled on this grid.
        return OrnsteinUhlenbeck(shape, dt_s=dt_s, rng=rng)

    def _init_signals(self, nominal: float) -> None:
        """Start the loop in auto, with setpoint, manual output and PV all at the nominal.

        Signature: `_init_signals(self, nominal: float) -> None`.

        Algorithm / model
        -----------------
        This method is the *initialisation* (a.k.a. boot / cold-start) hook of a
        feedback controller (think PID, but the same shape applies to any loop
        that compares a setpoint with a process variable). The controller holds
        six signals:

            pv          process variable          - the measured value, in EU
            local_sp    local setpoint requested  - operator request, in EU
            rsp         remote setpoint requested - value received from a remote
                                                  source (SCADA / cascade), in EU
            out         controller output         - the value actually driving the
                                                  valve / actuator, in % (0..100)
            manual_out  manual output requested   - operator-typed output, in %
            mode        operating mode            - AUTO | MAN (or similar enum)

        EU = "engineering units": the physical unit of the process (degC, bar,
        m3/h, ...). It is *not* necessarily equal to percent.

        Why "nominal"?
        --------------
        `nominal` is the value the process is supposed to sit at when nothing
        else is known. Bootstrapping every signal from it makes the loop start
        *bumbless*, i.e. with zero error and zero output jump:

            error = sp - pv = nominal - nominal = 0      (nothing to correct)
            output starts at NOMINAL_OUT                 (already in range)

        Why keep a separate `rsp` and `local_sp`?
        -----------------------------------------
        Both setpoint *sources* exist at the same time, but only one is used at
        runtime by the mode selector. The controller carries both so it can
        switch source without losing the last value typed on the inactive one.
        On boot they are deliberately made equal so the first switch cannot
        produce a step.

        Assumptions
        -----------
        * `nominal`, `NOMINAL_OUT`, `AUTO` are defined elsewhere (constants /
          enum). No validation is done here: garbage in, garbage out, as this
          function is only ever called with values the caller already validated.
        * `NOMINAL_OUT` is assumed to be inside the actuator range (0..100 %).
        * This method returns nothing. It is a state mutation, i.e. a *side
          effect* on `self`; it must be called before the first scan / cycle of
          the control loop.
        """
        self.mode = AUTO
        # Local setpoint is the value the operator would type in the HMI, in EU.
        self.local_sp = nominal
        self.rsp = nominal
        # Manual output is pre-loaded, in %, so that if the loop is flipped to MAN
        # before the first auto cycle, the actuator gets a sane value, not 0.
        self.manual_out = NOMINAL_OUT
        # Actual controller output, in %. Initialised equal to the manual one for a
        # bumpless transfer AUTO <-> MAN.
        self.out = NOMINAL_OUT
        # Measured process variable, in EU. Starting it at `nominal` is what
        # makes the initial error (sp - pv) exactly zero.
        self.pv = nominal


class MillCircuitPlant:
    """HPGR, ball mill and cyclone plant: three actuator loops and a hidden ore hardness."""

    tags: TagCatalog
    time_s: float
    dt_s: float

    def __init__(self) -> None:
        """Create the simulator with a full tag catalog and a deterministic initial state.

        The catalog maps every tag the historian can read to its physical unit, and the
        loop tag index maps every loop signal to the loop it belongs to. The simulation
        clock is then reset so the instance is ready to be stepped.
        """
        self.tags = _build_tag_catalog()
        # Simulation clock, in seconds, counting from process start.
        self.time_s = 0.0
        # Control period of one simulation step, in seconds (1 Hz sampling).
        self.dt_s = 1.0
        # Index from signal tag to (loop name, signal kind), e.g. "FIC101.PV" ->
        # ("FIC101", "pv"). Built once here so loops can look up their own signals
        # without scanning LOOPS on every step.
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

        In plain words: the true gain is the steady-state sensitivity of a controlled
        variable to a manipulated variable at the *current* ore hardness. The gain model
        has two parts: a reference gain, which is the sensitivity quoted at a reference
        hardness, plus a hardness sensitivity that shifts that gain as hardness drifts.

        Args:
            driver: One of ``DRIVERS``.
            cv: One of ``CVS``.
            hardness: Ore hardness to evaluate at; defaults to the current true hardness.
                Hardness is a dimensionless index (typically ~1.0 for nominal ore); higher
                means harder, more resistant ore that needs more energy per tonne.

        Returns:
            The gain (0.0 for driver/CV pairs without a causal path).

        Raises:
            KeyError: If the driver or the CV is unknown.
        """
        # Fail loudly on unknown tags: a silent lookup would hide a typo in the caller.
        if driver not in DRIVERS:
            raise KeyError(f"unknown driver: {driver!r}")
        if cv not in CVS:
            raise KeyError(f"unknown cv: {cv!r}")
        # A driver affects only some CVs. _PATHS is keyed by (driver, cv) pairs and holds a
        # 4-tuple per existing causal path: the reference gain, the hardness sensitivity,
        # and two dynamics parameters we do not need here. A missing key means there is no
        # path between this driver and this CV, so the gain is exactly zero.
        path = _PATHS.get((driver, cv))
        if path is None:
            return 0.0
        # Fall back to the process's current true hardness when the caller does not override it.
        evaluated_hardness = self.true_hardness if hardness is None else hardness
        # Take only the two fields the gain formula needs; the last two are unused here.
        reference_gain, hardness_sensitivity, _, _ = path
        # _gain applies the first-order hardness correction:
        # gain = reference_gain * (1 + hardness_sensitivity * (hardness - 1.0)),
        # i.e. the gain grows (or shrinks) linearly as hardness departs from its nominal 1.0.
        return _gain(reference_gain, hardness_sensitivity, evaluated_hardness)

    def reset(self, seed: int, scenario: Scenario | None = None) -> None:
        """Restore the nominal steady state at time 0 and seed all random generators.

        `seed` makes the run reproducible: every random generator in the simulation is derived
        from it, so the same seed plus the same scenario always replays the same trajectory.
        Passing `scenario=None` falls back to the default (nominal) scenario.
        """
        # The scenario carries all the tunable setpoints and physical constants; keep the one we
        # will actually simulate so later steps read consistent values.
        self._scenario = scenario if scenario is not None else Scenario()
        # Integration step of the simulation, in seconds. Used both to advance the clock and to
        # convert per-second rates into per-step increments.
        dt_s = self._scenario.dt_s
        self.dt_s = dt_s
        # Simulation clock, in seconds since the start of the episode.
        self.time_s = 0.0
        # Derive one independent random generator per stochastic source from the single seed:
        # separate streams so that drawing a measurement noise sample does not shift the draws
        # of, say, the disturbance sequence.
        rngs = self._spawn_rngs(seed)
        # Generators whose stream must be the same on every reset (sensor noise, weather, ...).
        self._assign_fixed_rngs(rngs)
        # Control loops: PID integrators and filters hold state, so they must start from the
        # steady-state values they had before the run, otherwise the first seconds drift.
        self._init_loops(dt_s, rngs)
        # Ore feed rate/concentration and moisture content, the slow state variables of the mill.
        self._init_ore_and_moisture(dt_s, rngs)
        # Unmodelled process disturbances (e.g. ore hardness drift) as filtered random walks.
        self._init_process_noise(dt_s, rngs)
        # Recorded trajectories, one buffer per logged signal; cleared so old data cannot leak
        # into the new episode.
        self._init_paths(dt_s)
        # Controlled variable (CV) states, i.e. the measured outputs the controllers regulate.
        self._init_cv_states()
        # Operator model: actions, timers and thresholds of the human/automation supervisor.
        self._init_operator()
        # Event schedule: alarms, setpoint changes and other discrete events, all reset to t=0.
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
        measurements.

        An Ornstein-Uhlenbeck (OU) process is the continuous-time analogue of an
        AR(1) process: a value that is pulled back towards its mean and kicked
        randomly at every step. It is used here to model the slow, noisy drift of
        two uncontrollable properties of the incoming ore.

        Two separate generator streams (rngs[4], rngs[5]) are drawn from so that
        the hardness and moisture noise stay independent and reproducible, no
        matter which other random draws happen in between.
        """
        # Nominal "true" hardness is stored on the instance so that other blocks
        # can compare the current estimate against the design value (dimensionless
        # work-index units, as defined in NOMINAL).
        self._hard_mean = NOMINAL["ore_hardness"]
        # Hardness OU: mean 0 because the process models a DEVIATION from
        # self._hard_mean, not the absolute value. sigma is the stationary
        # standard deviation (same units as ore_hardness); tau_s = 14400 correlates
        # the deviation over a 4-hour time constant, so consecutive samples are
        # strongly related. dt_s is the simulation step in seconds.
        self._hard_ou = OrnsteinUhlenbeck(
            OuShape(mean=0.0, sigma=self._scenario.param("hardness_sigma", 1.5), tau_s=14400.0),
            dt_s=dt_s,
            rng=rngs[4],
        )
        # Moisture OU: same deviation-from-mean construction, but with sigma = 0.4
        # percent-by-mass and tau_s = 7200 (2-hour time constant), i.e. moisture
        # wanders about four times faster than hardness.
        self._moist_ou = OrnsteinUhlenbeck(
            OuShape(mean=0.0, sigma=self._scenario.param("moisture_sigma", 0.4), tau_s=7200.0),
            dt_s=dt_s,
            rng=rngs[5],
        )
        # Estimator starts perfectly informed: the plant's first hardness estimate
        # is the nominal value, in the same units as ore_hardness.
        self._hard_est = NOMINAL["ore_hardness"]
        # Timestamp (in simulation seconds) at which the next hardness update is
        # due; 0.0 means "update on the very first step".
        self._next_est_s = 0.0
        # The measured moisture starts at its nominal value, in percent by mass,
        # matching the units of NOMINAL["feed_moisture"].
        self._moist_meas = NOMINAL["feed_moisture"]

    def _init_process_noise(self, dt_s: float, rngs: list[np.random.Generator]) -> None:
        """Create the per-CV Ornstein-Uhlenbeck process-noise generators.

        An Ornstein-Uhlenbeck (OU) process is the mean-reverting continuous-time
        random walk: dX = -(X - mean)/tau * dt + sigma * dW.  It returns towards
        ``mean`` with time constant ``tau_s`` while being kicked by Gaussian
        noise of amplitude ``sigma``; it is the standard model for slowly
        drifting biases in navigation state estimation.

        Args:
            dt_s: Simulator time step in SECONDS; the OU process is discretised
                at this step size.
            rngs: Per-component random generators; index 6 onward (the 7th
                generator and later) is reserved for the process-noise channel
                of each CV, so the state-update noise keeps its own stream.

        Returns:
            None; stores the generators on ``self._process_ou``, keyed by CV name.
        """
        # Scenario-level multiplicative factor on every sigma, so a whole run can
        # be made noisier or quieter without editing the per-CV table; dimensionless.
        process_scale = self._scenario.param("process_noise", 1.0)
        # One OU generator per controlled variable (CV). The dict key is the CV
        # name, the value is its noise source; the invariant is that every name in
        # CVS appears exactly once and nothing else does.
        self._process_ou: dict[str, OrnsteinUhlenbeck] = {
            # i is the CV's position in CVS (0-based); +6 maps it to that CV's
            # dedicated generator in rngs, giving each CV an independent stream.
            cv: OrnsteinUhlenbeck(
                # Per-CV base sigma scaled by the scenario factor; same unit as the CV.
                # tau_s is the mean-reversion time constant in SECONDS (5 min): the bias drifts
                # over that horizon, i.e. a slow disturbance, not fast sensor noise.
                OuShape(mean=0.0, sigma=_CV_PROCESS_SIGMA[cv] * process_scale, tau_s=300.0),
                dt_s=dt_s,
                rng=rngs[6 + i],
            )
            for i, cv in enumerate(CVS)
        }

    def _init_paths(self, dt_s: float) -> None:
        """Build the first-order-plus-dead-time models for every driver-CV path.

        A "path" is one dynamic relationship in this control study: how a single
        manipulated driver (an independent/MV, e.g. a valve opening) moves a single
        controlled variable (CV, e.g. a temperature). Each path is modelled as a
        FOPDT (first-order-plus-dead-time) process: a step change in the driver does
        not reach the CV instantly — there is transport/measurement delay (dead
        time) — and the CV then approaches the new steady state along an exponential
        curve set by its time constant. The steady-state ratio of the two step
        changes is the process gain K.

        This method turns the declarative ``_PATHS`` table into runtime list entries
        ready for the controller identification/loop. It runs once, during setup.

        Parameters
        ----------
        dt_s:
            Simulation sampling interval in SECONDS. Must match the interval the
            whole study is stepped at, because each FOPDT model discretises its
            delay into a whole number of samples (delay_s / dt_s) internally.

        Side effects
        ------------
        Sets ``self._paths`` to a list of tuples
        ``(driver, cv, gain_initial, variance, model)`` where:

        * ``driver`` / ``cv`` are the tag names of the input and output loops.
        * ``gain_initial`` is the STARTING ESTIMATE of the process gain K, in
          ENGINEERING UNITS OF CV PER ENGINEERING UNIT OF DRIVER
          (e.g. degC per % valve opening). It seeds the estimator and also gives
          the initial direction: its sign says whether the path acts normally or
          reverse-acting.
        * ``variance`` is the prior/assumed VARIANCE of the gain estimate, in
          (CV units per driver unit) squared. It quantifies how much we trust
          ``gain_initial``; used as the initial uncertainty (e.g. a Kalman/RLS
          covariance) that shrinks as the study observes real data.
        * ``model`` is the ``Fopdt`` instance (see the list comprehension below).

        ``_PATHS`` is a dict keyed by the ``(driver, cv)`` tag pair; each value is
        the tuple ``(gain_initial, variance, tau_minutes, delay_minutes)``, i.e.
        the time constant and dead time are stored there in MINUTES for human
        readability and converted to seconds here to match ``dt_s``.
        """
        # Build one entry per declarative path. The tuple layout
        # (driver, cv, gain_initial, variance, model) is the invariant every later
        # consumer of self._paths relies on, so keep the field order fixed.
        self._paths: list[tuple[str, str, float, float, Fopdt]] = [
            (
                driver,
                cv,
                gain_initial,
                variance,
                # The FOPDT model's own time constant and dead time in SECONDS (table stores
                # minutes, so multiply by 60 s/min), discretised at the study's sampling
                # interval dt_s.
                Fopdt(
                    gain=1.0,  # placeholder gain; the estimator starts from gain_initial
                    tau_s=tau_minutes * 60.0,
                    delay_s=delay_minutes * 60.0,
                    dt_s=dt_s,
                ),
            )
            # Unpack each table row so its four numbers become named locals with their
            # units made explicit by the loop variable names.
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
        """Validate scenario event tags and store events sorted by their start time.

        An "event" is a scheduled change of a tag's value at a given time in the
        simulated scenario, e.g. "at t_s=30 the tag 'valve_open' becomes True".
        The scenario is a list of such events, each carrying a tag id and a time.

        Raises:
            KeyError: if an event references a tag id that is not declared in
                ``self.tags`` -- a typo in the scenario would otherwise be
                silently ignored and change the simulation results.
        """
        events: Sequence[Event] = self._scenario.events
        for event in events:
            if event.tag_id not in self.tags:
                raise KeyError(f"Unknown tag in scenario event: {event.tag_id}")
        # Sort by start time so the simulation loop can consume events in order with
        # a single forward-moving cursor instead of searching each step.
        self._events: list[Event] = sorted(events, key=lambda event: event.t_s)
        # Index of the next event to apply in `self._events`; kept between steps so
        # each event is handled exactly once, and only when simulated time reaches the
        # event's t_s (seconds).
        self._event_idx = 0

    def step(self) -> None:
        """Advance the simulation by scenario.dt_s.

        One step is one discrete tick of length ``dt_s`` seconds. The internal order below is
        fixed and matters: drivers come before controllers, controllers before actuators, and
        actuators before the controlled variables, so that every block reads the values
        produced earlier in the same tick (a causal, forward-only pass, no fixed-point
        iteration). Events and operator actions are applied first so that everything
        downstream reacts to them immediately.
        """
        # Events scheduled for this instant (valve trips, setpoint changes, ...) are injected
        # before anything else so the rest of the tick already sees their effect.
        self._apply_due_events()
        # A human operator's queued manual action, if it is due now, is applied on top of the
        # automated control; it overrides the controller output until the operator releases it.
        self._maybe_apply_operator_action()
        hardness = self._update_process_drivers()
        # Controllers (PID and friends) read the error between setpoint and measured value
        # and compute a *requested* manipulated-variable position. Nothing moves yet.
        self._update_controllers()
        actual = self._update_actuators()
        self._update_controlled_variables(actual, hardness)
        # Advance the simulation clock by one tick, in seconds. It happens last so that all
        # of the above ran with the timestamp that is still current.
        self.time_s += self.dt_s

    def _apply_due_events(self) -> None:
        """Write every scenario event due at or before the current time.

        A scenario is a pre-recorded timeline of value writes ("events"), each stamped with
        the simulation time at which it must be applied. Events must be applied in time
        order, so the events list is sorted by timestamp and we remember how far we got.

        The cursor ``self._event_idx`` is the position in ``self._events`` of the next event
        that has not been applied yet. It only ever moves forward, so the total work across
        all calls is linear in the number of events.

        Returns:
            None. The writes happen as a side effect.
        """
        while self._event_idx < len(self._events):
            ev = self._events[self._event_idx]
            if ev.t_s > self.time_s:
                break
            # `enforce=False` skips the permission check: scenario writes are trusted.
            self._write(ev.tag_id, ev.value, enforce=False)
            # Advance the cursor so this event is never applied twice.
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
        """Compute each loop output; the active setpoint is RSP in CAS, local SP otherwise.

        One call is made per loop per control cycle. The output written to `loop.out` is the
        controller output in percent of output span, and `loop.local_sp`, `loop.pv` and
        `loop.manual_out` use the loop's engineering unit (EU) of the PV.

        A loop in CAS (cascade) takes its setpoint from the master/cascade source `loop.rsp`,
        so the local operator setpoint `loop.local_sp` is overwritten with it and the two
        always agree while the loop stays in CAS. In any other mode (AUTO, MAN) the local
        setpoint is the active one, so it is left untouched.
        """
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
        """Advance the actuators one timestep and return the measured actuator values by name.

        The controlled variable (pv) of each loop is also refreshed here: the real world
        never sees the actuator command exactly, so noise is added to the measured value.

        Returns:
            Measured actuator value by actuator name, each in the actuator's own
            engineering unit (e.g. valve opening in %, speed in rpm).
        """
        actual: dict[str, float] = {}
        for name, loop in self._loops.items():
            deviation = loop.actuator.update(loop.out - NOMINAL_OUT)

            # Measured actuator output: nominal plus controller deviation plus inner-loop
            # correction, all in the actuator's engineering unit.
            actual[name] = NOMINAL[name] + deviation + loop.inner.update()

            # Controller's process variable: simulated output plus measurement noise
            # (standard deviation loop.spec.meas_sd, same unit as the actuator).
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
        """Return the current (value, quality) reading of one process tag.

        A "tag" is a named signal in the plant (DCS/SCADA vocabulary), e.g. a
        temperature, a valve opening or the status of a control loop.  The
        second element of the pair is the OPC quality code: GOOD means the
        value is trustworthy, anything else means it should not be used.

        Raises:
            KeyError: if tag_id is not a tag this model exposes.
        """
        if tag_id not in self.tags:
            raise KeyError(f"Unknown tag: {tag_id}")

        # --- Tags that are constants during a run (read as-is) ---
        if tag_id == HARD_MEAN:
            return self._hard_mean, GOOD
        if tag_id == HARD_EST:
            return self._hard_est, GOOD
        if tag_id == MOIST:
            return self._moist_meas, GOOD

        # --- Controlled variables (CVs) of the control loops ---
        # CV_TAGS maps a CV name to the tag that publishes its measured value.
        for cv, cv_tag in CV_TAGS.items():
            if tag_id == cv_tag:
                return self._cv_meas[cv], GOOD

        name, kind = self._loop_tags[tag_id]
        loop = self._loops[name]
        return self._read_loop_field(loop, kind), GOOD

    def _read_loop_field(self, loop: _Loop, kind: str) -> float:
        """Return the loop attribute named by kind, in the order read() documents.

        The controller exposes a small set of named fields: the process variable
        ("pv"), the setpoint ("sp"), the remote setpoint ("rsp"), the operating
        mode ("mode") and the controller output ("out"). Any unrecognised kind
        falls through to the output, which is the value most callers want.

        Args:
            loop: the control loop whose field is read.
            kind: the field name, one of "pv", "sp", "rsp", "mode", "out".

        Returns:
            The field value as a float. Mode is an enum and is converted;
            all other fields are already numeric.
        """
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
        """Write a tag; with ``enforce`` False (scenario events) permission checks are skipped.

        This is the single entry point that turns a tag name plus a numeric value into a state
        change on the simulation model (a plant of control loops). ``enforce`` selects the caller's
        privilege level: operator writes go through the normal permission checks, while scenario
        replay events set the same state directly.

        Raises:
            KeyError: ``tag_id`` is not a tag known to this model.
            PermissionError: the tag is read-only, or the loop's current mode forbids the write.
            ValueError: a mode tag is written with a value that is not one of MAN, AUTO or CAS.
        """
        self._check_tag_is_writable(tag_id, enforce=enforce)

        # The plant-wide mean is a single scalar rather than a loop member, so it is handled before
        # the loop dispatch below. It has no writability or mode rules beyond the check above.
        if tag_id == HARD_MEAN:
            self._hard_mean = float(value)
            return
        # Tags that are read-only and not part of any loop can still arrive here from scenario
        # events (which skip the writable check). Those events are simply no-ops on the model.
        if tag_id not in self._loop_tags:
            return  # read-only measured tag reached by an event: nothing to write

        self._write_loop_tag(tag_id, value, enforce=enforce)

    def _write_loop_tag(self, tag_id: str, value: float, *, enforce: bool) -> None:
        """Dispatch a write on one loop member.

        ``_loop_tags`` maps each loop tag to the pair (loop name, kind), where kind is one of
        "out" (controller output, %), "sp" (active setpoint, same unit as the loop PV),
        "rsp" (remote setpoint, same unit as the loop PV), or "mode" (MAN / AUTO / CAS).
        """
        name, kind = self._loop_tags[tag_id]
        loop = self._loops[name]
        if kind == "out":
            self._write_output(loop, tag_id, value, enforce=enforce)
            return
        if kind == "sp":
            self._write_setpoint(loop, tag_id, value, enforce=enforce)
            return
        if kind == "rsp":
            # The remote setpoint is written by the supervisory layer, which is trusted, so it is
            # not subject to the mode rules of out/sp.
            loop.rsp = float(value)
            return
        if kind == "mode":
            self._write_mode(loop, value)

    def _check_tag_is_writable(self, tag_id: str, *, enforce: bool) -> None:
        """Reject an unknown tag, and a read-only tag when the caller is not privileged.

        Raises:
            KeyError: ``tag_id`` is not a tag known to this model.
            PermissionError: ``enforce`` is set and the tag is read-only.
        """
        if tag_id not in self.tags:
            raise KeyError(f"Unknown tag: {tag_id}")
        if enforce and not self.tags[tag_id].writable:
            raise PermissionError(f"Tag {tag_id} is read-only")

    def _write_output(self, loop: _Loop, tag_id: str, value: float, *, enforce: bool) -> None:
        """Write a controller output, saturating it to the 0-100 % actuator travel range.

        Raises:
            PermissionError: ``enforce`` is set and the loop is not in MAN mode.
        """
        # Manual output may only be moved while the loop is under operator control (MAN);
        # in AUTO or CAS the controller owns the output and a write would fight it.
        if enforce and loop.mode != MAN:
            raise PermissionError(f"Cannot write {tag_id} unless the loop is in MAN mode")
        # Outputs are actuator percentages, saturated to the 0-100 % physical travel range.
        clamped = float(np.clip(value, 0.0, 100.0))
        loop.manual_out = clamped
        loop.out = clamped

    def _write_setpoint(self, loop: _Loop, tag_id: str, value: float, *, enforce: bool) -> None:
        """Write the active setpoint of a loop.

        Raises:
            PermissionError: ``enforce`` is set and the loop is in CAS mode.
        """
        # In CAS (cascade) the setpoint is driven by the upstream loop, so an operator write
        # would be immediately overwritten; only MAN and AUTO accept local setpoint changes.
        if enforce and loop.mode == CAS:
            raise PermissionError(f"Cannot write {tag_id} while the loop is in CAS mode")
        loop.local_sp = float(value)

    def _write_mode(self, loop: _Loop, value: float) -> None:
        """Switch a loop's mode, seeding the manual output on entry to MAN for bumpless transfer.

        Raises:
            ValueError: ``value`` is not one of MAN, AUTO or CAS.
        """
        if value not in (MAN, AUTO, CAS):
            raise ValueError(f"Invalid mode value: {value}")
        new_mode = int(value)
        # Bumpless transfer: entering MAN, the manual output is seeded from the current output
        # so the actuator does not jump at the moment of the mode switch.
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
        """Operator writes local setpoints of AUTO loops based on the observed ore hardness.

        Simulates the human operator of the grinding circuit. Each control loop that is in
        AUTO mode receives a new setpoint derived from the operator's *belief* about the ore
        hardness, not from the true value: the operator only measures hardness indirectly
        (through power draw, throughput, etc.), so `h_obs` is the true hardness plus a bias.
        Loops left in MANUAL keep whatever setpoint the operator set by hand earlier.
        """
        # h_obs: operator's perceived ore hardness (same unit as true_hardness, a grindability
        # index centred on 14.0). `_operator_draw(x)` returns a random deviation of typical
        # magnitude x, modelling that the operator never reads the process exactly.
        h_obs = self.true_hardness + self._operator_draw(0.3)

        # HPGR (high-pressure grinding rolls) pressing force.
        # Setpoint in MPa. Harder ore drags more material into the rolls, so the operator
        # raises the force proportionally to the perceived hardness deviation from nominal
        # (14.0). Clipped to the safe operating window of the machine.
        press = self._loops["hpgr_press"]
        if press.mode == AUTO:
            sp = 3.5 + 0.12 * (h_obs - 14.0) + self._operator_draw(0.1)
            press.local_sp = float(np.clip(sp, 2.5, 4.5))

        # Mill feed rate.
        # Setpoint in t/h. Opposite correction to the press: harder ore is harder to grind,
        # so the operator reduces the feed to protect the mill from overload.
        feed = self._loops["mill_feed"]
        if feed.mode == AUTO:
            sp = 150.0 - 4.0 * (h_obs - 14.0) + self._operator_draw(3.0)
            feed.local_sp = float(np.clip(sp, 100.0, 200.0))

        # Cyclone feed water.
        # Setpoint in m3/h. This one reacts to the *measured* product fineness p80
        # (80% passing size, micrometres), not to hardness: a coarse product (p80 above the
        # 150 um target) needs more water to push fines through the cyclones.
        water = self._loops["cyc_water"]
        if water.mode == AUTO:
            sp = 100.0 + 0.5 * (self._cv_meas["p80"] - 150.0) + self._operator_draw(2.0)
            water.local_sp = float(np.clip(sp, 70.0, 130.0))

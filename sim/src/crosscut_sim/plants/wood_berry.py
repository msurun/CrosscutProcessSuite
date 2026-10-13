"""Wood-Berry binary distillation column simulation with dual PID composition control."""

from __future__ import annotations

import numpy as np

from crosscut_sim.core import AUTO, CAS, GOOD, MAN, Event, Fopdt, Scenario, TagCatalog, TagSpec
from crosscut_sim.disturbances import OrnsteinUhlenbeck, OuShape
from crosscut_sim.pid import PID, OutputLimits, PidTuning

NOMINAL: dict[str, float] = {
    "top_comp": 96.25,
    "bottom_comp": 0.5,
    "reflux": 1.95,
    "steam": 1.71,
    "feed_rate": 2.45,
}

TOP = "sim.wb.top_comp"
TOP_SP = "sim.wb.top_comp_sp"
TOP_RSP = "sim.wb.top_comp_rsp"
TOP_MODE = "sim.wb.top_comp_mode"
REFLUX = "sim.wb.reflux"

BOT = "sim.wb.bottom_comp"
BOT_SP = "sim.wb.bottom_comp_sp"
BOT_RSP = "sim.wb.bottom_comp_rsp"
BOT_MODE = "sim.wb.bottom_comp_mode"
STEAM = "sim.wb.steam"

FEED = "sim.wb.feed_rate"

# BLT tuning parameters from the distillation literature.
TOP_PID_KC = 0.375
TOP_PID_TI_S = 8.29 * 60.0

BOT_PID_KC = 0.075
BOT_PID_TI_S = 23.6 * 60.0

TOP_NOISE_STD = 0.03
BOT_NOISE_STD = 0.01


def _build_tag_catalog() -> TagCatalog:
    """Assemble the catalog of every tag the model exposes.

    The order of the specs is the order in which tags are discovered and
    reported; keep units and loops grouped by tag role, not by plant section,
    so callers reading the catalog see the control hierarchy top to bottom.

    Returns:
        TagCatalog: the specs below, wrapped in a catalog.
    """
    # Tag catalog: one spec per tag role the model owns. A spec is a
    # declarative description (name, unit, bounds) that the catalog turns into
    # tags and checks for duplicates; it carries no live value. The order
    # below is the discovery order: top-loop tags first (composition,
    # setpoint, remote setpoint, mode, output), then bottoms mirrors of the
    # same five roles, then steam and feed.
    specs = [
        _top_composition_spec(),
        _top_setpoint_spec(),
        _top_remote_setpoint_spec(),
        _top_mode_spec(),
        _reflux_spec(),
        _bottom_composition_spec(),
        _bottom_setpoint_spec(),
        _bottom_remote_setpoint_spec(),
        _bottom_mode_spec(),
        _steam_spec(),
        _feed_spec(),
    ]
    # Hand the list over as a whole: TagCatalog indexes it and rejects any
    # duplicate tag name, so the list must stay a plain sequence, not a set.
    return TagCatalog(specs)


def _top_composition_spec() -> TagSpec:
    """Describe the tag holding the methanol mass fraction of the distillate stream.

    wt% (mass percent) is used instead of mol% because the plant's operating
    envelope and the DCS faceplate for this column are both expressed in mass
    basis; converting between the two would need the full composition, which
    the tag does not carry.

    Returns:
        TagSpec: read-only spec (role "PV", i.e. the measured process value)
        bounded to 0..100 wt%; nothing may write to it because the value comes
        from the analyser, not from the operator.
    """
    return TagSpec(
        id=TOP,
        unit="wt%",
        # "PV" = Process Value: a measurement reported upward, never commanded.
        role="PV",
        type="float",
        description="Distillate top methanol composition",
        eng_min=0.0,
        eng_max=100.0,
        # False keeps the tag as a pure sensor: no operator or controller write.
        writable=False,
    )


def _top_setpoint_spec() -> TagSpec:
    """
    Describe the operator-facing setpoint tag for the top composition controller.

    A TagSpec is a static descriptor: it is data about a tag (its identity, unit,
    limits, whether a human may write to it), not the tag's live value. The values
    here are the same every call, so the function takes no arguments.

    Returns:
        TagSpec for the active setpoint of the top-composition control loop.
    """
    return TagSpec(
        id=TOP_SP,
        # Composition is expressed as a weight percent, hence unit "wt%".
        unit="wt%",
        # "SP" marks this tag as a setpoint: the target the control loop drives to.
        role="SP",
        type="float",
        description="Top composition active setpoint",
        # Engineering range in the tag's own unit (wt%); 0..100 covers a full
        # composition scale, and the HMI clamps operator input to these bounds.
        eng_min=0.0,
        eng_max=100.0,
        # True: an operator is allowed to change this setpoint at runtime.
        writable=True,
    )


def _top_remote_setpoint_spec() -> TagSpec:
    return TagSpec(
        id=TOP_RSP,
        unit="wt%",
        role="SP",
        type="float",
        description="Top composition remote setpoint",
        eng_min=0.0,
        eng_max=100.0,
        writable=True,
    )


def _top_mode_spec() -> TagSpec:
    """Describe the OPC tag that exposes the controller's top composition loop mode.

    Returns a TagSpec for TOP_MODE. The tag is an enumeration carrying no physical unit:
    the value is a discrete operating mode, not a measurement, so `unit` is empty and the
    engineering range only spans the integer codes 0, 1 and 2.
    """

    # Build the spec for the mode selector.
    # - role="MODE" marks this tag as an operating-mode selector rather than a process value.
    # - type="enum" tells clients to render/validate an integer code instead of a float.
    # - eng_min/eng_max = 0.0/2.0 are the bounds of the three valid codes below, so a client
    #   can range-check a write before sending it.
    # - writable=True: an operator may change the mode from the HMI or a supervisory system.
    # The three codes are:
    #   0 = MAN  -> manual: the output is set by hand, the loop does not auto-correct.
    #   1 = AUTO -> automatic: the PID (proportional-integral-derivative) regulator drives
    #               the output to hold the setpoint.
    #   2 = CAS  -> cascade: the setpoint comes from another (outer) controller instead of
    #               being entered by the operator.
    return TagSpec(
        id=TOP_MODE,
        unit="",
        role="MODE",
        type="enum",
        description="Top composition loop mode (0=MAN, 1=AUTO, 2=CAS)",
        eng_min=0.0,
        eng_max=2.0,
        writable=True,
    )


def _reflux_spec() -> TagSpec:
    """Describe the reflux flow-rate tag (its metadata, not its live value).

    A "tag" here is a named process signal with fixed metadata: unit, allowed
    engineering range, whether an operator may write to it, and so on.

    Returns a TagSpec for the reflux stream. Reflux is the condensed overhead
    liquid that is pumped back down into the top of the distillation column;
    the rest of the overhead is drawn off as product. Raising reflux improves
    separation but costs more energy, so operators tune it against product
    purity.

    All args below are tag metadata; no value is read from the plant here.
    """
    return TagSpec(
        id=REFLUX,  # stable identifier used to look this tag up elsewhere
        unit="lb/min",  # mass flow rate, not volume: pounds (mass) per minute
        role="OUT",  # direction from the model's point of view: a value it writes
        type="float",  # storage/transport type; floats can represent fractions
        description="Reflux flow rate",  # human-readable label shown on displays
        eng_min=0.0,  # lowest valid engineering value, in unit above (lb/min)
        eng_max=5.0,  # highest valid engineering value, in unit above (lb/min)
        writable=True,  # an operator or controller may set this tag, read-only if False
    )


def _bottom_composition_spec() -> TagSpec:
    """Describe the bottom-composition tag read from the column model.

    Returns:
        A read-only TagSpec holding the methanol mass fraction in the bottoms
        stream, ranging from 0 (pure water) to 100 (pure methanol).
    """
    return TagSpec(
        id=BOT,
        unit="wt%",
        # "PV" = process variable: a value the model computes and reports upward.
        # The simulation, not the operator, writes this tag.
        role="PV",
        type="float",
        description="Bottom methanol composition",
        eng_min=0.0,
        eng_max=100.0,
        writable=False,
    )


def _bottom_setpoint_spec() -> TagSpec:
    """Describe the writable setpoint tag that holds the bottom product composition target.

    A "tag" is one named process variable in the plant's tag database (the shared
    register the control system, historian and operator screens all read from).
    The setpoint is the target the bottom composition controller drives the plant
    towards, as opposed to the measurement of what the composition actually is.

    Returns:
        TagSpec: metadata for the bottom composition setpoint: identity, unit,
            range and write access. The value is not included; this only declares
            the shape of the tag so the rest of the code can validate and expose it.
    """
    return TagSpec(
        id=BOT_SP,
        unit="wt%",
        role="SP",
        type="float",
        description="Bottom composition active setpoint",
        # Lower bound of the valid range, in wt%. Composition cannot be negative.
        eng_min=0.0,
        # eng_max=100.0: compositions are a fraction of the whole stream, so 100 wt% is the physical
        # maximum.
        eng_max=100.0,
        # writable=True: an operator may change this setpoint at runtime.
        writable=True,
    )


def _bottom_remote_setpoint_spec() -> TagSpec:
    """Describe the operator-facing tag for the bottom composition remote setpoint.

    In a distillation column the "bottom" product is the heavy stream leaving the reboiler, and
    its composition is measured in weight percent (wt%). A "remote setpoint" (role "SP") is a
    target value that an operator writes to a controller; the controller then drives the process
    until the measured composition matches this target.

    Returns:
        TagSpec: immutable metadata describing the tag, including its engineering range and the
        fact that it accepts writes from an operator.
    """
    return TagSpec(
        id=BOT_RSP,  # unique tag identifier for this setpoint in the plant tag database
        unit="wt%",  # engineering unit of the value: weight percent of the key component
        role="SP",  # tag role: "SP" marks this tag as a setpoint rather than a measurement
        type="float",  # the setpoint is stored as a floating-point number
        description="Bottom composition remote setpoint",
        eng_min=0.0,  # lower bound of the valid engineering range, in wt%
        eng_max=100.0,  # upper bound of the valid engineering range, in wt%
        writable=True,  # operators may write to this tag, unlike read-only measurements
    )


def _bottom_mode_spec() -> TagSpec:
    """Build the tag specification for the bottom composition loop mode.

    A "tag" is one named process value (a sensor reading or a setpoint) that the
    control system exposes to operators and to other programs. This spec tells
    the data layer how to describe and validate that tag; it holds metadata, not
    a live value.

    Returns:
        TagSpec: spec for the bottom composition loop mode.
    """
    return TagSpec(
        id=BOT_MODE,  # Stable internal identifier for the tag. BOT_MODE is the
        # registry key; ids never change once published, because
        # historical data is stored against them.
        unit="",  # Engineering unit: dimensionless here. The value is a
        # discrete mode selector (0/1/2), not a measurement, so
        # there is nothing to measure it in.
        role="MODE",  # Semantic role, telling consumers the tag's purpose.
        # "MODE" marks it as an operating-mode selector rather
        # than a measured value ("PV") or a target ("SP").
        type="enum",  # Data type of the tag. "enum" means a closed set of
        # integer codes with names, so the UI shows the names and
        # the data layer rejects anything outside the set.
        # Human-readable description shown in operator displays and docs. The codes:
        #   0 = MAN  -> manual, operator sets the loop output directly
        #   1 = AUTO -> automatic, the controller computes the output
        #   2 = CAS  -> cascade, another controller supplies the setpoint
        description="Bottom composition loop mode (0=MAN, 1=AUTO, 2=CAS)",
        # Valid range for the raw value, in enum codes (unitless): 0..2.
        eng_min=0.0,
        eng_max=2.0,
        # True: operators may write this tag. Mode selection is a deliberate
        # human action, in contrast to read-only sensor tags.
        writable=True,
    )


def _steam_spec() -> TagSpec:
    """Describe the reboiler steam flow tag for process I/O.

    Returns:
        TagSpec: tag definition with the flow unit, engineering range and write access.
    """
    return TagSpec(
        id=STEAM,
        unit="lb/min",  # mass flow rate, pounds (mass) per minute
        role="OUT",
        type="float",
        description="Reboiler steam flow rate",
        eng_min=0.0,  # engineering range, same unit as above ("lb/min")
        eng_max=5.0,
        writable=True,
    )


def _feed_spec() -> TagSpec:
    """Describe the tag that carries the column feed flow rate disturbance.

    Returns:
        TagSpec: metadata for tag ``FEED``, the manipulated variable used by the
        controller to inject a feed-flow disturbance.
    """
    return TagSpec(
        id=FEED,
        # Engineering unit of the values written to this tag: mass flow rate in
        # pounds (mass) per minute.
        unit="lb/min",
        # "DV" = disturbance variable: an input the controller may drive, but that
        # the plant does not measure as a controlled output.
        role="DV",
        type="float",
        description="Column feed flow rate disturbance",
        eng_min=0.0,
        eng_max=10.0,
        writable=True,
    )


class WoodBerryPlant:
    """Wood-Berry binary distillation column plant model."""

    tags: TagCatalog
    time_s: float

    def __init__(self) -> None:
        self.tags = _build_tag_catalog()
        self.time_s = 0.0
        self.reset(seed=0)

    def reset(self, seed: int, scenario: Scenario | None = None) -> None:
        """Restore the nominal steady state at time 0 and seed all random generators."""
        self._scenario = scenario if scenario is not None else Scenario()
        dt_s = self._scenario.dt_s
        self.time_s = 0.0
        self._init_disturbance(seed, dt_s)
        self._init_process_models(dt_s)
        self._init_nominal_signals()
        self._init_controllers(dt_s)

        # Events sorted by trigger time
        self._events: list[Event] = sorted(self._scenario.events, key=self._event_trigger_time_s)
        self._event_idx = 0

    def _init_disturbance(self, seed: int, dt_s: float) -> None:
        """Seed the sensor-noise and feed-disturbance generators from one master ``seed``."""
        seeds = np.random.SeedSequence(seed).spawn(2)
        self._sensor_rng = np.random.default_rng(seeds[0])
        dist_rng = np.random.default_rng(seeds[1])

        self._feed_ou = OrnsteinUhlenbeck(
            OuShape(
                mean=NOMINAL["feed_rate"],
                sigma=self._scenario.disturbance_sigma,
                tau_s=self._scenario.disturbance_tau_s,
            ),
            dt_s=dt_s,
            rng=dist_rng,
        )

    def _init_process_models(self, dt_s: float) -> None:
        """Build the six Wood-Berry transfer functions (gain, tau, dead time given in minutes)."""
        self._g11 = Fopdt(gain=12.8, tau_s=16.7 * 60.0, delay_s=1.0 * 60.0, dt_s=dt_s)
        self._g12 = Fopdt(gain=-18.9, tau_s=21.0 * 60.0, delay_s=3.0 * 60.0, dt_s=dt_s)
        self._gd1 = Fopdt(gain=3.8, tau_s=14.9 * 60.0, delay_s=8.1 * 60.0, dt_s=dt_s)

        self._g21 = Fopdt(gain=6.6, tau_s=10.9 * 60.0, delay_s=7.0 * 60.0, dt_s=dt_s)
        self._g22 = Fopdt(gain=-19.4, tau_s=14.4 * 60.0, delay_s=3.0 * 60.0, dt_s=dt_s)
        self._gd2 = Fopdt(gain=4.9, tau_s=13.2 * 60.0, delay_s=3.4 * 60.0, dt_s=dt_s)

    def _init_nominal_signals(self) -> None:
        """Put both loops in auto with setpoints, outputs and measurements at the nominal."""
        self._top_mode = AUTO
        self._top_sp = NOMINAL["top_comp"]
        self._top_rsp = NOMINAL["top_comp"]
        self._reflux_out = NOMINAL["reflux"]
        self._reflux_man_out = NOMINAL["reflux"]
        self._top_pv_meas = NOMINAL["top_comp"]

        self._bot_mode = AUTO
        self._bot_sp = NOMINAL["bottom_comp"]
        self._bot_rsp = NOMINAL["bottom_comp"]
        self._steam_out = NOMINAL["steam"]
        self._steam_man_out = NOMINAL["steam"]
        self._bot_pv_meas = NOMINAL["bottom_comp"]

        self._feed_base = NOMINAL["feed_rate"]
        self._effective_feed = NOMINAL["feed_rate"]

    def _init_controllers(self, dt_s: float) -> None:
        """Create both PIDs and bumplessly initialise them at the nominal operating point."""
        top_tuning = PidTuning(kc=TOP_PID_KC, ti_s=TOP_PID_TI_S)
        self._top_pid = self._started_pid(top_tuning, dt_s, False, ("top_comp", "reflux"))
        bottom_tuning = PidTuning(kc=BOT_PID_KC, ti_s=BOT_PID_TI_S)
        self._bot_pid = self._started_pid(bottom_tuning, dt_s, True, ("bottom_comp", "steam"))

    @staticmethod
    def _started_pid(
        tuning: PidTuning, dt_s: float, direct: bool, nominal_keys: tuple[str, str]
    ) -> PID:
        """Create a PID (output limits 0-5) and run one MAN step so it starts at the nominal.

        ``nominal_keys`` are the NOMINAL entries of the measurement and of the manual output.
        """
        pv_key, out_key = nominal_keys
        pid = PID(tuning, dt_s=dt_s, limits=OutputLimits(low=0.0, high=5.0), direct=direct)
        pid.reset()
        pid.update(NOMINAL[pv_key], NOMINAL[pv_key], "MAN", man_out=NOMINAL[out_key])
        return pid

    @staticmethod
    def _event_trigger_time_s(event: Event) -> float:
        """Return the simulation time at which `event` must be applied.

        Used as the sort key so `self._events` is ordered by trigger time.
        """
        return event.t_s

    def _apply_event_write(self, tag_id: str, value: float) -> None:
        """Apply an event write directly to internal state bypassing permissions.

        Used when replaying a recorded event stream (a log of tag writes): the
        values were already validated when the events were recorded, so the
        permission checks done for a live write must be skipped here.

        Args:
            tag_id: Name of the tag to write, e.g. TOP_SP.
            value: New value for the tag. Setpoints use the engineering unit of
                the tag (e.g. bar for pressures, degC for temperatures); setpoint
                modes use a small integer enum (0 = local, 1 = remote, ...).
        """
        # Top and bottom loops each expose a setpoint (SP), a remote setpoint (RSP),
        # and a mode that selects between them.
        if self._apply_top_event_write(tag_id, value):
            return
        if self._apply_bottom_event_write(tag_id, value):
            return
        self._apply_flow_event_write(tag_id, value)

    def _apply_top_event_write(self, tag_id: str, value: float) -> bool:
        """Write the top loop tags; return True when tag_id matched one of them."""
        if tag_id == TOP_SP:
            self._top_sp = float(value)
        elif tag_id == TOP_RSP:
            self._top_rsp = float(value)
        elif tag_id == TOP_MODE:
            self._top_mode = int(value)
        else:
            return False
        return True

    def _apply_bottom_event_write(self, tag_id: str, value: float) -> bool:
        """Write the bottom loop tags; return True when tag_id matched one of them."""
        if tag_id == BOT_SP:
            self._bot_sp = float(value)
        elif tag_id == BOT_RSP:
            self._bot_rsp = float(value)
        elif tag_id == BOT_MODE:
            self._bot_mode = int(value)
        else:
            return False
        return True

    def _apply_flow_event_write(self, tag_id: str, value: float) -> None:
        """Write the flow tags, each routed to its own dedicated helper."""
        if tag_id == REFLUX:
            self._apply_reflux_write(value)
        elif tag_id == STEAM:
            self._apply_steam_write(value)  # reheating steam flow, handled like reflux
        elif tag_id == FEED:
            self._apply_feed_write(value)  # feed flow into the column, dedicated helper

    def _apply_reflux_write(self, value: float) -> None:
        """Write the reflux value to both its manual-output and output holders."""
        clamped = float(np.clip(value, 0.0, 5.0))
        self._reflux_man_out = clamped
        self._reflux_out = clamped

    def _apply_steam_write(self, value: float) -> None:
        """Write the steam value to both its manual-output and output holders."""
        clamped = float(np.clip(value, 0.0, 5.0))
        self._steam_man_out = clamped
        self._steam_out = clamped

    def _apply_feed_write(self, value: float) -> None:
        """Write the feed value to both its base and effective-feed holders."""
        self._feed_base = float(value)
        self._effective_feed = float(value)

    def step(self) -> None:
        """Advance the simulation by scenario.dt_s.

        One control cycle of a simulated distillation column, in the classic
        sequence: scheduled events, disturbance, controllers, plant, sensors,
        clock. Each call moves the simulation forward by exactly one sample
        period, self._scenario.dt_s (UNIT: s).
        """
        self._apply_pending_events()
        self._update_disturbance_and_feed()
        self._run_top_controller()
        self._run_bottom_controller()
        self._run_process_models()
        self._update_sensor_measurements()
        self.time_s += self._scenario.dt_s

    def _apply_pending_events(self) -> None:
        """Consume every scheduled event whose time has already arrived.

        self._events is sorted by event.t_s; self._event_idx is the cursor to
        the first un-applied event. Stops at the first future event.
        """
        while self._event_idx < len(self._events):
            event = self._events[self._event_idx]
            if event.t_s > self.time_s:
                break
            self._apply_event_write(event.tag_id, event.value)
            self._event_idx += 1

    def _update_disturbance_and_feed(self) -> None:
        """Draw a new feed disturbance and update the effective feed rate.

        self._effective_feed = feed_base + (ou_value - nominal), so only the
        deviation from nominal is added to the base feed.
        """
        ou_value = self._feed_ou.update()
        self._effective_feed = self._feed_base + (ou_value - NOMINAL["feed_rate"])

    def _run_top_controller(self) -> None:
        """Run the top (reflux) PID loop and store its output.

        In CAS mode the remote setpoint drives the loop; otherwise the local
        operator setpoint does. The active setpoint is cached in _top_sp so
        readers log one consistent value.
        """
        top_active_sp = self._top_rsp if self._top_mode == CAS else self._top_sp
        self._top_sp = top_active_sp
        # The PID object only understands the strings "MAN" and "AUTO", while
        # the controller mode is stored here as an enum, hence the conversion.
        top_mode_str = "MAN" if self._top_mode == MAN else "AUTO"
        # Reflux flow is the manipulated variable of the top loop: pv is the
        # measured top composition, sp the setpoint, man_out the flow used when
        # the controller is in manual.
        self._reflux_out = self._top_pid.update(
            pv=self._top_pv_meas,
            sp=top_active_sp,
            mode=top_mode_str,
            man_out=self._reflux_man_out,
        )

    def _run_bottom_controller(self) -> None:
        """Run the bottom (steam) PID loop and store its output.

        Mirrors _run_top_controller with steam as the manipulated variable.
        """
        bot_active_sp = self._bot_rsp if self._bot_mode == CAS else self._bot_sp
        self._bot_sp = bot_active_sp
        bot_mode_str = "MAN" if self._bot_mode == MAN else "AUTO"
        self._steam_out = self._bot_pid.update(
            pv=self._bot_pv_meas,
            sp=bot_active_sp,
            mode=bot_mode_str,
            man_out=self._steam_man_out,
        )

    def _run_process_models(self) -> None:
        """Run the FOPDT models and store the true compositions.

        FOPDT = First-Order Plus Dead Time. Each model outputs a deviation from
        nominal for its input deviation. u1 = reflux deviation, u2 = steam
        deviation, d = feed deviation. y1_dev and y2_dev are the resulting
        deviations in top and bottom composition.
        """
        u1_dev = self._reflux_out - NOMINAL["reflux"]
        u2_dev = self._steam_out - NOMINAL["steam"]
        d_dev = self._effective_feed - NOMINAL["feed_rate"]

        y1_dev = self._g11.update(u1_dev) + self._g12.update(u2_dev) + self._gd1.update(d_dev)
        y2_dev = self._g21.update(u1_dev) + self._g22.update(u2_dev) + self._gd2.update(d_dev)

        self._true_top = NOMINAL["top_comp"] + y1_dev
        self._true_bot = NOMINAL["bottom_comp"] + y2_dev

    def _update_sensor_measurements(self) -> None:
        """Sample the sensors, adding Gaussian noise when configured.

        A separate RNG keeps sensor noise reproducible and independent of other
        random draws. The controllers will see these measurements on the next
        step.
        """
        if self._scenario.measurement_noise > 0.0:
            scale = self._scenario.measurement_noise
            top_noise = TOP_NOISE_STD * scale * float(self._sensor_rng.standard_normal())
            bot_noise = BOT_NOISE_STD * scale * float(self._sensor_rng.standard_normal())
            self._top_pv_meas = self._true_top + top_noise
            self._bot_pv_meas = self._true_bot + bot_noise
        else:
            self._top_pv_meas = self._true_top
            self._bot_pv_meas = self._true_bot

    def read(self, tag_id: str) -> tuple[float, int]:
        """Return (value, quality); raise KeyError for unknown tags.

        value is in engineering units (whatever the tag's section defines: bar,
        degC, m3/h, ...); quality is GOOD when the value could be resolved, and
        any other code signals a bad/stale reading to the caller.

        The dispatch order is deliberate: concrete tags of the top and bottom
        sections first, then the derived feed field, so a tag that exists in a
        section is never shadowed by the same name elsewhere.
        """
        # Raise first for unknown tags so callers get a clear KeyError.
        if tag_id not in self.tags:
            raise KeyError(f"Unknown tag: {tag_id}")

        # _read_top_tag returns None for non-top tags; None means try the next section.
        top_value = self._read_top_tag(tag_id)
        if top_value is not None:
            return top_value, GOOD

        bottom_value = self._read_bottom_tag(tag_id)
        if bottom_value is not None:
            return bottom_value, GOOD

        # FEED is a derived value stored on the instance, not a section tag.
        if tag_id == FEED:
            return self._effective_feed, GOOD

        # Tag exists in catalog but is not handled by top, bottom, or FEED readers.
        raise KeyError(f"Unknown tag: {tag_id}")

    def _read_top_tag(self, tag_id: str) -> float | None:
        """Return the top-section value for tag_id, or None when it is not a top tag."""
        if tag_id == TOP:
            return self._top_pv_meas
        if tag_id == TOP_SP:
            return self._top_sp
        if tag_id == TOP_RSP:
            return self._top_rsp
        if tag_id == TOP_MODE:
            return float(self._top_mode)
        if tag_id == REFLUX:
            return self._reflux_out
        return None

    def _read_bottom_tag(self, tag_id: str) -> float | None:
        """Return the bottom-section value for tag_id, or None when it is not a bottom tag.

        A "tag" is a named process signal of the distillation column, identified here by a short
        string constant (BOT, BOT_SP, ...). The bottom section is the reboiler end of the column.

        Args:
            tag_id: The tag name to look up, compared against the known bottom tag constants.

        Returns:
            The current value of that tag as a float, or None if tag_id is not a bottom tag,
            so the caller can fall through to another section (top, feed, ...).

        Note:
            Several attributes already hold floats (measured value, setpoint, remote setpoint);
            BOT_MODE is stored as an enum, so it is converted to float with float() for a
            uniform return type.
        """
        if tag_id == BOT:
            return self._bot_pv_meas
        if tag_id == BOT_SP:
            return self._bot_sp
        if tag_id == BOT_RSP:
            return self._bot_rsp
        if tag_id == BOT_MODE:
            return float(self._bot_mode)
        if tag_id == STEAM:
            return self._steam_out
        return None

    def write(self, tag_id: str, value: float) -> None:
        """Write a tag value adhering to loop permissions and validation rules.

        Dispatch order matters: a tag can be registered in more than one
        category (for example a setpoint tag that also drives a ratio), so all
        matching writers run and later writers see the effects of earlier ones.

        Raises:
            KeyError: if tag_id is not registered in self.tags.
            PermissionError: if the tag spec is not writable.
        """
        # A tag must be registered before any permission or dispatch checks can run;
        if tag_id not in self.tags:
            raise KeyError(f"Unknown tag: {tag_id}")

        # tag_spec carries the static configuration of the tag (its kind, its
        # bounds and whether the field device accepts writes). It never changes
        # during a run, so it is safe to read it once here.
        tag_spec = self.tags[tag_id]
        if not tag_spec.writable:
            raise PermissionError(f"Tag {tag_id} is read-only")

        # Each _write_* helper handles exactly one tag category and does nothing for
        # other tags. The fixed order below means the outcome is deterministic when a
        # tag belongs to more than one category; later helpers see earlier writes.
        self._write_mode_tag(tag_id, value)
        self._write_output_tag(tag_id, value)
        self._write_setpoint_tag(tag_id, value)
        self._write_ratio_tag(tag_id, value)
        self._write_feed_tag(tag_id, value)

    def _write_mode_tag(self, tag_id: str, value: float) -> None:
        """Handle writes to mode tags TOP_MODE and BOT_MODE."""
        if tag_id == TOP_MODE:
            self._set_top_mode(value)
        if tag_id == BOT_MODE:
            self._set_bot_mode(value)

    def _set_top_mode(self, value: float) -> None:
        """Validate and store a new top loop mode.

        The top (rectifying) loop is controlled either by a human operator (MAN) or by an
        automatic controller. This setter is the only place where the mode changes.

        Arguments:
            value: the requested mode, one of MAN (0), AUTO (1) or CASCADE (2). Floats
                such as 0.0 are accepted for the same mode, because the value usually
                arrives from a UI or a protocol that carries numbers as floats.

        Raises:
            ValueError: if `value` is not one of the three known modes.
        """
        # Reject anything outside the three known mode codes before converting to int.
        # The tuple contains both int and float forms because callers send either; the
        # exact membership test also keeps bools out (True == 1 would pass a range check).
        if value not in (0, 1, 2, 0.0, 1.0, 2.0):
            raise ValueError(f"Invalid mode value: {value}")
        # Normalise to int so `_top_mode` always has one type, regardless of caller input.
        new_mode = int(value)
        # Entering MAN hands control to the operator. Bumpless transfer: the manual
        # output starts at the controller output that was active until now, so the valve
        # position does not jump at the moment the mode changes.
        if new_mode == MAN:
            self._reflux_man_out = self._reflux_out
        self._top_mode = new_mode
        return

    def _set_bot_mode(self, value: float) -> None:
        """Validate and store a new bottom loop mode.

        The bottom loop controls the steam valve at the bottom of the column.
        Three modes exist: MAN (manual), AUTO and CAS (cascade).

        Args:
            value: Requested mode. Accepts either the int form (0, 1, 2) or
                the float form (0.0, 1.0, 2.0); the caller may pass either.

        Raises:
            ValueError: If `value` is not one of the three valid mode codes.
        """
        # Validate by exact membership, not a range: `True == 1` must not slip through.
        if value not in (0, 1, 2, 0.0, 1.0, 2.0):
            raise ValueError(f"Invalid mode value: {value}")
        new_mode = int(value)
        # Bumpless transfer: when entering MAN, seed the manual output with the
        # last automatic output so the valve does not jump on the mode change.
        if new_mode == MAN:
            self._steam_man_out = self._steam_out
        self._bot_mode = new_mode
        return

    def _write_output_tag(self, tag_id: str, value: float) -> None:
        """Handle writes to output tags REFLUX and STEAM."""
        if tag_id == REFLUX:
            self._set_reflux(value)
        if tag_id == STEAM:
            self._set_steam(value)

    def _set_reflux(self, value: float) -> None:
        """Validate loop mode and store a new reflux output.

        Reflux is the liquid pumped back from the condenser into the top of the
        column; its flow (UNIT: m3/h) is the manipulated variable of the top
        composition loop, so writing it by hand only makes sense when that loop
        is switched off (MAN mode).

        Raises:
            PermissionError: if the top loop is not in MAN mode.
        """
        # Operator writes to the manipulated variable are only valid when the loop is
        # in MAN; in AUTO/CAS the PID owns the output and a manual write would conflict.
        if self._top_mode != MAN:
            raise PermissionError("Cannot write REFLUX unless top loop is in MAN mode")
        # REFLUX is bounded by the pump/valve range 0..5 lb/min (see REFLUX tag spec).
        clamped = float(np.clip(value, 0.0, 5.0))
        # Keep the manual demand (_reflux_man_out) equal to the actual output
        # (_reflux_out): the manual value is remembered for bumpless transfer when
        # the loop later returns to MAN.
        self._reflux_man_out = clamped
        self._reflux_out = clamped
        return

    def _set_steam(self, value: float) -> None:
        """Validate loop mode and store a new steam output.

        ``value`` is the requested steam output in tonnes per hour (t/h).
        The steam flow controller only accepts manual commands: writing while
        the bottom loop is not in manual mode is refused with a PermissionError,
        so the operator cannot fight the automatic controller for the actuator.
        """
        # STEAM may only be written by the operator when the bottom loop is in MAN.
        if self._bot_mode != MAN:
            raise PermissionError("Cannot write STEAM unless bottom loop is in MAN mode")
        # The steam valve/actuator accepts 0..5 lb/min; clip rather than reject so an
        # out-of-range request is held at the nearest valid output.
        clamped = float(np.clip(value, 0.0, 5.0))
        # Keep the manual demand separate from the applied output: _steam_man_out is
        # remembered for a future bumpless transfer to MAN, while _steam_out is what
        # the loop uses every scan.
        self._steam_man_out = clamped
        self._steam_out = clamped
        return

    def _write_setpoint_tag(self, tag_id: str, value: float) -> None:
        """Handle writes to setpoint tags TOP_SP and BOT_SP."""
        if tag_id == TOP_SP:
            self._set_top_sp(value)
        if tag_id == BOT_SP:
            self._set_bot_sp(value)

    def _set_top_sp(self, value: float) -> None:
        """Validate loop mode and store a new top setpoint."""
        if self._top_mode == CAS:
            raise PermissionError("Cannot write TOP_SP while top loop is in CAS mode")
        self._top_sp = float(value)
        return

    def _set_bot_sp(self, value: float) -> None:
        """Validate loop mode and store a new bottom setpoint."""
        if self._bot_mode == CAS:
            raise PermissionError("Cannot write BOT_SP while bottom loop is in CAS mode")
        self._bot_sp = float(value)
        return

    def _write_ratio_tag(self, tag_id: str, value: float) -> None:
        """Handle writes to ratio tags TOP_RSP and BOT_RSP.

        TOP_RSP and BOT_RSP are the operator-facing setpoints of a ratio control loop: two
        response (RSP) values whose ratio the controller keeps. Each is stored unchanged, as a
        fraction (dimensionless, typically 0.0 to 1.0), on the instance so the next scan of the
        control logic uses it as the new setpoint.

        Args:
            tag_id: Name of the tag being written; only the two ratio constants are handled here.
            value: New setpoint value for that tag, as a fraction (dimensionless).

        Returns:
            None.
        """
        # TOP_RSP and BOT_RSP are independent attributes; each check below writes only
        # its own tag.
        if tag_id == TOP_RSP:
            self._top_rsp = float(value)
        if tag_id == BOT_RSP:
            self._bot_rsp = float(value)
        return

    def _write_feed_tag(self, tag_id: str, value: float) -> None:
        """Handle writes to the FEED tag."""
        if tag_id == FEED:
            self._feed_base = float(value)
            self._effective_feed = float(value)
        return

    def snapshot(self) -> dict[str, tuple[float, int]]:
        """Return {tag_id: (value, quality)} for every tag in catalog order."""
        return {tag_id: self.read(tag_id) for tag_id in self.tags.ids()}

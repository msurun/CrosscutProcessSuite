"""Wood-Berry binary distillation column simulation with dual PID composition control."""

from __future__ import annotations

import numpy as np

from crosscut_sim.core import AUTO, CAS, GOOD, MAN, Event, Fopdt, Scenario, TagCatalog, TagSpec
from crosscut_sim.disturbances import OrnsteinUhlenbeck
from crosscut_sim.pid import PID

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
    return TagCatalog(specs)


def _top_composition_spec() -> TagSpec:
    return TagSpec(
        id=TOP,
        unit="wt%",
        role="PV",
        type="float",
        description="Distillate top methanol composition",
        eng_min=0.0,
        eng_max=100.0,
        writable=False,
    )


def _top_setpoint_spec() -> TagSpec:
    return TagSpec(
        id=TOP_SP,
        unit="wt%",
        role="SP",
        type="float",
        description="Top composition active setpoint",
        eng_min=0.0,
        eng_max=100.0,
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
    return TagSpec(
        id=REFLUX,
        unit="lb/min",
        role="OUT",
        type="float",
        description="Reflux flow rate",
        eng_min=0.0,
        eng_max=5.0,
        writable=True,
    )


def _bottom_composition_spec() -> TagSpec:
    return TagSpec(
        id=BOT,
        unit="wt%",
        role="PV",
        type="float",
        description="Bottom methanol composition",
        eng_min=0.0,
        eng_max=100.0,
        writable=False,
    )


def _bottom_setpoint_spec() -> TagSpec:
    return TagSpec(
        id=BOT_SP,
        unit="wt%",
        role="SP",
        type="float",
        description="Bottom composition active setpoint",
        eng_min=0.0,
        eng_max=100.0,
        writable=True,
    )


def _bottom_remote_setpoint_spec() -> TagSpec:
    return TagSpec(
        id=BOT_RSP,
        unit="wt%",
        role="SP",
        type="float",
        description="Bottom composition remote setpoint",
        eng_min=0.0,
        eng_max=100.0,
        writable=True,
    )


def _bottom_mode_spec() -> TagSpec:
    return TagSpec(
        id=BOT_MODE,
        unit="",
        role="MODE",
        type="enum",
        description="Bottom composition loop mode (0=MAN, 1=AUTO, 2=CAS)",
        eng_min=0.0,
        eng_max=2.0,
        writable=True,
    )


def _steam_spec() -> TagSpec:
    return TagSpec(
        id=STEAM,
        unit="lb/min",
        role="OUT",
        type="float",
        description="Reboiler steam flow rate",
        eng_min=0.0,
        eng_max=5.0,
        writable=True,
    )


def _feed_spec() -> TagSpec:
    return TagSpec(
        id=FEED,
        unit="lb/min",
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

        seeds = np.random.SeedSequence(seed).spawn(2)
        self._sensor_rng = np.random.default_rng(seeds[0])
        dist_rng = np.random.default_rng(seeds[1])

        self._feed_ou = OrnsteinUhlenbeck(
            mean=NOMINAL["feed_rate"],
            sigma=self._scenario.disturbance_sigma,
            tau_s=self._scenario.disturbance_tau_s,
            dt_s=dt_s,
            rng=dist_rng,
        )

        # Process model transfer functions: (gain, delay_min, tau_min)
        # G11 = (12.8, 1, 16.7), G12 = (-18.9, 3, 21), Gd1 = (3.8, 8.1, 14.9)
        # G21 = (6.6, 7, 10.9),  G22 = (-19.4, 3, 14.4), Gd2 = (4.9, 3.4, 13.2)
        self._g11 = Fopdt(gain=12.8, tau_s=16.7 * 60.0, delay_s=1.0 * 60.0, dt_s=dt_s)
        self._g12 = Fopdt(gain=-18.9, tau_s=21.0 * 60.0, delay_s=3.0 * 60.0, dt_s=dt_s)
        self._gd1 = Fopdt(gain=3.8, tau_s=14.9 * 60.0, delay_s=8.1 * 60.0, dt_s=dt_s)

        self._g21 = Fopdt(gain=6.6, tau_s=10.9 * 60.0, delay_s=7.0 * 60.0, dt_s=dt_s)
        self._g22 = Fopdt(gain=-19.4, tau_s=14.4 * 60.0, delay_s=3.0 * 60.0, dt_s=dt_s)
        self._gd2 = Fopdt(gain=4.9, tau_s=13.2 * 60.0, delay_s=3.4 * 60.0, dt_s=dt_s)

        # Loop state variables
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

        # Controllers
        self._top_pid = PID(
            kc=TOP_PID_KC,
            ti_s=TOP_PID_TI_S,
            dt_s=dt_s,
            out_min=0.0,
            out_max=5.0,
            direct=False,
        )
        self._top_pid.reset()
        self._top_pid.update(
            NOMINAL["top_comp"], NOMINAL["top_comp"], "MAN", man_out=NOMINAL["reflux"]
        )

        self._bot_pid = PID(
            kc=BOT_PID_KC,
            ti_s=BOT_PID_TI_S,
            dt_s=dt_s,
            out_min=0.0,
            out_max=5.0,
            direct=True,
        )
        self._bot_pid.reset()
        self._bot_pid.update(
            NOMINAL["bottom_comp"], NOMINAL["bottom_comp"], "MAN", man_out=NOMINAL["steam"]
        )

        # Events sorted by trigger time
        self._events: list[Event] = sorted(self._scenario.events, key=self._event_trigger_time_s)
        self._event_idx = 0

    @staticmethod
    def _event_trigger_time_s(event: Event) -> float:
        """Return the simulation time at which `event` must be applied.

        Used as the sort key so `self._events` is ordered by trigger time.
        """
        return event.t_s

    def _apply_event_write(self, tag_id: str, value: float) -> None:
        """Apply an event write directly to internal state bypassing permissions."""
        if tag_id == TOP_SP:
            self._top_sp = float(value)
        elif tag_id == TOP_RSP:
            self._top_rsp = float(value)
        elif tag_id == TOP_MODE:
            self._top_mode = int(value)
        elif tag_id == REFLUX:
            self._apply_reflux_write(value)
        elif tag_id == BOT_SP:
            self._bot_sp = float(value)
        elif tag_id == BOT_RSP:
            self._bot_rsp = float(value)
        elif tag_id == BOT_MODE:
            self._bot_mode = int(value)
        elif tag_id == STEAM:
            self._apply_steam_write(value)
        elif tag_id == FEED:
            self._apply_feed_write(value)

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
        """Advance the simulation by scenario.dt_s."""
        # 1. Apply pending events
        while self._event_idx < len(self._events):
            ev = self._events[self._event_idx]
            if ev.t_s <= self.time_s:
                self._apply_event_write(ev.tag_id, ev.value)
                self._event_idx += 1
            else:
                break

        # 2. Update stochastic disturbance and effective feed
        ou_val = self._feed_ou.update()
        self._effective_feed = self._feed_base + (ou_val - NOMINAL["feed_rate"])

        # 3. Controller execution
        top_active_sp = self._top_rsp if self._top_mode == CAS else self._top_sp
        self._top_sp = top_active_sp
        top_mode_str = "MAN" if self._top_mode == MAN else "AUTO"
        self._reflux_out = self._top_pid.update(
            pv=self._top_pv_meas,
            sp=top_active_sp,
            mode=top_mode_str,
            man_out=self._reflux_man_out,
        )

        bot_active_sp = self._bot_rsp if self._bot_mode == CAS else self._bot_sp
        self._bot_sp = bot_active_sp
        bot_mode_str = "MAN" if self._bot_mode == MAN else "AUTO"
        self._steam_out = self._bot_pid.update(
            pv=self._bot_pv_meas,
            sp=bot_active_sp,
            mode=bot_mode_str,
            man_out=self._steam_man_out,
        )

        # 4. Process simulation via FOPDT transfer functions
        u1_dev = self._reflux_out - NOMINAL["reflux"]
        u2_dev = self._steam_out - NOMINAL["steam"]
        d_dev = self._effective_feed - NOMINAL["feed_rate"]

        y1_dev = self._g11.update(u1_dev) + self._g12.update(u2_dev) + self._gd1.update(d_dev)
        y2_dev = self._g21.update(u1_dev) + self._g22.update(u2_dev) + self._gd2.update(d_dev)

        true_top = NOMINAL["top_comp"] + y1_dev
        true_bot = NOMINAL["bottom_comp"] + y2_dev

        # 5. Sensor measurements with optional Gaussian noise
        if self._scenario.measurement_noise > 0.0:
            scale = self._scenario.measurement_noise
            top_noise = TOP_NOISE_STD * scale * float(self._sensor_rng.standard_normal())
            bot_noise = BOT_NOISE_STD * scale * float(self._sensor_rng.standard_normal())
            self._top_pv_meas = true_top + top_noise
            self._bot_pv_meas = true_bot + bot_noise
        else:
            self._top_pv_meas = true_top
            self._bot_pv_meas = true_bot

        # 6. Advance simulation time
        self.time_s += self._scenario.dt_s

    def read(self, tag_id: str) -> tuple[float, int]:
        """Return (value, quality); raise KeyError for unknown tags."""
        if tag_id not in self.tags:
            raise KeyError(f"Unknown tag: {tag_id}")

        # Top-section tags share one switch so that each helper stays short.
        top_value = self._read_top_tag(tag_id)
        if top_value is not None:
            return top_value, GOOD

        bottom_value = self._read_bottom_tag(tag_id)
        if bottom_value is not None:
            return bottom_value, GOOD

        if tag_id == FEED:
            return self._effective_feed, GOOD

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
        """Return the bottom-section value for tag_id, or None when it is not a bottom tag."""
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
        """Write a tag value adhering to loop permissions and validation rules."""
        if tag_id not in self.tags:
            raise KeyError(f"Unknown tag: {tag_id}")

        tag_spec = self.tags[tag_id]
        if not tag_spec.writable:
            raise PermissionError(f"Tag {tag_id} is read-only")

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
        """Validate and store a new top loop mode."""
        if value not in (0, 1, 2, 0.0, 1.0, 2.0):
            raise ValueError(f"Invalid mode value: {value}")
        new_mode = int(value)
        if new_mode == MAN:
            self._reflux_man_out = self._reflux_out
        self._top_mode = new_mode
        return

    def _set_bot_mode(self, value: float) -> None:
        """Validate and store a new bottom loop mode."""
        if value not in (0, 1, 2, 0.0, 1.0, 2.0):
            raise ValueError(f"Invalid mode value: {value}")
        new_mode = int(value)
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
        """Validate loop mode and store a new reflux output."""
        if self._top_mode != MAN:
            raise PermissionError("Cannot write REFLUX unless top loop is in MAN mode")
        clamped = float(np.clip(value, 0.0, 5.0))
        self._reflux_man_out = clamped
        self._reflux_out = clamped
        return

    def _set_steam(self, value: float) -> None:
        """Validate loop mode and store a new steam output."""
        if self._bot_mode != MAN:
            raise PermissionError("Cannot write STEAM unless bottom loop is in MAN mode")
        clamped = float(np.clip(value, 0.0, 5.0))
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
        """Handle writes to ratio tags TOP_RSP and BOT_RSP."""
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

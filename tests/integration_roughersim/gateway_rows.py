"""The 12 gateway scenarios (L5-G01..G12) against RougherSim over OPC UA.

Each scenario has the same safety assertion as its twin in gateway/tests/test_gateway_scenarios.py
but runs the real WriteGateway on the real OpcUaPlant against a RougherSim server started with
the hook file of docs/CONTRACT.md section 4. Differences from the simulated plant are listed in
docs/L5_FINDINGS.md. ``run_scenario(ref, tmp)`` runs one scenario and always stops the server.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from crosscut_gateway import engine
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.engine_params import ParamConfig, param_set_key
from crosscut_gateway.interfaces import (
    Gateway,
    ParamItem,
    ParamPolicy,
    ParamSetProposal,
    WritePolicy,
    WriteProposal,
)
from rs_harness import STEP_S, Harness, S, plant_map_for, rs_server

TAG = "FIC203.RSP"
POLICY = WritePolicy(
    limits=(0.0, 400.0),
    max_step=10.0,
    max_rate_per_s=5.0,
    min_interval_s=1.0,
    allowed_loop_modes=("CAS", "RSP"),
    hold_off_s=60.0,
    watchdog_s=600.0,  # the supervisor re-proposes far less often than every 30 sim s
    readback_tolerance=0.5,
)
HOOK = "gw.{}.v1"
DCS_WATCHDOG_WALL_S = 4.0  # rs_server default --watchdog-s (wall-clock seconds)


@dataclass
class Rig:
    """A running server, the harness on it and a supervised gateway."""

    h: Harness
    gw: Gateway
    tmp: Path
    clock_ns: int = 0  # simulation time of the last gateway tick

    def tick(self, now_ns: int | None = None) -> None:
        """Tick the gateway at ``now_ns`` (default: the current simulation time)."""
        self.clock_ns = self.h.now_ns() if now_ns is None else now_ns
        self.gw.tick(self.clock_ns)

    def up(self, delta: float, tick: bool = True) -> WriteProposal:
        """A proposal ``delta`` above the read-back (the CAS setpoint drifts in RougherSim).

        The gateway is ticked first, as in production, so its clock is current; with
        ``tick=False`` the proposal is stamped 2 s after the last tick instead.
        """
        if tick:
            self.tick()
        stamp = self.clock_ns if tick else self.clock_ns + 2 * S
        return WriteProposal(TAG, self.h.read(TAG) + delta, "supervisor", stamp, "l5")

    def step(self, steps: int = 1, tick: bool = False) -> None:
        """Wait ``steps`` plant steps; optionally tick the gateway after each one."""
        for _ in range(steps):
            self.h.advance(STEP_S)
            if tick:
                self.tick()

    def run(self, seconds: float) -> None:
        """Advance ``seconds`` of sim time in plant steps, ticking the gateway each step."""
        self.step(int(seconds / STEP_S), tick=True)

    def source(self) -> str:
        """Setpoint source as the adapter reports it."""
        return self.h.setpoint_source(TAG)


@contextmanager
def rig(
    tmp: Path, hook: str | None, speed: float = 20.0, mode: str = "supervised"
) -> Iterator[Rig]:
    """Start RougherSim with ``hook`` (a gateway_hooks id) and build the gateway on it."""
    with rs_server(tmp / "server.log", hook and HOOK.format(hook), speed) as port:
        harness = Harness(plant_map_for(port), speed)
        try:
            harness.wait_ready()
            gateway = engine.WriteGateway(harness, {TAG: POLICY}, mode)
            yield Rig(harness, gateway, tmp)
        finally:
            harness.close()


def g01(tmp: Path) -> None:
    """A write takes the setpoint remote; a kill gives it back to local."""
    with rig(tmp, None) as r:
        p = r.up(5.0)
        assert r.gw.propose(p).accepted
        r.step()
        assert r.source() == "remote"
        assert r.h.read(TAG) == p.value
        r.gw.kill()
        r.tick()
        r.step()
        assert r.source() == "local"


def g02(tmp: Path) -> None:
    """When the gateway stops ticking, the plant is local within the DCS watchdog."""
    with rig(tmp, None) as r:
        assert r.gw.propose(r.up(5.0)).accepted
        r.step()
        assert r.source() == "remote"
        time.sleep(DCS_WATCHDOG_WALL_S + 1.5)  # the gateway is silent
        assert r.source() == "local"
        r.tick()  # operator wins: the engine sees it and holds off
        assert r.gw.status()[TAG] == "hold_off"


def g03(tmp: Path) -> None:
    """If the control system refuses, the gateway reports it and stops writing that target."""
    with rig(tmp, "rejected_write_stops_and_reports") as r:
        assert not r.gw.propose(r.up(5.0)).accepted
        r.step(2)
        assert not r.gw.propose(r.up(6.0)).accepted
        assert r.h.writes == []
        assert r.h.loop_mode(TAG) != "RSP"  # the take was undone, nothing is remote
        assert r.gw.status()[TAG] != "enabled"


def g04(tmp: Path) -> None:
    """A written value never exceeds limits, max_step or max_rate_per_s."""
    with rig(tmp, None) as r:
        base = r.h.read(TAG)
        first = r.up(500.0)
        d = r.gw.propose(first)
        r.step()
        second = r.up(500.0)
        d2 = r.gw.propose(second)
        dt_s = (second.t_ns - first.t_ns) / S
        assert d.clamped_value is not None and d2.clamped_value is not None
        assert d.clamped_value <= POLICY.limits[1]
        assert abs(d.clamped_value - base) <= POLICY.max_step + 1.0  # SP drifts
        assert d2.clamped_value - d.clamped_value <= POLICY.max_rate_per_s * max(dt_s, 1.0)
        assert d2.clamped_value - d.clamped_value <= POLICY.max_step
        assert all(POLICY.limits[0] <= v <= POLICY.limits[1] for _, _, v in r.h.writes)


def g05(tmp: Path) -> None:
    """After an operator setpoint change, no write for hold_off_s, then only after re-enable."""
    with rig(tmp, "operator_override_and_hold_off", speed=8.0) as r:
        assert r.h.now_ns() < 50 * S, "harness too slow: operator hook (t=60 s) already due"
        assert r.gw.propose(r.up(5.0)).accepted
        while r.h.now_ns() < 70 * S:
            r.step(tick=True)
        assert r.gw.status()[TAG] == "hold_off"
        n = len(r.h.writes)
        r.run(POLICY.hold_off_s - 10)
        assert not r.gw.propose(r.up(6.0)).accepted
        r.run(20)  # hold-off over, but no explicit re-enable
        assert not r.gw.propose(r.up(6.0)).accepted
        assert len(r.h.writes) == n


def g06(tmp: Path) -> None:
    """A read-back differing by more than the tolerance disables the target."""
    with rig(tmp, "readback_mismatch_stops_writing") as r:
        r.h.wait_until_ns(15 * S)  # the offset hook starts at t = 10 s
        r.gw.propose(r.up(5.0))
        r.step()
        r.tick()
        n = len(r.h.writes)
        r.step()
        assert not r.gw.propose(r.up(6.0)).accepted
        assert len(r.h.writes) == n
        assert r.gw.status()[TAG] != "enabled"


def g07(tmp: Path) -> None:
    """A link failure during a write ends in a disabled target and local setpoint, no exception."""
    with rig(tmp, "communication_loss_mid_write_fails_closed") as r:
        p = r.up(5.0)
        r.gw.propose(p)
        for _ in range(8):  # the dead link refuses even the clock read: tick on wall time
            time.sleep(0.5)
            r.tick(r.clock_ns)  # must not raise
        assert r.gw.status()[TAG] != "enabled"
        again = WriteProposal(TAG, p.value + 1.0, "supervisor", r.clock_ns + S, "l5")
        assert not r.gw.propose(again).accepted
        assert len(r.h.writes) <= 1
        assert any(rec["event"] == "release" for rec in r.gw.audit_records())


def g08(tmp: Path) -> None:
    """The same proposal sent twice produces exactly one write."""
    with rig(tmp, None) as r:
        p = r.up(5.0)
        r.gw.propose(p)
        r.gw.propose(p)
        r.step()
        assert len(r.h.writes) == 1
        assert r.h.read(TAG) == p.value


def g09(tmp: Path) -> None:
    """If the operator leaves CAS between proposals, the next one is refused, nothing written."""
    with rig(tmp, "mode_change_race_never_writes_in_wrong_mode", speed=4.0) as r:
        assert r.h.now_ns() < 20 * S, "harness too slow: operator hook (t=30 s) already due"
        assert r.gw.propose(r.up(5.0)).accepted
        r.tick()
        r.h.wait_until_ns(40 * S)  # the gateway does not tick while the operator acts
        n = len(r.h.writes)
        assert not r.gw.propose(r.up(6.0, tick=False)).accepted
        assert len(r.h.writes) == n
        assert r.h.loop_mode(TAG) == "AUTO"
        assert r.source() == "local"


def g10(tmp: Path) -> None:
    """A policy file whose hash differs from the pinned one prevents startup."""
    with rig(tmp, None) as r:
        policy = tmp / "write-policy.json"
        policy.write_text('{"limits": [0, 100]}', encoding="utf-8")
        (tmp / "write-policy.sha256").write_text("0" * 64, encoding="utf-8")
        with pytest.raises(ValueError, match="hash"):
            engine.start_from_policy_file(policy, r.h, "supervised", allow_legacy_sidecar=True)
        assert r.h.writes == []
        assert r.h.loop_mode(TAG) == "CAS"


def g11(tmp: Path) -> None:
    """After kill() and one tick, no write is accepted and the setpoint is local."""
    with rig(tmp, None) as r:
        assert r.gw.propose(r.up(5.0)).accepted
        r.gw.kill()
        r.tick()
        n = len(r.h.writes)
        r.step(2)
        assert not r.gw.propose(r.up(6.0)).accepted
        assert len(r.h.writes) == n
        assert r.source() == "local"


def g12(tmp: Path) -> None:
    """A dry run writes an audit record of the would-be write and sends zero writes."""
    with rig(tmp, None, mode="dry_run") as r:
        decision = r.gw.propose(r.up(5.0))
        r.tick()
        r.step()
        assert r.h.writes == []
        assert r.h.loop_mode(TAG) == "CAS"
        assert r.h.loop_mode(TAG) == "CAS"
        assert decision.clamped_value is not None
        assert r.gw.audit_records()


SCENARIOS: dict[str, Callable[[Path], None]] = {
    "test_cas_handover_take_and_give_back": g01,
    "test_watchdog_loss_returns_plant_to_local": g02,
    "test_rejected_write_stops_and_reports": g03,
    "test_limit_and_rate_clamp": g04,
    "test_operator_override_and_hold_off": g05,
    "test_readback_mismatch_stops_writing": g06,
    "test_communication_loss_mid_write_fails_closed": g07,
    "test_duplicate_proposal_is_idempotent": g08,
    "test_mode_change_race_never_writes_in_wrong_mode": g09,
    "test_tampered_policy_file_refuses_to_start": g10,
    "test_kill_switch_stops_writes_within_one_tick": g11,
    "test_dry_run_sends_nothing": g12,
}


def run_scenario(scenario_ref: str, tmp: Path) -> None:
    """Run the scenario named like the gateway test function, with scratch files in ``tmp``."""
    SCENARIOS[scenario_ref](tmp)


GAIN, TI = "FIC203.GAIN", "FIC203.TI"
ALICE = ActorContext(actor="alice", roles=("engineer",))
BOB = ActorContext(actor="bob", roles=("engineer",))
LOOP = "FIC203"
PARAM_POLICIES = {
    GAIN: ParamPolicy(
        LOOP, "gain", "1", "abb_pidcc", (0.01, 10.0), 2.0, 0.0, 60.0, ("CAS", "AUTO", "RSP", "MAN")
    ),
    TI: ParamPolicy(
        LOOP, "ti", "s", "abb_pidcc", (1.0, 600.0), 2.0, 0.0, 60.0, ("CAS", "AUTO", "RSP", "MAN")
    ),
}


def _param_set(
    h: Harness, pid: str, now: int, targets: dict[str, float], of: str | None = None
) -> ParamSetProposal:
    """A parameter set taking each target to its value; ``from`` is read live from RougherSim."""
    unit = {GAIN: "1", TI: "s"}
    items = tuple(
        ParamItem(tag.split(".")[1].lower(), tag, unit[tag], "abb_pidcc", h.read_param(tag), to)
        for tag, to in targets.items()
    )
    return ParamSetProposal(pid, LOOP, items, "alice", now, now + 3600 * S, "l5 tuning", of)


def _approve(gw: engine.WriteGateway, proposal: ParamSetProposal, now: int) -> str:
    """Propose as alice, approve as bob; the final reason code."""
    gw.tick(now)
    if gw.propose_params(proposal, actor_ctx=ALICE).reason_code != "queued":
        return "not_queued"
    return gw.approve(param_set_key(proposal), actor_ctx=BOB).reason_code


def tuning(tmp: Path) -> None:
    """Gain and Ti change on Double nodes with exact read-back; rollback restores them exactly."""
    with rig(tmp, None, mode="confirm") as r:
        gw = engine.WriteGateway(
            r.h, {TAG: POLICY}, "confirm", params=ParamConfig(dict(PARAM_POLICIES), r.h)
        )
        old = {tag: r.h.read_param(tag) for tag in PARAM_POLICIES}
        now = r.h.now_ns()
        new = {GAIN: old[GAIN] * 1.5, TI: old[TI] * 1.5}
        assert _approve(gw, _param_set(r.h, "p1", now, new), now) == "applied"
        assert {tag: r.h.read_param(tag) for tag in new} == new  # tolerance 0
        later = now + 120 * S
        undo = _param_set(r.h, "p2", later, old, of="p1")
        assert _approve(gw, undo, later) == "applied"
        assert {tag: r.h.read_param(tag) for tag in old} == old  # tolerance 0

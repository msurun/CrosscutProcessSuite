"""Hardening of the parameter write path: one failing test per finding of the safety review.

Audit failure after a write, unexpected plant errors, tick order, interval over the whole loop,
kill during a batch, kill reset, clock not started, float32 read-back, values read from the
plant, tolerance bound of the policy and the actor requirement on approve.
"""

from __future__ import annotations

import dataclasses
import json
import struct
from pathlib import Path
from typing import Any

import pytest
from auth_helpers import drop, signed
from crosscut_gateway import engine
from crosscut_gateway import engine_params as ep
from crosscut_gateway.engine_params import ParamConfig, param_set_key
from crosscut_gateway.interfaces import WriteProposal
from crosscut_gateway.policy import PolicyError, params_from_dict, policy_from_dict
from test_engine_params import (
    ALICE,
    BOB,
    KP,
    NOW,
    PARAMS,
    TD,
    TI,
    ParamPlant,
    events,
    it,
    make,
    pset,
    queued,
)
from test_gateway_scenarios import POLICY, TAG, S
from test_service_params import SECOND_ENGINEER, make_param_env, pending_key, propose

# ---------------------------------------------------------------- 1: audit failure after write


def _fail_audit_of(gw: engine.WriteGateway, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make the file write of audit records ``name`` raise OSError (record not kept in memory)."""
    original = gw._audit._write_record

    def flaky(record: dict[str, str]) -> None:
        if record["event"] == name:
            raise OSError("disk full")
        original(record)

    monkeypatch.setattr(gw._audit, "_write_record", flaky)


def test_audit_failure_after_write_stops_target_keeps_state_and_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0))
    _fail_audit_of(gw, monkeypatch, "param_write")
    decision = gw.approve(key, actor_ctx=BOB)  # must not raise
    assert plant.params[KP] == 3.0 and decision.accepted
    assert gw.status()[KP] == "stopped:comm"
    assert gw.alarms()[KP] == "check_dcs"
    assert events(gw, "param_write") == []  # failed record is not kept in memory
    gw.re_enable(KP)
    soon = pset(it(KP, 2.5, 3.0), pid="p2")
    assert gw.propose_params(soon, actor_ctx=ALICE).reason_code == "min_interval"
    replay = gw.propose_params(pset(it(KP, 3.0)), actor_ctx=ALICE)
    assert replay == decision  # idempotency cache was set


# ---------------------------------------------------------------- 2: unexpected plant error


def test_plant_map_gap_before_write_refuses_with_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0))

    def gap(tag: str) -> str:
        raise KeyError(tag)

    monkeypatch.setattr(plant, "loop_mode", gap)
    decision = gw.approve(key, actor_ctx=BOB)  # must not raise
    assert not decision.accepted and decision.reason_code == "plant_error"
    assert events(gw, "param_decision")[-1]["reason_code"] == "plant_error"
    assert plant.param_writes == [] and gw.pending_params() == []
    assert gw.status()[KP] == "enabled"


def test_unexpected_error_after_write_reverts_and_stops_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0))

    def broken(p: Any, policies: Any, items: Any) -> Any:
        p.write_param(KP, 3.0)
        raise KeyError("map gap")

    monkeypatch.setattr(ep, "write_set", broken)
    decision = gw.approve(key, actor_ctx=BOB)
    assert decision.reason_code == "plant_error" and not decision.accepted
    assert plant.params[KP] == 2.0  # revert attempted and done
    assert gw.status()[KP] == "stopped:comm"
    assert events(gw, "param_decision")[-1]["reason_code"] == "plant_error"


# ---------------------------------------------------------------- 3: tick robustness and order


def test_param_tick_error_is_audited_and_stops_target(monkeypatch: pytest.MonkeyPatch) -> None:
    gw, plant = make()
    gw.approve(queued(gw, it(KP, 3.0)), actor_ctx=BOB)

    def odd(tag: str) -> float:
        raise RuntimeError("boom")

    monkeypatch.setattr(plant, "read_param", odd)
    gw.tick(NOW + S)  # must not raise
    assert gw.status()[KP] == "stopped:comm"
    assert events(gw, "param_tick_error")[0]["tag"] == KP


def test_param_tick_runs_after_setpoint_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    gw, plant = make("supervised")
    gw.propose(WriteProposal(TAG, 55.0, "alice", NOW, "t"), actor_ctx=ALICE)
    gw.approve(queued(gw, it(KP, 3.0)), actor_ctx=BOB)
    order: list[str] = []
    real_hb, real_read = plant.send_heartbeat, plant.read_param

    def heartbeat() -> None:
        order.append("heartbeat")
        real_hb()

    def read(tag: str) -> float:
        order.append("param")
        return real_read(tag)

    monkeypatch.setattr(plant, "send_heartbeat", heartbeat)
    monkeypatch.setattr(plant, "read_param", read)
    gw.tick(NOW + S)
    assert "heartbeat" in order and "param" in order
    assert order.index("heartbeat") < order.index("param")


# ---------------------------------------------------------------- 4: interval over the loop


def test_min_interval_is_the_max_over_all_policies_of_the_loop() -> None:
    params = dict(PARAMS)
    params[TD] = dataclasses.replace(PARAMS[TD], min_interval_s=0.0)
    plant = ParamPlant()
    gw = engine.WriteGateway(plant, {TAG: POLICY}, "confirm", params=ParamConfig(params))  # type: ignore[arg-type]
    gw.tick(NOW)
    gw.approve(queued(gw, it(KP, 3.0)), actor_ctx=BOB)
    td_only = pset(it(TD, 5.0), pid="p2")
    assert gw.propose_params(td_only, actor_ctx=ALICE).reason_code == "min_interval"


# ---------------------------------------------------------------- 5: kill before each write


def test_kill_file_created_mid_batch_stops_a_later_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_param_env(tmp_path)
    propose(env)
    key = pending_key(env)
    drop(env, signed(env, "approve", {"key": key}, **SECOND_ENGINEER))
    real = env.service._inbox_files

    def late_kill() -> list[Path]:
        (env.root / "_gateway" / "KILL").write_text("x", encoding="utf-8")
        return real()

    monkeypatch.setattr(env.service, "_inbox_files", late_kill)
    env.service.poll_once()
    assert env.plant.params[KP] == 2.0  # type: ignore[attr-defined]
    assert env.gateway.killed


def test_apply_refuses_when_killed_at_apply_start() -> None:
    gw, plant = make()
    queued(gw, it(KP, 3.0))
    pending = gw.pending_params()[0]
    gw._killed = True
    decision = gw._params._apply(pending)
    assert decision.reason_code == "killed" and plant.param_writes == []


# ---------------------------------------------------------------- 6: kill reset flushes


def test_reset_kill_flushes_pending_sets() -> None:
    gw, _ = make()
    queued(gw, it(KP, 3.0))
    gw.reset_kill()
    assert gw.pending_params() == []
    assert events(gw, "param_flushed")[-1]["reason_code"] == "kill_reset"


# ---------------------------------------------------------------- 7: clock not started


def test_propose_refused_before_first_tick() -> None:
    plant = ParamPlant()
    gw = engine.WriteGateway(plant, {TAG: POLICY}, "confirm", params=ParamConfig(dict(PARAMS)))  # type: ignore[arg-type]
    decision = gw.propose_params(pset(it(KP, 3.0)), actor_ctx=ALICE)
    assert decision.reason_code == "clock_not_started" and gw.pending_params() == []


def test_approve_refused_while_clock_not_started() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0))
    gw._clock_started = False
    assert gw.approve(key, actor_ctx=BOB).reason_code == "clock_not_started"
    assert plant.param_writes == []


# ---------------------------------------------------------------- 8: float32 read-back


class Float32Plant(ParamPlant):
    """Stores parameters as a Float node does: rounded to float32."""

    def write_param(self, tag: str, value: float) -> bool:
        ok = super().write_param(tag, value)
        self.params[tag] = struct.unpack("f", struct.pack("f", self.params[tag]))[0]
        return ok

    def param_data_type(self, tag: str) -> str:
        return "Float"


def _tight_gateway(plant: ParamPlant) -> engine.WriteGateway:
    tight = {KP: dataclasses.replace(PARAMS[KP], readback_tolerance=1e-12)}
    gw = engine.WriteGateway(plant, {TAG: POLICY}, "confirm", params=ParamConfig(tight))  # type: ignore[arg-type]
    gw.tick(NOW)
    return gw


def test_float_target_with_tight_tolerance_reads_back_against_float32() -> None:
    plant = Float32Plant()
    gw = _tight_gateway(plant)
    key = queued(gw, it(KP, 3.1))
    assert gw.approve(key, actor_ctx=BOB).reason_code == "applied"
    gw.tick(NOW + S)  # the periodic read-back must agree too
    assert gw.status()[KP] == "enabled"


def test_double_target_keeps_exact_comparison() -> None:
    class RoundingDouble(Float32Plant):
        def param_data_type(self, tag: str) -> str:
            return "Double"

    gw = _tight_gateway(RoundingDouble())
    decision = gw.approve(queued(gw, it(KP, 3.1)), actor_ctx=BOB)
    assert decision.reason_code == "readback_mismatch"


# ---------------------------------------------------------------- 9: values read, alarm flag


class OffsetPlant(ParamPlant):
    """Writes land slightly off (inside the tolerance)."""

    def write_param(self, tag: str, value: float) -> bool:
        ok = super().write_param(tag, value)
        self.params[tag] = value + 0.0005
        return ok


def test_param_write_audits_values_read_from_the_plant() -> None:
    plant = OffsetPlant()
    plant.params[KP] = 2.0004  # inside the tolerance of 0.001
    gw = engine.WriteGateway(plant, {TAG: POLICY}, "confirm", params=ParamConfig(dict(PARAMS)))  # type: ignore[arg-type]
    gw.tick(NOW)
    gw.approve(queued(gw, it(KP, 3.0)), actor_ctx=BOB)
    record = events(gw, "param_write")[0]
    assert float(record["applied_from"]) == pytest.approx(2.0004)
    assert float(record["applied_to"]) == pytest.approx(3.0005)
    assert record["applied_from"] != "2.0" and record["applied_to"] != "3.0"


def test_alarm_check_dcs_sets_visible_flag() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 1.5), it(TI, 150.0))
    plant.refuse_tags.add(TI)
    plant.refuse_values.add((KP, 2.0))
    assert gw.approve(key, actor_ctx=BOB).reason_code == "revert_failed"
    assert gw.status()[KP] == "stopped:comm" and gw.alarms()[KP] == "check_dcs"
    gw.re_enable(KP)
    assert KP not in gw.alarms()


# ---------------------------------------------------------------- 10: tolerance bound


def _gain_doc(tolerance: float) -> dict[str, Any]:
    target = {
        "kind": "pid_param", "loop": "FIC101", "param": "gain", "unit": "1",
        "vendor_form": "siemens_pid_compact", "limits": [0.1, 10.0], "max_ratio": 2.0,
        "readback_tolerance": tolerance, "min_interval_s": 60.0, "allowed_loop_modes": ["AUTO"],
    }
    return {"version": 1, "mode": "confirm", "targets": {"A.KP": target}}


def test_param_tolerance_above_ten_percent_of_range_is_rejected() -> None:
    assert params_from_dict(_gain_doc(0.99))["A.KP"].readback_tolerance == 0.99  # 10% of 9.9
    with pytest.raises(PolicyError, match="readback_tolerance"):
        params_from_dict(_gain_doc(1.0))


def test_setpoint_tolerance_is_unchanged() -> None:
    sp = {
        "limits": [0.0, 100.0], "max_step": 10.0, "max_rate_per_s": 5.0, "min_interval_s": 1.0,
        "allowed_loop_modes": ["CAS"], "hold_off_s": 60.0, "watchdog_s": 5.0,
        "readback_tolerance": 50.0,
    }
    parsed = policy_from_dict({"version": 1, "mode": "confirm", "targets": {"A.SP": sp}})
    assert parsed["A.SP"].readback_tolerance == 50.0


# ---------------------------------------------------------------- 12: actor required


def test_approve_without_actor_is_refused_and_set_stays_queued() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0))
    decision = gw.approve(key)
    assert decision.reason_code == "actor_required" and not decision.accepted
    assert plant.param_writes == [] and len(gw.pending_params()) == 1
    assert gw.approve(key, actor_ctx=BOB).reason_code == "applied"


# ---------------------------------------------------------------- idempotency key


def test_key_covers_rollback_of() -> None:
    base = pset(it(KP, 3.0))
    other = dataclasses.replace(base, rollback_of="p0")
    assert param_set_key(base) != param_set_key(other)


def test_state_json_shows_the_dcs_alarm(tmp_path: Path) -> None:
    env = make_param_env(tmp_path)
    plant: Any = env.plant
    plant.refuse_tags.add(TI)
    plant.refuse_values.add((KP, 2.0))
    env.gateway.propose_params(
        pset(it(KP, 1.5), it(TI, 150.0), pid="p9", proposer="erin", t_ns=int(env.clock() * S)),
        actor_ctx=ALICE,
    )
    key = env.gateway.pending_params()[-1].key
    env.gateway.approve(key, actor_ctx=BOB)
    env.service.poll_once()
    state = json.loads((env.root / "_gateway" / "state.json").read_text(encoding="utf-8"))
    assert state["alarms"] == {KP: "check_dcs"}

"""PID parameter sets in the engine (ADR 014 steps 2): confirm-only, refuse-not-clamp, revert.

A fake control system implements both ControlSystem and ParamControlSystem; the fake clock is the
``now_ns`` given to ``tick``.
"""

from __future__ import annotations

from typing import Any

import pytest
from crosscut_gateway import engine
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.engine_params import (
    KIND_MODE_CAP,
    ParamConfig,
    effective_mode,
    param_set_key,
)
from crosscut_gateway.engine_params_apply import detune_order
from crosscut_gateway.interfaces import (
    ParamControlSystem,
    ParamItem,
    ParamPolicy,
    ParamSetProposal,
    WriteProposal,
)
from test_gateway_scenarios import POLICY, TAG, S, SimPlant

KP, TI, TD = "FIC101.KP", "FIC101.TI", "FIC101.TD"
NOW = 10_000 * S
HOUR = 3600 * S
MODES = ("off", "advisory", "dry_run", "confirm", "supervised")
ALICE = ActorContext(actor="alice", roles=("engineer",))
BOB = ActorContext(actor="bob", roles=("engineer",))


def _policy(param: str, unit: str, limits: tuple[float, float], tol: float) -> ParamPolicy:
    return ParamPolicy(
        loop="L1", param=param, unit=unit, vendor_form="siemens_pid", limits=limits,
        max_ratio=2.0, readback_tolerance=tol, min_interval_s=60.0,
        allowed_loop_modes=("AUTO", "MAN"),
    )


PARAMS = {
    KP: _policy("gain", "1", (0.1, 10.0), 0.001),
    TI: _policy("ti", "s", (5.0, 600.0), 0.01),
    TD: _policy("td", "s", (0.0, 60.0), 0.01),
}


class ParamPlant(SimPlant):
    """SimPlant plus PID parameters, with switches to inject faults."""

    def __init__(self) -> None:
        super().__init__()
        self.params = {KP: 2.0, TI: 100.0, TD: 0.0}
        self.pmode = "AUTO"
        self.param_writes: list[tuple[str, float]] = []
        self.refuse_tags: set[str] = set()
        self.refuse_values: set[tuple[str, float]] = set()
        self.stuck_tags: set[str] = set()
        self.raise_once_on: str | None = None
        self.down = False
        self.releases: list[str] = []
        self.heartbeats = 0

    def read_param(self, tag: str) -> float:
        if self.down:
            raise ConnectionError("link down")
        return self.params[tag]

    def write_param(self, tag: str, value: float) -> bool:
        if self.down:
            raise ConnectionError("link down")
        if self.raise_once_on == tag:
            self.raise_once_on = None
            raise TimeoutError("write timed out")
        self.param_writes.append((tag, value))
        if tag in self.refuse_tags or (tag, value) in self.refuse_values:
            return False
        if tag not in self.stuck_tags:
            self.params[tag] = value
        return True

    def loop_mode(self, tag: str) -> str:
        if tag in self.params:
            if self.down:
                raise ConnectionError("link down")
            return self.pmode
        return super().loop_mode(tag)

    def release(self, tag: str) -> None:
        self.releases.append(tag)
        super().release(tag)

    def send_heartbeat(self) -> None:
        self.heartbeats += 1
        super().send_heartbeat()


def make(mode: str = "confirm") -> tuple[engine.WriteGateway, ParamPlant]:
    plant = ParamPlant()
    gw = engine.WriteGateway(plant, {TAG: POLICY}, mode, params=ParamConfig(dict(PARAMS)))  # type: ignore[arg-type]
    gw.tick(NOW)
    return gw, plant


def it(target: str, to: float, frm: float | None = None, **kw: Any) -> ParamItem:
    param = {KP: "gain", TI: "ti", TD: "td"}[target]
    default_from = {KP: 2.0, TI: 100.0, TD: 0.0}[target]
    return ParamItem(
        param=kw.get("param", param), target=target, unit=kw.get("unit", PARAMS[target].unit),
        vendor_form=kw.get("form", "siemens_pid"),
        from_value=default_from if frm is None else frm, to_value=to,
    )


def pset(*items: ParamItem, **kw: Any) -> ParamSetProposal:
    return ParamSetProposal(
        proposal_id=kw.get("pid", "p1"), loop_id=kw.get("loop", "L1"), items=tuple(items),
        proposer=kw.get("proposer", "alice"), t_ns=kw.get("t_ns", NOW),
        expires_ns=kw.get("expires_ns", NOW + 8 * HOUR), reason="tune",
        rollback_of=kw.get("rollback_of"),
    )


def events(gw: engine.WriteGateway, name: str) -> list[dict[str, str]]:
    return [r for r in gw.audit_records() if r["event"] == name]


def queued(gw: engine.WriteGateway, *items: ParamItem, **kw: Any) -> str:
    proposal = pset(*items, **kw)
    decision = gw.propose_params(proposal, actor_ctx=ALICE)
    assert decision.reason_code == "queued", decision
    return param_set_key(proposal)


# ---------------------------------------------------------------- modes and kinds


def test_kind_mode_cap_table() -> None:
    assert KIND_MODE_CAP == {"setpoint": "supervised", "pid_param": "confirm"}
    for mode in MODES:
        assert effective_mode("setpoint", mode) == mode
    expected = ["off", "advisory", "dry_run", "confirm", "confirm"]
    assert [effective_mode("pid_param", m) for m in MODES] == expected


@pytest.mark.parametrize(
    ("mode", "setpoint_code", "param_code"),
    [
        ("off", "mode_off", "mode_off"),
        ("advisory", "ok", "ok"),
        ("dry_run", "dry_run", "dry_run"),
        ("confirm", "queued", "queued"),
        ("supervised", "ok", "queued"),
    ],
)
def test_all_modes_by_kind(mode: str, setpoint_code: str, param_code: str) -> None:
    gw, plant = make(mode)
    sp = gw.propose(WriteProposal(TAG, 55.0, "alice", NOW, "t"), actor_ctx=ALICE)
    pdec = gw.propose_params(pset(it(KP, 3.0)), actor_ctx=ALICE)
    assert sp.reason_code == setpoint_code
    assert pdec.reason_code == param_code
    assert plant.param_writes == []  # a parameter is never written by propose
    assert len(plant.writes) == (1 if mode == "supervised" else 0)
    assert len(gw.pending_params()) == (1 if param_code == "queued" else 0)


def test_supervised_queues_then_second_person_applies() -> None:
    gw, plant = make("supervised")
    key = queued(gw, it(KP, 3.0))
    assert plant.param_writes == []
    assert gw.pending_kind(key) == "pid_param"
    assert gw.approve(key, actor_ctx=BOB).reason_code == "applied"
    assert plant.params[KP] == 3.0


def test_approve_refused_when_mode_dropped_below_confirm() -> None:
    gw, plant = make("confirm")
    key = queued(gw, it(KP, 3.0))
    gw.set_mode("dry_run")
    assert gw.approve(key, actor_ctx=BOB).reason_code == "not_confirm_mode"
    assert plant.param_writes == [] and len(gw.pending_params()) == 1


def test_self_approval_refused_and_set_stays_queued() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0))
    assert gw.pending_proposer(key) == "alice"
    assert gw.approve(key, actor_ctx=ActorContext(actor=" ALICE ")).reason_code == "self_approval"
    assert plant.param_writes == [] and len(gw.pending_params()) == 1


def test_service_principal_cannot_propose_tuning() -> None:
    gw, _ = make()
    svc = ActorContext(actor="svc:runtime", roles=("service",))
    assert gw.propose_params(pset(it(KP, 3.0)), actor_ctx=svc).reason_code == (
        "service_cannot_propose_tuning"
    )
    claimed = pset(it(KP, 3.0), pid="p2", proposer="svc:runtime")
    refused = gw.propose_params(claimed, actor_ctx=ALICE)
    assert refused.reason_code == "service_cannot_propose_tuning"
    assert gw.pending_params() == []


# ---------------------------------------------------------------- refuse, never clamp


@pytest.mark.parametrize(
    ("kwargs", "first_code", "all_codes"),
    [
        ({"to": 20.0}, "out_of_limits", ("out_of_limits", "ratio_exceeded")),
        ({"to": 5.0}, "ratio_exceeded", ("ratio_exceeded",)),
        ({"to": 0.0}, "out_of_limits", ("nonpositive_gain",)),
        ({"to": -1.0}, "out_of_limits", ("nonpositive_gain",)),
        ({"to": 3.0, "unit": "%"}, "unit_mismatch", ("unit_mismatch",)),
        ({"to": 3.0, "form": "abb_pidcc"}, "form_mismatch", ("form_mismatch",)),
        ({"to": 3.0, "param": "ti"}, "param_mismatch", ("param_mismatch",)),
        ({"to": float("nan")}, "bad_value", ("bad_value",)),
    ],
)
def test_refused_never_clamped(
    kwargs: dict[str, Any], first_code: str, all_codes: tuple[str, ...]
) -> None:
    gw, plant = make()
    to = kwargs.pop("to")
    decision = gw.propose_params(pset(it(KP, to, **kwargs)), actor_ctx=ALICE)
    assert decision.accepted is False
    assert decision.reason_code == first_code
    assert decision.clamped_value is None
    assert gw.pending_params() == [] and plant.param_writes == []
    detail = events(gw, "param_decision")[-1]["value"].split(",")
    assert all(code in detail for code in all_codes)


def test_unknown_target_empty_set_duplicate_and_wrong_loop_refused() -> None:
    gw, _ = make()
    ghost = ParamItem("gain", "NOPE.KP", "1", "siemens_pid", 2.0, 3.0)
    assert gw.propose_params(pset(ghost, pid="a"), actor_ctx=ALICE).reason_code == "no_policy"
    assert gw.propose_params(pset(pid="b"), actor_ctx=ALICE).reason_code == "no_items"
    twice = pset(it(KP, 3.0), it(KP, 2.5), pid="c")
    assert gw.propose_params(twice, actor_ctx=ALICE).reason_code == "duplicate_target"
    other_loop = pset(it(KP, 3.0), pid="d", loop="L2")
    assert gw.propose_params(other_loop, actor_ctx=ALICE).reason_code == "loop_mismatch"
    assert gw.pending_params() == []


# ---------------------------------------------------------------- apply flow


def test_from_mismatch_writes_nothing_and_reports_values_read() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0), it(TI, 150.0))
    plant.params[TI] = 120.0  # somebody retuned Ti at the DCS
    decision = gw.approve(key, actor_ctx=BOB)
    assert decision.reason_code == "from_mismatch" and not decision.accepted
    assert plant.param_writes == []
    assert f"{TI}=120.0" in events(gw, "param_decision")[-1]["value"]
    assert gw.pending_params() == []


def test_from_within_tolerance_is_accepted() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0))
    plant.params[KP] = 2.0005
    assert gw.approve(key, actor_ctx=BOB).reason_code == "applied"


def test_loop_mode_must_be_allowed_for_every_item() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0))
    plant.pmode = "CAS"
    assert gw.approve(key, actor_ctx=BOB).reason_code == "mode_not_allowed"
    assert plant.param_writes == []


def test_detune_order_function() -> None:
    gain_up, gain_down = it(KP, 3.0), it(KP, 1.5)
    ti_long, ti_short = it(TI, 150.0), it(TI, 60.0)
    td_up, td_down = it(TD, 5.0, 2.0), it(TD, 1.0, 2.0)
    shuffled = [gain_up, ti_short, td_up, td_down, ti_long, gain_down]
    assert detune_order(shuffled) == [gain_down, ti_long, td_down, td_up, ti_short, gain_up]
    assert detune_order([]) == []


def test_writes_follow_detuning_order_with_readback() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0), it(TI, 150.0))  # gain up, Ti longer
    assert gw.approve(key, actor_ctx=BOB).reason_code == "applied"
    assert [tag for tag, _ in plant.param_writes] == [TI, KP]
    gw.tick(NOW + 61 * S)
    key = queued(gw, it(KP, 2.0, 3.0), it(TI, 120.0, 150.0), pid="p2")  # gain down, Ti shorter
    gw.approve(key, actor_ctx=BOB)
    assert [tag for tag, _ in plant.param_writes][2:] == [KP, TI]


def test_success_audits_param_write_with_strings() -> None:
    gw, _ = make()
    key = queued(gw, it(KP, 3.0))
    gw.approve(key, actor_ctx=BOB)
    record = events(gw, "param_write")[0]
    assert record["applied_from"] == "2.0" and record["applied_to"] == "3.0"
    assert record["tag"] == KP and record["actor"] == "bob" and record["key"] == key
    assert gw.pending_params() == []


@pytest.mark.parametrize("fault", ["refuse", "stuck"])
def test_partial_revert_on_refused_write_or_readback_mismatch(fault: str) -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 1.5), it(TI, 150.0))  # order: KP (down) then TI (longer)
    (plant.refuse_tags if fault == "refuse" else plant.stuck_tags).add(TI)
    decision = gw.approve(key, actor_ctx=BOB)
    assert not decision.accepted
    assert decision.reason_code == ("write_refused" if fault == "refuse" else "readback_mismatch")
    assert plant.params[KP] == 2.0  # restored
    assert plant.param_writes[0] == (KP, 1.5) and (KP, 2.0) in plant.param_writes
    revert = events(gw, "partial_revert")[0]
    assert KP in revert["written"] and revert["revert_failed"] == ""
    assert gw.status()[TI] == "stopped:readback" and gw.status()[KP] == "enabled"
    assert events(gw, "alarm_check_dcs") == []


def test_first_write_refused_writes_nothing_back() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 1.5))
    plant.refuse_tags.add(KP)
    assert gw.approve(key, actor_ctx=BOB).reason_code == "write_refused"
    assert events(gw, "partial_revert") == [] and gw.status()[KP] == "stopped:readback"


def test_revert_failure_stops_comm_and_raises_alarm() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 1.5), it(TI, 150.0))
    plant.refuse_tags.add(TI)
    plant.refuse_values.add((KP, 2.0))
    decision = gw.approve(key, actor_ctx=BOB)
    assert decision.reason_code == "revert_failed"
    assert gw.status()[KP] == "stopped:comm" and gw.status()[TI] == "stopped:readback"
    assert events(gw, "alarm_check_dcs")[0]["tag"] == KP


def test_comm_error_during_write_reverts_and_fails_closed() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 1.5), it(TI, 150.0))
    plant.raise_once_on = TI
    decision = gw.approve(key, actor_ctx=BOB)
    assert decision.reason_code == "comm_loss"
    assert plant.params[KP] == 2.0 and gw.status()[TI] == "stopped:comm"


def test_comm_error_everywhere_never_escapes() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0))
    plant.down = True
    assert gw.approve(key, actor_ctx=BOB).reason_code == "comm_loss"
    assert gw.status()[KP] == "stopped:comm"
    assert events(gw, "comm_loss")
    gw.tick(NOW + 5 * S)  # still must not raise


def test_comm_error_in_dry_run_fails_closed() -> None:
    gw, plant = make("dry_run")
    plant.down = True
    decision = gw.propose_params(pset(it(KP, 3.0)), actor_ctx=ALICE)
    assert decision.reason_code == "comm_loss" and gw.status()[KP] == "stopped:comm"


def test_dry_run_checks_live_values_but_writes_nothing() -> None:
    gw, plant = make("dry_run")
    plant.params[KP] = 2.5
    bad = gw.propose_params(pset(it(KP, 3.0), pid="a"), actor_ctx=ALICE)
    assert bad.reason_code == "from_mismatch"
    good = gw.propose_params(pset(it(KP, 3.0, 2.5), pid="b"), actor_ctx=ALICE)
    assert good.reason_code == "dry_run" and plant.param_writes == []


# ---------------------------------------------------------------- external change


def test_external_change_goes_hold_off_without_release_or_heartbeat() -> None:
    gw, plant = make()
    gw.approve(queued(gw, it(KP, 3.0)), actor_ctx=BOB)
    gw.tick(NOW + S)
    assert gw.status()[KP] == "enabled"
    plant.params[KP] = 2.5  # operator retunes at the DCS
    gw.tick(NOW + 2 * S)
    gw.tick(NOW + 3 * S)
    assert gw.status()[KP] == "hold_off"
    changed = events(gw, "param_changed_externally")
    assert len(changed) == 1 and changed[0]["value"] == "2.5" and changed[0]["review"] == "invalid"
    assert plant.releases == [] and plant.heartbeats == 0
    assert plant.params[KP] == 2.5  # no write-back
    gw.re_enable(KP)
    assert gw.status()[KP] == "enabled"


def test_target_in_hold_off_refuses_new_sets() -> None:
    gw, plant = make()
    gw.approve(queued(gw, it(KP, 3.0)), actor_ctx=BOB)
    plant.params[KP] = 2.5
    gw.tick(NOW + 2 * S)
    refused = gw.propose_params(pset(it(KP, 2.6, 2.5), pid="p2"), actor_ctx=ALICE)
    assert refused.reason_code == "target_hold_off"


def test_queued_set_is_flushed_when_its_target_leaves_enabled() -> None:
    gw, plant = make()
    gw.approve(queued(gw, it(TI, 150.0)), actor_ctx=BOB)
    gw.tick(NOW + 61 * S)
    second = pset(it(TI, 200.0, 150.0), pid="p2", t_ns=NOW + 61 * S, expires_ns=NOW + HOUR)
    assert gw.propose_params(second, actor_ctx=ALICE).reason_code == "queued"
    plant.params[TI] = 160.0  # retuned at the DCS
    gw.tick(NOW + 62 * S)
    assert gw.status()[TI] == "hold_off" and gw.pending_params() == []
    assert gw.propose_params(second, actor_ctx=ALICE).reason_code == "flushed"


# ---------------------------------------------------------------- stale rules


def test_expiry_at_propose_and_at_approve() -> None:
    gw, plant = make()
    past = pset(it(KP, 3.0), pid="old", expires_ns=NOW - S)
    assert gw.propose_params(past, actor_ctx=ALICE).reason_code == "expired"
    key = queued(gw, it(KP, 3.0), expires_ns=NOW + 100 * S)
    gw.tick(NOW + 200 * S)
    assert gw.approve(key, actor_ctx=BOB).reason_code == "expired"
    assert plant.param_writes == [] and gw.pending_params() == []


def test_expiry_longer_than_twelve_hours_refused() -> None:
    gw, _ = make()
    long = pset(it(KP, 3.0), expires_ns=NOW + 13 * HOUR)
    assert gw.propose_params(long, actor_ctx=ALICE).reason_code == "expiry_too_long"


def test_id_conflict_and_idempotent_replay() -> None:
    gw, _ = make()
    first = pset(it(KP, 3.0))
    decision = gw.propose_params(first, actor_ctx=ALICE)
    assert gw.propose_params(first, actor_ctx=ALICE) == decision
    assert len(gw.pending_params()) == 1 and len(events(gw, "param_duplicate")) == 1
    clash = gw.propose_params(pset(it(KP, 2.5)), actor_ctx=ALICE)
    assert clash.reason_code == "id_conflict"
    assert len(gw.pending_params()) == 1 and gw.pending_params()[0].proposal == first


def test_key_ignores_reason_but_not_items() -> None:
    base = pset(it(KP, 3.0))
    assert param_set_key(base) == param_set_key(pset(it(KP, 3.0), expires_ns=NOW + 5))
    assert param_set_key(base) != param_set_key(pset(it(KP, 3.1)))
    assert param_set_key(base) != param_set_key(pset(it(KP, 3.0), proposer="bob"))


def test_one_pending_set_per_loop() -> None:
    gw, _ = make()
    queued(gw, it(KP, 3.0))
    busy = gw.propose_params(pset(it(TI, 150.0), pid="p2"), actor_ctx=ALICE)
    assert busy.reason_code == "loop_busy"


def test_min_interval_between_applies() -> None:
    gw, _ = make()
    gw.approve(queued(gw, it(KP, 3.0)), actor_ctx=BOB)
    soon = pset(it(KP, 2.5, 3.0), pid="p2")
    assert gw.propose_params(soon, actor_ctx=ALICE).reason_code == "min_interval"
    gw.tick(NOW + 61 * S)
    later = pset(it(KP, 2.5, 3.0), pid="p3", t_ns=NOW + 61 * S, expires_ns=NOW + HOUR)
    assert gw.propose_params(later, actor_ctx=ALICE).reason_code == "queued"


def test_verified_rollback_is_exempt_from_min_interval() -> None:
    # In plain words:
    # When a bad tuning change is applied, the operator must be able to revert to the safe baseline
    # immediately, without waiting for the normal 60 s inter-apply cooling period.
    gw, plant = make()
    key1 = queued(gw, it(KP, 3.5), pid="p1")
    gw.approve(key1, actor_ctx=BOB)
    assert plant.params[KP] == 3.5

    # Propose rollback immediately at 5 s (min_interval is 60 s).
    rb = pset(it(KP, 2.0, frm=3.5), pid="p2", t_ns=NOW + 5 * S, rollback_of="p1")
    decision = gw.propose_params(rb, actor_ctx=ALICE)
    assert decision.reason_code == "queued"
    key2 = param_set_key(rb)
    assert gw.approve(key2, actor_ctx=BOB).reason_code == "applied"
    assert plant.params[KP] == 2.0


def test_verified_rollback_is_exempt_from_max_ratio() -> None:
    # In plain words:
    # If restoring the baseline requires a ratio greater than max_ratio, the rollback is still
    # allowed because the baseline was already audited and verified as safe by the plant.
    plant = ParamPlant()
    strict_policy = {
        KP: ParamPolicy(
            loop="L1", param="gain", unit="1", vendor_form="siemens_pid",
            limits=(0.1, 10.0), max_ratio=1.4, readback_tolerance=0.001, min_interval_s=60.0,
            allowed_loop_modes=("AUTO", "MAN"),
        )
    }
    gw = engine.WriteGateway(plant, {TAG: POLICY}, "confirm", params=ParamConfig(strict_policy))
    gw.tick(NOW)

    # p1 changes 2.0 -> 2.6 (ratio 1.3 < 1.4: ok)
    key1 = queued(gw, it(KP, 2.6), pid="p1")
    gw.approve(key1, actor_ctx=BOB)
    gw.tick(NOW + 100 * S)

    # A non-rollback proposal from 2.6 -> 1.0 has ratio 2.6 > 1.4: refused ratio_exceeded
    normal = pset(it(KP, 1.0, frm=2.6), pid="p_norm", t_ns=NOW + 100 * S)
    assert gw.propose_params(normal, actor_ctx=ALICE).reason_code == "ratio_exceeded"

    # A verified rollback restoring 1.0 has exemption
    gw.remember_applied_params("p_prev", {KP: 1.0})
    rb = pset(it(KP, 1.0, frm=2.6), pid="p_rb", t_ns=NOW + 100 * S, rollback_of="p_prev")
    decision = gw.propose_params(rb, actor_ctx=ALICE)
    assert decision.reason_code == "queued"


def test_unverified_rollback_does_not_get_exemption() -> None:
    # In plain words:
    # A proposal claiming to be a rollback for an unknown ID or with fabricated values does not
    # get exemptions from min_interval or max_ratio.
    gw, _ = make()
    gw.approve(queued(gw, it(KP, 3.0)), actor_ctx=BOB)
    fake_rb = pset(it(KP, 2.0, frm=3.0), pid="p_fake", t_ns=NOW + 5 * S, rollback_of="unknown_id")
    assert gw.propose_params(fake_rb, actor_ctx=ALICE).reason_code == "min_interval"


def test_kill_drops_pending_sets() -> None:
    gw, plant = make()
    key = queued(gw, it(KP, 3.0))
    gw.kill(actor_ctx=BOB)
    assert gw.pending_params() == [] and gw.status()[KP] == "killed"
    with pytest.raises(KeyError):
        gw.approve(key, actor_ctx=BOB)
    refused = gw.propose_params(pset(it(KP, 3.0), pid="p2"), actor_ctx=ALICE)
    assert refused.reason_code == "killed"
    gw.tick(NOW + S)
    assert plant.param_writes == []
    gw.reset_kill()
    assert gw.status()[KP] == "stopped:kill"
    gw.re_enable(KP)
    assert gw.status()[KP] == "enabled"


def test_reject_drops_set() -> None:
    gw, _ = make()
    key = queued(gw, it(KP, 3.0))
    gw.reject(key, actor_ctx=BOB)
    assert gw.pending_params() == [] and events(gw, "param_rejected")
    with pytest.raises(KeyError):
        gw.reject(key)


# ---------------------------------------------------------------- wiring


def test_status_is_additive_and_pending_kind_for_setpoints() -> None:
    gw, _ = make("confirm")
    assert set(gw.status()) == {TAG, KP, TI, TD}
    assert gw.status()[TAG] == "enabled"
    gw.propose(WriteProposal(TAG, 55.0, "alice", NOW, "t"), actor_ctx=ALICE)
    key = gw.pending()[0]
    assert gw.pending_kind("nope") is None
    assert len(gw.pending()) == 1 and key.target_tag == TAG


def test_tag_cannot_be_both_kinds() -> None:
    plant = ParamPlant()
    clash = {TAG: _policy("gain", "1", (0.1, 10.0), 0.001)}
    with pytest.raises(ValueError, match="both"):
        engine.WriteGateway(plant, {TAG: POLICY}, "confirm", params=ParamConfig(clash))  # type: ignore[arg-type]


def test_no_param_control_system_fails_loudly_at_construction() -> None:
    """Parameter targets without a plant that can handle them are refused, not ignored."""
    assert not isinstance(SimPlant(), ParamControlSystem)
    with pytest.raises(ValueError, match="need a plant that reads and writes parameters"):
        engine.WriteGateway(
            SimPlant(), {TAG: POLICY}, "confirm", params=ParamConfig(dict(PARAMS))  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("actor", [None, ActorContext(actor=""), ActorContext(actor="  \t ")])
@pytest.mark.parametrize("mode", ["advisory", "dry_run", "confirm"])
def test_proposal_without_proposer_is_refused(mode: str, actor: ActorContext | None) -> None:
    gw, _ = make(mode)
    decision = gw.propose_params(pset(it(KP, 3.0)), actor_ctx=actor)
    assert not decision.accepted and decision.reason_code == "proposer_required"
    assert gw.pending_params() == []
    assert events(gw, "param_decision")[-1]["reason_code"] == "proposer_required"

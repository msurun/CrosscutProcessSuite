"""Rollback exemption of min_interval / max_ratio (ADR 014 section 6), driven by REAL applies.

The exemption comes only from the gateway's own ledger (values it read and audited), never from
proposal data: every test applies a set through propose/approve and then proposes the rollback.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from crosscut_gateway import engine, engine_params
from crosscut_gateway.audit import AuditLog
from crosscut_gateway.engine_params import ParamConfig, param_set_key
from crosscut_gateway.engine_params_apply import LiveCheck
from crosscut_gateway.interfaces import ParamItem
from test_engine_params import (
    ALICE,
    BOB,
    KP,
    NOW,
    PARAMS,
    TI,
    ParamPlant,
    S,
    events,
    it,
    make,
    pset,
)
from test_gateway_scenarios import POLICY, TAG


def apply(gw: engine.WriteGateway, items: list[ParamItem], pid: str, at: int, **kw: str) -> str:
    """Propose at ``at`` seconds after NOW, approve, return the approve reason code."""
    gw.tick(NOW + at * S)
    proposal = pset(*items, pid=pid, t_ns=NOW + at * S, **kw)
    decision = gw.propose_params(proposal, actor_ctx=ALICE)
    if decision.reason_code != "queued":
        return decision.reason_code
    return gw.approve(param_set_key(proposal), actor_ctx=BOB).reason_code


def rollback(gw: engine.WriteGateway, items: list[ParamItem], pid: str, at: int, of: str) -> str:
    """Propose and approve a rollback of ``of`` at ``at`` seconds; the final reason code."""
    return apply(gw, items, pid, at, rollback_of=of)


def test_rollback_skips_min_interval_after_real_apply() -> None:
    gw, plant = make()
    assert apply(gw, [it(KP, 3.5)], "p1", 0) == "applied"
    assert rollback(gw, [it(KP, 2.0, frm=3.5)], "p2", 5, "p1") == "applied"
    assert plant.params[KP] == 2.0


def test_rollback_of_rollback_gets_no_exemption() -> None:
    gw, _ = make()
    apply(gw, [it(KP, 3.5)], "p1", 0)
    assert rollback(gw, [it(KP, 2.0, frm=3.5)], "p2", 5, "p1") == "applied"
    assert rollback(gw, [it(KP, 3.5, frm=2.0)], "p3", 10, "p2") == "min_interval"


def test_second_rollback_of_same_set_is_refused() -> None:
    gw, _ = make()
    apply(gw, [it(KP, 3.5)], "p1", 0)
    rollback(gw, [it(KP, 2.0, frm=3.5)], "p2", 5, "p1")
    assert rollback(gw, [it(KP, 2.0, frm=2.0)], "p3", 10, "p1") == "min_interval"
    check = gw._params.rollback_refusal(pset(it(KP, 2.0, frm=3.5), rollback_of="p1"))
    assert check == "already_rolled_back"


def test_not_latest_apply_gets_no_exemption() -> None:
    gw, _ = make()
    apply(gw, [it(KP, 3.5)], "p1", 0)
    assert apply(gw, [it(TI, 150.0)], "p2", 100) == "applied"
    assert rollback(gw, [it(KP, 2.0, frm=3.5)], "p3", 105, "p1") == "min_interval"
    check = gw._params.rollback_refusal(pset(it(KP, 2.0, frm=3.5), rollback_of="p1"))
    assert check == "not_latest_apply"


def test_wrong_to_value_gets_no_exemption() -> None:
    gw, _ = make()
    apply(gw, [it(KP, 3.5)], "p1", 0)
    assert rollback(gw, [it(KP, 2.2, frm=3.5)], "p2", 5, "p1") == "min_interval"


def test_wrong_from_value_gets_no_exemption() -> None:
    gw, _ = make()
    apply(gw, [it(KP, 3.5)], "p1", 0)
    assert rollback(gw, [it(KP, 2.0, frm=3.4)], "p2", 5, "p1") == "min_interval"


def test_unknown_original_gets_no_exemption() -> None:
    gw, _ = make()
    apply(gw, [it(KP, 3.0)], "p1", 0)
    assert rollback(gw, [it(KP, 2.0, frm=3.0)], "px", 5, "unknown") == "min_interval"


def test_duplicate_or_missing_targets_get_no_exemption() -> None:
    gw, _ = make()
    assert apply(gw, [it(KP, 3.5), it(TI, 150.0)], "p1", 0) == "applied"
    dup = pset(it(KP, 2.0, frm=3.5), it(KP, 2.0, frm=3.5), rollback_of="p1")
    assert gw._params.rollback_refusal(dup) == "targets_mismatch"
    partial = pset(it(KP, 2.0, frm=3.5), rollback_of="p1")
    assert gw._params.rollback_refusal(partial) == "targets_mismatch"
    full = pset(it(KP, 2.0, frm=3.5), it(TI, 100.0, frm=150.0), rollback_of="p1")
    assert gw._params.rollback_refusal(full) is None


def test_ratio_exemption_only_for_verified_rollback() -> None:
    gw, _ = make()
    apply(gw, [it(KP, 3.5)], "p1", 0)  # ratio 1.75 passes max_ratio 2.0
    gw._params.swap_policies({**PARAMS, KP: replace(PARAMS[KP], max_ratio=1.2)})
    plain = pset(it(KP, 2.0, frm=3.5), pid="p_plain", t_ns=NOW + 100 * S)
    gw.tick(NOW + 100 * S)
    assert gw.propose_params(plain, actor_ctx=ALICE).reason_code == "ratio_exceeded"
    assert rollback(gw, [it(KP, 2.0, frm=3.5)], "p2", 101, "p1") == "applied"


def test_limits_still_apply_to_a_verified_rollback() -> None:
    gw, _ = make()
    apply(gw, [it(KP, 3.5)], "p1", 0)
    gw._params.swap_policies({**PARAMS, KP: replace(PARAMS[KP], limits=(2.5, 10.0))})
    assert rollback(gw, [it(KP, 2.0, frm=3.5)], "p2", 5, "p1") == "out_of_limits"


def test_replay_after_restart_valid_exactly_once(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    gw = _gateway(ParamPlant(), AuditLog(path))
    apply(gw, [it(KP, 3.5)], "p1", 0)
    restarted = _gateway(ParamPlant(), AuditLog(path))
    rb = pset(it(KP, 2.0, frm=3.5), pid="p2", rollback_of="p1")
    assert restarted._params.rollback_refusal(rb) is None
    restarted._plant.params[KP] = 3.5  # type: ignore[attr-defined]
    assert rollback(restarted, [it(KP, 2.0, frm=3.5)], "p2", 5, "p1") == "applied"
    again = _gateway(ParamPlant(), AuditLog(path))
    assert again._params.rollback_refusal(rb) == "already_rolled_back"
    third = pset(it(KP, 3.5, frm=2.0), pid="p3", rollback_of="p2")
    assert again._params.rollback_refusal(third) == "rollback_of_rollback"


def test_unread_from_value_is_refused_not_assumed(monkeypatch: pytest.MonkeyPatch) -> None:
    gw, plant = make()
    monkeypatch.setattr(engine_params, "live_check", lambda *a, **k: LiveCheck())
    assert apply(gw, [it(KP, 3.5)], "p1", 0) == "from_unread"
    assert plant.param_writes == [] and events(gw, "param_write") == []


def test_baseline_is_not_remembered_when_the_audit_write_fails() -> None:
    class FailingAudit(AuditLog):
        def append(self, event, fields, t_ns):  # type: ignore[no-untyped-def]
            if event == "param_write":
                raise OSError("disk full")
            return super().append(event, fields, t_ns)

    gw = _gateway(ParamPlant(), FailingAudit())
    assert apply(gw, [it(KP, 3.5)], "p1", 0) == "applied_unaudited"
    rb = pset(it(KP, 2.0, frm=3.5), pid="p2", rollback_of="p1")
    assert gw._params.rollback_refusal(rb) == "no_baseline"
    assert rollback(gw, [it(KP, 2.0, frm=3.5)], "p2", 5, "p1") != "applied"


def _gateway(plant: ParamPlant, audit: AuditLog) -> engine.WriteGateway:
    """A confirm-mode gateway on ``plant`` with the given audit log, clock started."""
    gw = engine.WriteGateway(
        plant, {TAG: POLICY}, "confirm", params=ParamConfig(dict(PARAMS)), audit=audit  # type: ignore[arg-type]
    )
    gw.tick(NOW)
    return gw

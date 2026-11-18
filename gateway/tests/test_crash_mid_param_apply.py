"""Crash recovery and durable write-intent tests for PID parameter writes (ADR 014 addendum).

Validates atomic write-intent persistence, crash tolerance mid-apply across all write stages,
process kill recovery in subprocesses, open-intent blocking, and intent resolution.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from crosscut_gateway import engine
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.engine_params import ParamConfig, param_set_key
from crosscut_gateway.interfaces import (
    ParamControlSystem,
    ParamItem,
    ParamPolicy,
    ParamSetProposal,
    WriteProposal,
)
from crosscut_gateway.param_intent_store import ParamIntentStore
from test_gateway_scenarios import POLICY, S, SimPlant

KP, TI, TD = "FIC101.KP", "FIC101.TI", "FIC101.TD"
KP2, TI2 = "FIC102.KP", "FIC102.TI"
SP_TAG = "FIC101.SP"
NOW = 10_000 * S
HOUR = 3600 * S
ALICE = ActorContext(actor="alice", roles=("engineer",))
BOB = ActorContext(actor="bob", roles=("engineer",))

_KILL_SCRIPT = (
    "import os, sys\n"
    "from pathlib import Path\n"
    "from crosscut_gateway import engine\n"
    "from crosscut_gateway.actor import ActorContext\n"
    "from crosscut_gateway.engine_params import ParamConfig, param_set_key\n"
    "from crosscut_gateway.interfaces import ParamItem, ParamPolicy, ParamSetProposal\n"
    "from crosscut_gateway.param_intent_store import ParamIntentStore\n"
    "from test_gateway_scenarios import POLICY, SimPlant\n"
    "class KillPlant(SimPlant):\n"
    "    def __init__(self):\n"
    "        super().__init__()\n"
    "        self.params = {'FIC101.KP': 2.0}\n"
    "    def read_param(self, tag): return self.params[tag]\n"
    "    def write_param(self, tag, val): os._exit(99)\n"
    "    def loop_mode(self, tag): return 'AUTO'\n"
    "p = KillPlant()\n"
    "pol = ParamPolicy(\n"
    "    'L1', 'gain', '1', 'siemens_pid', (0.1, 10.0), 2.0, 0.001, 60.0, ('AUTO', 'MAN')\n"
    ")\n"
    "st = Path(sys.argv[1])\n"
    "cfg = ParamConfig({'FIC101.KP': pol})\n"
    "sp_map = {'FIC101.SP': POLICY}\n"
    "gw = engine.WriteGateway(p, sp_map, 'confirm', params=cfg, intent_store=st)\n"
    "gw.tick(10000000000000)\n"
    "item = ParamItem('gain', 'FIC101.KP', '1', 'siemens_pid', 2.0, 3.0)\n"
    "prop = ParamSetProposal(\n"
    "    'p1', 'L1', (item,), 'alice', 10000000000000, 13600000000000, 'tune'\n"
    ")\n"
    "ctx_a = ActorContext(actor='alice', roles=('engineer',))\n"
    "ctx_b = ActorContext(actor='bob', roles=('engineer',))\n"
    "gw.propose_params(prop, actor_ctx=ctx_a)\n"
    "gw.approve(param_set_key(prop), actor_ctx=ctx_b)\n"
)


class SimulatedCrash(BaseException):
    """Simulated process crash or uncatchable signal (BaseException subclass)."""


def _policy(
    param: str, limits: tuple[float, float], tol: float, loop: str = "L1"
) -> ParamPolicy:
    """Build a parameter policy for testing."""
    unit = "s" if param in ("ti", "td") else "1"
    return ParamPolicy(
        loop=loop, param=param, unit=unit, vendor_form="siemens_pid", limits=limits,
        max_ratio=2.0, readback_tolerance=tol, min_interval_s=60.0,
        allowed_loop_modes=("AUTO", "MAN"),
    )


PARAMS = {
    KP: _policy("gain", (0.1, 10.0), 0.001, "L1"),
    TI: _policy("ti", (5.0, 600.0), 0.01, "L1"),
    TD: _policy("td", (0.0, 60.0), 0.01, "L1"),
    KP2: _policy("gain", (0.1, 10.0), 0.001, "L2"),
    TI2: _policy("ti", (5.0, 600.0), 0.01, "L2"),
}


class CrashPlant(SimPlant, ParamControlSystem):
    """SimPlant plus PID parameters and configurable crash injection hooks."""

    def __init__(self, crash_after_writes: int | None = None) -> None:
        """Start plant with default parameter values and crash point."""
        super().__init__()
        self.params: dict[str, float] = {KP: 2.0, TI: 100.0, TD: 0.0, KP2: 1.0, TI2: 50.0}
        self.param_writes: list[tuple[str, float]] = []
        self.crash_after_writes = crash_after_writes
        self.read_fails = False

    def read_param(self, tag: str) -> float:
        """Read a parameter value, raising on simulated transport failure."""
        if self.read_fails:
            raise ConnectionError("link down")
        return self.params[tag]

    def write_param(self, tag: str, value: float) -> bool:
        """Write a parameter value; raises SimulatedCrash after configured write count."""
        if self.crash_after_writes == 0:
            raise SimulatedCrash("crash after 0 writes")
        self.param_writes.append((tag, value))
        self.params[tag] = value
        if self.crash_after_writes == len(self.param_writes):
            raise SimulatedCrash(f"crash after {self.crash_after_writes} writes")
        return True

    def loop_mode(self, tag: str) -> str:
        """Return loop mode for tag: AUTO for parameters, super() (CAS) for setpoint."""
        if tag in self.params:
            return "AUTO"
        return super().loop_mode(tag)


def it(target: str, to: float, frm: float | None = None, loop: str = "L1") -> ParamItem:
    """Create a test parameter item."""
    param = {"KP": "gain", "TI": "ti", "TD": "td"}[target.split(".")[1]]
    default_from = 2.0 if "KP" in target else (100.0 if "TI" in target else 0.0)
    return ParamItem(
        param=param, target=target, unit=PARAMS[target].unit, vendor_form="siemens_pid",
        from_value=default_from if frm is None else frm, to_value=to,
    )


def pset(*items: ParamItem, **kw: Any) -> ParamSetProposal:
    """Create a parameter set proposal."""
    return ParamSetProposal(
        proposal_id=kw.get("pid", "p1"), loop_id=kw.get("loop", "L1"), items=tuple(items),
        proposer=kw.get("proposer", "alice"), t_ns=kw.get("t_ns", NOW),
        expires_ns=kw.get("expires_ns", NOW + 8 * HOUR), reason="tune",
        rollback_of=kw.get("rollback_of"),
    )


def make_gateway(
    storage: Path, plant: CrashPlant, mode: str = "confirm"
) -> engine.WriteGateway:
    """Build a WriteGateway backed by durable storage at *storage*."""
    sp_policy = {SP_TAG: POLICY}
    params_config = ParamConfig(dict(PARAMS), plant, intent_store=ParamIntentStore(storage))
    gw = engine.WriteGateway(plant, sp_policy, mode, params=params_config, intent_store=storage)  # type: ignore[arg-type]
    gw.tick(NOW)
    return gw


def _assert_crashed_engine_state(
    gw: engine.WriteGateway, loop_id: str = "L1", other_loop: str = "L2"
) -> None:
    """Assert all invariants of a gateway started over storage with an open intent."""
    assert gw.has_open_intent(loop_id) is True
    assert len(gw.open_intents()) >= 1
    events = [r for r in gw.audit_records() if r["event"] == "intent_open_at_start"]
    assert any(r.get("loop") == loop_id for r in events)
    blocked_proposal = pset(it(KP, 2.5), loop=loop_id, pid="reconcile_check")
    blocked_decision = gw.propose_params(blocked_proposal, actor_ctx=ALICE)
    assert blocked_decision.accepted is False
    assert blocked_decision.reason_code == "reconcile_required"
    other_proposal = pset(it(KP2, 1.5, loop=other_loop), loop=other_loop, pid="other_check")
    other_decision = gw.propose_params(other_proposal, actor_ctx=ALICE)
    assert other_decision.reason_code == "queued"
    sp_prop = WriteProposal(SP_TAG, 55.0, "alice", NOW, "test_setpoint")
    sp_decision = gw.propose(sp_prop, actor_ctx=ALICE)
    assert sp_decision.accepted is True


@pytest.mark.parametrize("k", [0, 1, 2, 3])
def test_in_process_crash_after_k_writes_leaves_open_intent_blocking_loop(
    tmp_path: Path, k: int
) -> None:
    """Crashing mid-apply after k writes leaves open intent blocking parameter loop."""
    plant1 = CrashPlant(crash_after_writes=k)
    gw1 = make_gateway(tmp_path, plant1)
    proposal = pset(it(KP, 3.0), it(TI, 120.0), it(TD, 0.0))
    key = param_set_key(proposal)
    gw1.propose_params(proposal, actor_ctx=ALICE)
    with pytest.raises(SimulatedCrash):
        gw1.approve(key, actor_ctx=BOB)
    plant2 = CrashPlant()
    gw2 = make_gateway(tmp_path, plant2)
    _assert_crashed_engine_state(gw2, "L1", "L2")


def test_in_process_crash_after_last_write_before_audit_blocks_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crashing after all writes but before audit keeps the write intent open."""
    plant1 = CrashPlant()
    gw1 = make_gateway(tmp_path, plant1)
    proposal = pset(it(KP, 3.0), it(TI, 120.0), it(TD, 0.0))
    key = param_set_key(proposal)
    gw1.propose_params(proposal, actor_ctx=ALICE)

    def crash_audit(record: dict[str, str]) -> None:
        if record.get("event") == "param_write":
            raise SimulatedCrash("crash before audit completes")

    monkeypatch.setattr(gw1._audit, "_write_record", crash_audit)
    with pytest.raises(SimulatedCrash):
        gw1.approve(key, actor_ctx=BOB)
    plant2 = CrashPlant()
    gw2 = make_gateway(tmp_path, plant2)
    _assert_crashed_engine_state(gw2, "L1", "L2")


def _run_kill_subprocess(tmp_path: Path) -> int:
    """Run apply in a child process that crashes via os._exit and return exit code."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    cmd = [sys.executable, "-c", _KILL_SCRIPT, str(tmp_path)]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    return proc.returncode


def test_real_kill_subprocess_leaves_open_intent_blocking_loop(tmp_path: Path) -> None:
    """A killed subprocess executing apply leaves an open intent that blocks the loop."""
    code = _run_kill_subprocess(tmp_path)
    assert code == 99
    plant2 = CrashPlant()
    gw2 = make_gateway(tmp_path, plant2)
    _assert_crashed_engine_state(gw2, "L1", "L2")


def test_resolve_intent_reads_plant_and_closes_intent_without_writes(tmp_path: Path) -> None:
    """Resolving an open intent audits read values, closes it, and writes nothing."""
    plant1 = CrashPlant(crash_after_writes=1)
    gw1 = make_gateway(tmp_path, plant1)
    proposal = pset(it(KP, 3.0))
    key = param_set_key(proposal)
    gw1.propose_params(proposal, actor_ctx=ALICE)
    with pytest.raises(SimulatedCrash):
        gw1.approve(key, actor_ctx=BOB)
    plant2 = CrashPlant()
    gw2 = make_gateway(tmp_path, plant2)
    assert gw2.has_open_intent("L1") is True
    plant2.param_writes.clear()
    decision = gw2.resolve_intent(key, actor="charlie")
    assert decision.accepted is True and decision.reason_code == "resolved"
    assert gw2.has_open_intent("L1") is False
    assert plant2.param_writes == []
    resolved_events = [r for r in gw2.audit_records() if r["event"] == "intent_resolved"]
    assert len(resolved_events) == 1
    assert resolved_events[0]["actor"] == "charlie"


def test_resolve_intent_refuses_and_keeps_intent_open_on_read_failure(tmp_path: Path) -> None:
    """If reading from the plant fails during resolution, the intent stays open."""
    plant1 = CrashPlant(crash_after_writes=1)
    gw1 = make_gateway(tmp_path, plant1)
    proposal = pset(it(KP, 3.0))
    key = param_set_key(proposal)
    gw1.propose_params(proposal, actor_ctx=ALICE)
    with pytest.raises(SimulatedCrash):
        gw1.approve(key, actor_ctx=BOB)
    plant2 = CrashPlant()
    plant2.read_fails = True
    gw2 = make_gateway(tmp_path, plant2)
    decision = gw2.resolve_intent(key, actor="charlie")
    assert decision.accepted is False and decision.reason_code == "read_failed"
    assert gw2.has_open_intent("L1") is True


def test_intent_write_failure_refuses_with_zero_plant_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If writing the intent record fails, refuse without touching the plant."""
    plant = CrashPlant()
    gw = make_gateway(tmp_path, plant)
    proposal = pset(it(KP, 3.0))
    key = param_set_key(proposal)
    gw1_decision = gw.propose_params(proposal, actor_ctx=ALICE)
    assert gw1_decision.accepted is True

    def failing_record(record: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(gw._params._store, "record_intent", failing_record)
    decision = gw.approve(key, actor_ctx=BOB)
    assert decision.accepted is False and decision.reason_code == "intent_write_failed"
    assert plant.param_writes == []


def test_rollback_after_restart_refused_without_baseline(tmp_path: Path) -> None:
    """A rollback proposal after restart is refused fail closed without a baseline."""
    plant1 = CrashPlant(crash_after_writes=1)
    gw1 = make_gateway(tmp_path, plant1)
    proposal = pset(it(KP, 3.0), pid="p1")
    key = param_set_key(proposal)
    gw1.propose_params(proposal, actor_ctx=ALICE)
    with pytest.raises(SimulatedCrash):
        gw1.approve(key, actor_ctx=BOB)
    plant2 = CrashPlant()
    gw2 = make_gateway(tmp_path, plant2)
    rollback_prop = pset(it(KP, 2.0, 3.0), pid="p2", rollback_of="p1")
    decision = gw2.propose_params(rollback_prop, actor_ctx=ALICE)
    assert decision.accepted is False


def test_normal_apply_leaves_no_open_intent(tmp_path: Path) -> None:
    """A normal, successful apply closes its intent record on completion."""
    plant = CrashPlant()
    gw = make_gateway(tmp_path, plant)
    proposal = pset(it(KP, 3.0))
    key = param_set_key(proposal)
    gw.propose_params(proposal, actor_ctx=ALICE)
    decision = gw.approve(key, actor_ctx=BOB)
    assert decision.accepted is True and decision.reason_code == "applied"
    assert gw.has_open_intent("L1") is False
    assert gw.open_intents() == []


def test_policy_file_start_keeps_intents_on_disk(tmp_path: Path) -> None:
    """The production entry point never falls back to a memory-only intent store."""
    from test_engine_hardening import write_signed_policy

    path = write_signed_policy(tmp_path / "write-policy.json", "dry_run")
    gw = engine.start_from_policy_file(
        path, CrashPlant(), "supervised", allow_legacy_sidecar=True
    )
    assert gw._params._store._path == tmp_path / "param-intents.json"


@pytest.mark.parametrize("content", [b"{broken", b"{}", b'{"intents": {"k": {"key": "k"}}}'])
def test_damaged_intent_file_blocks_every_loop_and_refuses_resolve(
    tmp_path: Path, content: bytes
) -> None:
    """A damaged intent file may hide an open intent, so parameter writes stay blocked."""
    (tmp_path / "param-intents.json").write_bytes(content)
    gw = make_gateway(tmp_path, CrashPlant())
    events = [r["event"] for r in gw.audit_records()]
    assert "intent_store_unreadable" in events
    decision = gw.propose_params(pset(it(KP, 2.5)), actor_ctx=ALICE)
    assert decision.reason_code == "reconcile_required"
    assert gw.resolve_intent("k", "alice", actor_ctx=ALICE).reason_code == "intent_store_unreadable"


def test_resolve_intent_close_failure_audits_intent_close_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When close_intent fails after resolve, audit intent_close_failed and keep intent open."""
    plant1 = CrashPlant(crash_after_writes=1)
    gw1 = make_gateway(tmp_path, plant1)
    proposal = pset(it(KP, 3.0))
    key = param_set_key(proposal)
    gw1.propose_params(proposal, actor_ctx=ALICE)
    with pytest.raises(SimulatedCrash):
        gw1.approve(key, actor_ctx=BOB)

    gw2 = make_gateway(tmp_path, CrashPlant())

    def failing_close(intent_key: str) -> None:
        raise OSError("disk write error")

    monkeypatch.setattr(gw2._params._store, "close_intent", failing_close)
    decision = gw2.resolve_intent(key, actor="charlie")

    assert decision.accepted is False
    assert decision.reason_code == "intent_close_failed"
    events = [r["event"] for r in gw2.audit_records()]
    assert "intent_resolved" in events
    assert "intent_close_failed" in events
    failed_record = next(r for r in gw2.audit_records() if r["event"] == "intent_close_failed")
    assert failed_record["reason_code"] == "intent_close_failed"
    assert failed_record["actor"] == "charlie"
    assert gw2.has_open_intent("L1") is True

"""Exercise the fuzzy closed loop through confirm and supervised gateway modes.

Only live observations establish operator priority on the pinned hardness-shift hook.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from controller_rows import MOVE_MAX, NS, CtlRig, ctl_rig
from crosscut_gateway.policy import proposal_key
from gateway_rows import POLICY, TAG
from rs_harness import S

HOOK = "gw.hardness_shift_operator_override.v1"
CYCLES = 3  # controller cycles before approval and after mode transition
MAX_CYCLES = 150  # bounded wait for the 600 s simulation-time takeover
TAKEOVER_S = 600.0  # simulation seconds, hook contract
OPERATOR_SP = 200.0  # FIC203 local setpoint, flow engineering units
MOVE_TOLERANCE = 1e-9  # floating-point comparison in setpoint units


def _writes(controller: CtlRig) -> list[tuple[int, str, float]]:
    """Return accepted FIC203 remote-setpoint writes from the real adapter."""
    return [write for write in controller.rig.h.writes if write[1] == TAG]


def _confirm(controller: CtlRig) -> None:
    """Queue controller moves, then approve exactly one and verify its live read-back."""
    controller.command("switch_on")
    records = [controller.cycle() for _ in range(CYCLES)]
    assert all(record["state"] == "on" for record in records), records
    pending = controller.rig.gw.pending()
    assert len(pending) >= 2
    assert all(decision.reason_code == "queued" for decision in controller.decisions)
    assert _writes(controller) == []
    proposal = pending[-1]
    decision = controller.rig.gw.approve(proposal_key(proposal))
    assert decision.accepted, decision
    assert [value for _, _, value in _writes(controller)] == [proposal.value]
    controller.rig.step()
    assert controller.rig.h.read(TAG) == pytest.approx(
        proposal.value, abs=POLICY.readback_tolerance
    )
    assert len(controller.rig.gw.pending()) == len(pending) - 1


def _supervised(controller: CtlRig) -> None:
    """Switch from confirmed operation to automatic writes bounded by move and policy limits."""
    _confirm(controller)
    controller.rig.gw.set_mode("supervised")
    previous_writes = len(_writes(controller))
    previous_decisions = len(controller.decisions)
    records = [controller.cycle() for _ in range(CYCLES)]
    assert all(record["state"] == "on" for record in records), records
    assert len(_writes(controller)) > previous_writes
    assert all(decision.reason_code != "queued"
               for decision in controller.decisions[previous_decisions:])
    assert all(abs(new - seen) <= MOVE_MAX + MOVE_TOLERANCE
               for seen, new in controller.seen)
    assert all(POLICY.limits[0] <= value <= POLICY.limits[1]
               for _, _, value in _writes(controller))
    assert controller.rig.h.read(TAG) == pytest.approx(
        _writes(controller)[-1][2], abs=POLICY.readback_tolerance
    )


def p6_confirm(tmp: Path) -> None:
    """Confirm mode writes only the approved controller proposal."""
    with ctl_rig(tmp, hook=HOOK, mode="confirm") as controller:
        _confirm(controller)


def p6_supervised(tmp: Path) -> None:
    """After confirmation, supervised mode writes controller moves without approval."""
    with ctl_rig(tmp, hook=HOOK, mode="confirm") as controller:
        _supervised(controller)


def _reach_takeover(controller: CtlRig) -> dict[str, Any]:
    """Run bounded cycles until the live clock reaches takeover and the gateway holds off."""
    assert controller.rig.h.now_ns() < TAKEOVER_S * S, "takeover preceded controller start"
    for _ in range(MAX_CYCLES):
        record = controller.cycle()
        if controller.rig.clock_ns >= TAKEOVER_S * S:
            assert controller.rig.gw.status()[TAG] == "hold_off"
            return record
        assert record["state"] == "on", record
    pytest.fail(f"operator takeover at {TAKEOVER_S} sim s not reached in {MAX_CYCLES} cycles")


def _assert_operator_preserved(controller: CtlRig) -> None:
    """Read the operator's local mode and SP, distinct from the remote RSP register."""
    assert controller.rig.h.loop_mode(TAG) == "AUTO"
    address = NS.format("FIC203/Sp")
    snapshot = controller.connectors[-1].read_snapshot([address])
    assert snapshot.comm_ok
    assert float(snapshot.values[address].value) == pytest.approx(OPERATOR_SP)


def p6_operator_wins(tmp: Path) -> None:
    """Operator takeover sheds the controller and survives switch-on during hold-off."""
    with ctl_rig(tmp, hook=HOOK, mode="confirm") as controller:
        _supervised(controller)
        record = _reach_takeover(controller)
        assert (record["state"], record["reason"]) == ("shed", "mv_unavailable"), record
        assert any(entry["event"] == "operator_override"
                   for entry in controller.rig.gw.audit_records())
        # a write stamped at the takeover instant precedes it (same sim step); none may follow
        assert all(stamp <= TAKEOVER_S * S for stamp, _, _ in _writes(controller))
        previous_writes = _writes(controller)
        hold_started_ns = controller.rig.clock_ns
        _assert_operator_preserved(controller)
        controller.command("switch_on")
        records = [controller.cycle() for _ in range(CYCLES)]
        assert all(record["state"] != "on" for record in records), records
        assert controller.rig.h.now_ns() < hold_started_ns + POLICY.hold_off_s * S
        assert controller.rig.gw.status()[TAG] == "hold_off"
        assert _writes(controller) == previous_writes
        _assert_operator_preserved(controller)


P6_CASES = (p6_confirm, p6_supervised, p6_operator_wins)

"""Exercise tuning failures through the real gateway and RougherSim hook API 1.1.0.

Keep plant readbacks and audit evidence together so failures cannot pass on decisions alone.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from crosscut_gateway import engine
from crosscut_gateway.engine_params import ParamConfig, param_set_key
from crosscut_gateway.interfaces import ParamItem, ParamSetProposal, WriteDecision
from gateway_rows import ALICE, BOB, GAIN, LOOP, PARAM_POLICIES, POLICY, TAG, TI, Rig
from rs_harness import STEP_S, Harness, S, plant_map_for, rs_server

HOOK_DIRECTORY = Path(__file__).parent / "tuning_hooks"
HOOK_START_S = 300  # Simulation seconds; leave startup and baseline reads outside the fault.
HOOK_END_S = 600  # Simulation seconds; read stored values only after the offset expires.
SERVER_SPEED = 20.0  # Simulation seconds per wall second, as in the existing gateway rows.
READBACK_TOLERANCE = 0.05  # Gain units or Ti seconds; the plant map uses native Ti seconds.
TARGET_RATIO = 1.5  # Dimensionless; inside the policy's maximum ratio of 2.
PROPOSAL_LIFETIME_S = 3600  # Simulation seconds.


class UnsafeTuningRestoration(AssertionError):
    """Stored tuning differs from the pre-fault baseline after a partial revert."""


@contextmanager
def tuning_rig(tmp: Path, hook_name: str) -> Iterator[Rig]:
    """Yield a confirm-mode gateway using an absolute hook file path; always close it."""
    hook_path = str((HOOK_DIRECTORY / f"{hook_name}.json").resolve())
    with rs_server(tmp / "server.log", hook_path, SERVER_SPEED) as port:
        harness = Harness(plant_map_for(port), SERVER_SPEED)
        try:
            harness.wait_ready()
            policies = {
                tag: replace(policy, readback_tolerance=READBACK_TOLERANCE)
                for tag, policy in PARAM_POLICIES.items()
            }
            gateway = engine.WriteGateway(
                harness, {TAG: POLICY}, "confirm", params=ParamConfig(policies, harness)
            )
            yield Rig(harness, gateway, tmp)
        finally:
            harness.close()


def read_tuning(rig: Rig) -> dict[str, float]:
    """Read both stored parameters through the real adapter."""
    return {GAIN: rig.h.read_param(GAIN), TI: rig.h.read_param(TI)}


def read_baseline(rig: Rig) -> dict[str, float]:
    """Read the original tuning before the fault window, failing loudly on late startup."""
    baseline = read_tuning(rig)
    assert rig.h.now_ns() < HOOK_START_S * S, "startup missed baseline; increase hook start_s"
    return baseline


def wait_for_fault(rig: Rig) -> None:
    """Enter the hook window on a complete plant step while maintaining the heartbeat."""
    rig.h.wait_until_ns(int((HOOK_START_S + STEP_S) * S))
    assert rig.h.now_ns() < HOOK_END_S * S, "fault window expired before the proposal"


def approve_change(rig: Rig, targets: dict[str, float]) -> WriteDecision:
    """Propose live from-values as Alice, then approve the set as Bob."""
    now_ns = rig.h.now_ns()
    items = tuple(
        ParamItem(
            PARAM_POLICIES[tag].param, tag, PARAM_POLICIES[tag].unit,
            PARAM_POLICIES[tag].vendor_form, rig.h.read_param(tag), value,
        )
        for tag, value in targets.items()
    )
    proposal = ParamSetProposal(
        "tuning-failure", LOOP, items, ALICE.actor, now_ns,
        now_ns + PROPOSAL_LIFETIME_S * S, "L5 tuning failure",
    )
    rig.tick(now_ns)
    assert rig.gw.propose_params(proposal, actor_ctx=ALICE).reason_code == "queued"
    return rig.gw.approve(param_set_key(proposal), actor_ctx=BOB)


def audit_events(rig: Rig, event: str) -> list[dict[str, str]]:
    """Collect every matching audit record eagerly, including later failure evidence."""
    return [record for record in rig.gw.audit_records() if record["event"] == event]


def assert_loop_is_local(rig: Rig) -> None:
    """Confirm tuning did not acquire remote ownership of the cascade secondary."""
    # Parameter policy never takes or releases the loop: CAS must remain under DCS control.
    assert rig.h.loop_mode(TAG) == "CAS"
    assert rig.source() == "local"


def reject_gain_change(tmp: Path, hook_name: str) -> None:
    """TF1/TF2: a refused Gain write is audited, stopped and leaves the plant unchanged."""
    with tuning_rig(tmp, hook_name) as rig:
        baseline = read_baseline(rig)
        wait_for_fault(rig)
        decision = approve_change(rig, {GAIN: baseline[GAIN] * TARGET_RATIO})
        assert not decision.accepted
        assert decision.reason_code == "write_refused"
        rig.step(2)
        assert read_tuning(rig) == baseline
        assert rig.gw.status()[GAIN].startswith("stopped:")
        decisions = audit_events(rig, "param_decision")
        assert [record["reason_code"] for record in decisions] == ["write_refused"]
        assert decisions[0]["value"] == GAIN
        assert_loop_is_local(rig)


def reject_mismatched_gain(tmp: Path) -> None:
    """TF3: mismatched Gain must revert the whole set, including the earlier Ti write."""
    with tuning_rig(tmp, "tf3_gain_offset") as rig:
        baseline = read_baseline(rig)
        wait_for_fault(rig)
        # Longer Ti detunes first; higher Gain goes last, exercising a multi-item revert.
        targets = {GAIN: baseline[GAIN] * TARGET_RATIO, TI: baseline[TI] * TARGET_RATIO}
        decision = approve_change(rig, targets)
        assert not decision.accepted
        assert decision.reason_code == "revert_failed"
        reverts = audit_events(rig, "partial_revert")
        assert len(reverts) == 1
        assert reverts[0]["reason_code"] == "readback_mismatch"
        assert reverts[0]["written"] == f"{TI},{GAIN}"
        assert rig.gw.status()[GAIN].startswith("stopped:")
        assert_loop_is_local(rig)
        rig.h.wait_until_ns(int((HOOK_END_S + STEP_S) * S))
        assert_restored_tuning(rig, baseline)


def assert_restored_tuning(rig: Rig, baseline: dict[str, float]) -> None:
    """Raise the specific expected failure only for unsafe stored tuning after hook expiry."""
    actual = read_tuning(rig)
    if actual != baseline:
        raise UnsafeTuningRestoration(f"partial revert left {actual}; expected {baseline}")


def accept_tolerated_ti_offset(tmp: Path) -> None:
    """TF4: a Ti offset below tolerance accepts the write without a false mismatch alarm."""
    with tuning_rig(tmp, "tf4_ti_offset") as rig:
        baseline = read_baseline(rig)
        wait_for_fault(rig)
        target = baseline[TI] * TARGET_RATIO
        decision = approve_change(rig, {TI: target})
        assert decision.accepted
        assert decision.reason_code == "applied"
        rig.step(2, tick=True)
        assert abs(rig.h.read_param(TI) - target) <= READBACK_TOLERANCE
        assert rig.gw.status()[TI] == "enabled"
        assert audit_events(rig, "partial_revert") == []
        assert len(audit_events(rig, "param_write")) == 1
        assert rig.gw.alarms() == {}
        rig.h.wait_until_ns(int((HOOK_END_S + STEP_S) * S))
        assert read_tuning(rig) == {GAIN: baseline[GAIN], TI: target}
        assert_loop_is_local(rig)

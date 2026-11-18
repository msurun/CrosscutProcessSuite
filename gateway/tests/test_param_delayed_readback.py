"""Verify settling parameter writes on the engine tick without a background worker.

Read-count faults distinguish immediate acceptance from delayed plant divergence.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from crosscut_gateway import engine
from crosscut_gateway.engine_params import ParamConfig
from crosscut_gateway.interfaces import DEFAULT_VERIFY_AFTER_S, ParamPolicy
from crosscut_gateway.policy import PolicyError, params_from_dict
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
    pset,
    queued,
)
from test_gateway_scenarios import POLICY, TAG
from test_policy_params import GAIN

CHANGED_GAIN = 3.0  # Gain units, the value whose read-back can diverge.
DELAYED_READ_NUMBER = 2  # Reads since write; the first read confirms the immediate write.
LONG_SETTLE_S = 5.0  # Seconds, a per-parameter override above the default settle time.
GAIN_OFFSET = 0.5  # Gain units, larger than the gain read-back tolerance.


class DelayedParamPlant(ParamPlant):
    """Return a configurable gain offset only after the immediate read-back has passed."""

    def __init__(self, offset: float = 0.0) -> None:
        """Start a stable plant with an optional delayed gain offset in gain units."""
        super().__init__()
        self.offset = offset
        self.reads_since_write: dict[str, int] = {}
        self.read_targets: list[str] = []
        self.fail_delayed_read = False

    def write_param(self, tag: str, value: float) -> bool:
        """Reset the read counter so the revert has its own immediate confirmation."""
        self.reads_since_write[tag] = 0
        return super().write_param(tag, value)

    def read_param(self, tag: str) -> float:
        """Expose a delayed fault for the proposed gain and keep revert reads accurate."""
        self.read_targets.append(tag)
        count = self.reads_since_write.get(tag, 0) + 1
        self.reads_since_write[tag] = count
        actual = super().read_param(tag)
        if tag == KP and actual == CHANGED_GAIN and count >= DELAYED_READ_NUMBER:
            if self.fail_delayed_read:
                raise ConnectionError("delayed gain read failed; inspect the control-system link")
            return actual + self.offset
        return actual


def make_gateway(
    plant: DelayedParamPlant,
    policies: dict[str, ParamPolicy] | None = None,
    storage: Path | None = None,
) -> engine.WriteGateway:
    """Build an engine using the caller-controlled tick clock and optional durable store."""
    gateway = engine.WriteGateway(
        plant, {TAG: POLICY}, "confirm", params=ParamConfig(policies or dict(PARAMS), plant),
        intent_store=storage,
    )
    gateway.tick(NOW)
    return gateway


def apply_gain(gateway: engine.WriteGateway) -> str:
    """Apply gain while asserting that immediate read-back succeeds."""
    key = queued(gateway, it(KP, CHANGED_GAIN))
    assert gateway.approve(key, actor_ctx=BOB).reason_code == "applied"
    return key


def test_delayed_divergence_reverts_the_whole_set_and_audits_the_reason() -> None:
    """Delayed gain mismatch restores both gain and the earlier detuning Ti write."""
    plant = DelayedParamPlant(GAIN_OFFSET)
    gateway = make_gateway(plant)
    key = queued(gateway, it(KP, CHANGED_GAIN), it(TI, 150.0))
    assert gateway.approve(key, actor_ctx=BOB).accepted

    gateway.tick(NOW + int(DEFAULT_VERIFY_AFTER_S * S))

    assert plant.param_writes == [(TI, 150.0), (KP, CHANGED_GAIN), (KP, 2.0), (TI, 100.0)]
    assert plant.params[KP] == 2.0 and plant.params[TI] == 100.0
    assert gateway.status()[KP] == "stopped:readback"
    assert events(gateway, "partial_revert")[0]["reason_code"] == "readback_mismatch_delayed"
    assert events(gateway, "partial_revert")[0]["written"] == f"{TI},{KP}"
    assert not gateway.has_open_intent("L1")
    proposal = pset(it(KP, CHANGED_GAIN), pid="next")
    refusal = gateway.propose_params(proposal, actor_ctx=ALICE)
    assert refusal.reason_code == "target_stopped_readback"


def test_a_stable_value_closes_the_intent_only_after_the_configured_settle_time() -> None:
    """Custom settling time delays closure even though the immediate value was correct."""
    plant = DelayedParamPlant()
    policies = {KP: replace(PARAMS[KP], verify_after_s=LONG_SETTLE_S)}
    gateway = make_gateway(plant, policies)
    apply_gain(gateway)
    assert gateway.has_open_intent("L1")

    gateway.tick(NOW + int(LONG_SETTLE_S * S) - 1)
    assert gateway.has_open_intent("L1")
    assert plant.read_targets == [KP, KP]
    gateway.tick(NOW + int(LONG_SETTLE_S * S))

    assert not gateway.has_open_intent("L1")
    assert plant.read_targets == [KP, KP, KP]
    assert events(gateway, "partial_revert") == []


def test_a_restart_before_verification_preserves_the_open_intent(tmp_path: Path) -> None:
    """A process lost after applying must require reconciliation when its engine restarts."""
    plant = DelayedParamPlant()
    gateway = make_gateway(plant, storage=tmp_path)
    key = apply_gain(gateway)

    restarted = make_gateway(plant, storage=tmp_path)
    restarted.tick(NOW + int(DEFAULT_VERIFY_AFTER_S * S))

    assert restarted.has_open_intent("L1")
    assert restarted.open_intents()[0].key == key
    assert events(restarted, "intent_open_at_start")[0]["key"] == key
    proposal = pset(it(KP, 3.5, CHANGED_GAIN), pid="after-crash")
    assert restarted.propose_params(proposal, actor_ctx=ALICE).reason_code == "reconcile_required"
    assert plant.param_writes == [(KP, CHANGED_GAIN)]


def test_the_set_waits_for_its_longest_settle_time_and_reads_every_item() -> None:
    """A stable atomic set checks every parameter after the slowest member settles."""
    plant = DelayedParamPlant()
    policies = {KP: PARAMS[KP], TI: replace(PARAMS[TI], verify_after_s=LONG_SETTLE_S)}
    gateway = make_gateway(plant, policies)
    key = queued(gateway, it(KP, CHANGED_GAIN), it(TI, 150.0))
    assert gateway.approve(key, actor_ctx=BOB).accepted
    plant.read_targets.clear()

    gateway.tick(NOW + int(DEFAULT_VERIFY_AFTER_S * S))
    assert plant.read_targets == []
    assert gateway.has_open_intent("L1")
    gateway.tick(NOW + int(LONG_SETTLE_S * S))

    assert plant.read_targets == [KP, TI]
    assert not gateway.has_open_intent("L1")


def test_a_delayed_offset_inside_tolerance_does_not_revert() -> None:
    """The delayed pass uses the same engineering-unit tolerance as immediate read-back."""
    plant = DelayedParamPlant(PARAMS[KP].readback_tolerance / 2)
    gateway = make_gateway(plant)
    apply_gain(gateway)

    gateway.tick(NOW + int(DEFAULT_VERIFY_AFTER_S * S))

    assert not gateway.has_open_intent("L1")
    assert gateway.status()[KP] == "enabled"
    assert plant.param_writes == [(KP, CHANGED_GAIN)]
    assert events(gateway, "partial_revert") == []


def test_a_failed_delayed_read_reverts_and_stops_the_target() -> None:
    """A delayed transport failure fails closed through the existing revert path."""
    plant = DelayedParamPlant()
    plant.fail_delayed_read = True
    gateway = make_gateway(plant)
    apply_gain(gateway)

    gateway.tick(NOW + int(DEFAULT_VERIFY_AFTER_S * S))

    assert plant.params[KP] == 2.0
    assert gateway.status()[KP] == "stopped:comm"
    assert events(gateway, "partial_revert")[0]["reason_code"] == "comm_loss"
    assert not gateway.has_open_intent("L1")


def test_a_failed_delayed_revert_keeps_the_intent_open_and_raises_an_alarm() -> None:
    """Unrestored gain remains blocked for reconciliation instead of closing its intent."""
    plant = DelayedParamPlant(GAIN_OFFSET)
    gateway = make_gateway(plant)
    apply_gain(gateway)
    plant.refuse_values.add((KP, 2.0))

    gateway.tick(NOW + int(DEFAULT_VERIFY_AFTER_S * S))

    assert gateway.has_open_intent("L1")
    assert gateway.status()[KP] == "stopped:comm"
    assert events(gateway, "partial_revert")[0]["revert_failed"] == KP
    assert events(gateway, "alarm_check_dcs")[0]["reason_code"] == "revert_failed"


def test_an_omitted_settle_time_uses_the_module_default() -> None:
    """Older policy documents inherit the delayed verification interval in seconds."""
    policies = params_from_dict({KP: dict(GAIN)})

    assert policies[KP].verify_after_s == DEFAULT_VERIFY_AFTER_S


def test_a_policy_can_override_the_settle_time() -> None:
    """A per-parameter override survives policy parsing in seconds."""
    policies = params_from_dict({KP: {**GAIN, "verify_after_s": LONG_SETTLE_S}})

    assert policies[KP].verify_after_s == LONG_SETTLE_S


@pytest.mark.parametrize("settle_time", [-1, True, float("nan"), float("inf"), "2"])
def test_an_invalid_settle_time_is_refused(settle_time: object) -> None:
    """Negative, non-finite and nonnumeric intervals cannot schedule verification."""
    raw_policy = {**GAIN, "verify_after_s": settle_time}

    with pytest.raises(PolicyError, match="verify_after_s"):
        params_from_dict({KP: raw_policy})

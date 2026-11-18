"""ADR 016: the ``allow_take_remote`` policy flag and the ``not_remote`` refusal.

Engine refusal with a plant that raises NotRemoteError (no state change, audited), the
policy flag in schema and loader, and its hand-over to a plant adapter.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_gateway import engine as engine_module
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import NotRemoteError
from crosscut_gateway.policy import PolicyError
from crosscut_gateway.policy_file import load_policy_documents
from test_gateway_scenarios import POLICY, TAG, SimPlant, proposal
from test_write_policy_schema import VALID_POLICY_DOC, _validator


class LocalPlant(SimPlant):
    """SimPlant that, like OpcUaPlant without the flag, refuses a write when not remote."""

    def __init__(self) -> None:
        """Start with the setpoint in local control."""
        super().__init__()
        self.allow_take_remote = False

    def set_allow_take_remote(self, allow: bool) -> None:
        """Record the policy flag."""
        self.allow_take_remote = allow

    def write(self, tag: str, value: float) -> bool:
        """Write only while remote, unless taking remote is allowed."""
        if not (self.remote or self.allow_take_remote):
            raise NotRemoteError(tag)
        return super().write(tag, value)


def _gateway(plant: LocalPlant) -> WriteGateway:
    """A supervised gateway on ``plant`` with the shared policy."""
    return WriteGateway(plant, {TAG: POLICY}, "supervised")


def test_not_remote_is_refused_audited_and_writes_nothing() -> None:
    """A write while the loop is not remote is refused with not_remote and changes nothing."""
    plant = LocalPlant()
    gw = _gateway(plant)
    decision = gw.propose(proposal(55.0))
    assert not decision.accepted and decision.reason_code == "not_remote"
    assert gw.status()[TAG] == "enabled"
    assert any(r["event"] == "not_remote" for r in gw.audit_records())
    assert not any(r["event"] == "release" for r in gw.audit_records())


def test_not_remote_decision_is_replayed_idempotently() -> None:
    """The same proposal again returns the cached refusal."""
    gw = _gateway(LocalPlant())
    first = gw.propose(proposal(55.0))
    assert gw.propose(proposal(55.0)) == first


def test_writes_while_remote() -> None:
    """The same gateway accepts the write once the loop shows remote."""
    plant = LocalPlant()
    plant.remote = True
    assert _gateway(plant).propose(proposal(55.0)).accepted


def _policy_file(tmp_path: Path, extra: dict[str, Any]) -> Path:
    """Write a policy document with ``extra`` top-level fields."""
    path = tmp_path / "write-policy.json"
    path.write_text(json.dumps({**VALID_POLICY_DOC, **extra}), encoding="utf-8")
    return path


def test_schema_accepts_boolean_flag_and_rejects_other_types() -> None:
    """allow_take_remote is an optional boolean."""
    assert _validator().is_valid(VALID_POLICY_DOC)
    assert _validator().is_valid({**copy.deepcopy(VALID_POLICY_DOC), "allow_take_remote": True})
    assert not _validator().is_valid({**VALID_POLICY_DOC, "allow_take_remote": "yes"})


@pytest.mark.parametrize(("extra", "expected"), [({}, False), ({"allow_take_remote": True}, True)])
def test_loader_reads_flag_with_default_false(
    tmp_path: Path, extra: dict[str, Any], expected: bool
) -> None:
    """The loaded policy carries the flag, false when absent."""
    assert load_policy_documents(_policy_file(tmp_path, extra)).allow_take_remote is expected


def test_loader_rejects_non_boolean_flag(tmp_path: Path) -> None:
    """A non-boolean flag is a policy error."""
    with pytest.raises(PolicyError):
        load_policy_documents(_policy_file(tmp_path, {"allow_take_remote": 1}))


@pytest.mark.parametrize("flag", [False, True])
def test_start_hands_the_flag_to_the_plant(flag: bool) -> None:
    """start_from_policy_file passes the policy flag to an adapter that can take remote."""
    plant = LocalPlant()
    plant.allow_take_remote = not flag
    engine_module._apply_take_remote(plant, flag)
    assert plant.allow_take_remote is flag
    engine_module._apply_take_remote(SimPlant(), flag)  # a plant without the setter is fine

"""MV availability query: engine reasons and the read-only mailbox command (Phase 2.5 step 4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WriteProposal
from crosscut_gateway.service import VALIDATION_SCHEMA, GatewayService
from test_gateway_scenarios import POLICY, TAG, SimPlant
from test_gateway_service import FakeClock, outbox_payload, state_payload, write_command


def make_gateway(mode: str = "supervised") -> tuple[WriteGateway, SimPlant]:
    """A gateway on a sim plant with one CAS-only target."""
    plant = SimPlant()
    return WriteGateway(plant, {TAG: POLICY}, mode), plant  # type: ignore[arg-type]


def ask(gateway: WriteGateway, *tags: str) -> dict:
    """Run the availability query for the given tags."""
    return gateway.mv_availability(list(tags))


def test_enabled_target_is_available() -> None:
    """A fresh target in supervised mode with an allowed loop mode is available."""
    gateway, _plant = make_gateway()
    assert ask(gateway, TAG) == {TAG: {"available": True, "reasons": []}}


def test_unknown_target() -> None:
    """A tag without policy is reported unavailable with unknown_target."""
    gateway, _plant = make_gateway()
    assert ask(gateway, "NOPE")["NOPE"] == {"available": False, "reasons": ["unknown_target"]}


def test_loop_mode_outside_policy() -> None:
    """A loop mode the policy does not allow gives the reason mode."""
    gateway, plant = make_gateway()
    plant.modes[TAG] = "MAN"
    assert ask(gateway, TAG)[TAG]["reasons"] == ["mode"]


@pytest.mark.parametrize("mode", ["off", "advisory", "dry_run"])
def test_gateway_mode_that_cannot_write(mode: str) -> None:
    """Off, advisory and dry_run modes give mode_no_write."""
    gateway, _plant = make_gateway(mode)
    assert ask(gateway, TAG)[TAG] == {"available": False, "reasons": ["mode_no_write"]}


def test_hold_off_after_operator_takeover() -> None:
    """An operator mode change while holding puts the target in hold_off."""
    gateway, plant = make_gateway()
    gateway.propose(WriteProposal(TAG, 55.0, "sup", 0, "t"))
    plant.modes[TAG] = "MAN"
    gateway.tick(plant.now_ns)
    assert gateway.target_state(TAG) == "hold_off"
    assert "hold_off" in ask(gateway, TAG)[TAG]["reasons"]


def test_kill_latch() -> None:
    """After kill the target is unavailable with reason killed."""
    gateway, _plant = make_gateway()
    gateway.kill()
    result = ask(gateway, TAG)[TAG]
    assert result["available"] is False
    assert "killed" in result["reasons"]


def test_unreadable_plant_is_comm_loss() -> None:
    """A plant that cannot answer the loop-mode read gives comm_loss."""
    gateway, plant = make_gateway()

    def broken(_tag: str) -> str:
        raise ConnectionError("down")

    plant.loop_mode = broken  # type: ignore[method-assign]
    assert ask(gateway, TAG)[TAG]["reasons"] == ["comm_loss"]


def test_query_is_read_only() -> None:
    """Asking changes neither states nor the audit trail."""
    gateway, _plant = make_gateway()
    before = (gateway.status(), len(gateway.audit_records()))
    ask(gateway, TAG, "NOPE")
    assert (gateway.status(), len(gateway.audit_records())) == before


def test_mailbox_command_replies_and_changes_nothing(tmp_path: Path) -> None:
    """The mv_availability command answers through the outbox; state.json is unchanged."""
    gateway, _plant = make_gateway()
    service = GatewayService(tmp_path, gateway, clock=FakeClock())
    service.poll_once()
    targets_before = state_payload(tmp_path)["targets"]
    args = {"targets": [TAG, "NOPE"]}
    write_command(tmp_path, "a1", {"id": "a1", "cmd": "mv_availability", "args": args})
    service.poll_once()
    payload = outbox_payload(tmp_path, "a1")
    assert payload["ok"] is True
    assert payload["result"][TAG]["available"] is True
    assert payload["result"]["NOPE"]["reasons"] == ["unknown_target"]
    assert state_payload(tmp_path)["targets"] == targets_before


def test_mailbox_command_rejects_bad_targets(tmp_path: Path) -> None:
    """Targets must be a list of non-empty strings."""
    gateway, _plant = make_gateway()
    service = GatewayService(tmp_path, gateway, clock=FakeClock())
    assert VALIDATION_SCHEMA["mv_availability"] == [("targets", "str_list")]
    write_command(tmp_path, "b1", {"id": "b1", "cmd": "mv_availability", "args": {"targets": "x"}})
    service.poll_once()
    assert list((tmp_path / "_gateway" / "rejected").glob("b1*"))

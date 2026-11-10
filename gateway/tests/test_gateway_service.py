"""End-to-end tests for GatewayService: inbox files in, outbox/state/rejected out.

Uses the real WriteGateway on a deterministic SimPlant and a fake clock so every
timestamp in proposals, state.json and the engine write window is reproducible.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.engine_params import ParamConfig
from crosscut_gateway.interfaces import ParamPolicy, WriteProposal
from crosscut_gateway.param_intent_store import (
    ParamIntentItem,
    ParamIntentRecord,
    ParamIntentStore,
)
from crosscut_gateway.service import GatewayService, serve
from test_gateway_scenarios import POLICY, TAG, S, SimPlant

CLOCK_START_S = 1000.0


class FakeClock:
    """Mutable fake clock: seconds since epoch, advanced by tests."""

    def __init__(self, start_s: float = CLOCK_START_S) -> None:
        """Store the starting time in seconds."""
        self.now_s = start_s

    def __call__(self) -> float:
        """Return the current fake time in seconds."""
        return self.now_s

    def advance(self, seconds: float) -> None:
        """Move the clock forward by *seconds*."""
        self.now_s += seconds


def inbox_path(root: Path, name: str) -> Path:
    """Path of a command file named *name* under the inbox directory."""
    return root / "_gateway" / "inbox" / f"{name}.json"


def write_command(root: Path, name: str, command: dict[str, object]) -> Path:
    """Serialise *command* to inbox/<name>.json and return the path."""
    path = inbox_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(command), encoding="utf-8")
    return path


def outbox_payload(root: Path, command_id: str) -> dict:
    """Read and parse outbox/<command_id>.json."""
    path = root / "_gateway" / "outbox" / f"{command_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def state_payload(root: Path) -> dict:
    """Read and parse _gateway/state.json."""
    return json.loads((root / "_gateway" / "state.json").read_text(encoding="utf-8"))


def proposal_args(clock: FakeClock, value: float = 55.0) -> dict[str, object]:
    """Valid ``propose`` args stamped at the current fake clock time."""
    return {
        "target_tag": TAG,
        "value": value,
        "proposer": "tester",
        "t_ns": int(clock() * S),
        "reason": "test",
    }


def propose(root: Path, clock: FakeClock, name: str, value: float = 55.0) -> str:
    """Write a propose command as inbox/<name>.json, return its id."""
    write_command(root, name, {"id": name, "cmd": "propose", "args": proposal_args(clock, value)})
    return name


@pytest.fixture
def env(tmp_path: Path):
    """(root, clock, plant, gateway, service) wired in confirm mode."""
    clock = FakeClock()
    plant = SimPlant()
    gateway = WriteGateway(plant, {TAG: POLICY}, "confirm")
    root = tmp_path
    service = GatewayService(root, gateway, clock=clock)
    return root, clock, plant, gateway, service


def start_engine_clock(service: GatewayService) -> None:
    """One poll with an empty inbox so the engine records time 0 (opens the write window)."""
    service.poll_once()


def test_propose_round_trip_queues_and_deletes_inbox(env) -> None:
    """A propose in confirm mode writes an ok outbox record, removes the file, queues pending."""
    root, clock, _plant, _gw, service = env
    start_engine_clock(service)
    propose(root, clock, "p1")
    service.poll_once()
    payload = outbox_payload(root, "p1")
    assert payload["ok"] is True
    assert payload["result"]["reason_code"] == "queued"
    assert not inbox_path(root, "p1").exists()
    pending = state_payload(root)["pending"]
    assert len(pending) == 1
    assert pending[0]["target_tag"] == TAG
    assert pending[0]["value"] == 55.0
    assert pending[0]["proposer"] == "tester"
    assert pending[0]["reason"] == "test"
    assert pending[0]["t_ns"] == int(clock() * S)


def test_approve_pending_key_writes_once(env) -> None:
    """Approving the queued key yields accepted True and exactly one plant write."""
    root, clock, plant, _gw, service = env
    start_engine_clock(service)
    propose(root, clock, "p1")
    service.poll_once()
    key = state_payload(root)["pending"][0]["key"]
    write_command(root, "a1", {"id": "a1", "cmd": "approve", "args": {"key": key}})
    service.poll_once()
    payload = outbox_payload(root, "a1")
    assert payload["ok"] is True
    assert payload["result"]["accepted"] is True
    assert len(plant.writes) == 1


def test_reject_clears_pending(env) -> None:
    """Rejecting a queued key returns ok True and leaves pending empty."""
    root, clock, _plant, _gw, service = env
    start_engine_clock(service)
    propose(root, clock, "p1")
    service.poll_once()
    key = state_payload(root)["pending"][0]["key"]
    write_command(root, "r1", {"id": "r1", "cmd": "reject", "args": {"key": key}})
    service.poll_once()
    assert outbox_payload(root, "r1")["ok"] is True
    assert state_payload(root)["pending"] == []


def test_approve_unknown_key_reports_error(env) -> None:
    """Approving a key that is not pending returns ok False with an unknown-key error."""
    root, _clock, _plant, _gw, service = env
    write_command(root, "a1", {"id": "a1", "cmd": "approve", "args": {"key": "nope"}})
    service.poll_once()
    payload = outbox_payload(root, "a1")
    assert payload["ok"] is False
    assert payload["error"].startswith("unknown key")


def test_set_mode_changes_state_and_rejects_unknown(env) -> None:
    """A valid mode change is reflected in state.json; an unknown mode returns an error."""
    root, _clock, _plant, _gw, service = env
    write_command(root, "m1", {"id": "m1", "cmd": "set_mode", "args": {"mode": "supervised"}})
    service.poll_once()
    assert state_payload(root)["mode"] == "supervised"
    write_command(root, "m2", {"id": "m2", "cmd": "set_mode", "args": {"mode": "bogus"}})
    service.poll_once()
    payload = outbox_payload(root, "m2")
    assert payload["ok"] is False
    assert "bogus" in payload["error"]


def test_kill_then_re_enable_is_refused(env) -> None:
    """After kill the target is 'killed' and re-enable returns an error mentioning it."""
    root, _clock, _plant, _gw, service = env
    write_command(root, "k1", {"id": "k1", "cmd": "kill", "args": {}})
    service.poll_once()
    assert outbox_payload(root, "k1")["ok"] is True
    assert state_payload(root)["targets"][TAG] == "killed"
    write_command(root, "e1", {"id": "e1", "cmd": "re_enable", "args": {"tag": TAG}})
    service.poll_once()
    payload = outbox_payload(root, "e1")
    assert payload["ok"] is False
    assert "killed" in payload["error"]


def test_re_enable_unknown_tag_reports_error(env) -> None:
    """Re-enabling a tag with no policy returns ok False and an unknown-key error."""
    root, _clock, _plant, _gw, service = env
    write_command(root, "e1", {"id": "e1", "cmd": "re_enable", "args": {"tag": "NOPE.TAG"}})
    service.poll_once()
    payload = outbox_payload(root, "e1")
    assert payload["ok"] is False
    assert payload["error"].startswith("unknown key")


def test_re_enable_after_control_system_rejection(env) -> None:
    """A write refused by the plant stops the target; re_enable brings it back to enabled."""
    root, clock, plant, gateway, service = env
    gateway.set_mode("supervised")
    start_engine_clock(service)
    plant.refuse = True
    propose(root, clock, "p1")
    service.poll_once()
    assert state_payload(root)["targets"][TAG] == "stopped:rejected"
    write_command(root, "e1", {"id": "e1", "cmd": "re_enable", "args": {"tag": TAG}})
    service.poll_once()
    assert outbox_payload(root, "e1")["ok"] is True
    assert state_payload(root)["targets"][TAG] == "enabled"


def test_malformed_commands_go_to_rejected(env) -> None:
    """Invalid JSON, unknown cmd, missing args and bad id land in rejected.

    Only the unknown cmd has a trusted id and is answered in the outbox (unknown_cmd).
    """
    root, _clock, _plant, _gw, service = env
    bad_json = root / "_gateway" / "inbox" / "bad1.json"
    bad_json.write_text("{not json", encoding="utf-8")
    write_command(root, "bad2", {"id": "bad2", "cmd": "unknown_cmd", "args": {}})
    write_command(root, "bad3", {"id": "bad3", "cmd": "propose"})
    write_command(root, "bad4", {"id": "bad 4", "cmd": "re_enable", "args": {"tag": TAG}})
    service.poll_once()
    rejected = root / "_gateway" / "rejected"
    for name in ("bad1", "bad2", "bad3", "bad4"):
        assert (rejected / f"{name}.json").exists()
        assert (rejected / f"{name}.json.reason.txt").exists()
    assert list((root / "_gateway" / "inbox").glob("*.json")) == []
    outbox_files = sorted((root / "_gateway" / "outbox").glob("*.json"))
    assert [path.name for path in outbox_files] == ["bad2.json"]
    assert outbox_payload(root, "bad2")["error"] == "unknown_cmd"


def test_state_json_shape_and_audit_tail_cap(env) -> None:
    """state.json has the clock time, mode/targets/chain_ok, and audit_tail capped at 200."""
    root, clock, _plant, gateway, service = env
    gateway.set_mode("dry_run")
    for index in range(210):
        gateway.propose(WriteProposal(TAG, 50.0 + index * 0.1, "bulk", index, "bulk"))
    service.poll_once()
    state = state_payload(root)
    expected = datetime.fromtimestamp(clock(), tz=UTC).isoformat()
    assert datetime.fromisoformat(state["updated_at_utc"]) == datetime.fromisoformat(expected)
    assert state["mode"] == "dry_run"
    assert TAG in state["targets"]
    assert state["chain_ok"] is True
    assert len(state["audit_tail"]) == 200


def test_serve_processes_commands_until_stopped(env) -> None:
    """serve() loops, processes an inbox command, and exits once the stop event is set."""
    root, clock, _plant, _gw, service = env
    start_engine_clock(service)
    propose(root, clock, "p1")
    stop_event = threading.Event()
    thread = threading.Thread(target=serve, args=(service, 0.05, stop_event), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5.0
    while not (root / "_gateway" / "outbox" / "p1.json").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    stop_event.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert outbox_payload(root, "p1")["ok"] is True


class ParamSimPlant(SimPlant):
    """Simulated plant supporting PID parameters for gateway service tests."""

    def __init__(self) -> None:
        super().__init__()
        self.params: dict[str, float] = {"FIC101.KP": 2.0}

    def read_param(self, tag: str) -> float:
        return self.params[tag]

    def write_param(self, tag: str, val: float) -> None:
        self.params[tag] = val

    def loop_mode(self, tag: str) -> str:
        return "AUTO"


def test_list_open_intents_returns_empty_when_no_intents_exist(env) -> None:
    """The list_open_intents command reports store_state ok and empty intents list."""
    root, _clock, _plant, _gw, service = env
    write_command(root, "list1", {"id": "list1", "cmd": "list_open_intents", "args": {}})
    service.poll_once()
    payload = outbox_payload(root, "list1")
    assert payload["ok"] is True
    assert payload["result"]["store_state"] == "ok"
    assert payload["result"]["damaged"] is False
    assert payload["result"]["intents"] == []


def test_list_open_intents_reports_damaged_store_without_crashing(tmp_path: Path) -> None:
    """When param-intents.json is corrupt, list_open_intents reports damaged and does not crash."""
    clock = FakeClock()
    plant = SimPlant()
    intent_file = tmp_path / "_gateway" / "param-intents.json"
    intent_file.parent.mkdir(parents=True, exist_ok=True)
    intent_file.write_bytes(b"corrupted-non-json")

    store = ParamIntentStore(intent_file)
    gw = WriteGateway(plant, {TAG: POLICY}, "confirm", intent_store=store)
    service = GatewayService(tmp_path, gw, clock=clock)

    write_command(tmp_path, "list2", {"id": "list2", "cmd": "list_open_intents", "args": {}})
    service.poll_once()
    payload = outbox_payload(tmp_path, "list2")
    assert payload["ok"] is True
    assert payload["result"]["store_state"] == "damaged"
    assert payload["result"]["damaged"] is True
    assert payload["result"]["intents"] == []


def test_resolve_intent_command_resolves_open_intent_via_mailbox(tmp_path: Path) -> None:
    """resolve_intent command reads plant parameters and marks the intent closed."""
    clock = FakeClock()
    plant = ParamSimPlant()
    policy = ParamPolicy(
        loop="L1", param="gain", unit="1", vendor_form="siemens_pid",
        limits=(0.1, 10.0), max_ratio=2.0, readback_tolerance=0.001,
        min_interval_s=60.0, allowed_loop_modes=("AUTO", "MAN"),
    )
    cfg = ParamConfig({"FIC101.KP": policy}, plant=plant)
    store = ParamIntentStore(tmp_path / "_gateway")
    item = ParamIntentItem(target="FIC101.KP", from_value=2.0, to_value=3.0)
    record = ParamIntentRecord(
        key="key-123", loop_id="L1", items=(item,), created_time="2026-11-05T10:00:00Z"
    )
    store.record_intent(record)

    gw = WriteGateway(plant, {TAG: POLICY}, "confirm", params=cfg, intent_store=store)
    service = GatewayService(tmp_path, gw, clock=clock)
    args = {"key": "key-123", "actor": "engineer1"}
    write_command(tmp_path, "res1", {"id": "res1", "cmd": "resolve_intent", "args": args})
    service.poll_once()

    payload = outbox_payload(tmp_path, "res1")
    assert payload["ok"] is True
    assert payload["result"]["accepted"] is True
    assert payload["result"]["reason_code"] == "resolved"
    assert store.load_open() == []

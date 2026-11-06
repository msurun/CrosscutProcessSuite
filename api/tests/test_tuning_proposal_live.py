"""Tuning proposals against a real GatewayService thread and a fake parameter plant (ADR 014).

The API signs propose_params / approve with the logged-in engineer, the gateway authenticates
the envelopes (roles, self-approval, read-back, audit) and the API reads the result back from
the files under <root>/_gateway/. Only the report and the policy view are stubbed.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.gateway_client import FileGatewayClient
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.engine_params import ParamConfig
from crosscut_gateway.interfaces import ParamPolicy
from crosscut_gateway.service import GatewayService, ServiceOptions, serve
from tuning_fakes import (
    BODY,
    KP,
    LOOP,
    START_VALUES,
    TI,
    Session,
    World,
    build_world,
    patch_report,
    policy_document,
)

PROPOSE = f"/loops/{LOOP}/tuning/proposals"
WAIT_S = 5.0


class ParamPlant:
    """A control system holding the two parameters; AUTO mode; read-back equals what was written."""

    def __init__(self) -> None:
        """Start with the detuned loop values."""
        self.values = dict(START_VALUES)
        self.writes: list[tuple[str, float]] = []
        self.last_hb_ns: int | None = None

    def read(self, tag: str) -> float:
        """Setpoint reads are not used by parameter targets."""
        return 0.0

    def write(self, tag: str, value: float) -> bool:
        """No setpoint target exists in these tests."""
        return False

    def heartbeat_seen(self) -> bool:
        """The watchdog is irrelevant for parameters."""
        return True

    def send_heartbeat(self) -> None:
        """Record nothing."""

    def setpoint_source(self, tag: str) -> str:
        """Unused."""
        return "local"

    def release(self, tag: str) -> None:
        """Unused."""

    def loop_mode(self, tag: str) -> str:
        """The loop is in AUTO."""
        return "AUTO"

    def read_param(self, tag: str) -> float:
        """Current value of a parameter."""
        return self.values[tag]

    def write_param(self, tag: str, value: float) -> bool:
        """Write a parameter."""
        self.values[tag] = value
        self.writes.append((tag, value))
        return True


def param_policy(param: str, unit: str, limits: tuple[float, float]) -> ParamPolicy:
    """A permissive pid_param policy of one parameter of the loop."""
    return ParamPolicy(
        loop=LOOP,
        param=param,
        unit=unit,
        vendor_form="siemens_pid_compact",
        limits=limits,
        max_ratio=10.0,
        readback_tolerance=1e-6,
        min_interval_s=0.0,
        allowed_loop_modes=("AUTO",),
    )


class PolicyClient(FileGatewayClient):
    """The file client with a fixed live policy view (no pinned policy file in these tests)."""

    def live_policy(self) -> dict[str, Any] | None:
        """The two parameter targets of the loop."""
        return {"document": policy_document(), "pin": {}}


@dataclass
class Live:
    """The running system under test."""

    world: World
    plant: ParamPlant
    stop: threading.Event
    thread: threading.Thread


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Live]:
    """A gateway service thread on a fake plant, and the API in front of it."""
    monkeypatch.delenv("CROSSCUT_SECRETS_DIR", raising=False)
    patch_report(monkeypatch)
    key_file = tmp_path / "_secrets" / "gateway-hmac.key"
    key_file.parent.mkdir(parents=True)
    key_file.write_bytes(os.urandom(32))
    plant = ParamPlant()
    policies = {
        KP: param_policy("gain", "OUT/PV", (0.1, 10.0)),
        TI: param_policy("ti", "s", (1.0, 1000.0)),
    }
    gateway = WriteGateway(plant, {}, "confirm", params=ParamConfig(policies, plant))
    options = ServiceOptions(auth_required=True, key_path=key_file, enforce_start_floor=False)
    service = GatewayService(tmp_path, gateway, options=options)
    stop = threading.Event()
    thread = threading.Thread(target=serve, args=(service, 0.02, stop), daemon=True)
    thread.start()
    client = PolicyClient(tmp_path, timeout_s=WAIT_S)
    _wait(lambda: (tmp_path / "_gateway" / "state.json").exists())
    world = build_world(tmp_path, client, connector=_PlantConnector(plant), wait_s=WAIT_S)
    yield Live(world, plant, stop, thread)
    stop.set()
    thread.join(timeout=WAIT_S)


class _PlantConnector:
    """Read-only connector over the parameter plant."""

    def __init__(self, plant: ParamPlant) -> None:
        """Bind to the plant."""
        self.plant = plant

    def read_live(self, tags: list[str]) -> dict[str, Any]:
        """Live values of the parameter tags."""
        from crosscut_connectors.base import LiveValue

        return {t: LiveValue(self.plant.values[t], 0, "2026-11-06T12:00:00+00:00") for t in tags}


def _wait(probe: Callable[[], Any]) -> Any:
    """The first truthy result of probe within WAIT_S seconds, else fail."""
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(0.02)
    pytest.fail("timed out")


def propose(live: Live, user: str = "eng1") -> dict[str, Any]:
    """Create a proposal through the API; expects a queued record."""
    response = Session(live.world, user).call("POST", PROPOSE, BODY)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    assert body["status"] == "queued", body
    return body


def test_second_engineer_approval_writes_the_plant_once_and_rollback_restores_it(
    live: Live,
) -> None:
    created = propose(live)
    assert live.plant.writes == [] and len(created["gateway_key"]) == 64
    approved = Session(live.world, "eng2").call(
        "POST", f"/tuning/proposals/{created['id']}/approve"
    )
    assert approved.status_code == 200, approved.text
    applied = approved.json()["applied"]
    assert approved.json()["status"] == "applied" and applied["approver"] == "eng2"
    assert applied["from_read"] == START_VALUES
    assert live.plant.values[KP] == pytest.approx(1.25)
    assert live.plant.values[TI] == pytest.approx(100.0)
    back = Session(live.world, "eng1").call("POST", f"/tuning/proposals/{created['id']}/rollback")
    assert back.status_code == 201 and back.json()["status"] == "queued", back.text
    undone = Session(live.world, "lead1").call(
        "POST", f"/tuning/proposals/{back.json()['id']}/approve"
    )
    assert undone.status_code == 200, undone.text
    assert live.plant.values == START_VALUES


def test_self_approval_and_operator_approval_are_refused_and_nothing_is_written(
    live: Live,
) -> None:
    created = propose(live)
    path = f"/tuning/proposals/{created['id']}/approve"
    assert Session(live.world, "eng1").call("POST", path).status_code == 403
    assert Session(live.world, "op1").call("POST", path).status_code == 403
    assert Session(live.world, "view1").call("POST", path).status_code == 403
    assert live.plant.writes == []
    shown = Session(live.world, "view1").call("GET", f"/tuning/proposals/{created['id']}")
    assert shown.json()["status"] == "queued"


def test_from_mismatch_at_approve_refuses_and_closes_the_record(live: Live) -> None:
    created = propose(live)
    live.plant.values[KP] = 0.9  # someone retuned the loop at the DCS after the proposal
    refused = Session(live.world, "eng2").call("POST", f"/tuning/proposals/{created['id']}/approve")
    assert refused.status_code == 409 and refused.json()["detail"] == "from_mismatch"
    assert live.plant.writes == []
    shown = Session(live.world, "view1").call("GET", f"/tuning/proposals/{created['id']}")
    assert shown.json()["status"] == "refused:from_mismatch"


def test_operator_reject_drops_the_queued_set_in_the_gateway(live: Live) -> None:
    created = propose(live)
    rejected = Session(live.world, "op1").call("POST", f"/tuning/proposals/{created['id']}/reject")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    _wait(lambda: not live.world.gateway.pending_params())
    again = Session(live.world, "eng2").call("POST", f"/tuning/proposals/{created['id']}/approve")
    assert again.status_code == 409


def test_a_change_at_the_dcs_marks_the_applied_record_invalid(live: Live) -> None:
    created = propose(live)
    approved = Session(live.world, "eng2").call(
        "POST", f"/tuning/proposals/{created['id']}/approve"
    )
    assert approved.status_code == 200
    live.plant.values[KP] = 4.0  # an engineer changes the gain at the DCS
    viewer = Session(live.world, "view1")

    def flagged() -> dict[str, Any] | None:
        shown = viewer.call("GET", f"/tuning/proposals/{created['id']}").json()
        return shown if shown["applied"].get("invalid") else None

    shown = _wait(flagged)
    assert shown["applied"]["invalid"] == "param_changed_externally"
    assert shown["status"] == "applied"

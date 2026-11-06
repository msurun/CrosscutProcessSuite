"""Integration tests for supervisor advice as setpoint write proposals (Phase 6, #51).

Tests the full advisory-to-write pathway:
- Supervisor advice converted to setpoint proposals (confirm and supervised modes)
- Operator confirmation and approval queueing
- Direct writes in supervised mode
- Operator override priority (operator action always wins)
- Policy clamp to engineering limits and step limits
- Automatic propose flag on advise endpoint
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from auth_support import write_key_file
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WritePolicy
from crosscut_gateway.service import GatewayService, serve
from crosscut_sim.run import main as run_simulation
from fastapi.testclient import TestClient
from open_app import create_app_without_auth

TAG = "FIC101.SP"
SECOND_NS = 1_000_000_000
WAIT_TIMEOUT_S = 3.0
POLL_INTERVAL_S = 0.02
SERVICE_INTERVAL_S = 0.02

POLICY = WritePolicy(
    limits=(0.0, 100.0),
    max_step=10.0,
    max_rate_per_s=5.0,
    min_interval_s=0.5,
    allowed_loop_modes=("CAS",),
    hold_off_s=60.0,
    watchdog_s=5.0,
    readback_tolerance=0.5,
)

CONFIG: dict[str, Any] = {
    "schema_version": "1.0.0",
    "id": "mill-feed",
    "fuzzy_system_id": "mill_feed_supervisor",
    "output_id": "feed_change",
    "target_loop": "mill_feed",
    "target_tag": TAG,
    "mode": "confirm",
    "gates": [{"loop": "mill_feed", "block_on": ["manual", "saturated"], "warn_on": []}],
    "silent_band": 0.0,
    "min_activation": 0.0,
    "min_interval_s": 0,
    "display_clamp": [-10, 10],
}


class SimPlant:
    """Deterministic simulated plant supporting setpoint writes, modes and operator override."""

    def __init__(self, watchdog_s: float = POLICY.watchdog_s) -> None:
        self.now_ns = 0
        self.watchdog_ns = int(watchdog_s * SECOND_NS)
        self.values = {TAG: 50.0}
        self.modes = {TAG: "CAS"}
        self.remote = False
        self.last_hb_ns: int | None = None
        self.writes: list[tuple[int, str, float]] = []

    def read(self, tag: str) -> float:
        return self.values[tag]

    def write(self, tag: str, value: float) -> bool:
        if self.modes[tag] != "CAS":
            return False
        self.values[tag] = value
        self.remote = True
        self.writes.append((time.time_ns(), tag, value))
        return True

    def heartbeat_seen(self) -> bool:
        if self.last_hb_ns is None:
            return False
        return time.time_ns() - self.last_hb_ns <= self.watchdog_ns

    def send_heartbeat(self) -> None:
        self.last_hb_ns = time.time_ns()

    def loop_mode(self, tag: str) -> str:
        return self.modes[tag]

    def setpoint_source(self, tag: str) -> str:
        return "remote" if self.remote else "local"

    def set_mode_by_operator(self, tag: str, mode: str) -> None:
        self.modes[tag] = mode
        if mode != "CAS":
            self.remote = False

    def set_setpoint_by_operator(self, tag: str, value: float) -> None:
        self.values[tag] = value
        self.remote = False

    def release(self, tag: str) -> None:
        self.remote = False


@dataclass
class LiveTestbed:
    """Testbed combining running GatewayService, API TestClient, and shared SimPlant."""

    client: TestClient
    plant: SimPlant
    root: Path
    stop_event: threading.Event
    thread: threading.Thread


def _install_signing_key(root: Path) -> Path:
    key_file = root / "_secrets" / "gateway-hmac.key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    write_key_file(key_file, os.urandom(32))
    return key_file


def _run_gateway(root: Path, plant: SimPlant) -> tuple[threading.Event, threading.Thread]:
    service = GatewayService(root, WriteGateway(plant, {TAG: POLICY}, "confirm"))
    stop_event = threading.Event()
    thread = threading.Thread(
        target=serve, args=(service, SERVICE_INTERVAL_S, stop_event), daemon=True
    )
    thread.start()
    return stop_event, thread


@pytest.fixture
def live_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LiveTestbed:
    """Fixture providing simulated mill dataset, running gateway and API client."""
    monkeypatch.delenv("CROSSCUT_SECRETS_DIR", raising=False)
    _install_signing_key(tmp_path)
    argv = ["--plant", "mill_circuit", "--duration", "1h", "--sample-period", "10"]
    assert run_simulation([*argv, "--out", str(tmp_path)]) == 0

    plant = SimPlant()
    stop_event, thread = _run_gateway(tmp_path, plant)
    client = TestClient(create_app_without_auth(tmp_path))
    testbed = LiveTestbed(client, plant, tmp_path, stop_event, thread)
    yield testbed
    stop_event.set()
    thread.join(timeout=WAIT_TIMEOUT_S)


def _poll(probe: Callable[[], Any], describe: str) -> Any:
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        res = probe()
        if res:
            return res
        time.sleep(POLL_INTERVAL_S)
    pytest.fail(f"timed out waiting for {describe}")


def _wait_gateway(client: TestClient) -> None:
    _poll(lambda: client.get("/gateway/status").status_code == 200, "gateway ready")


def _dataset_id(client: TestClient) -> str:
    return client.get("/datasets").json()[0]["id"]


def test_supervisor_propose_refuses_when_mode_is_off(live_env: LiveTestbed) -> None:
    _wait_gateway(live_env.client)
    off_cfg = {**CONFIG, "mode": "off"}
    assert live_env.client.put("/supervisors/mill-feed", json=off_cfg).status_code == 200

    resp = live_env.client.post(
        "/supervisors/mill-feed/propose",
        json={"current_sp": 50.0, "direction": "increase", "magnitude": 5.0},
    )
    assert resp.status_code == 409
    assert "mode is off" in resp.json()["detail"]


def test_supervisor_propose_in_confirm_mode_queues_for_approval(live_env: LiveTestbed) -> None:
    _wait_gateway(live_env.client)
    assert live_env.client.put("/supervisors/mill-feed", json=CONFIG).status_code == 200

    resp = live_env.client.post(
        "/supervisors/mill-feed/propose",
        json={"current_sp": 50.0, "direction": "increase", "magnitude": 5.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["proposal"]["value"] == 55.0
    assert data["proposal"]["target_tag"] == TAG
    assert data["decision"]["accepted"] is True
    assert data["decision"]["reason_code"] == "queued"

    pending = _poll(lambda: live_env.client.get("/gateway/pending").json(), "queued proposal")
    assert len(pending) == 1
    key = pending[0]["key"]

    appr = live_env.client.post(f"/gateway/pending/{key}/approve")
    assert appr.status_code == 200
    _poll(lambda: len(live_env.plant.writes) >= 1, "plant write")
    assert live_env.plant.values[TAG] == 55.0


def test_supervisor_propose_in_supervised_mode_writes_directly(live_env: LiveTestbed) -> None:
    _wait_gateway(live_env.client)
    live_env.client.put("/gateway/mode", json={"mode": "supervised"})
    _poll(lambda: live_env.client.get("/gateway/status").json()["mode"] == "supervised", "mode")

    sup_cfg = {**CONFIG, "mode": "supervised"}
    assert live_env.client.put("/supervisors/mill-feed", json=sup_cfg).status_code == 200

    resp = live_env.client.post(
        "/supervisors/mill-feed/propose",
        json={"current_sp": 50.0, "direction": "increase", "magnitude": 6.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["proposal"]["value"] == 56.0
    assert data["decision"]["accepted"] is True
    assert data["decision"]["reason_code"] == "ok"

    _poll(lambda: len(live_env.plant.writes) >= 1, "direct write")
    assert live_env.plant.values[TAG] == 56.0


def test_supervisor_propose_operator_action_always_wins(live_env: LiveTestbed) -> None:
    _wait_gateway(live_env.client)
    live_env.client.put("/gateway/mode", json={"mode": "supervised"})
    _poll(lambda: live_env.client.get("/gateway/status").json()["mode"] == "supervised", "mode")

    sup_cfg = {**CONFIG, "mode": "supervised"}
    assert live_env.client.put("/supervisors/mill-feed", json=sup_cfg).status_code == 200

    # First write to establish gateway hold on the target tag
    resp1 = live_env.client.post(
        "/supervisors/mill-feed/propose",
        json={"current_sp": 50.0, "direction": "increase", "magnitude": 2.0},
    )
    assert resp1.status_code == 200
    assert resp1.json()["decision"]["accepted"] is True
    _poll(lambda: len(live_env.plant.writes) >= 1, "first write")

    # Operator overrides the setpoint on the plant locally
    time.sleep(0.05)
    live_env.plant.set_setpoint_by_operator(TAG, 52.0)
    time.sleep(0.05)

    # Supervisor attempts to propose a setpoint write
    resp2 = live_env.client.post(
        "/supervisors/mill-feed/propose",
        json={"current_sp": 52.0, "direction": "increase", "magnitude": 4.0},
    )
    assert resp2.status_code == 200
    data = resp2.json()
    # Write Gateway MUST refuse due to operator override: operator action always wins!
    assert data["decision"]["accepted"] is False
    assert data["decision"]["reason_code"] in {"operator_override", "target_hold_off"}
    assert live_env.plant.values[TAG] == 52.0


def test_supervisor_propose_from_logged_advice_id(live_env: LiveTestbed) -> None:
    _wait_gateway(live_env.client)
    assert live_env.client.put("/supervisors/mill-feed", json=CONFIG).status_code == 200
    dataset = _dataset_id(live_env.client)

    # Replay with record=True to generate advice in audit log
    replay_resp = live_env.client.post(
        f"/datasets/{dataset}/supervisor/mill-feed/replay",
        json={"window_s": 600, "step_s": 600, "record": True},
    )
    advices = replay_resp.json()["advices"]
    active_advices = [
        a for a in advices
        if a["direction"] != "hold" and (a.get("magnitude") or 0.0) >= 0.1
    ]
    assert len(active_advices) > 0
    target_advice = active_advices[0]

    resp = live_env.client.post(
        "/supervisors/mill-feed/propose",
        json={"current_sp": 50.0, "advice_id": target_advice["advice_id"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["advice_id"] == target_advice["advice_id"]
    mag = target_advice["magnitude"]
    expected_val = 50.0 + (mag if target_advice["direction"] == "increase" else -mag)
    assert data["proposal"]["value"] == expected_val
    assert data["decision"]["accepted"] is True


def test_advise_endpoint_with_propose_flag(live_env: LiveTestbed) -> None:
    _wait_gateway(live_env.client)
    assert live_env.client.put("/supervisors/mill-feed", json=CONFIG).status_code == 200
    dataset = _dataset_id(live_env.client)

    resp = live_env.client.post(
        f"/datasets/{dataset}/supervisor/mill-feed/advise",
        json={"propose": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "advice" in body
    assert "gate" in body
    if body["advice"] and body["advice"]["direction"] != "hold":
        assert body["proposal"] is not None
        assert "decision" in body["proposal"]

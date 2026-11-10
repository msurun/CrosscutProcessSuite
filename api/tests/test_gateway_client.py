"""End-to-end tests of the file-mailbox gateway client (Phase 2, #46).

A real GatewayService thread drives a real WriteGateway on a simulated plant under
tmp_path; the HTTP API talks to it only through the files under <root>/_gateway/.
Every test proves one behaviour of that handshake, including the failure paths.
"""

from __future__ import annotations

import ast
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from auth_support import write_key_file
from crosscut_api.auth.actor import local_actor
from crosscut_api.gateway_client import FileGatewayClient, gateway_provider
from crosscut_api.gateway_routes import build_gateway_router
from crosscut_gateway.engine import WriteGateway
from crosscut_gateway.interfaces import WritePolicy
from crosscut_gateway.service import GatewayService, serve
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from open_app import create_app_without_auth

TAG ="FIC101.SP"
SECOND_NS = 1_000_000_000
WAIT_TIMEOUT_S = 3.0
POLL_INTERVAL_S = 0.02
SERVICE_INTERVAL_S = 0.02
# The state file is rewritten every poll; older than this means the gateway is dead.
STALE_STATE_AGE_S = 0.2
# Long enough for the stale-state check to see the last write as old.
STALE_SLEEP_S = 0.4
COMMAND_TIMEOUT_S = 0.3
# The API ships a cached client; a per-request fresh client avoids stale in-memory state.
FRESH_STATE_AGE_S = 60.0
# Modules the API must not import: the gateway runs as a separate process.
FORBIDDEN_MODULES = ("crosscut_gateway", "asyncua", "opcua")

POLICY = WritePolicy(
    limits=(0.0, 100.0),
    max_step=10.0,
    max_rate_per_s=5.0,
    min_interval_s=1.0,
    allowed_loop_modes=("CAS",),
    hold_off_s=60.0,
    watchdog_s=5.0,
    readback_tolerance=0.5,
)


class SimPlant:
    """Deterministic simulated control system; time comes from the real clock around it."""

    def __init__(self) -> None:
        """One loop in CAS mode holding the setpoint remotely (as after a write)."""
        self.values = {TAG: 50.0}
        self.modes = {TAG: "CAS"}
        self.remote = True
        self.last_hb_ns: int | None = None
        self.writes: list[tuple[int, str, float]] = []
        self.refuse = False

    def read(self, tag: str) -> float:
        """Return the current value of tag."""
        return self.values[tag]

    def write(self, tag: str, value: float) -> bool:
        """Accept a write unless refused or the loop left CAS."""
        if self.refuse or self.modes[tag] != "CAS":
            return False
        self.values[tag] = value
        self.remote = True
        self.writes.append((time.time_ns(), tag, value))
        return True

    def heartbeat_seen(self) -> bool:
        """True while the last heartbeat is younger than the watchdog period."""
        if self.last_hb_ns is None:
            return False
        return time.time_ns() - self.last_hb_ns <= POLICY.watchdog_s * SECOND_NS

    def send_heartbeat(self) -> None:
        """Record a heartbeat at the current time."""
        self.last_hb_ns = time.time_ns()

    def loop_mode(self, tag: str) -> str:
        """Return the current loop mode of tag."""
        return self.modes[tag]

    def setpoint_source(self, tag: str) -> str:
        """Return 'remote' while the gateway owns the setpoint, else 'local'."""
        return "remote" if self.remote else "local"

    def set_mode_by_operator(self, tag: str, mode: str) -> None:
        """Change the loop mode; leaving CAS returns the setpoint to local."""
        self.modes[tag] = mode
        if mode != "CAS":
            self.remote = False

    def set_setpoint_by_operator(self, tag: str, value: float) -> None:
        """Take the setpoint back with a new operator value."""
        self.values[tag] = value
        self.remote = False

    def release(self, tag: str) -> None:
        """Hand the setpoint of tag back to local control."""
        self.remote = False


@dataclass
class LiveService:
    """Handles the running gateway thread, its API client and the shared plant."""

    client: TestClient
    plant: SimPlant
    root: Path
    stop_event: threading.Event
    thread: threading.Thread


def _run_service(root: Path, plant: SimPlant) -> tuple[threading.Event, threading.Thread]:
    """Start a gateway service thread on root; return its stop event and the thread."""
    service = GatewayService(root, WriteGateway(plant, {TAG: POLICY}, "confirm"))
    stop_event = threading.Event()
    thread = threading.Thread(
        target=serve, args=(service, SERVICE_INTERVAL_S, stop_event), daemon=True
    )
    thread.start()
    return stop_event, thread


def _fresh_client(root: Path) -> TestClient:
    """Build the real API app over ``root`` and return a test client for it."""
    return TestClient(create_app_without_auth(root))


def _install_signing_key(root: Path) -> Path:
    """Write a random 32-byte HMAC key under root/_secrets and return its path."""
    key_file = root / "_secrets" / "gateway-hmac.key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    write_key_file(key_file, os.urandom(32))
    return key_file


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LiveService:
    """A running gateway service, the API in front of it, and the shared plant."""
    monkeypatch.delenv("CROSSCUT_SECRETS_DIR", raising=False)
    _install_signing_key(tmp_path)
    plant = SimPlant()
    stop_event, thread = _run_service(tmp_path, plant)
    client = _fresh_client(tmp_path)
    service = LiveService(client, plant, tmp_path, stop_event, thread)
    yield service
    stop_event.set()
    thread.join(timeout=WAIT_TIMEOUT_S)


def _poll(probe: Callable[[], Any], describe: str) -> Any:
    """Return the first truthy result of probe() within WAIT_TIMEOUT_S, else fail."""
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(POLL_INTERVAL_S)
    pytest.fail(f"timed out waiting for {describe}")


def _status_response(client: TestClient) -> Response:
    """Return the GET /gateway/status response, whatever its status code."""
    return client.get("/gateway/status")


def _wait_status(client: TestClient) -> dict:
    """Return the status payload once the gateway answers 200 (it needs one tick first)."""
    return _poll(lambda: _status_payload(client), "GET /gateway/status to answer 200")


def _status_payload(client: TestClient) -> dict:
    """Return the status payload when the response is 200, else an empty dict."""
    response = _status_response(client)
    return response.json() if response.status_code == 200 else {}


def _propose(root: Path, value: float) -> str:
    """Write one propose command into the inbox atomically and return its id."""
    inbox_dir = root / "_gateway" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    cmd_id = f"p{time.time_ns()}"
    args = {
        "target_tag": TAG,
        "value": float(value),
        "proposer": "test",
        "t_ns": time.time_ns(),
        "reason": "test",
    }
    temp_path = inbox_dir / f"{cmd_id}.tmp"
    temp_path.write_text(json.dumps({"id": cmd_id, "cmd": "propose", "args": args}))
    os.replace(temp_path, inbox_dir / f"{cmd_id}.json")
    return cmd_id


def _pending_entries(client: TestClient) -> list[dict]:
    """Return the pending proposals, or an empty list while none is queued."""
    response = client.get("/gateway/pending")
    return response.json() if response.status_code == 200 else []


def _wait_pending_key(client: TestClient) -> str:
    """Return the key of the first pending proposal once the queue is non-empty."""
    entries = _poll(lambda: _pending_entries(client), "a proposal to appear in /gateway/pending")
    assert entries[0]["key"], "pending entry has no key"
    return str(entries[0]["key"])


def _approve(client: TestClient, root: Path, value: float) -> str:
    """Propose value, wait for it to be queued and approve it; return the proposal key."""
    _wait_status(client)
    _propose(root, value)
    key = _wait_pending_key(client)
    response = client.post(f"/gateway/pending/{key}/approve")
    assert response.status_code == 200
    return key


def _wait_for_write(plant: SimPlant) -> None:
    """Block until the plant has recorded exactly one write, then require exactly one."""
    _poll(lambda: len(plant.writes) >= 1, "the approved write to reach the plant")
    assert len(plant.writes) == 1


def test_status_is_served_while_the_gateway_is_alive(live: LiveService) -> None:
    """A running gateway makes GET /gateway/status answer 200 in confirm mode."""
    status = _wait_status(live.client)
    assert status["mode"] == "confirm"


def test_status_returns_503_when_the_state_file_is_stale(live: LiveService) -> None:
    """After the gateway thread stops, a provider with a short max age reports 503."""
    live.stop_event.set()
    live.thread.join(timeout=WAIT_TIMEOUT_S)
    time.sleep(STALE_SLEEP_S)
    app = FastAPI()
    app.include_router(build_gateway_router(gateway_provider(live.root, STALE_STATE_AGE_S)))
    assert TestClient(app).get("/gateway/status").status_code == 503


def test_approve_writes_once_and_the_key_is_then_gone(live: LiveService) -> None:
    """Approving a queued proposal writes once; approving the same key again is 404."""
    key = _approve(live.client, live.root, 55.0)
    _wait_for_write(live.plant)
    again = live.client.post(f"/gateway/pending/{key}/approve")
    assert again.status_code == 404


def _killed_targets(client: TestClient) -> dict:
    """Return the target states once TAG is killed, else an empty dict."""
    response = client.get("/gateway/status")
    targets = response.json()["targets"]
    return targets if targets.get(TAG) == "killed" else {}


def _wait_for_kill_record(client: TestClient) -> dict:
    """Return the audit payload once it holds a kill record, else fail."""
    return _poll(lambda: _audit_with_kill(client), "a kill record in the audit tail")


def _audit_with_kill(client: TestClient) -> dict:
    """Return the audit payload when it contains a kill event, else an empty dict."""
    payload = client.get("/gateway/audit?limit=200").json()
    if any(record["event"] == "kill" for record in payload["records"]):
        return payload
    return {}


def test_mv_availability_round_trips_through_the_mailbox(live: LiveService) -> None:
    """The route asks the real gateway: confirm mode, CAS loop: known target available."""
    _wait_status(live.client)
    response = live.client.get(
        "/gateway/mv-availability", params=[("targets", TAG), ("targets", "NOPE")]
    )
    assert response.status_code == 200
    body = response.json()
    assert body[TAG] == {"available": True, "reasons": []}
    assert body["NOPE"] == {"available": False, "reasons": ["unknown_target"]}


def test_kill_is_published_in_the_audit_tail(live: LiveService) -> None:
    """Kill makes the state report the target killed, releases the plant and is logged."""
    _approve(live.client, live.root, 55.0)
    assert live.client.post("/gateway/kill").status_code == 200
    targets = _poll(lambda: _killed_targets(live.client), "the target to be killed")
    assert targets[TAG] == "killed"
    audit = _wait_for_kill_record(live.client)
    assert audit["chain_ok"] is True
    assert live.plant.remote is False


def test_approving_an_unknown_key_returns_404(live: LiveService) -> None:
    """An approve request for a key nobody queued is reported as not found."""
    _wait_status(live.client)
    response = live.client.post("/gateway/pending/no-such-key/approve")
    assert response.status_code == 404


def test_re_enable_rejects_unknown_and_killed_targets(live: LiveService) -> None:
    """Re-enabling an unknown tag is 404; re-enabling a killed tag is 409."""
    _wait_status(live.client)
    unknown = live.client.post("/gateway/targets/NOPE/re-enable")
    assert unknown.status_code == 404
    live.client.post("/gateway/kill")
    _poll(lambda: _killed_targets(live.client), "the target to be killed")
    killed = live.client.post(f"/gateway/targets/{TAG}/re-enable")
    assert killed.status_code == 409


def _app_with_short_timeout(root: Path) -> FastAPI:
    """Build an app whose gateway client gives up after COMMAND_TIMEOUT_S."""
    provider = gateway_provider(root, max_age_s=FRESH_STATE_AGE_S)
    client = FileGatewayClient(root, timeout_s=COMMAND_TIMEOUT_S)
    app = FastAPI()
    app.include_router(build_gateway_router(lambda: client if provider() else None))
    return app


def test_command_without_service_times_out_as_504(tmp_path: Path) -> None:
    """With a fresh state file but no pump thread, a command times out as 504."""
    service = GatewayService(tmp_path, WriteGateway(SimPlant(), {TAG: POLICY}, "confirm"))
    service.poll_once()
    client = TestClient(_app_with_short_timeout(tmp_path))
    assert client.post("/gateway/kill").status_code == 504


def _mode_is(client: TestClient, expected: str) -> bool:
    """True when GET /gateway/status reports the expected mode."""
    response = client.get("/gateway/status")
    return response.json()["mode"] == expected


def test_put_mode_changes_the_published_mode(live: LiveService) -> None:
    """PUT /gateway/mode accepts a valid mode and the state then reports it."""
    _wait_status(live.client)
    response = live.client.put("/gateway/mode", json={"mode": "supervised"})
    assert response.status_code == 200
    _poll(lambda: _mode_is(live.client, "supervised"), "the mode to become supervised")


def test_file_gateway_client_propose_in_confirm_mode(live: LiveService) -> None:
    """FileGatewayClient.propose sends signed propose command and returns decision."""
    _wait_status(live.client)
    gw_client = FileGatewayClient(live.root)
    actor = local_actor("127.0.0.1")
    args = {
        "target_tag": TAG,
        "value": 55.0,
        "proposer": "test_actor",
        "t_ns": time.time_ns(),
        "reason": "Test proposal",
    }
    decision = gw_client.propose(args, actor)
    assert decision["accepted"] is True
    assert decision["reason_code"] == "queued"



def test_signed_command_without_key_file_answers_503(live: LiveService) -> None:
    """With no HMAC key file, approve answers 503 while kill is still sent unsigned."""
    _wait_status(live.client)
    (live.root / "_secrets" / "gateway-hmac.key").unlink()
    assert live.client.post("/gateway/pending/x/approve").status_code == 503
    assert live.client.post("/gateway/kill").status_code != 503


def _imported_roots(node: ast.AST) -> list[str]:
    """Return the root module names imported by one AST node, empty for other nodes."""
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [(node.module or "").split(".")[0]]
    return []


def test_client_module_imports_no_gateway_code() -> None:
    """gateway_client must stay free of the gateway and OPC UA modules (separate process)."""
    source = Path(__file__).resolve().parents[1] / "src" / "crosscut_api" / "gateway_client.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = [name for node in ast.walk(tree) for name in _imported_roots(node)]
    assert not [name for name in imported if name in FORBIDDEN_MODULES]

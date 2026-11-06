"""Start the real Write Gateway stack for the live e2e spec (Phase 2 exit criterion, L5).

Usage: python start_gateway_stack.py --root <data root with the gateway key>

Starts a local asyncua server with the writable nodes of one target, a small HTTP control
channel on 127.0.0.1 (read the nodes, simulate an operator takeover), writes the plant map, the
write policy and its signed pin (two different signers) under the data root and starts
`python -m crosscut_gateway` in advisory mode. Prints one JSON line with the endpoints and paths,
then runs until stdin closes or it is terminated; everything is stopped on exit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from asyncua import Server, ua
from crosscut_gateway.keyfile import default_key_path, read_key
from crosscut_gateway.policy_pin import PinRequest, PinSigners, install_policy_with_pin
from make_tuning_dataset import main as make_tuning_dataset
from tuning_stack import (
    TUNING_NODES,
    install_site_and_jobs,
    plant_map_targets,
    policy_targets,
    simulate,
    tuning_info,
)

TAG = "E2E.FIC1.SP"
NAMESPACE_URI = "urn:crosscut:e2e-gateway"
MODE_VALUES = {"MAN": 0, "AUTO": 1, "CAS": 2}
SOURCE_LOCAL, SOURCE_REMOTE = 0, 1
INITIAL_SETPOINT = 50.0
# name -> (initial value, variant type); the read-back is the setpoint node (runbook section 7).
NODES: dict[str, tuple[Any, ua.VariantType]] = {
    "setpoint": (INITIAL_SETPOINT, ua.VariantType.Double),
    "mode": (MODE_VALUES["CAS"], ua.VariantType.Int32),
    "source": (SOURCE_LOCAL, ua.VariantType.Int32),
    "heartbeat": (0, ua.VariantType.Int64),
    **TUNING_NODES,
}
POLICY_TARGET = {
    "limits": [0.0, 60.0],
    "max_step": 5.0,
    "max_rate_per_s": 5.0,
    "min_interval_s": 1.0,
    "allowed_loop_modes": ["CAS"],
    "hold_off_s": 8.0,
    "watchdog_s": 600.0,
    "readback_tolerance": 0.5,
}
GATEWAY_INTERVAL_S = 0.5
# The policy mode is the cap of the gateway: supervised lets the tuning spec show that a parameter
# set is still queued there (KIND_MODE_CAP); every setpoint test starts in advisory as before.
POLICY_MODE_CAP = "supervised"


def free_port() -> int:
    """Return a localhost TCP port that was free when asked for."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class PlantServer:
    """asyncua server with the target nodes, running on its own event loop thread."""

    def __init__(self, port: int) -> None:
        self.endpoint = f"opc.tcp://127.0.0.1:{port}"
        self.index = 0
        self._nodes: dict[str, Any] = {}
        self._server: Server | None = None
        self._sim_task: asyncio.Future[None] | None = None
        self.sim_started = (0.0, 0.0)  # (monotonic, wall clock) of the process simulation start
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def _run(self, coro: Any) -> Any:
        """Run a coroutine on the server loop and return its result."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=10)

    def node_id(self, name: str) -> str:
        """Return the text NodeId of a node in the plant namespace."""
        return f"ns={self.index};s=E2E.{name}"

    def start(self) -> None:
        """Build the address space and start listening."""
        self._run(self._build())

    async def _build(self) -> None:
        """Create the server, the namespace and every writable node."""
        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        self.index = await server.register_namespace(NAMESPACE_URI)
        folder = await server.nodes.objects.add_object(self.node_id("Plant"), "Plant")
        for name, (initial, vtype) in NODES.items():
            node = await folder.add_variable(self.node_id(name), name, initial, vtype)
            await node.set_writable()
            self._nodes[name] = node
        await server.start()
        self._server = server
        self.sim_started = (time.monotonic(), time.time())
        self._sim_task = asyncio.ensure_future(simulate(self._nodes, self.sim_started[0]))

    def get(self, name: str) -> Any:
        """Read a node value on the server side."""
        return self._run(self._nodes[name].read_value())

    def set(self, name: str, value: Any) -> None:
        """Write a node value on the server side, keeping the node's declared type."""
        variant = ua.Variant(value, NODES[name][1])
        self._run(self._nodes[name].write_value(ua.DataValue(variant)))

    def snapshot(self) -> dict[str, Any]:
        """Return every node value by name."""
        return {name: self.get(name) for name in NODES}

    def stop(self) -> None:
        """Stop the server and its loop thread."""
        if self._sim_task is not None:
            self._loop.call_soon_threadsafe(self._sim_task.cancel)
        if self._server is not None:
            self._run(self._server.stop())
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)


def _handler_for(plant: PlantServer) -> type[BaseHTTPRequestHandler]:
    """Build the request handler class of the control channel for one plant server."""

    class Handler(BaseHTTPRequestHandler):
        """GET /nodes, POST /takeover, POST /set {"name", "value"}."""

        def _reply(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            """Return the node values."""
            if self.path == "/nodes":
                self._reply(plant.snapshot())
            else:
                self._reply({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            """Simulate an operator takeover or set a node."""
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/takeover":
                plant.set("source", SOURCE_LOCAL)
            elif self.path == "/set" and body.get("name") in NODES:
                plant.set(body["name"], body["value"])
            else:
                self._reply({"error": "not found"}, 404)
                return
            self._reply(plant.snapshot())

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            """Keep the test output quiet."""

    return Handler


def plant_map(plant: PlantServer) -> dict[str, Any]:
    """Return the plant map of the one target, pointing at the local server."""
    return {
        "version": 1,
        "endpoint": plant.endpoint,
        "heartbeat": {"node": plant.node_id("heartbeat"), "period_s": 0.2},
        "targets": {
            **plant_map_targets(plant.node_id),
            TAG: {
                "setpoint_node": plant.node_id("setpoint"),
                "readback_node": plant.node_id("setpoint"),
                "mode_node": plant.node_id("mode"),
                "source_node": plant.node_id("source"),
                "remote_value": SOURCE_REMOTE,
                "local_value": SOURCE_LOCAL,
                "release_value": SOURCE_LOCAL,
                "mode_values": MODE_VALUES,
                "take_remote": {
                    "node": plant.node_id("source"),
                    "value": SOURCE_REMOTE,
                    "before_setpoint": True,
                },
            }
        },
    }


def install_files(root: Path, plant: PlantServer) -> tuple[Path, Path]:
    """Write the plant map and the pinned policy under `root`; return their paths."""
    key = read_key(default_key_path(root))
    if key is None:
        raise SystemExit("gateway key missing: run auth_cli init first")
    plant_map_path = root / "plant-map.json"
    plant_map_path.write_text(json.dumps(plant_map(plant), indent=2), encoding="utf-8")
    policy_path = root / "_gateway" / "policy" / "write-policy.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    targets = {TAG: POLICY_TARGET, **policy_targets()}
    document = {"version": 1, "mode": POLICY_MODE_CAP, "targets": targets}
    signers = PinSigners("e2e-policy-author", "e2e-policy-approver")
    install_policy_with_pin(PinRequest(policy_path, document, key, signers, datetime.now(UTC)))
    return plant_map_path, policy_path


def start_gateway(root: Path, policy: Path, plant_map_path: Path) -> subprocess.Popen[bytes]:
    """Start the gateway process in advisory mode."""
    command = [
        sys.executable, "-m", "crosscut_gateway", "--root", str(root), "--policy", str(policy),
        "--plant-map", str(plant_map_path), "--mode", "advisory",
        "--interval", str(GATEWAY_INTERVAL_S), "--timeout", "5",
    ]  # fmt: skip
    return subprocess.Popen(command)


def wait_for_state(root: Path, gateway: subprocess.Popen[bytes]) -> None:
    """Wait until the gateway has written a state with a good key and policy."""
    state_path = root / "_gateway" / "state.json"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if gateway.poll() is not None:
            raise SystemExit(f"gateway exited early (code {gateway.returncode})")
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("auth") == "ok" and state.get("policy") is not None:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise SystemExit("gateway did not write a usable state.json")


def stop_gateway(gateway: subprocess.Popen[bytes]) -> None:
    """Terminate the gateway process, killing it when it does not stop in time."""
    if gateway.poll() is not None:
        return
    gateway.terminate()
    try:
        gateway.wait(timeout=10)
    except subprocess.TimeoutExpired:
        gateway.kill()


def main() -> int:
    """Start the stack, print its description and wait until stdin closes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    root = parser.parse_args().root
    plant = PlantServer(free_port())
    control = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(plant))
    gateway: subprocess.Popen[bytes] | None = None
    try:
        plant.start()
        threading.Thread(target=control.serve_forever, daemon=True).start()
        make_tuning_dataset(root)
        install_site_and_jobs(root, plant.endpoint, plant.node_id)
        plant_map_path, policy_path = install_files(root, plant)
        gateway = start_gateway(root, policy_path, plant_map_path)
        wait_for_state(root, gateway)
        info = {
            "tag": TAG,
            "opcua_endpoint": plant.endpoint,
            "control_url": f"http://127.0.0.1:{control.server_address[1]}",
            "root": str(root),
            "policy": str(policy_path),
            "plant_map": str(plant_map_path),
            "initial_setpoint": INITIAL_SETPOINT,
            "hold_off_s": POLICY_TARGET["hold_off_s"],
            "tuning": tuning_info(plant.sim_started[1]),
        }
        print(json.dumps(info), flush=True)
        sys.stdin.read()  # returns at EOF: the launcher closed our stdin or exited
        return 0
    finally:
        control.shutdown()
        if gateway is not None:
            stop_gateway(gateway)
        plant.stop()


if __name__ == "__main__":
    raise SystemExit(main())

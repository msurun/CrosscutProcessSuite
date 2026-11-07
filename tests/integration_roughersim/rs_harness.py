"""Harness for the L5 gateway rows: a RougherSim OPC UA server plus the real Crosscut adapter.

``rs_server`` starts ``roughersim serve`` as a subprocess on a free port and always stops it.
``Harness`` wraps ``OpcUaPlant`` (the real adapter) for the engine, counts accepted writes and
reads the simulation clock (``Application/System/TimeS``). RougherSim has no step API, so
"advancing time" means waiting until TimeS has moved (server speed = sim seconds per wall second).
"""

from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from crosscut_gateway.opcua_plant import OpcUaPlant
from golden import roughersim_dir, venv_python

PLANT_MAP = Path(__file__).parent / "plant_maps" / "rougher_fic203.json"
TIME_NODE = "nsu=urn:roughersim:abb800xa;s=Application/System/TimeS"
CLOCK_TAG = "SIM.TIME"
SETPOINT_TAG = "FIC203.RSP"
STEP_S = 5.0  # RougherSim plant step (examples/rougher_mvp.json dt_s)
S = 1_000_000_000
START_TIMEOUT_S = 60.0
SERVE = "import sys; from roughersim.cli import main; sys.exit(main(sys.argv[1:]))"


def free_port() -> int:
    """A currently free TCP port on localhost."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve_command(rs_dir: Path, port: int, speed: float, watchdog_s: float) -> list[str]:
    """Command line of ``roughersim serve`` for the MVP plant."""
    return [
        str(venv_python(rs_dir)), "-c", SERVE, "serve", str(rs_dir / "examples/rougher_mvp.json"),
        "--port", str(port), "--speed", str(speed), "--watchdog-s", str(watchdog_s),
    ]


def _stop(proc: subprocess.Popen[bytes]) -> None:
    """Stop the server and its children (a venv python.exe on Windows spawns the real one)."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@contextmanager
def rs_server(
    log: Path, hooks: str | None, speed: float, watchdog_s: float = 4.0
) -> Iterator[int]:
    """Run the RougherSim server for the duration of the block; yields its port."""
    rs_dir, port = roughersim_dir(), free_port()
    cmd = _serve_command(rs_dir, port, speed, watchdog_s)
    if hooks:
        cmd += ["--hooks", hooks]
    env = {**os.environ, "PYTHONPATH": str(rs_dir / "src")}
    with log.open("wb") as sink:
        proc = subprocess.Popen(cmd, cwd=rs_dir, env=env, stdout=sink, stderr=sink)
        try:
            yield port
        finally:
            _stop(proc)


def plant_map_for(port: int) -> dict[str, Any]:
    """The rougher_fic203 plant map aimed at ``port``, plus a read-only clock target."""
    data: dict[str, Any] = json.loads(PLANT_MAP.read_text(encoding="utf-8"))
    data["endpoint"] = f"opc.tcp://127.0.0.1:{port}"
    clock = copy.deepcopy(data["targets"][SETPOINT_TAG])
    clock["readback_node"] = TIME_NODE
    data["targets"][CLOCK_TAG] = clock
    return data


class Harness:
    """ControlSystem for the engine: the real OpcUaPlant, a write counter and a sim clock."""

    def __init__(self, plant_map: dict[str, Any], speed: float) -> None:
        """Open the adapter on ``plant_map``; ``speed`` is the server's sim s per wall s."""
        self.plant = OpcUaPlant(plant_map)
        self.speed = speed
        self.writes: list[tuple[int, str, float]] = []

    def close(self) -> None:
        """Close the adapter."""
        self.plant.close()

    def wait_ready(self) -> None:
        """Block until the server answers, then prime its heartbeat watchdog."""
        deadline = time.monotonic() + START_TIMEOUT_S
        while True:
            try:
                self.now_ns()
                break
            except (ConnectionError, TimeoutError, OSError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.3)
        self.plant.send_heartbeat()

    def now_ns(self) -> int:
        """Simulation time in ns (TimeS of the server)."""
        return int(self.plant.read(CLOCK_TAG) * S)

    def advance(self, seconds: float) -> None:
        """Wait until the simulation clock moved by ``seconds``, keeping the heartbeat alive."""
        self.wait_until_ns(self.now_ns() + int(seconds * S))

    def wait_until_ns(self, target_ns: int) -> None:
        """Wait until sim time reaches ``target_ns`` (heartbeat sent while waiting)."""
        deadline = time.monotonic() + (target_ns - self.now_ns()) / S / self.speed + 20.0
        while self.now_ns() < target_ns:
            self.plant.send_heartbeat()
            if time.monotonic() > deadline:
                raise TimeoutError("simulation clock did not advance")
            time.sleep(0.05)

    # --- ControlSystem protocol (delegates to the real adapter) ---------------------------

    def read(self, tag: str) -> float:
        """Read-back value of ``tag``."""
        return self.plant.read(tag)

    def write(self, tag: str, value: float) -> bool:
        """Write through the adapter; count the write when the server accepted it."""
        accepted = self.plant.write(tag, value)
        if accepted:
            self.writes.append((self.now_ns(), tag, value))
        return accepted

    def heartbeat_seen(self) -> bool:
        """Whether the DCS acknowledges the heartbeat."""
        return self.plant.heartbeat_seen()

    def send_heartbeat(self) -> None:
        """Send the heartbeat counter."""
        self.plant.send_heartbeat()

    def loop_mode(self, tag: str) -> str:
        """Mode name of the loop of ``tag``."""
        return self.plant.loop_mode(tag)

    def setpoint_source(self, tag: str) -> str:
        """``remote`` while the loop is in RSP, else ``local``."""
        return self.plant.setpoint_source(tag)

    def release(self, tag: str) -> None:
        """Give the loop back (release_value of the plant map; CAS for FIC203)."""
        self.plant.release(tag)

    # --- ParamControlSystem (PID parameters, Double nodes) --------------------------------

    def read_param(self, tag: str) -> float:
        """Read-back of a pid_param target."""
        return self.plant.read_param(tag)

    def write_param(self, tag: str, value: float) -> bool:
        """Write a pid_param target as Double."""
        return self.plant.write_param(tag, value)

    def param_data_type(self, tag: str) -> str:
        """Configured data type of a pid_param target."""
        return self.plant.param_data_type(tag)

    def param_tags(self) -> frozenset[str]:
        """Tags of the pid_param targets."""
        return self.plant.param_tags()

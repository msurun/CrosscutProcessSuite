"""Start the plant side of the no-code L5 acceptance run (#151): live RougherSim plus the gateway.

Usage: python start_l5_stack.py --root <empty data root with the gateway key>

The browser spec builds the project itself (source, catalogue, KPI job, tuning), so this rig
provides only what a plant would already have: the pinned `roughersim serve` OPC UA server, a
history extract of the loop (a step test recorded by RougherSim, imported as a dataset whose tag
ids are the ones the catalogue wizard proposes), and the Write Gateway with its plant map and
signed policy (the plant owner's file, as in production). No site.json, jobs.json or proposal
is written here. Prints one JSON line with the endpoints, then runs until stdin closes.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RS_TESTS = HERE.parents[2] / "tests" / "integration_roughersim"
sys.path.insert(0, str(RS_TESTS))

from asyncua.sync import Client  # noqa: E402
from crosscut_connectors.csv_import import import_csv  # noqa: E402
from crosscut_gateway.keyfile import default_key_path, read_key  # noqa: E402
from crosscut_gateway.policy_pin import PinRequest, PinSigners, install_policy_with_pin  # noqa: E402
from golden import checkout_problem, load_pin, roughersim_dir, venv_python  # noqa: E402
from rs_harness import rs_server  # noqa: E402

LOOP = "FIC203"
GAIN_TAG, TI_TAG = f"{LOOP}.Gain", f"{LOOP}.Ti"
DATASET_ID = "l5_fic203"
NS = "nsu=urn:roughersim:abb800xa;s=Application/Loop"
SERVE_SPEED = 20.0
SAMPLE_S = 5.0  # history sample period: the plant step of RougherSim, so a 5 s loop is visible
WARMUP_S = 21600  # the scenario's warm-up: the run duration includes it, the recording does not
RECORD_S = 24000  # recorded seconds: lead-in, the MAN step test of the scenario and its return
RECORD_CODE = """
import sys
from dataclasses import replace
from pathlib import Path
from roughersim.scenario.loader import load_scenario
from roughersim.scenario.runner import run_loaded
scenario = load_scenario(Path('scenarios/rs.step_test.fic203.v1.json'))
run_loaded(replace(scenario, sample_period_s=float(sys.argv[2]), duration_s=int(sys.argv[3])),
           Path(sys.argv[1]))
"""
FIELDS = ("Gain", "Ti", "Pv", "Sp", "Rsp", "Out", "Mode")
MODE_VALUES = {"MAN": 0, "AUTO": 1, "CAS": 2, "RSP": 3}
POLICY = {
    "limits_gain": [0.001, 500.0],
    "limits_ti": [1.0, 20000.0],
    "max_ratio": 100.0,
    "min_interval_s": 60.0,
}
GATEWAY_INTERVAL_S = 0.5
POLICY_MODE_CAP = "supervised"
INITIAL_TUNING = {"gain": 0.3, "ti": 10.0}  # RougherSim's own FIC203 settings (rougher_mvp.json)


def _node(field: str) -> str:
    """Text NodeId of one FIC203 field (by namespace URI, as the gateway plant map has it)."""
    return f"{NS}/{LOOP}/{field}"


def _client_node(field: str) -> str:
    """NodeId of one FIC203 field for this rig's own client (namespace index 2 of RougherSim)."""
    return f"ns=2;s=Application/Loop/{LOOP}/{field}"


def _param_target(field: str) -> dict[str, Any]:
    """Plant map entry of one controller parameter (a Double node of the RougherSim loop)."""
    return {
        "param_node": _node(field), "readback_node": _node(field), "data_type": "Double",
        "mode_node": _node("Mode"), "mode_values": MODE_VALUES,
    }


def plant_map(port: int) -> dict[str, Any]:
    """The plant map: the two FIC203 parameters, aimed at the running server."""
    system = "nsu=urn:roughersim:abb800xa;s=Application/System"
    return {
        "version": 1,
        "endpoint": f"opc.tcp://127.0.0.1:{port}",
        "heartbeat": {
            "node": f"{system}/Heartbeat", "period_s": 0.2, "ack_node": f"{system}/HeartbeatOk",
        },
        "targets": {GAIN_TAG: _param_target("Gain"), TI_TAG: _param_target("Ti")},
    }


def _param_policy(param: str, unit: str, limits: list[float]) -> dict[str, Any]:
    """One pid_param policy target of FIC203 (refuse, never clamp)."""
    return {
        "kind": "pid_param", "loop": LOOP, "param": param, "unit": unit,
        "vendor_form": "siemens_pid_compact", "limits": limits, "max_ratio": POLICY["max_ratio"],
        "readback_tolerance": 0.001, "min_interval_s": POLICY["min_interval_s"],
        "allowed_loop_modes": ["MAN", "AUTO", "CAS", "RSP"],
    }  # fmt: skip


def install_gateway_files(root: Path, port: int) -> tuple[Path, Path]:
    """Write the plant map and the pinned policy under `root`; return their paths."""
    key = read_key(default_key_path(root))
    if key is None:
        raise SystemExit("gateway key missing: run auth_cli init first")
    plant_map_path = root / "plant-map.json"
    plant_map_path.write_text(json.dumps(plant_map(port), indent=2), encoding="utf-8")
    policy_path = root / "_gateway" / "policy" / "write-policy.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    targets = {
        GAIN_TAG: _param_policy("gain", "OUT/PV", POLICY["limits_gain"]),
        TI_TAG: _param_policy("ti", "s", POLICY["limits_ti"]),
    }
    document = {
        "version": 1, "mode": POLICY_MODE_CAP, "allow_take_remote": False, "targets": targets,
    }
    signers = PinSigners("l5-policy-author", "l5-policy-approver")
    install_policy_with_pin(PinRequest(policy_path, document, key, signers, datetime.now(UTC)))
    return plant_map_path, policy_path


def record_history(work: Path) -> Path:
    """Record the FIC203 step test with RougherSim's interpreter; return the recording folder."""
    rs_dir = roughersim_dir().resolve()
    out = work / "recording"
    duration = str(WARMUP_S + RECORD_S)
    command = [str(venv_python(rs_dir)), "-c", RECORD_CODE, str(out), str(SAMPLE_S), duration]
    env = {**os.environ, "PYTHONPATH": str(rs_dir / "src")}
    subprocess.run(command, cwd=rs_dir, env=env, check=True, capture_output=True, text=True)
    return out


def _series(recording: Path) -> dict[str, dict[int, float]]:
    """Value by timestamp (ns) for the four FIC203 channels of a recording."""
    import pyarrow as pa
    import pyarrow.parquet as parquet

    paths = sorted((recording / "data").rglob("*.parquet"))
    table = pa.concat_tables([parquet.read_table(path) for path in paths])
    stamps = table["ts"].cast(pa.timestamp("ns", tz="UTC")).cast(pa.int64()).to_pylist()
    tags, values = table["tag_id"].to_pylist(), table["value"].to_pylist()
    wanted = {LOOP: "Pv", f"{LOOP}_sp": "Sp", f"{LOOP}_out": "Out", f"{LOOP}_mode": "Mode"}
    series: dict[str, dict[int, float]] = {name: {} for name in wanted.values()}
    for stamp, tag, value in zip(stamps, tags, values, strict=True):
        if tag in wanted:
            series[wanted[tag]][stamp] = float(value)
    return series


def write_history_csv(recording: Path, target: Path) -> None:
    """Wide CSV of the loop; the columns carry the tag ids the catalogue wizard proposes."""
    series = _series(recording)
    stamps = sorted(series["Pv"])
    start = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", *(f"{LOOP}.{name}" for name in ("Pv", "Sp", "Out", "Mode"))])
        for stamp in stamps:
            when = start + timedelta(seconds=(stamp - stamps[0]) / 1e9)
            row = [series[name][stamp] for name in ("Pv", "Sp", "Out", "Mode")]
            writer.writerow([when.isoformat(), *(f"{value:.5f}" for value in row)])


def install_dataset(root: Path) -> None:
    """Record the step test and import it as the dataset the tuning view reads."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # L5_RECORDING reuses a finished recording of this scenario (local reruns, saves minutes).
        reused = os.environ.get("L5_RECORDING")
        recording = Path(reused) if reused else record_history(work)
        write_history_csv(recording, work / "history.csv")
        import_csv(work / "history.csv", root / DATASET_ID, dataset_id=DATASET_ID)


def read_nodes(port: int) -> dict[str, float]:
    """Live Gain, Ti, Pv, Sp, Out and Mode of FIC203 read straight from the server."""
    client = Client(f"opc.tcp://127.0.0.1:{port}")
    client.connect()
    try:
        return {f: float(client.get_node(_client_node(f)).get_value()) for f in FIELDS}
    finally:
        client.disconnect()


def write_gain_ti(port: int, gain: float, ti: float) -> None:
    """Put the controller parameters of FIC203 on the server (the plant's own starting tuning)."""
    client = Client(f"opc.tcp://127.0.0.1:{port}")
    client.connect()
    try:
        for field, value in (("Gain", gain), ("Ti", ti)):
            client.get_node(_client_node(field)).set_value(value)
    finally:
        client.disconnect()


def _handler_for(port: int) -> type[BaseHTTPRequestHandler]:
    """Request handler of the read-only control channel (GET /nodes)."""

    class Handler(BaseHTTPRequestHandler):
        """GET /nodes: the live FIC203 values."""

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            """Return the node values as JSON."""
            body = json.dumps(read_nodes(port) if self.path == "/nodes" else {}).encode("utf-8")
            self.send_response(200 if self.path == "/nodes" else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            """Keep the test output quiet."""

    return Handler


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


def wait_for_server(port: int) -> None:
    """Block until the OPC UA server answers (a start takes several seconds)."""
    deadline = time.monotonic() + 60
    while True:
        try:
            read_nodes(port)
            return
        except Exception:  # noqa: BLE001 (any connect failure means: not up yet)
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def main() -> int:
    """Check the pin, start the plant and the gateway, print the description, wait for EOF."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    root = parser.parse_args().root
    problem = checkout_problem(roughersim_dir(), load_pin())
    if problem:
        raise SystemExit(f"RougherSim is not the pinned checkout: {problem}")
    with ExitStack() as stack:
        log = Path(tempfile.gettempdir()) / "l5-rs.log"
        port = stack.enter_context(rs_server(log, None, SERVE_SPEED, watchdog_s=600.0))
        wait_for_server(port)
        write_gain_ti(port, **INITIAL_TUNING)
        install_dataset(root)
        control = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(port))
        threading.Thread(target=control.serve_forever, daemon=True).start()
        stack.callback(control.shutdown)
        plant_map_path, policy_path = install_gateway_files(root, port)
        gateway = start_gateway(root, policy_path, plant_map_path)
        stack.callback(gateway.terminate)
        wait_for_state(root, gateway)
        info = {
            "root": str(root), "opcua_endpoint": f"opc.tcp://127.0.0.1:{port}",
            "control_url": f"http://127.0.0.1:{control.server_address[1]}",
            "loop": LOOP, "gain_tag": GAIN_TAG, "ti_tag": TI_TAG, "dataset": DATASET_ID,
            "initial_gain": INITIAL_TUNING["gain"], "initial_ti": INITIAL_TUNING["ti"],
        }
        print(json.dumps(info), flush=True)
        sys.stdin.read()  # returns at EOF: the launcher closed our stdin or exited
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Live demo: a scripted OPC UA client watches loop health while a plant runs with a fault.

It starts the simulated mill circuit as an OPC UA server (the same one UaExpert can browse),
connects to it like a DCS client would, steps a setpoint and prints the health of the loop
every few simulated minutes, computed with the same analysis the web UI uses. Run:
``python opcua/examples/live_demo.py --scenario stiction`` (see docs/LIVE_DEMO.md).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import socket
from dataclasses import dataclass, field

import numpy as np
from asyncua import Client
from crosscut_loops.overview import LoopTags, analyze_dataset
from crosscut_opcua.server import NAMESPACE_URI, PlantServer, ServerConfig
from crosscut_sim.core import Scenario
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario

LOOP = "hpgr_press"
SPEED = 100.0  # simulated seconds per wall-clock second; coarser sampling (> 15 s) hides stiction
TICK_S = 0.1  # wall-clock seconds per server tick; one client sample = SPEED * TICK_S = 10 sim s
SETPOINT_STEP = 1.0  # engineering units; a sticking valve hunts around a moved setpoint
STEP_AT_S = 1800.0  # the setpoint moves 30 min into the run
REPORT_EVERY_S = 3600.0  # print the health once per simulated hour
MIN_REPORT_S = 10800.0  # the first report comes after 3 h: stiction needs several limit cycles
DEFAULT_HOURS = 5.0
DEFAULT_BAND_PERCENT = 12.0  # a badly sticking valve: with full noise bands under 8 % are not found
JUMP_RATIO = 0.5  # slip jump as a fraction of the band (the simulator needs jump <= band)
SECONDS_PER_HOUR = 3600.0
CONNECT_TIMEOUT_S = 30.0


@dataclass
class Recording:
    """Samples of one loop collected from the server, one entry per client read."""

    t_s: list[float] = field(default_factory=list)
    values: dict[str, list[float]] = field(
        default_factory=lambda: {"pv": [], "sp": [], "out": [], "mode": []}
    )

    def add(self, time_s: float, sample: dict[str, float]) -> None:
        """Append one read of the four loop tags taken at plant time ``time_s``."""
        self.t_s.append(time_s)
        for key, value in sample.items():
            self.values[key].append(value)


def free_port() -> int:
    """A TCP port nobody listens on, so the demo never collides with another server."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def loop_tags() -> LoopTags:
    """The tag description of the demo loop, as the loop analysis expects it."""
    base = f"sim.mc.{LOOP}"
    return LoopTags(LOOP, base, f"{base}_sp", f"{base}_out", f"{base}_mode", "N/mm2", 0.0, 6.0)


def health_line(recording: Recording) -> str:
    """One text line with time, health, findings and the stiction verdict of the loop so far."""
    tags = loop_tags()
    columns = {
        tags.pv: np.array(recording.values["pv"]),
        tags.sp: np.array(recording.values["sp"]),
        tags.out: np.array(recording.values["out"]),
        tags.mode: np.array(recording.values["mode"]),
    }
    [row] = analyze_dataset(np.array(recording.t_s), columns, [tags])
    findings = ", ".join(finding["code"] for finding in row["findings"]) or "none"
    hours = recording.t_s[-1] / SECONDS_PER_HOUR
    return (
        f"t={hours:4.1f} h  health={row['health_percent']}%  status={row['status']}  "
        f"findings: {findings}  stiction verdict: {row['stiction_verdict']}"
    )


async def read_loop(client: Client, idx: int) -> dict[str, float]:
    """Read PV, SP, OUT and MODE of the demo loop from the server."""
    base = f"sim.mc.{LOOP}"
    names = {"pv": base, "sp": f"{base}_sp", "out": f"{base}_out", "mode": f"{base}_mode"}
    sample = {}
    for key, tag in names.items():
        sample[key] = float(await client.get_node(f"ns={idx};s={tag}").read_value())
    return sample


def with_valve_band(scenario: Scenario, band_percent: float) -> Scenario:
    """The scenario with the HPGR valve sticking by ``band_percent`` (0 keeps it as it is)."""
    if band_percent <= 0.0:
        return scenario
    params = dict(scenario.params)
    params[f"stiction_band_{LOOP}"] = band_percent
    params[f"stiction_jump_{LOOP}"] = band_percent * JUMP_RATIO
    return dataclasses.replace(scenario, params=tuple(params.items()))


async def run_demo(scenario_name: str, hours: float, band_percent: float) -> None:
    """Run the plant, step the setpoint and print the loop health once per simulated hour."""
    scenario = build_scenario("mill_circuit", scenario_name, duration_s=hours * SECONDS_PER_HOUR)
    scenario = with_valve_band(scenario, band_percent)
    config = ServerConfig(seed=1, port=free_port(), speed=SPEED, tick_s=TICK_S)
    async with PlantServer(MillCircuitPlant(), scenario, config) as server:
        async with Client(server.endpoint, timeout=CONNECT_TIMEOUT_S) as client:
            await watch(client, server, hours * SECONDS_PER_HOUR)


async def watch(client: Client, server: PlantServer, duration_s: float) -> None:
    """Sample the loop every tick until ``duration_s`` of plant time has passed."""
    idx = await client.get_namespace_index(NAMESPACE_URI)
    recording, stepped, next_report_s = Recording(), False, MIN_REPORT_S
    print(f"OPC UA endpoint {server.endpoint}  (browse it with UaExpert while this runs)")
    while server.plant.time_s < duration_s:
        await asyncio.sleep(TICK_S)
        sample = await read_loop(client, idx)
        recording.add(float(server.plant.time_s), sample)
        if not stepped and server.plant.time_s >= STEP_AT_S:
            setpoint = client.get_node(f"ns={idx};s=sim.mc.{LOOP}_sp")
            await setpoint.write_value(sample["sp"] + SETPOINT_STEP)
            stepped = True
            print(f"t={STEP_AT_S / SECONDS_PER_HOUR:4.1f} h  setpoint stepped by {SETPOINT_STEP}")
        if server.plant.time_s >= next_report_s:
            print(health_line(recording))
            next_report_s += REPORT_EVERY_S
    print("final:", health_line(recording))


def main() -> None:
    """Parse the command line and run the demo."""
    parser = argparse.ArgumentParser(description="Live OPC UA loop-health demo")
    parser.add_argument("--scenario", default="stiction", choices=("stiction", "nominal"))
    parser.add_argument("--hours", type=float, default=DEFAULT_HOURS, help="simulated hours to run")
    parser.add_argument("--band", type=float, default=None, help="valve stiction band in %%")
    args = parser.parse_args()
    default_band = DEFAULT_BAND_PERCENT if args.scenario == "stiction" else 0.0
    band = args.band if args.band is not None else default_band
    asyncio.run(run_demo(args.scenario, args.hours, band))


if __name__ == "__main__":
    main()

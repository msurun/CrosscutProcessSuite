"""Live demo: record a step test over OPC UA, tune the loop from it, retune and compare.

Three short runs of the simulated mill circuit, each served over OPC UA and read by a scripted
client: (1) the detuned loop answering a setpoint step, (2) an open-loop step test of the same
loop (the loop is in manual and the output is stepped), (3) the loop again with the gains that
the tuning report derived from the step test. Prints the loop health and the error integral
before and after. Tuning stays advisory: the demo applies the gains only to the simulator.
Run: ``python opcua/examples/retune_demo.py`` (see docs/LIVE_DEMO.md).
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass

import numpy as np
from asyncua import Client
from crosscut_loops.tuning_report import TuningReport, build_tuning_report
from crosscut_loops.tuning_view import suggest_windows
from crosscut_opcua.server import NAMESPACE_URI, PlantServer, ServerConfig
from crosscut_sim.core import Scenario
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario
from live_demo import LOOP, Recording, free_port, health_line, read_loop

SPEED = 50.0  # simulated seconds per wall-clock second; with the tick below, 5 s per sample
TICK_S = 0.1
SAMPLE_S = SPEED * TICK_S
SETPOINT_STEP = 1.0  # engineering units
SETPOINT_STEP_AT_S = 600.0
CLOSED_LOOP_S = 3600.0  # length of the two setpoint-step runs
STEP_TEST_S = 2400.0  # the step_test scenario raises OUT at 900 s and restores it at 2100 s
MIN_WINDOW_S = 600.0
MAX_WAIT_S = 600.0  # safety stop: wall-clock seconds one run may take
ROBUSTNESS = 0.5
SEED = 1


@dataclass(frozen=True)
class RunResult:
    """What one run produced: the recording and its error integral after the setpoint step."""

    recording: Recording
    iae: float


async def record(scenario: Scenario, duration_s: float, step_setpoint: bool) -> Recording:
    """Serve ``scenario`` over OPC UA and sample the loop until ``duration_s`` has passed."""
    config = ServerConfig(seed=SEED, port=free_port(), speed=SPEED, tick_s=TICK_S)
    recording = Recording()
    async with PlantServer(MillCircuitPlant(), scenario, config) as server:
        async with Client(server.endpoint, timeout=30.0) as client:
            idx = await client.get_namespace_index(NAMESPACE_URI)
            stepped = not step_setpoint
            while server.plant.time_s < duration_s:
                await asyncio.sleep(TICK_S)
                sample = await read_loop(client, idx)
                recording.add(float(server.plant.time_s), sample)
                if not stepped and server.plant.time_s >= SETPOINT_STEP_AT_S:
                    node = client.get_node(f"ns={idx};s=sim.mc.{LOOP}_sp")
                    await node.write_value(sample["sp"] + SETPOINT_STEP)
                    stepped = True
    return recording


def error_integral(recording: Recording) -> float:
    """Integral of |SP - PV| after the setpoint step, in engineering units times seconds."""
    t_s = np.array(recording.t_s)
    error = np.abs(np.array(recording.values["sp"]) - np.array(recording.values["pv"]))
    return float(np.sum(error[t_s >= SETPOINT_STEP_AT_S]) * SAMPLE_S)


def tuning_from_step_test(recording: Recording) -> TuningReport:
    """Identify the loop from the recorded open-loop step and return the tuning report."""
    t_s = np.array(recording.t_s)
    mode, out, pv = (np.array(recording.values[key]) for key in ("mode", "out", "pv"))
    windows = suggest_windows(t_s, mode, out, min_length_s=MIN_WINDOW_S)
    if not windows:
        raise RuntimeError("the step test left no usable window")
    start_s, end_s = windows[0]
    inside = (t_s >= start_s) & (t_s <= end_s)
    return build_tuning_report(LOOP, out[inside], pv[inside], SAMPLE_S, robustness=ROBUSTNESS)


def with_gains(scenario: Scenario, kc: float, ti_s: float) -> Scenario:
    """The scenario with the demo loop's proportional gain and integral time replaced."""
    params = dict(scenario.params)
    params[f"kc_{LOOP}"] = kc
    params[f"ti_s_{LOOP}"] = ti_s
    return dataclasses.replace(scenario, params=tuple(params.items()))


async def main() -> None:
    """Run the three steps and print the comparison."""
    detuned = build_scenario("mill_circuit", "detuned", duration_s=CLOSED_LOOP_S)
    print("1/3 detuned loop, setpoint step ...")
    before = await record(detuned, CLOSED_LOOP_S, step_setpoint=True)
    print("2/3 open-loop step test ...")
    step_test = build_scenario("mill_circuit", "step_test", duration_s=STEP_TEST_S)
    report = tuning_from_step_test(await record(step_test, STEP_TEST_S, step_setpoint=False))
    if report.blocked_reason is not None or report.simc is None or report.model is None:
        print("tuning refused:", report.blocked_reason)
        return
    model, simc = report.model, report.simc
    print(f"   model: gain {model.gain:.3f}, tau {model.time_constant_s:.0f} s, "
          f"delay {model.delay_s:.0f} s -> SIMC kc {simc.kc:.2f}, Ti {simc.ti_s:.0f} s")
    print("3/3 retuned loop, same setpoint step ...")
    after = await record(with_gains(detuned, simc.kc, simc.ti_s), CLOSED_LOOP_S, step_setpoint=True)
    print(f"before: {health_line(before)}  error integral {error_integral(before):.0f}")
    print(f"after : {health_line(after)}  error integral {error_integral(after):.0f}")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=3 * MAX_WAIT_S))

"""The tuning part of the live gateway stack (ADR 014, Phase 3 exit evidence).

Adds to the stack of start_gateway_stack.py: the nodes of one simulated loop (PV, SP, OUT, MODE)
and its two controller parameters (gain as a Double, Ti as a Float), a coroutine that steps the
process of tuning_plant_sim.py on the OPC UA server so the loop reacts to the parameters the gateway
writes, the pid_param targets of the policy and the plant map, the site document of the runtime
service and its jobs (loop_kpi so the history fills, tuning_review so applied sets get a verdict).
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asyncua import ua
from crosscut_connectors.site import load_site
from crosscut_runtime.store import RuntimeStore
from tuning_plant_sim import INITIAL_KP, INITIAL_TI_S, START_VALUE, TICK_S, LoopSim, setpoint_at

LOOP_ID = "TUNE1"
SOURCE_ID = "e2e_plant"
GAIN_TAG, TI_TAG = "E2E.TUNE1.KP", "E2E.TUNE1.TI"
LOOP_TAGS = {
    "pv": ("E2E.TUNE1.PV", "loop_pv"),
    "sp": ("E2E.TUNE1.SP", "loop_sp"),
    "out": ("E2E.TUNE1.OUT", "loop_out"),
    "mode": ("E2E.TUNE1.MODE", "loop_mode"),
}
AUTO_MODE = 1
# name -> (initial value, variant type); merged into the NODES of the stack.
TUNING_NODES: dict[str, tuple[Any, ua.VariantType]] = {
    "loop_pv": (START_VALUE, ua.VariantType.Double),
    "loop_sp": (START_VALUE, ua.VariantType.Double),
    "loop_out": (START_VALUE, ua.VariantType.Double),
    "loop_mode": (AUTO_MODE, ua.VariantType.Int32),
    "kp": (INITIAL_KP, ua.VariantType.Double),
    "ti": (INITIAL_TI_S, ua.VariantType.Float),
}
MODE_VALUES = {"MAN": 0, "AUTO": 1, "CAS": 2}
RATIO_LIMIT = 6.0  # wide: the forward change and its rollback have the same ratio
MIN_INTERVAL_S = 60.0  # a rollback seconds after the apply is refused unless it is exempt
KPI_JOB, REVIEW_JOB = "tuning-kpi", "tuning-review"
KPI_PERIOD_S, REVIEW_PERIOD_S, KPI_WINDOW_S = 0.5, 2.0, 600
LIVE_VARIANTS = ("loop_pv", "loop_sp", "loop_out", "loop_mode")


def _param_policy(param: str, unit: str, limits: list[float]) -> dict[str, Any]:
    """One pid_param policy target of the loop (refuse, never clamp; 60 s between applies)."""
    return {
        "kind": "pid_param", "loop": LOOP_ID, "param": param, "unit": unit,
        "vendor_form": "siemens_pid_compact", "limits": limits, "max_ratio": RATIO_LIMIT,
        "readback_tolerance": 0.001, "min_interval_s": MIN_INTERVAL_S,
        "allowed_loop_modes": ["AUTO"],
    }  # fmt: skip


def policy_targets() -> dict[str, Any]:
    """The pid_param targets for the policy document: gain (OUT/PV) and Ti (s)."""
    return {
        GAIN_TAG: _param_policy("gain", "OUT/PV", [0.1, 20.0]),
        TI_TAG: _param_policy("ti", "s", [1.0, 600.0]),
    }


def plant_map_targets(node_id: Any) -> dict[str, Any]:
    """The pid_param entries of the plant map; `node_id(name)` gives the text NodeId of a node."""
    common = {"mode_node": node_id("loop_mode"), "mode_values": MODE_VALUES}
    return {
        GAIN_TAG: {"param_node": node_id("kp"), "data_type": "Double", **common},
        TI_TAG: {"param_node": node_id("ti"), "data_type": "Float", **common},
    }


def _data_value(value: Any, vtype: ua.VariantType, stamp: datetime) -> ua.DataValue:
    """A good DataValue with an explicit source timestamp (the four loop tags share one)."""
    return ua.DataValue(ua.Variant(value, vtype), SourceTimestamp=stamp)


async def _tick(nodes: dict[str, Any], sim: LoopSim, started: float) -> None:
    """One process step: read the tuning, step the loop, write the four tags with one stamp."""
    gain = float(await nodes["kp"].read_value())
    ti_s = float(await nodes["ti"].read_value())
    mode = int(await nodes["loop_mode"].read_value())
    setpoint = setpoint_at(time.monotonic() - started)
    pv, out = sim.advance(setpoint, gain, ti_s)
    stamp = datetime.now(UTC).replace(tzinfo=None)
    values = {"loop_pv": pv, "loop_sp": setpoint, "loop_out": out, "loop_mode": mode}
    for name in LIVE_VARIANTS:
        await nodes[name].write_value(_data_value(values[name], TUNING_NODES[name][1], stamp))


async def simulate(nodes: dict[str, Any], started: float) -> None:
    """Step the simulated loop in real time until cancelled; runs on the server's event loop.

    `started` is the time.monotonic() instant that counts as t = 0 of the setpoint profile.
    """
    sim = LoopSim()
    tick = 0
    while True:
        tick += 1
        await _tick(nodes, sim, started)
        await asyncio.sleep(max(0.0, started + tick * TICK_S - time.monotonic()))


def _site_document(endpoint: str, node_id: Any) -> dict[str, Any]:
    """The site: one OPC UA source, the six tags of the loop and its parameters, one loop."""
    names = {tag: node for tag, node in LOOP_TAGS.values()} | {GAIN_TAG: "kp", TI_TAG: "ti"}
    tags = [
        {"id": tag, "source": SOURCE_ID, "address": node_id(node)}
        for tag, node in names.items()
    ]
    loop = {
        "id": LOOP_ID, "name": LOOP_ID, "out_limits": {"min": 0, "max": 100},
        **{channel: tag for channel, (tag, _) in LOOP_TAGS.items()},
    }
    return {
        "schema_version": 1,
        "site": {"name": "E2E tuning", "timezone": "UTC"},
        "sources": [{"id": SOURCE_ID, "driver": "opcua", "endpoint": endpoint, "options": {}}],
        "tags": tags,
        "loops": [loop],
    }


def _jobs_document() -> dict[str, Any]:
    """The runtime jobs: the KPI job that fills the history and the review of applied sets."""
    kpi = {
        "id": KPI_JOB, "kind": "loop_kpi", "source": SOURCE_ID, "loops": [LOOP_ID],
        "period_s": KPI_PERIOD_S, "window_s": KPI_WINDOW_S, "enabled": True,
    }
    review = {
        "id": REVIEW_JOB, "kind": "tuning_review", "source": SOURCE_ID, "loops": [LOOP_ID],
        "period_s": REVIEW_PERIOD_S, "enabled": True,
    }
    return {"schema_version": 1, "jobs": [kpi, review]}


def install_site_and_jobs(root: Path, endpoint: str, node_id: Any) -> float:
    """Write site.json and jobs.json under `root`; returns the time (epoch s) they were written."""
    site_path = root / "_site" / "site.json"
    site_path.parent.mkdir(parents=True, exist_ok=True)
    site_path.write_text(json.dumps(_site_document(endpoint, node_id), indent=2), encoding="utf-8")
    load_site(root)  # fails here, not later in the runtime, when the document is invalid
    RuntimeStore(root).save_jobs(_jobs_document())
    return time.time()


def tuning_info(sim_started_epoch: float) -> dict[str, Any]:
    """What the specs need to know about the tuning part (printed in the stack description)."""
    return {
        "loop_id": LOOP_ID,
        "gain_tag": GAIN_TAG,
        "ti_tag": TI_TAG,
        "dataset_id": "tuning_live_demo",
        "sim_started_epoch": sim_started_epoch,
        "initial_kp": INITIAL_KP,
        "initial_ti": INITIAL_TI_S,
    }

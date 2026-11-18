"""L5-P1 chain: RougherSim recording -> truth project -> site catalogue -> live loop KPI job.

The catalogue is built from `roughersim export-crosscut-project` (loops with pv/sp/out/mode) and
validated with the Crosscut site schema; tags are addressed by the OPC UA node of the running
`roughersim serve`. The live KPI job then runs on `OpcUaConnector.read_live` for a short window.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from crosscut_connectors.opcua_connector import OpcUaConnector
from crosscut_connectors.site import validate_site
from crosscut_runtime.addressing import AddressedConnector
from crosscut_runtime.jobs.loop_kpi import LoopKpiJob
from golden import record, roughersim_dir, venv_python
from rs_harness import rs_server

NODE = "nsu=urn:roughersim:abb800xa;s=Application/Loop/{loop}/{field}"
FIELDS = {"pv": "Pv", "sp": "Sp", "out": "Out", "mode": "Mode"}
SERVE_SPEED = 20.0  # simulation seconds per wall second
TICK_WALL_S = 0.3  # wall seconds between live reads (>= one 5 s plant step at SERVE_SPEED)
LIVE_TICKS = 60  # reads per loop; the job needs MIN_KPI_SAMPLES = 50
WINDOW_S = 3600.0  # rolling window of the job in seconds
SERVICE_FACTOR_TOLERANCE = 0.05  # share of time not in AUTO/CAS allowed in a nominal run, [0, 1]
FLATLINE_LIMIT = 0.10  # frozen PV share allowed in a nominal run, [0, 1]
HEALTH_KPIS = ("service_factor", "saturation_fraction", "flatline_fraction", "classification")
SCENARIO = "scenarios/rs.nominal.base.v1.json"


def export_project(recording: Path, out: Path) -> dict[str, Any]:
    """Run RougherSim's own export helper on a recording and load the project it writes."""
    rs_dir = roughersim_dir().resolve()
    code = "import sys; from roughersim.cli import main; sys.exit(main(sys.argv[1:]))"
    cmd = [
        str(venv_python(rs_dir)),
        "-c",
        code,
        "export-crosscut-project",
        str(recording),
        "--out",
        str(out),
    ]
    env = {**os.environ, "PYTHONPATH": str(rs_dir / "src")}
    subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=rs_dir, env=env)
    return json.loads(out.read_text(encoding="utf-8"))


def build_catalogue(project: dict[str, Any]) -> dict[str, Any]:
    """Site catalogue: one tag per loop channel addressed by its OPC UA node, one loop each."""
    tags: list[dict[str, Any]] = []
    loops: list[dict[str, Any]] = []
    for entry in project["loops"]:
        loop = {
            "id": entry["name"],
            "out_limits": {"min": entry["out_eng_min"], "max": entry["out_eng_max"]},
        }
        for channel, field in FIELDS.items():
            loop[channel] = entry[channel]
            address = NODE.format(loop=entry["name"], field=field)
            tags.append({"id": entry[channel], "address": address})
        loops.append(loop)
    return {"schema_version": 1, "site": {"name": "roughersim"}, "tags": tags, "loops": loops}


def run_live_kpi(catalogue: dict[str, Any], log: Path) -> dict[str, Any]:
    """Serve the MVP plant, tick the live KPI job for a short window, return its last result."""
    loops = {loop["id"]: loop for loop in catalogue["loops"]}
    addresses = {tag["id"]: tag["address"] for tag in catalogue["tags"]}
    job_doc = {
        "id": "kpi",
        "kind": "loop_kpi",
        "source": "roughersim",
        "loops": list(loops),
        "period_s": TICK_WALL_S,
        "window_s": WINDOW_S,
        "enabled": True,
    }
    with rs_server(log, None, SERVE_SPEED, watchdog_s=600.0) as port:
        time.sleep(8.0)  # server start-up
        connector = AddressedConnector(OpcUaConnector(f"opc.tcp://127.0.0.1:{port}"), addresses)
        job = LoopKpiJob(job_doc, loops, connector)
        result: dict[str, Any] = {}
        for _ in range(LIVE_TICKS):
            result = job.run()
            time.sleep(TICK_WALL_S)
    return result


def execute() -> None:
    """Executor of L5-P1: catalogue from a recording, then a live KPI row for every loop."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        record(roughersim_dir(), roughersim_dir() / SCENARIO, work / "rec")
        project = export_project(work / "rec", work / "project.json")
        catalogue = build_catalogue(project)
        assert validate_site(catalogue) == [], validate_site(catalogue)
        result = run_live_kpi(catalogue, work / "serve.log")
    check_kpi_rows(catalogue, result)


def check_kpi_rows(catalogue: dict[str, Any], result: dict[str, Any]) -> None:
    """Every catalogue loop has a KPI row with the health KPIs, inside nominal tolerances."""
    kpi = result["kpi"]
    assert kpi is not None, "no loop reached the sample threshold"
    for loop in catalogue["loops"]:
        row = kpi.get(loop["id"])
        assert row is not None, f"{loop['id']}: no KPI row"
        assert all(name in row for name in HEALTH_KPIS), f"{loop['id']}: {row}"
        assert row["service_factor"] >= 1.0 - SERVICE_FACTOR_TOLERANCE, f"{loop['id']}: {row}"
        assert (row["flatline_fraction"] or 0.0) <= FLATLINE_LIMIT, f"{loop['id']}: {row}"
        assert row["classification"] != "manual", f"{loop['id']}: {row}"

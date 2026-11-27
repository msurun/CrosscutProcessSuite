"""L5-P7a: the MPC controller on the RougherSim grinding MIMO bed, advisory proposals only.

Real chain: ``build_controller_job`` (runtime wiring) -> ``OpcUaConnector`` snapshots of the
grinding flowsheet (RougherSim M9, #22) -> MPC host in the advisory state. The gateway port
answers that the mode cannot write (``mode_no_write``), so the host keeps every move as advice
and proposes nothing.
The identified model is built from the step-test truth of RougherSim #24 (scenario
``rs.grinding.step_test_sequential.v1``, seed 100024, ``step_test.json`` ``sp_gains`` and
``gain_matrix``): the four self-regulating pairs of MVs WIC101 (fresh feed, t/h) and FIC102 (mill
water, m3/h) to CVs PDT204 (cyclone pressure, kPa) and DIC202 (density proxy, %). The other pairs
integrate and are outside a FOPDT model. Nothing is written to the plant and nothing is tuned on it.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from crosscut_connectors.opcua_connector import OpcUaConnector
from crosscut_mpc.artifact import save_ident_model
from crosscut_mpc.identification import IdentifiedModel, PairQuality
from crosscut_runtime.controllers.protocol import Move
from crosscut_runtime.controllers.wiring import ControllerJob, build_controller_job
from golden import roughersim_dir
from rs_harness import rs_server

FLOWSHEET = "scenarios/grinding/flowsheet.json"
HOOKS = "scenarios/grinding/hooks.json"
NS = "nsu=urn:roughersim:abb800xa;s=Application/{}"
SOURCE, CONTROLLER_ID, ARTIFACT = "rs", "mpc1", "grinding"
CYCLE_S = 30.0  # sim seconds per controller cycle (model sample time)
SPEED = 20.0
MV_MOVE_MAX = {"WIC101": 2.0, "FIC102": 1.0}
# Truth of rs.grinding.step_test_sequential.v1: (sp_gain in CV unit per SP unit, tau_s, theta_s).
PAIRS = {
    ("WIC101", "PDT204"): (0.019542677837094367, 416.84864831194136, 42.5),
    ("WIC101", "DIC202"): (0.05632692747839742, 416.84864831194136, 40.0),
    ("FIC102", "PDT204"): (0.004300114459556536, 82.05329859123627, 27.5),
    ("FIC102", "DIC202"): (0.012519433346450818, 82.05329859123627, 27.5),
}
ADDRESSES = {
    "PDT204.PV": NS.format("Instrument/PDT204/Pv"),
    "DIC202.PV": NS.format("Loop/DIC202/Pv"),
    "WIC101.PV": NS.format("Loop/WIC101/Pv"),
    "WIC101.SP": NS.format("Loop/WIC101/Sp"),
    "FIC102.PV": NS.format("Loop/FIC102/Pv"),
    "FIC102.SP": NS.format("Loop/FIC102/Sp"),
}
MODE_NO_WRITE = "mode_no_write"


def grinding_available() -> str | None:
    """Why the grinding bed cannot run here, or None when the checkout has it."""
    base = roughersim_dir()
    needed = [base / FLOWSHEET, base / HOOKS, base / "scenarios/grinding/step_test_sequential.json"]
    missing = [p.name for p in needed if not p.is_file()]
    if missing:
        names = ", ".join(missing)
        return f"RougherSim at {base} lacks the grinding MIMO bed ({names}; needs #22, #24)"
    return None


def truth_model() -> IdentifiedModel:
    """The step-test truth as an accepted ident_model (MVs WIC101, FIC102; CVs PDT204, DIC202)."""
    inputs, cvs = ("WIC101", "FIC102"), ("PDT204", "DIC202")
    table = [[PAIRS[(u, y)] for u in inputs] for y in cvs]
    quality = tuple(tuple(PairQuality(1.0, 3, True, ()) for _ in inputs) for _ in cvs)
    return IdentifiedModel(
        inputs, cvs, np.array([[g for g, _, _ in row] for row in table]),
        np.array([[tau for _, tau, _ in row] for row in table]),
        np.array([[theta for _, _, theta in row] for row in table]),
        CYCLE_S, quality, {}, "truth",
    )


def site_for(port: int, start: dict[str, float], sha: str) -> dict[str, Any]:
    """Site document: RougherSim source, six addressed tags, two loops, one mpc controller."""
    pdt, dic = start["PDT204.PV"], start["DIC202.PV"]
    variables: list[dict[str, Any]] = [
        {"id": loop, "role": "MV", "required": True, "binding": {"loop": loop},
         "limits": {"operator": {"lo": sp - 10, "hi": sp + 10}, "move_max": MV_MOVE_MAX[loop]}}
        for loop, sp in ((n, start[f"{n}.SP"]) for n in MV_MOVE_MAX)
    ]
    variables += [
        {"id": "PDT204", "role": "CV", "binding": {"tag": "PDT204.PV"}, "priority": 2,
         "target": pdt + 0.2, "limits": {"operator": {"lo": pdt - 5, "hi": pdt + 5}}},
        {"id": "DIC202", "role": "CV", "binding": {"tag": "DIC202.PV"}, "priority": 1,
         "limits": {"operator": {"lo": dic - 0.5, "hi": dic + 0.3}}},
    ]
    return {
        "schema_version": 1, "site": {"name": "l5-mpc"},
        "sources": [{"id": SOURCE, "type": "opcua", "endpoint": f"opc.tcp://127.0.0.1:{port}"}],
        "tags": [{"id": t, "source": SOURCE, "address": a} for t, a in ADDRESSES.items()],
        "loops": [{"id": n, "pv": f"{n}.PV", "sp": f"{n}.SP", "out": f"{n}.PV", "mode": f"{n}.PV"}
                  for n in MV_MOVE_MAX],
        "controllers": [{
            "id": CONTROLLER_ID, "type": "mpc", "cycle_s": CYCLE_S, "variables": variables,
            "mpc": {"model": {"artifact": ARTIFACT, "sha256": sha},
                    "prediction_horizon": 20, "move_horizon": 4},
        }],
    }


@dataclass
class MpcRig:
    """A running grinding server and the MPC job on it, in advisory (no gateway)."""

    root: Path
    site: dict[str, Any]
    start: dict[str, float]
    sent: list[Move] = field(default_factory=list)
    connectors: list[OpcUaConnector] = field(default_factory=list)
    job: ControllerJob | None = None

    def _connector(self, source: dict[str, Any]) -> OpcUaConnector:
        """Connector factory of the runtime wiring."""
        connector = OpcUaConnector(source["endpoint"])
        self.connectors.append(connector)
        return connector

    def _ports(self, *_: Any) -> tuple[Any, Any]:
        """Gateway ports: the mode cannot write, so the host stays in advisory."""
        answer = lambda targets: {  # noqa: E731
            t: {"available": False, "reasons": [MODE_NO_WRITE]} for t in targets}
        return answer, self.sent.append

    def start_job(self) -> ControllerJob:
        """Build the job through the runtime wiring."""
        job = {"controller": CONTROLLER_ID, "source": SOURCE}
        self.job = build_controller_job(job, self.site, self.root, (self._connector, self._ports))
        return self.job

    def cycle(self, wait_s: float = CYCLE_S / SPEED) -> dict[str, Any]:
        """Wait one controller cycle of simulation time, run one host cycle; the record."""
        assert self.job is not None
        time.sleep(wait_s)
        record: dict[str, Any] = self.job.run()["controller"]
        return record

    def read(self, tag: str) -> float:
        """Current value of one tag straight from the server."""
        snapshot = self.connectors[0].read_snapshot([ADDRESSES[tag]])
        return float(snapshot.values[ADDRESSES[tag]].value)

    def close(self) -> None:
        """Close every connector."""
        for connector in self.connectors:
            connector.close()


def _read_start(port: int) -> dict[str, float]:
    """Nominal values of the six tags at the start of the run."""
    connector = OpcUaConnector(f"opc.tcp://127.0.0.1:{port}")
    try:
        snapshot = connector.read_snapshot(list(ADDRESSES.values()))
        return {t: float(snapshot.values[a].value) for t, a in ADDRESSES.items()}
    finally:
        connector.close()


@contextmanager
def mpc_rig(tmp: Path) -> Iterator[MpcRig]:
    """Server, model store, site and job; closes the connectors and stops the server."""
    log = tmp / "server.log"
    with rs_server(log, HOOKS, SPEED, watchdog_s=3600.0, flowsheet=FLOWSHEET) as port:
        start = _wait_start(port)
        sha = save_ident_model(tmp / "root" / "_mpc" / "models" / ARTIFACT, truth_model())
        rig = MpcRig(tmp / "root", site_for(port, start, sha), start)
        try:
            rig.start_job()
            yield rig
        finally:
            rig.close()


def _wait_start(port: int, timeout_s: float = 60.0) -> dict[str, float]:
    """Read the start values, retrying while the server comes up."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            return _read_start(port)
        except (ConnectionError, TimeoutError, OSError, KeyError, TypeError):
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)

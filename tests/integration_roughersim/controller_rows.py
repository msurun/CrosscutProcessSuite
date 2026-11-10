"""Helpers for the L5 controller rows (C01..C05): fuzzy APC core on RougherSim via the gateway.

The real chain runs in-process: ``build_controller_job`` (runtime wiring) reads snapshots from
RougherSim with the real ``OpcUaConnector`` and hands each move to the real ``WriteGateway`` on
the real ``OpcUaPlant``. Ground truth is never read. One loop (FIC203, cascade secondary, written
through its remote setpoint) is the MV; DIC202 and LIT201 process values are the CVs.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asyncua import Client, ua
from crosscut_connectors.base import Snapshot
from crosscut_connectors.opcua_connector import OpcUaConnector
from crosscut_gateway import engine
from crosscut_gateway.interfaces import WriteDecision, WriteProposal
from crosscut_runtime.controllers.commands import enqueue_command
from crosscut_runtime.controllers.protocol import Move
from crosscut_runtime.controllers.wiring import ControllerJob, build_controller_job
from gateway_rows import POLICY, TAG, Rig
from rs_harness import Harness, plant_map_for, rs_server

NS = "nsu=urn:roughersim:abb800xa;s=Application/Loop/{}"
CONTROLLER_ID = "c1"
MOVE_MAX = 2.0  # setpoint units per cycle
CYCLE_S = 2.0  # wall seconds; sets the staleness limit and the overrun guard
SOURCE = "rs"
MAN = 0  # raw value of mode MAN in the plant map
CV_A, CV_B, MV_PV = "DIC202.PV", "LIT201.PV", "FIC203.PV"
RANGES = {CV_A: (0.0, 100.0), CV_B: (0.0, 1.0)}
ADDRESSES = {
    CV_A: NS.format("DIC202/Pv"),
    CV_B: NS.format("LIT201/Pv"),
    MV_PV: NS.format("FIC203/Pv"),
    TAG: NS.format("FIC203/Rsp"),
}


class SensorFaultUnavailable(NotImplementedError):
    """RougherSim ``serve`` cannot fail one transmitter (hook API 1.1.0 has no PV fault)."""


def inject_transmitter_fault(tag: str) -> None:
    """Fail the transmitter of ``tag`` on the live server.

    Raises:
        SensorFaultUnavailable: always; sensor faults exist only in recorded scenarios and
            the hook types (reject_writes, comm_loss, readback_offset, operator_action) never
            touch a PV node.
    """
    raise SensorFaultUnavailable(f"RougherSim serve cannot fail the transmitter of {tag}")


async def _set_mode(endpoint: str, node_text: str, value: int) -> None:
    """Write ``value`` to a mode node with the node's own data type (an operator at the HMI)."""
    async with Client(url=endpoint, timeout=5.0) as client:
        index = await client.get_namespace_index("urn:roughersim:abb800xa")
        node = client.get_node(node_text.replace("nsu=urn:roughersim:abb800xa", f"ns={index}"))
        kind = await node.read_data_type_as_variant_type()
        await node.write_value(ua.Variant(value, kind))


def rule_base(cv_count: int) -> dict[str, Any]:
    """Fuzzy rule base: each CV alone (a term spanning its range) pushes the MV up."""
    names = [f"cv{n}" for n in range(1, cv_count + 1)]
    ranges = [RANGES[tag] for tag in (CV_A, CV_B)][:cv_count]
    up = [{"name": "up", "shape": "tri", "params": [5, 10, 10]}]
    inputs = [
        {"id": n, "low": lo, "high": hi,
         "terms": [{"name": "any", "shape": "trap", "params": [lo, lo, hi, hi]}]}
        for n, (lo, hi) in zip(names, ranges, strict=True)
    ]
    return {
        "name": "l5",
        "inputs": inputs,
        "outputs": [{"id": "mv1", "low": -10, "high": 10, "terms": up}],
        "rules": [{"id": f"r_{n}", "if": [{"variable": n, "is": "any"}],
                   "then": {"variable": "mv1", "is": "up"}} for n in names],
    }


def site_for(port: int, cvs: Sequence[str]) -> dict[str, Any]:
    """Site document: RougherSim source, addressed tags, one loop and one fuzzy controller."""
    variables: list[dict[str, Any]] = [
        {"id": f"cv{n}", "role": "CV", "binding": {"tag": tag}} for n, tag in enumerate(cvs, 1)
    ]
    variables.append({
        "id": "mv1", "role": "MV", "required": True, "binding": {"loop": "FIC203"},
        "limits": {"move_max": MOVE_MAX},
    })
    return {
        "schema_version": 1, "site": {"name": "l5"},
        "sources": [{"id": SOURCE, "type": "opcua", "endpoint": f"opc.tcp://127.0.0.1:{port}"}],
        "tags": [{"id": t, "source": SOURCE, "address": a} for t, a in ADDRESSES.items()],
        "loops": [{"id": "FIC203", "pv": MV_PV, "sp": TAG, "out": MV_PV}],
        "controllers": [{
            "id": CONTROLLER_ID, "type": "fuzzy", "rule_base": "rb", "cycle_s": CYCLE_S,
            "variables": variables,
        }],
    }


class RecordingConnector(OpcUaConnector):
    """The real OPC UA connector that keeps its last snapshot (to compare moves with it)."""

    last: Snapshot | None = None

    def read_snapshot(self, tag_ids: Sequence[str]) -> Snapshot:
        """Sample as the base class does and remember the answer."""
        self.last = super().read_snapshot(tag_ids)
        return self.last

    def last_value(self, address: str) -> float:
        """Last sampled value at ``address``."""
        assert self.last is not None
        return float(self.last.values[address].value)


@dataclass
class CtlRig:
    """A running RougherSim + gateway rig and the controller job on it."""

    rig: Rig
    root: Path
    site: dict[str, Any]
    connectors: list[RecordingConnector] = field(default_factory=list)
    decisions: list[WriteDecision] = field(default_factory=list)
    seen: list[tuple[float, float]] = field(default_factory=list)  # (sp_seen, proposed)
    job: ControllerJob | None = None

    def _ports(self, root: Path, controller_id: str, now_ns: Callable[[], int]) -> Any:
        """Gateway ports of the host: the in-process real gateway."""
        del root, controller_id, now_ns
        return self.rig.gw.mv_availability, self._propose

    def _propose(self, move: Move) -> None:
        """Hand a move to the real gateway as a proposal; remember it and the decision."""
        sp_seen = self.connectors[-1].last_value(ADDRESSES[TAG])
        proposal = WriteProposal(
            move.target_tag, move.value, f"controller:{CONTROLLER_ID}", self.rig.clock_ns, "l5"
        )
        self.seen.append((sp_seen, move.value))
        self.decisions.append(self.rig.gw.propose(proposal))

    def _connector(self, source: dict[str, Any]) -> RecordingConnector:
        """Connector factory of the runtime wiring."""
        connector = RecordingConnector(source["endpoint"])
        self.connectors.append(connector)
        return connector

    def start_job(self) -> ControllerJob:
        """Build a new job (a new host: its record is restored from disk)."""
        job = {"controller": CONTROLLER_ID, "source": SOURCE}
        deps = (self._connector, self._ports)
        self.job = build_controller_job(job, self.site, self.root, deps)
        return self.job

    def cycle(self) -> dict[str, Any]:
        """One plant step, one gateway tick, one controller cycle; returns the record."""
        assert self.job is not None
        self.rig.step()
        self.rig.tick()
        record: dict[str, Any] = self.job.run()["controller"]
        return record

    def operator_manual(self) -> None:
        """An operator puts the base loop FIC203 into manual (mode node written over OPC UA)."""
        endpoint = self.site["sources"][0]["endpoint"]
        asyncio.run(_set_mode(endpoint, NS.format("FIC203/Mode"), MAN))

    def command(self, command: str) -> None:
        """Queue an operator command like the console does."""
        enqueue_command(self.root, CONTROLLER_ID, command)

    def accepted(self) -> int:
        """Number of proposals the gateway accepted."""
        return sum(1 for d in self.decisions if d.accepted)

    def close(self) -> None:
        """Close every connector."""
        for connector in self.connectors:
            connector.close()


def _prepare_root(root: Path, cv_count: int) -> None:
    """Create the data root with the fuzzy store holding the rule base ``rb``."""
    (root / "_fuzzy").mkdir(parents=True)
    text = json.dumps(rule_base(cv_count))
    (root / "_fuzzy" / "rb.json").write_text(text, encoding="utf-8")


@contextmanager
def ctl_rig(
    tmp: Path, cvs: Sequence[str] = (CV_A,), speed: float = 20.0
) -> Iterator[CtlRig]:
    """RougherSim, supervised gateway, rule base and a controller job."""
    with rs_server(tmp / "server.log", None, speed) as port:
        harness = Harness(plant_map_for(port), speed)
        try:
            harness.wait_ready()
            gateway = engine.WriteGateway(harness, {TAG: POLICY}, "supervised")
            _prepare_root(tmp / "root", len(cvs))
            c = CtlRig(Rig(harness, gateway, tmp), tmp / "root", site_for(port, cvs))
            yield from _run_job(c)
        finally:
            harness.close()


def _run_job(c: CtlRig) -> Iterator[CtlRig]:
    """Start the job, yield the rig and always close the connectors."""
    try:
        c.start_job()
        yield c
    finally:
        c.close()

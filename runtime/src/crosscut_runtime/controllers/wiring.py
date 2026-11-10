"""Builds the runtime job that drives one controller from a site ``controllers[]`` entry.

The job is one host cycle per run: queued operator commands first, then ``run_cycle``. Every
failure to build raises ValueError with a stable code (``unknown_controller``,
``unsupported_type``, ``rule_base``, ``binding``, ``no_snapshot``, ``no_setpoint``).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from crosscut_connectors.base import Snapshot
from crosscut_fuzzy.library import load_document
from crosscut_fuzzy.model import FuzzyModelError, FuzzySystem, system_from_dict
from crosscut_loops.mv_readiness import loop_readiness

from crosscut_runtime.controllers.commands import pick_command, take_commands
from crosscut_runtime.controllers.fuzzy import ControllerBindingError, FuzzyController
from crosscut_runtime.controllers.gateway_adapter import make_gateway_ports
from crosscut_runtime.controllers.host import (
    UNKNOWN_READINESS,
    ControllerHost,
    HostConfig,
    HostPorts,
    Readiness,
)
from crosscut_runtime.controllers.state import DEFAULT_MAX_OVERRUNS
from crosscut_runtime.store import RuntimeStore

FUZZY_FOLDER = "_fuzzy"
GatewayPorts = Callable[[Path, str, Callable[[], int]], tuple[Any, Any]]
default_gateway_ports: GatewayPorts = make_gateway_ports


class AddressedSnapshot:
    """Reads snapshots at the configured addresses and keys the answer by tag id."""

    def __init__(self, inner: Any, addresses: Mapping[str, str]) -> None:
        """Keep the wrapped connector (it must offer ``read_snapshot``) and the address map."""
        self._inner, self._addresses = inner, addresses

    def read_snapshot(self, tag_ids: Sequence[str]) -> Snapshot:
        """Sample the addresses of the tags; values are re-keyed by the original tag ids."""
        pairs = [(self._addresses.get(tag, tag), tag) for tag in tag_ids]
        snap: Snapshot = self._inner.read_snapshot([address for address, _ in pairs])
        values = {tag: snap.values[address] for address, tag in pairs if address in snap.values}
        return Snapshot(snap.cycle_utc, values, snap.comm_ok, snap.reason)


class ControllerJob:
    """One runtime job: queued commands, then one controller cycle."""

    def __init__(self, host: ControllerHost, root: Path, controller_id: str) -> None:
        """Bind the host and the place its command queue lives."""
        self._host, self._root, self._id = host, root, controller_id

    def run(self) -> dict[str, Any]:
        """Apply the newest operator command, run one cycle and return the record."""
        command = pick_command(take_commands(self._root, self._id))
        if command is not None:
            self._host.request(command)
        return {"controller": asdict(self._host.run_cycle())}


def _latest_kpi_row(root: Path, loop_id: str) -> Mapping[str, Any] | None:
    """The newest loop_kpi row of a loop in the runtime state, or None when there is none."""
    jobs = RuntimeStore(root).load_state().get("jobs", {})
    rows = [
        (str(job.get("last_run_utc", "")), job["kpi"][loop_id])
        for job in jobs.values()
        if isinstance(job, dict) and isinstance(job.get("kpi"), dict) and job["kpi"].get(loop_id)
    ]
    return max(rows, key=lambda row: row[0])[1] if rows else None


def make_readiness(root: Path) -> Readiness:
    """Readiness port: ``loop_readiness`` of the latest loop_kpi row; no row = unknown, ready."""

    def readiness(loop_id: str) -> Mapping[str, Any]:
        row = _latest_kpi_row(root, loop_id)
        if row is None:
            return {"ready": True, "reasons": [UNKNOWN_READINESS]}
        return loop_readiness(row)

    return readiness


def _find(site: Mapping[str, Any], controller_id: str) -> Mapping[str, Any]:
    """The controller entry of the site; ValueError ``unknown_controller`` when absent."""
    for entry in site.get("controllers", []):
        if entry["id"] == controller_id:
            return dict(entry)
    raise ValueError(f"unknown_controller: {controller_id}")


def _load_system(root: Path, rule_base: str | None) -> FuzzySystem:
    """The fuzzy system named by ``rule_base`` from the fuzzy store."""
    try:
        return system_from_dict(load_document(str(rule_base), root / FUZZY_FOLDER))
    except (FuzzyModelError, FileNotFoundError, ValueError) as error:
        raise ValueError(f"rule_base: {rule_base}: {error}") from error


def _variable_tags(
    doc: Mapping[str, Any], loops: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """``tags_of`` (MV: PV tag then SP tag) and the gateway target of each MV (its SP tag)."""
    tags_of: dict[str, list[str]] = {}
    targets: dict[str, str] = {}
    for var in doc["variables"]:
        binding = var["binding"]
        if var["role"] != "MV":
            tags_of[var["id"]] = [binding["tag"]]
            continue
        loop = loops[binding["loop"]]
        if "sp" not in loop:
            raise ValueError(f"no_setpoint: loop {binding['loop']}")
        tags_of[var["id"]] = [loop["pv"], loop["sp"]]
        targets[var["id"]] = loop["sp"]
    return tags_of, targets


def _connector(
    factory: Callable[[dict[str, Any]], Any], source: Any, site: Mapping[str, Any]
) -> Any:
    """The snapshot connector of the job's source, reading at the catalogue addresses."""
    addresses = {t["id"]: t["address"] for t in site.get("tags", []) if t.get("address")}
    inner = factory(source)
    if not hasattr(inner, "read_snapshot"):
        raise ValueError("no_snapshot: the source cannot sample a snapshot")
    return AddressedSnapshot(inner, addresses)


def build_controller_job(
    job: Mapping[str, Any],
    site: Mapping[str, Any],
    root: Path,
    deps: tuple[Callable[[dict[str, Any]], Any], GatewayPorts],
) -> ControllerJob:
    """Build the job; ``deps`` is ``(connector_factory, gateway_ports_factory)``."""
    doc = _find(site, job["controller"])
    if doc["type"] != "fuzzy":
        raise ValueError(f"unsupported_type: {doc['type']}")
    loops = {loop["id"]: loop for loop in site.get("loops", [])}
    tags_of, targets = _variable_tags(doc, loops)
    try:
        controller = FuzzyController(doc, _load_system(root, doc.get("rule_base")), targets)
    except ControllerBindingError as error:
        raise ValueError(f"binding: {error}") from error
    sources = {src["id"]: src for src in site.get("sources", [])}
    connector = _connector(deps[0], sources.get(job["source"], {}), site)
    availability, propose = deps[1](root, doc["id"], time.time_ns)
    config = HostConfig(
        doc, tags_of, targets, root, int(doc.get("max_overruns", DEFAULT_MAX_OVERRUNS))
    )
    ports = HostPorts(connector, availability, propose, readiness=make_readiness(root))
    host = ControllerHost(controller, config, ports)
    return ControllerJob(host, root, doc["id"])

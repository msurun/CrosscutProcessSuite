"""Controller host: runs one controller cycle by cycle (Phase 2.5, step 5).

Per cycle: read one snapshot, evaluate the variable statuses, check the guards, apply the
state machine and, while ``on``, hand each move to ``propose`` (a gateway proposal, never a
direct write). The state record is written atomically to
``<root>/_runtime/controllers/<id>.json``; a restart never resumes ``on``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_connectors.base import Snapshot, SnapshotConnector

from crosscut_runtime.controllers.overrides import (
    CONTROLLERS_FOLDER,
    apply_overrides,
    read_overrides,
)
from crosscut_runtime.controllers.protocol import Controller, Move
from crosscut_runtime.controllers.state import (
    DEFAULT_MAX_OVERRUNS,
    OFF,
    ON,
    SHED,
    STANDBY,
    Health,
    enters_on,
    transition,
)
from crosscut_runtime.store import RUNTIME_FOLDER, write_json_atomic, write_variable_status
from crosscut_runtime.variable_status import (
    BAD,
    DEFAULT_CYCLE_S,
    GOOD,
    StatusInputs,
    VariableStatus,
    evaluate,
)

OVERRUN_MARGIN = 0.1  # a start later than period * (1 + margin) after the last start is late
NO_WRITE_REASON = "mode_no_write"  # gateway reason: mode off, advisory or dry_run

Availability = Callable[[list[str]], Mapping[str, Mapping[str, Any]]]
Readiness = Callable[[str], Mapping[str, Any]]


def _utc_now() -> datetime:
    """Current time in UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class HostConfig:
    """Static inputs of one host.

    ``tags_of`` maps a variable id to its tags (an MV: PV tag first, then SP tag);
    ``mv_targets`` maps an MV variable id to the gateway target tag it is written through.
    """

    controller_doc: Mapping[str, Any]
    tags_of: Mapping[str, list[str]]
    mv_targets: Mapping[str, str]
    data_root: Path
    max_overruns: int = DEFAULT_MAX_OVERRUNS


@dataclass(frozen=True)
class HostPorts:
    """Everything the host talks to; all injectable so tests need no plant."""

    connector: SnapshotConnector
    availability: Availability
    propose: Callable[[Move], None]
    clock: Callable[[], datetime] = _utc_now
    readiness: Readiness | None = None  # loop id -> {"ready": bool, "reasons": [...]}


@dataclass
class ControllerRecord:
    """The persisted state of one controller."""

    state: str = OFF
    reason: str = "new"
    last_cycle_utc: str | None = None
    last_duration_s: float | None = None
    overruns: int = 0
    consecutive_overruns: int = 0
    liveness_utc: str | None = None
    last_explanation: str = ""
    disabled: list[str] | None = None


def record_path(root: Path, controller_id: str) -> Path:
    """Path of the state record of one controller."""
    return root / RUNTIME_FOLDER / CONTROLLERS_FOLDER / f"{controller_id}.json"


def load_record(path: Path) -> ControllerRecord:
    """Read a record; a missing or corrupt file gives a fresh ``off`` record.

    A restored ``on`` or ``shed`` comes back as ``standby``: the operator switches on again.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        known = asdict(ControllerRecord())
        record = ControllerRecord(**{k: v for k, v in data.items() if k in known})
    except (FileNotFoundError, json.JSONDecodeError, TypeError, AttributeError):
        return ControllerRecord()
    if record.state in (ON, SHED):
        record.state, record.reason = STANDBY, "restart"
    record.consecutive_overruns = 0
    return record


class ControllerHost:
    """Runs the cycles of one controller and keeps its record."""

    def __init__(self, controller: Controller, config: HostConfig, ports: HostPorts) -> None:
        """Bind controller, config and ports; restore the record from disk."""
        self._controller, self._config, self._ports = controller, config, ports
        self._path = record_path(config.data_root, controller.id)
        self.record = load_record(self._path)
        self._command: str | None = None
        self._previous_start: datetime | None = None
        self._tags = sorted({tag for tags in config.tags_of.values() for tag in tags})
        variables = config.controller_doc.get("variables", [])
        self._roles = {v["id"]: v["role"] for v in variables}
        self._required = [v for v in variables if v["role"] == "MV" and v.get("required")]

    @property
    def period_s(self) -> float:
        """Cycle period of the controller document."""
        return float(self._config.controller_doc.get("cycle_s", DEFAULT_CYCLE_S))

    def request(self, command: str) -> None:
        """Queue an operator command (switch_on, switch_off, standby) for the next cycle."""
        self._command = command

    def set_disabled(self, ids: list[str] | None) -> None:
        """Set the operator-disabled variable ids (``None``: use each ``enabled_default``)."""
        self.record.disabled = None if ids is None else sorted(ids)

    def run_cycle(self) -> ControllerRecord:
        """Run one cycle and return the record."""
        start = self._ports.clock()
        self._count_overrun(start)
        snapshot = self._ports.connector.read_snapshot(self._tags)
        statuses = self._statuses(snapshot, start)
        old = self.record.state
        command, self._command = self._command, None
        health = self._health(snapshot, statuses)
        self.record.state, self.record.reason = transition(old, command, health)
        self._act(old, statuses)
        self._persist(start, statuses)
        return self.record

    def _count_overrun(self, start: datetime) -> None:
        """Count a late start; consecutive lates only count while the controller is on."""
        previous, self._previous_start = self._previous_start, start
        gap = 0.0 if previous is None else (start - previous).total_seconds()
        late = gap > self.period_s * (1 + OVERRUN_MARGIN)
        self.record.overruns += int(late)
        if late and self.record.state == ON:
            self.record.consecutive_overruns += 1
        else:
            self.record.consecutive_overruns = 0

    def _statuses(self, snapshot: Snapshot, now: datetime) -> list[VariableStatus]:
        """Variable statuses of this cycle."""
        disabled = None if self.record.disabled is None else frozenset(self.record.disabled)
        inputs = StatusInputs(snapshot, now, self._config.tags_of, disabled=disabled)
        return evaluate(self._effective_doc(), inputs)

    def _effective_doc(self) -> Mapping[str, Any]:
        """The controller document with the operator overrides of this cycle applied."""
        overrides = read_overrides(self._config.data_root, self._controller.id)
        doc = apply_overrides(self._config.controller_doc, overrides)
        apply_limits = getattr(self._controller, "apply_limits", None)
        if apply_limits is not None:
            apply_limits(doc["variables"])
        return doc

    def _health(self, snapshot: Snapshot, statuses: list[VariableStatus]) -> Health:
        """Guard inputs: communication, required MVs, good CVs, gateway mode, overruns."""
        unavailable, advisory = self._mv_problems(statuses)
        cv_good = any(s.status == GOOD for s in statuses if self._roles[s.variable_id] == "CV")
        return Health(
            comm_loss=not snapshot.comm_ok,
            unavailable_mvs=tuple(unavailable),
            any_cv_good=cv_good,
            advisory_only=advisory,
            overrun_limit=self.record.consecutive_overruns >= self._config.max_overruns,
        )

    def _mv_problems(self, statuses: list[VariableStatus]) -> tuple[list[str], bool]:
        """Unavailable required MVs, and whether the gateway mode alone blocks writing."""
        targets = [self._config.mv_targets[v["id"]] for v in self._required]
        answer = self._ports.availability(targets) if targets else {}
        bad = {s.variable_id for s in statuses if s.status == BAD}
        unavailable = [v["id"] for v in self._required if self._mv_down(v, answer, v["id"] in bad)]
        advisory = any(NO_WRITE_REASON in answer.get(t, {}).get("reasons", []) for t in targets)
        return unavailable, advisory

    def _mv_down(self, var: Mapping[str, Any], answer: Mapping[str, Any], bad: bool) -> bool:
        """True when a required MV cannot be used (gateway, bad status or loop readiness)."""
        entry = answer.get(self._config.mv_targets[var["id"]])
        if bad or entry is None or set(entry.get("reasons", [])) - {NO_WRITE_REASON}:
            return True
        readiness = self._ports.readiness
        return readiness is not None and not readiness(var["binding"]["loop"]).get("ready", True)

    def _act(self, old: str, statuses: list[VariableStatus]) -> None:
        """Run ``initialise`` on entering on; step and propose when already on."""
        new = self.record.state
        if enters_on(old, new):
            self._controller.initialise(statuses)
        elif new == ON:
            result = self._controller.step(statuses)
            self.record.last_explanation = result.explanation
            for move in result.moves:
                self._ports.propose(move)
        if new != ON:
            self.record.consecutive_overruns = 0

    def _persist(self, start: datetime, statuses: list[VariableStatus]) -> None:
        """Write the state record and the variable statuses."""
        end = self._ports.clock()
        self.record.last_cycle_utc = start.isoformat()
        self.record.last_duration_s = (end - start).total_seconds()
        self.record.liveness_utc = end.isoformat()
        write_json_atomic(self._path, asdict(self.record))
        write_variable_status(self._config.data_root, self._controller.id, statuses)

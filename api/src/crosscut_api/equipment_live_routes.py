"""Expose equipment anomaly state and audited operator feedback.

Runtime event snapshots stay append-only; operator choices use separate sidecars.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from crosscut_runtime.store import RuntimeStore, write_json_atomic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir
from crosscut_api.equipment_anomaly_routes import EquipmentId, _catalogue, _equipment

EVENT_LIMIT = 50  # Events per equipment shown in the worklist.
Actor = Annotated[ActorContext, Depends(actor_of)]
Document = dict[str, Any]


class ShelveRequest(BaseModel):
    """An explicitly zoned expiry for temporary alarm suppression."""

    until_utc: datetime


class OutcomeRequest(BaseModel):
    """Operator feedback attached to an existing event."""

    outcome: Literal["real", "false_alarm", "maintenance_raised", "deferred"]


def _read_document(path: Path) -> Document:
    """Read an optional JSON object, reporting corrupt operator state explicitly."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=503, detail=f"cannot read {path.name}") from error
    if not isinstance(document, dict):
        raise HTTPException(status_code=503, detail=f"{path.name} must contain an object")
    return document


def read_equipment_events(root: Path) -> list[Document]:
    """Replay append-only snapshots into the latest record for every event identity."""
    path = root / "_runtime" / "equipment_events.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except OSError as error:
        raise HTTPException(status_code=503, detail="equipment events unavailable") from error
    events: dict[tuple[str, str], Document] = {}
    try:
        for line in lines:
            event = json.loads(line)
            events[(event["equipment"], event["opened_utc"])] = event
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=503, detail="equipment event record is invalid") from error
    return list(events.values())


def _event_key(event: Document) -> str:
    """Identify feedback without placing request-controlled timestamps in a filename."""
    return f"{event['opened_utc']}/{event['equipment']}"


def _live_states(root: Path) -> Document:
    """Collect each equipment's most recently recorded runtime state."""
    jobs = RuntimeStore(root).load_state().get("jobs", {})
    ordered = sorted(jobs.values(), key=lambda row: row.get("last_run_utc") or "")
    states: Document = {}
    for job in ordered:
        states.update(job.get("equipment") or {})
    return states


def _equipment_row(entry: Document, root: Path, context: Document) -> Document:
    """Join one catalogue entry with its model, current state and event history."""
    equipment_id = entry["id"]
    _equipment(context["site"], equipment_id)
    model = _read_document(root / "_anomaly/equipment" / f"{equipment_id}.model.json")
    events = [event for event in context["events"] if event["equipment"] == equipment_id]
    events.sort(key=lambda event: event["opened_utc"], reverse=True)
    opened = next((event for event in events if event.get("closed_utc") is None), None)
    live = context["states"].get(equipment_id, {"status": "unknown" if model else "no_model"})
    return {"equipment_id": equipment_id, "model_status": model.get("status", "none"),
            "live_state": live, "open_event": opened, "events": events[:EVENT_LIMIT],
            "shelved_until_utc": context["shelved"].get(equipment_id)}


def _summary_context(root: Path) -> Document:
    """Read shared files once so a catalogue listing observes one consistent snapshot."""
    outcomes = _read_document(root / "_runtime/outcomes.json")
    events = [{**event, "outcome": outcomes.get(_event_key(event))}
              for event in read_equipment_events(root)]
    return {"site": _catalogue(root), "events": events, "states": _live_states(root),
            "shelved": _read_document(root / "_runtime/shelved.json")}


class EquipmentLiveEndpoints:
    """Bind equipment worklist actions to one root and one audit clock."""

    def __init__(self, root: Path, clock: Callable[[], float]) -> None:
        """Store the data root and the authoritative operator-action clock."""
        self.root, self.clock = root, clock

    def anomalies(self, actor: Actor) -> list[Document]:
        """List every catalogue equipment with model, runtime and event details."""
        actor.require("data.view")
        context = _summary_context(self.root)
        return [_equipment_row(entry, self.root, context)
                for entry in context["site"].get("equipment", [])
                if entry.get("level", "equipment") == "equipment"]

    def shelve(self, equipment_id: EquipmentId, body: ShelveRequest, actor: Actor) -> Document:
        """Suppress equipment alarms until a future, explicitly zoned UTC instant."""
        actor.require("ctl.operate")
        _equipment(_catalogue(self.root), equipment_id)
        expiry = body.until_utc
        if expiry.tzinfo is None or expiry.timestamp() <= self.clock():
            raise HTTPException(status_code=422, detail="until_utc must be aware and in the future")
        until = expiry.astimezone(UTC).isoformat()
        document = _read_document(self.root / "_runtime/shelved.json")
        document[equipment_id] = until
        self._audit("equipment_shelve", actor, {"equipment": equipment_id, "until_utc": until})
        self._write("shelved.json", document)
        return {"equipment_id": equipment_id, "until_utc": until}

    def unshelve(self, equipment_id: EquipmentId, actor: Actor) -> Document:
        """Remove a shelving expiry, leaving an audit record even when already absent."""
        actor.require("ctl.operate")
        _equipment(_catalogue(self.root), equipment_id)
        document = _read_document(self.root / "_runtime/shelved.json")
        document.pop(equipment_id, None)
        self._audit("equipment_unshelve", actor, {"equipment": equipment_id})
        self._write("shelved.json", document)
        return {"equipment_id": equipment_id, "until_utc": None}

    def outcome(self, opened_utc: str, equipment_id: EquipmentId,
                body: OutcomeRequest, actor: Actor) -> Document:
        """Attach audited feedback to a known event without rewriting runtime history."""
        actor.require("ctl.operate")
        _equipment(_catalogue(self.root), equipment_id)
        event = self._find_event(opened_utc, equipment_id)
        document = _read_document(self.root / "_runtime/outcomes.json")
        document[_event_key(event)] = body.outcome
        fields = {"equipment": equipment_id, "opened_utc": opened_utc, "outcome": body.outcome}
        self._audit("equipment_outcome", actor, fields)
        self._write("outcomes.json", document)
        return {**event, "outcome": body.outcome}

    def _find_event(self, opened_utc: str, equipment_id: str) -> Document:
        """Find the exact event identity or reject feedback with HTTP 404."""
        for event in read_equipment_events(self.root):
            if event["equipment"] == equipment_id and event["opened_utc"] == opened_utc:
                return event
        raise HTTPException(status_code=404, detail="equipment event not found")

    def _audit(self, event: str, actor: ActorContext, fields: dict[str, str]) -> None:
        """Require an audit append before making an operator action effective."""
        audit = AuthAudit(auth_dir(self.root) / AUDIT_FILE, self.clock)
        try:
            audit.append(event, actor=actor.actor, source_ip=actor.source_ip, **fields)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail="audit_unavailable") from error

    def _write(self, filename: str, document: Document) -> None:
        """Publish one sidecar atomically or report an unavailable operator action."""
        try:
            write_json_atomic(self.root / "_runtime" / filename, document)
        except OSError as error:
            raise HTTPException(status_code=503, detail=f"cannot save {filename}") from error


def build_equipment_live_router(root: Path, clock: Callable[[], float] = time.time) -> APIRouter:
    """Build equipment worklist, shelving and event feedback routes."""
    endpoints = EquipmentLiveEndpoints(root, clock)
    router = APIRouter()
    router.add_api_route("/equipment/anomalies", endpoints.anomalies, methods=["GET"])
    router.add_api_route("/equipment/{equipment_id}/shelve", endpoints.shelve, methods=["POST"])
    router.add_api_route("/equipment/{equipment_id}/shelve", endpoints.unshelve, methods=["DELETE"])
    router.add_api_route("/equipment/events/{opened_utc}/{equipment_id}/outcome",
                         endpoints.outcome, methods=["PUT"])
    return router

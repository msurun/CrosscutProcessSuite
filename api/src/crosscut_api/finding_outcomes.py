"""Store and serve the user's outcome for each live loop finding (PRODUCT.md 4.1, issue #150).

A finding is identified by loop id + finding code + first-seen time, so a finding that clears and
later returns is a new finding and needs a new outcome. Records live in one runtime sidecar and
every change is audited with the acting user.
"""
from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from crosscut_runtime.store import write_json_atomic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.deps import AUDIT_FILE
from crosscut_api.auth.store import auth_dir
from crosscut_api.equipment_live_routes import _read_document

FILE = "finding_outcomes.json"
OUTCOMES = ("fixed", "not_a_problem", "deferred", "maintenance_raised")
Actor = Annotated[ActorContext, Depends(actor_of)]
Document = dict[str, Any]


class FindingOutcomeRequest(BaseModel):
    """The user's verdict on one finding; `until_utc` only for deferred, work order optional."""

    since_utc: str | None = None
    outcome: Literal["fixed", "not_a_problem", "deferred", "maintenance_raised"]
    until_utc: datetime | None = None
    work_order: Annotated[str, Field(max_length=64)] | None = None


def finding_key(loop_id: str, code: str, since_utc: str | None) -> str:
    """Identity of one finding occurrence: loop, code and first-seen time."""
    return f"{loop_id}|{code}|{since_utc or ''}"


def read_outcomes(root: Path) -> Document:
    """All stored records keyed by finding_key; empty when none was saved."""
    return _read_document(root / "_runtime" / FILE)


def _is_active(record: Document, now: float) -> bool:
    """A deferral counts only until its date; every other outcome stays in force."""
    if record["outcome"] != "deferred":
        return True
    return datetime.fromisoformat(record["until_utc"]).timestamp() > now


def attach_outcomes(rows: list[Document], records: Document, now: float) -> None:
    """Set finding["outcome"] (and outcome_detail) on rows' findings that have an active record."""
    for row in rows:
        for finding in row["findings"]:
            record = records.get(finding_key(row["id"], finding["code"], finding.get("since_utc")))
            if record is not None and _is_active(record, now):
                finding["outcome"] = record["outcome"]
                finding["outcome_detail"] = {key: record.get(key) for key in
                                             ("until_utc", "work_order", "actor", "at_utc")}


def usefulness_summary(records: Document) -> list[Document]:
    """Per finding code: outcome counts and their shares (0..1) of all outcomes for that code."""
    counts: dict[str, Counter[str]] = {}
    for record in records.values():
        counts.setdefault(record["code"], Counter())[record["outcome"]] += 1
    summary = []
    for code in sorted(counts):
        total = sum(counts[code].values())
        summary.append({"code": code, "total": total,
                        "counts": {name: counts[code][name] for name in OUTCOMES},
                        "shares": {name: counts[code][name] / total for name in OUTCOMES}})
    return summary


class FindingOutcomeEndpoints:
    """Bind outcome routes to one data root, one audit clock and the live worklist."""

    def __init__(self, root: Path, clock: Callable[[], float],
                 loops: Callable[[], dict[str, Any]]) -> None:
        """`loops` returns the current live worklist, used to check the finding exists."""
        self.root, self.clock, self.loops = root, clock, loops

    def list_outcomes(self, actor: Actor) -> list[Document]:
        """Every stored outcome record."""
        actor.require("data.view")
        return list(read_outcomes(self.root).values())

    def usefulness(self, actor: Actor) -> list[Document]:
        """Share of each outcome per finding code."""
        actor.require("data.view")
        return usefulness_summary(read_outcomes(self.root))

    def put(self, loop_id: str, code: str, body: FindingOutcomeRequest, actor: Actor) -> Document:
        """Record an audited outcome for a finding that is currently open on the loop."""
        actor.require("ctl.operate")
        self._check_finding(loop_id, code, body.since_utc)
        record = self._record(loop_id, code, body, actor)
        self._audit(actor, {"loop": loop_id, "code": code, "outcome": body.outcome})
        records = read_outcomes(self.root)
        records[finding_key(loop_id, code, body.since_utc)] = record
        self._save(records)
        return record

    def _check_finding(self, loop_id: str, code: str, since_utc: str | None) -> None:
        """404 unless that exact finding occurrence is on the live worklist now."""
        row = next((row for row in self.loops()["loops"] if row["id"] == loop_id), None)
        if row is None or not any(f["code"] == code and f.get("since_utc") == since_utc
                                  for f in row["findings"]):
            raise HTTPException(status_code=404, detail="finding not found")

    def _record(self, loop_id: str, code: str, body: FindingOutcomeRequest,
                actor: ActorContext) -> Document:
        """Validate the outcome-specific fields and build the stored record."""
        until = body.until_utc
        if body.outcome == "deferred":
            if until is None or until.tzinfo is None or until.timestamp() <= self.clock():
                raise HTTPException(status_code=422,
                                    detail="until_utc must be aware and in the future")
        elif until is not None:
            raise HTTPException(status_code=422, detail="until_utc only applies to deferred")
        if body.work_order and body.outcome != "maintenance_raised":
            raise HTTPException(status_code=422,
                                detail="work_order only applies to maintenance_raised")
        return {"loop_id": loop_id, "code": code, "since_utc": body.since_utc,
                "outcome": body.outcome,
                "until_utc": until.astimezone(UTC).isoformat() if until else None,
                "work_order": body.work_order or None, "actor": actor.actor,
                "at_utc": datetime.fromtimestamp(self.clock(), UTC).isoformat()}

    def _audit(self, actor: ActorContext, fields: dict[str, str]) -> None:
        """Require an audit append before the outcome becomes effective."""
        audit = AuthAudit(auth_dir(self.root) / AUDIT_FILE, self.clock)
        try:
            audit.append("finding_outcome", actor=actor.actor, source_ip=actor.source_ip, **fields)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail="audit_unavailable") from error

    def _save(self, records: Document) -> None:
        """Publish the sidecar atomically or report it unavailable."""
        try:
            write_json_atomic(self.root / "_runtime" / FILE, records)
        except OSError as error:
            raise HTTPException(status_code=503, detail=f"cannot save {FILE}") from error


def build_finding_outcome_router(root: Path, loops: Callable[[], dict[str, Any]],
                                 clock: Callable[[], float] = time.time) -> APIRouter:
    """Routes: PUT an outcome, GET all outcomes, GET the usefulness summary."""
    endpoints = FindingOutcomeEndpoints(root, clock, loops)
    router = APIRouter()
    router.add_api_route("/live/loops/{loop_id}/findings/{code}/outcome",
                         endpoints.put, methods=["PUT"])
    router.add_api_route("/live/finding-outcomes", endpoints.list_outcomes, methods=["GET"])
    router.add_api_route("/live/finding-outcomes/usefulness", endpoints.usefulness,
                         methods=["GET"])
    return router

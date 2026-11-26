"""Catalogue-backed live loop worklist and recent KPI observations.

These read-only endpoints join catalogue identity with runtime-owned state files.
"""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Annotated, Any

from crosscut_loops.worklist import add_worklist
from crosscut_runtime.kpi_history import finding_codes
from fastapi import APIRouter, HTTPException, Query

from crosscut_api.equipment_live_routes import read_equipment_events
from crosscut_api.finding_outcomes import (
    attach_outcomes,
    build_finding_outcome_router,
    read_outcomes,
)
from crosscut_api.runtime_routes import (
    SERVICE_FRESHNESS_S,
    _is_fresh,
    _load_site_document,
    _RuntimeEndpoints,
)

HISTORY_LIMIT = 500  # observations returned by default
HISTORY_LIMIT_MAX = 5000  # observations per response
MIN_FRESHNESS_S = 120  # seconds before even a fast job is considered stale
FRESHNESS_PERIODS = 3  # job periods allowed between observations


def _is_loop_fresh(job: dict[str, Any], entry: dict[str, Any]) -> bool:
    """Apply the runtime timestamp parser with this job's freshness window."""
    allowance_s = max(MIN_FRESHNESS_S, FRESHNESS_PERIODS * job.get("period_s", 0))
    # Shifting 'now' reuses the runtime parser's fixed service-age comparison.
    comparison_time = time.time() - allowance_s + SERVICE_FRESHNESS_S
    return _is_fresh(entry.get("last_run_utc"), comparison_time)


def _loop_findings(kpi: dict[str, Any] | None, since: dict[str, str]) -> list[dict[str, Any]]:
    """Use observed findings, preserving known findings during missing measurements."""
    codes = finding_codes(kpi) if kpi is not None else set(since)
    details = {finding["code"]: finding for finding in (kpi or {}).get("findings", [])
               if isinstance(finding, dict) and "code" in finding}
    return [{**details.get(code, {}), "code": code, "since_utc": since.get(code)}
            for code in sorted(codes)]


def _loop_row(
    loop: dict[str, Any], job: dict[str, Any], entry: dict[str, Any],
) -> dict[str, Any]:
    """Combine one catalogue loop with its enabled job's latest observation."""
    loop_id = loop["id"]
    kpi = (entry.get("kpi") or {}).get(loop_id)
    since = entry.get("findings_since", {}).get(loop_id, {})
    return {
        **(kpi or {}),
        "knowledge": loop,
        "id": loop_id, "name": loop.get("name", loop_id), "type": loop.get("type"),
        "job": job.get("id"), "job_status": entry.get("status", "idle") if job else None,
        "last_run_utc": entry.get("last_run_utc"),
        "fresh": bool(job) and _is_loop_fresh(job, entry), "kpi": kpi,
        "findings": _loop_findings(kpi, since),
    }


def _add_catalogue_criticality(rows: list[dict[str, Any]], site: dict[str, Any]) -> None:
    """Use primary owning equipment's consequence rating as the ranking input."""
    # Ratings are ordinal, dimensionless multipliers, not failure probabilities.
    # Multiple primary owners use the worst consequence; references are not ownership.
    ratings = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    for row in rows:
        owners = [equipment.get("criticality") for equipment in site.get("equipment", [])
                  if row["id"] in equipment.get("loops", [])]
        known = [rating for rating in owners if rating in ratings]
        if known:
            row["criticality"] = max(known, key=ratings.__getitem__)


def _read_history(path: Path, limit: int) -> list[dict[str, Any]]:
    """Read the newest observations in file order; missing history is empty."""
    try:
        with path.open(encoding="utf-8") as stream:
            lines = deque(stream, maxlen=limit)
    except FileNotFoundError:
        return []
    observations = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # A concurrent append can expose an unfinished last line.
        observations.append({"utc": entry["utc"], "kpi": entry["kpi"]})
    return observations


def _add_equipment_findings(rows: list[dict[str, Any]], root: Path) -> None:
    """Attach open equipment events to affected loops without changing KPI findings."""
    # Journal replay replaces opening snapshots with closing records, so a closed
    # equipment alarm cannot leave a stale action in the operator's worklist.
    events = read_equipment_events(root)
    for row in rows:
        opened = [event["opened_utc"] for event in events
                  if event.get("closed_utc") is None
                  and row["id"] in event.get("loops_affected", [])]
        if opened:
            row["findings"].append({"code": "equipment_anomaly", "since_utc": min(opened)})


class _LiveLoopsEndpoints(_RuntimeEndpoints):
    """Read the same runtime documents as the existing runtime endpoints."""

    def loops(self) -> dict[str, Any]:
        """Return catalogue loops ranked by severity, consequence and benefit."""
        site = _load_site_document(self._root) or {}
        jobs = self._load_jobs().get("jobs", [])
        states = self._load_state().get("jobs", {})
        rows = []
        for loop in site.get("loops", []):
            job = next((job for job in jobs if job.get("kind") == "loop_kpi"
                        and job.get("enabled") and loop["id"] in job.get("loops", [])), {})
            rows.append(_loop_row(loop, job, states.get(job.get("id"), {})))
        _add_equipment_findings(rows, self._root)
        _add_catalogue_criticality(rows, site)
        attach_outcomes(rows, read_outcomes(self._root), time.time())
        add_worklist(rows)
        return {"loops": sorted(rows, key=lambda row: row["priority_rank"])}

    def detail(
        self, loop_id: str,
        limit: Annotated[int, Query(ge=1, le=HISTORY_LIMIT_MAX)] = HISTORY_LIMIT,
    ) -> dict[str, Any]:
        """Return one catalogue loop and its bounded chronological history; 404 if unknown."""
        row = next((row for row in self.loops()["loops"] if row["id"] == loop_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown catalogue loop {loop_id!r}")
        path = self._root / "_runtime" / "kpi" / f"{loop_id}.jsonl"
        return {**row, "history": _read_history(path, limit)}


def build_live_loops_router(root: Path) -> APIRouter:
    """Build read-only routes for the live loop worklist and detail."""
    endpoints = _LiveLoopsEndpoints(root)
    router = APIRouter()
    router.add_api_route("/live/loops", endpoints.loops, methods=["GET"])
    router.add_api_route("/live/loops/{loop_id}", endpoints.detail, methods=["GET"])
    router.include_router(build_finding_outcome_router(root, endpoints.loops))
    return router

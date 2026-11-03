"""HTTP routes over the runtime service (Phase 1, #44).

The runtime runs as a separate process; these routes read the state it writes under
``<data root>/_runtime/`` and edit ``jobs.json``, which the runtime reloads by itself
(it notices the file mtime change). The service status is derived from the age of
``state.json``, not from a socket: a service younger than ``SERVICE_FRESHNESS_S`` is
"running".
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from crosscut_connectors.site import SiteError, load_site
from crosscut_runtime.store import JobStoreError, RuntimeStore
from fastapi import APIRouter, Body, HTTPException, Query
from jsonschema import Draft202012Validator

SERVICE_FRESHNESS_S = 30.0
LOG_LIMIT_DEFAULT = 200
LOG_LIMIT_MAX = 2000

_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "job.schema.json"
_JOB_FIELDS = frozenset(
    {"id", "kind", "source", "loops", "tags", "period_s", "window_s", "enabled"}
)


def _job_schema() -> dict[str, Any]:
    """The parsed job schema; one job is validated as ``{"schema_version": 1, "jobs": [job]}``."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _where(path: Any) -> str:
    """Render a JSON pointer path for error messages, defaulting to the document root."""
    return ".".join(str(part) for part in path) or "root"


def _schema_problems(job: dict[str, Any]) -> list[str]:
    """Validate a single job wrapped in a one-job document against the job schema."""
    one_job_document = {"schema_version": 1, "jobs": [job]}
    validator = Draft202012Validator(_job_schema())
    errors = sorted(
        validator.iter_errors(one_job_document),
        key=lambda error: list(error.absolute_path),
    )
    return [f"{_where(error.absolute_path)}: {error.message}" for error in errors]


def _cross_check_problems(
    job: dict[str, Any],
    site_doc: dict[str, Any],
    existing_ids: set[str],
) -> list[str]:
    """Cross-references of one job against the site catalogue and the existing jobs."""
    problems = _check_source(job, site_doc)
    problems += _check_loops(job, site_doc)
    problems += _check_tags(job, site_doc)
    problems += _check_duplicate_id(job, existing_ids)
    return problems


def _check_source(job: dict[str, Any], site_doc: dict[str, Any]) -> list[str]:
    """The job's source must exist in the site catalogue."""
    source_ids = {source.get("id") for source in site_doc.get("sources", [])}
    if job.get("source") not in source_ids:
        return [f"job.source: unknown source {job.get('source')!r}"]
    return []


def _check_loops(job: dict[str, Any], site_doc: dict[str, Any]) -> list[str]:
    """A loop_kpi job must name at least one known loop and no unknown loops."""
    if job.get("kind") != "loop_kpi":
        return []
    loop_ids = job.get("loops") or []
    if not loop_ids:
        return ["job.loops: required and non-empty for loop_kpi jobs"]
    known = {loop.get("id") for loop in site_doc.get("loops", [])}
    return [f"job.loops: unknown loop {loop_id!r}" for loop_id in loop_ids if loop_id not in known]


def _check_tags(job: dict[str, Any], site_doc: dict[str, Any]) -> list[str]:
    """An anomaly_scan job must name at least one known tag and no unknown tags."""
    if job.get("kind") != "anomaly_scan":
        return []
    tag_ids = job.get("tags") or []
    if not tag_ids:
        return ["job.tags: required and non-empty for anomaly_scan jobs"]
    known = {tag.get("id") for tag in site_doc.get("tags", [])}
    return [f"job.tags: unknown tag {tag_id!r}" for tag_id in tag_ids if tag_id not in known]


def _check_duplicate_id(job: dict[str, Any], existing_ids: set[str]) -> list[str]:
    """The job id must not collide with an existing job."""
    if job.get("id") in existing_ids:
        return [f"job.id: duplicate job {job.get('id')!r}"]
    return []


def job_problems(
    job: dict[str, Any],
    site_doc: dict[str, Any] | None,
    existing_ids: set[str],
) -> list[str]:
    """Problems of one job: schema problems first, then cross-checks.

    ``site_doc`` is the site catalogue (``None`` when it does not exist);
    ``existing_ids`` are the ids of jobs already stored.
    """
    problems = _schema_problems(job)
    if site_doc is None:
        return problems + ["no site catalogue: create it first"]
    problems += _cross_check_problems(job, site_doc, existing_ids)
    return problems


def _is_fresh(updated_at_utc: str | None, now: float) -> bool:
    """Whether the given UTC timestamp lies within ``SERVICE_FRESHNESS_S`` of ``now``."""
    if updated_at_utc is None:
        return False
    try:
        updated_at = datetime.fromisoformat(updated_at_utc)
    except ValueError:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return (now - updated_at.timestamp()) <= SERVICE_FRESHNESS_S


def _job_summary(job: dict[str, Any], state_entry: dict[str, Any] | None) -> dict[str, Any]:
    """A job merged with its runtime state; a missing state entry means "idle"."""
    entry = state_entry or {}
    return {
        "id": job.get("id"),
        "kind": job.get("kind"),
        "source": job.get("source"),
        "enabled": job.get("enabled"),
        "status": entry.get("status", "idle"),
        "last_run_utc": entry.get("last_run_utc"),
        "error": entry.get("error"),
        "samples": entry.get("samples", 0),
        "kpi": entry.get("kpi"),
        "scan": entry.get("scan"),
    }


def _load_site_document(root: Path) -> dict[str, Any] | None:
    """The site catalogue, or ``None`` when it does not exist or is unreadable."""
    try:
        return load_site(root)
    except SiteError:
        return None


def _job_ids(document: dict[str, Any]) -> set[str]:
    """Ids of the jobs in a jobs document."""
    return {job.get("id") for job in document.get("jobs", [])}


class _RuntimeEndpoints:
    """HTTP endpoint handlers for the runtime service: status, log, and job editing."""

    def __init__(self, root: Path) -> None:
        """Keep the data root and open the runtime store over it."""
        self._root = root
        self._store = RuntimeStore(root)

    def status(self) -> dict[str, Any]:
        """Return the service health (freshness of state.json) and every job with its state."""
        state = self._load_state()
        service = self._service_block(state)
        jobs = self._load_jobs()
        state_jobs = state.get("jobs", {})
        summaries = [
            _job_summary(job, state_jobs.get(job.get("id"))) for job in jobs.get("jobs", [])
        ]
        return {"service": service, "jobs": summaries}

    def log(
        self,
        limit: Annotated[int, Query(ge=1, le=LOG_LIMIT_MAX)] = LOG_LIMIT_DEFAULT,
    ) -> dict[str, Any]:
        """Return the most recent ``limit`` log lines from the runtime, as JSON strings."""
        entries = self._store.read_log(limit)
        return {"lines": [json.dumps(entry, ensure_ascii=False) for entry in entries]}

    def jobs(self) -> dict[str, Any]:
        """Return the jobs document as stored."""
        return self._load_jobs()

    def create_job(self, body: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        """Add one job after schema and cross-check validation; 422 or 409 on failure.

        A duplicate id is a conflict (409): the job already exists, the body is not at fault.
        """
        document = self._load_jobs()
        job = dict(body)
        existing_ids = _job_ids(document)
        if job.get("id") in existing_ids:
            raise HTTPException(status_code=409, detail=f"duplicate job {job.get('id')!r}")
        problems = job_problems(job, _load_site_document(self._root), existing_ids)
        if problems:
            raise HTTPException(status_code=422, detail=problems)
        document.setdefault("jobs", []).append(job)
        self._save_jobs(document)
        return document

    def update_job(
        self,
        job_id: str,
        body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        """Merge ``body`` over the stored job, then validate and save; 404 unknown."""
        document = self._load_jobs()
        existing = self._find_job(document, job_id)
        merged = self._merge(existing, body)
        problems = job_problems(merged, _load_site_document(self._root), set())
        if problems:
            raise HTTPException(status_code=422, detail=problems)
        document["jobs"] = [merged if job.get("id") == job_id else job for job in document["jobs"]]
        self._save_jobs(document)
        return document

    def delete_job(self, job_id: str) -> dict[str, Any]:
        """Remove a job by id and save; 404 when it does not exist."""
        document = self._load_jobs()
        self._find_job(document, job_id)
        document["jobs"] = [job for job in document["jobs"] if job.get("id") != job_id]
        self._save_jobs(document)
        return document

    def start_job(self, job_id: str) -> dict[str, Any]:
        """Set ``enabled`` to True via the update path; 404 unknown."""
        return self.update_job(job_id, {"enabled": True})

    def stop_job(self, job_id: str) -> dict[str, Any]:
        """Set ``enabled`` to False via the update path; 404 unknown."""
        return self.update_job(job_id, {"enabled": False})

    def _load_jobs(self) -> dict[str, Any]:
        """The jobs document, mapping storage failures to HTTP 502."""
        try:
            return self._store.load_jobs()
        except JobStoreError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    def _save_jobs(self, document: dict[str, Any]) -> None:
        """Persist the jobs document, mapping storage failures to HTTP 502."""
        try:
            self._store.save_jobs(document)
        except JobStoreError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    def _load_state(self) -> dict[str, Any]:
        """The runtime state document, empty when unreadable."""
        try:
            return self._store.load_state()
        except JobStoreError:
            return {}

    def _service_block(self, state: dict[str, Any]) -> dict[str, Any]:
        """Service running flag from ``state.json`` freshness."""
        updated = state.get("updated_at_utc")
        running = state.get("service") == "running" and _is_fresh(updated, time.time())
        return {"running": running, "updated_at_utc": updated}

    def _find_job(self, document: dict[str, Any], job_id: str) -> dict[str, Any]:
        """The stored job with that id, or HTTP 404."""
        for job in document.get("jobs", []):
            if job.get("id") == job_id:
                return job
        raise HTTPException(status_code=404, detail=f"no job {job_id!r}")

    def _merge(self, existing: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        """Shallow merge ``body`` over the job, rejecting unknown fields."""
        unknown = sorted(set(body) - _JOB_FIELDS)
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown job field: {unknown[0]}")
        return {**existing, **body}


def build_runtime_router(root: Path) -> APIRouter:
    """Create and return the APIRouter for runtime status, log, and job editing."""
    endpoints = _RuntimeEndpoints(root)
    router = APIRouter()
    router.add_api_route("/runtime/status", endpoints.status, methods=["GET"])
    router.add_api_route("/runtime/log", endpoints.log, methods=["GET"])
    router.add_api_route("/runtime/jobs", endpoints.jobs, methods=["GET"])
    router.add_api_route("/runtime/jobs", endpoints.create_job, methods=["POST"])
    router.add_api_route("/runtime/jobs/{job_id}", endpoints.update_job, methods=["PATCH"])
    router.add_api_route("/runtime/jobs/{job_id}", endpoints.delete_job, methods=["DELETE"])
    router.add_api_route("/runtime/jobs/{job_id}/start", endpoints.start_job, methods=["POST"])
    router.add_api_route("/runtime/jobs/{job_id}/stop", endpoints.stop_job, methods=["POST"])
    return router

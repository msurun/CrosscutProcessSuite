"""
Runtime service orchestrating periodic jobs (Phase 1, #44).

Loads site and jobs, synchronizes the scheduler, executes due jobs, and updates
the state store with results and service status.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_connectors.registry import connector_from_source
from crosscut_connectors.site import SiteError, load_site

from crosscut_runtime.history import HistoryError, HistoryStore, history_path
from crosscut_runtime.jobs.loop_kpi import LoopKpiJob
from crosscut_runtime.scheduler import JobSlot, Scheduler
from crosscut_runtime.store import RuntimeStore


class RuntimeService:
    """Service that manages job scheduling, execution, and state reporting."""

    def __init__(
        self,
        root: Path,
        connector_factory: Callable[[dict[str, Any]], Any] = connector_from_source,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Initialize the service with a storage root and injected dependencies."""
        self._store = RuntimeStore(root)
        self._scheduler = Scheduler(clock)
        self._connector_factory = connector_factory
        self._clock = clock
        self._job_docs: dict[str, dict[str, Any]] = {}
        self._connectors: dict[str, Any] = {}
        self._kpi_jobs: dict[str, LoopKpiJob] = {}
        self._history = HistoryStore(history_path(root))
        self._pending_samples: list[tuple[str, float, float]] = []

    def run_once(self) -> None:
        """Synchronize configuration, run due jobs, and record the results."""
        jobs_doc = self._store.load_jobs()
        try:
            site = load_site(self._store.root)
        except SiteError as error:
            self._store.append_log("error", f"Failed to load site: {error}")
            return

        self._sync_scheduler(jobs_doc.get("jobs", []), site)
        results = self._scheduler.tick(self._clock())
        self._flush_samples()
        self._update_state(jobs_doc.get("jobs", []), results)

    def stop(self) -> None:
        """Mark the service as stopped in the state file."""
        state = self._store.load_state()
        state["service"] = "stopped"
        state["updated_at_utc"] = datetime.now(UTC).isoformat()
        self._store.save_state(state)

    def _sync_scheduler(self, jobs: list[dict[str, Any]], site: dict[str, Any]) -> None:
        """Update job slots based on current configuration and site."""
        loop_docs = {loop["id"]: loop for loop in site.get("loops", [])}
        sources = {src["id"]: src for src in site.get("sources", [])}
        active_ids = set()

        for job in jobs:
            job_id = job["id"]
            if not job.get("enabled", False) or job["kind"] == "anomaly_scan":
                self._remove_job(job_id)
                continue

            active_ids.add(job_id)
            if job["kind"] == "loop_kpi":
                self._sync_loop_kpi_job(job, loop_docs, sources)

        for job_id in self._scheduler.ids():
            if job_id not in active_ids:
                self._remove_job(job_id)

    def _remove_job(self, job_id: str) -> None:
        """Unschedule a job and drop its cached KPI job (the rolling window goes with it)."""
        self._scheduler.remove(job_id)
        self._kpi_jobs.pop(job_id, None)

    def _sync_loop_kpi_job(
        self,
        job: dict[str, Any],
        loop_docs: dict[str, dict[str, Any]],
        sources: dict[str, dict[str, Any]],
    ) -> None:
        """Update or create a JobSlot for a loop_kpi job."""
        job_id = job["id"]
        unchanged = self._job_docs.get(job_id) == job

        if not unchanged:
            self._job_docs[job_id] = job
            source_doc = sources.get(job["source"], {})
            self._connectors[job_id] = self._connector_factory(source_doc)

        kpi_job = self._kpi_job_for(job, loop_docs)

        def run_fn() -> Any:
            return kpi_job.run()

        existing = self._scheduler.get(job_id)
        if existing and unchanged:
            existing.run = run_fn
            existing.period_s = job["period_s"]
        else:
            self._scheduler.put(JobSlot(job_id, job["period_s"], run_fn))

    def _kpi_job_for(self, job: dict[str, Any], loop_docs: dict[str, dict[str, Any]]) -> LoopKpiJob:
        """The cached LoopKpiJob of a job, so its rolling window survives across runs.

        A new instance (and an empty window) is made only when the job doc or the loop docs change.
        """
        job_id = job["id"]
        cached = self._kpi_jobs.get(job_id)
        if cached is None or cached.job_doc != job or cached.loop_docs != loop_docs:
            cached = LoopKpiJob(
                job, loop_docs, self._connectors[job_id], on_sample=self._buffer_sample
            )
            self._kpi_jobs[job_id] = cached
        return cached

    def _buffer_sample(self, tag: str, ts: float, value: float) -> None:
        """Queue one accepted live sample; it is written to history at the end of the pass."""
        self._pending_samples.append((tag, ts, value))

    def _flush_samples(self) -> None:
        """Write the samples queued during this pass; a store failure is logged, not raised."""
        if not self._pending_samples:
            return
        rows, self._pending_samples = self._pending_samples, []
        try:
            self._history.append(rows)
        except HistoryError as error:
            self._store.append_log("error", f"History write failed: {error}")

    def _update_state(self, jobs: list[dict[str, Any]], results: list[Any]) -> None:
        """Merge job outcomes into the runtime state file."""
        state = self._store.load_state()
        job_states = state.get("jobs", {})
        results_by_id = {run.job_id: run for run in results}
        now_utc = datetime.now(UTC).isoformat()

        for job in jobs:
            job_id = job["id"]
            st = job_states.setdefault(job_id, {})
            if not job.get("enabled", False):
                continue
            if job["kind"] == "anomaly_scan":
                st["status"] = "unsupported"
                continue

            run = results_by_id.get(job_id)
            if run:
                st["last_run_utc"] = now_utc
                if run.ok:
                    st.update({"status": "ok", "error": None})
                    st["samples"] = run.result.get("samples")
                    st["kpi"] = run.result.get("kpi")
                else:
                    st.update({"status": "error", "error": run.error})
                    self._store.append_log("error", run.error, job_id)
            elif not st.get("status"):
                st["status"] = "idle"

        state.update({"service": "running", "updated_at_utc": now_utc, "jobs": job_states})
        self._store.save_state(state)


def serve(
    root: Path,
    interval_s: float = 1.0,
    stop_event: threading.Event | None = None,
) -> None:
    """Run the runtime service periodically until stopped."""
    service = RuntimeService(root)
    if stop_event is None:
        stop_event = threading.Event()

    try:
        while not stop_event.is_set():
            service.run_once()
            stop_event.wait(interval_s)
    finally:
        service.stop()

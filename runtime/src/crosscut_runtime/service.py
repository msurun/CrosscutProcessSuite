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

from crosscut_runtime.addressing import AddressedConnector
from crosscut_runtime.controllers.wiring import (
    ControllerJob,
    build_controller_job,
    default_gateway_ports,
)
from crosscut_runtime.history import HistoryError, HistoryStore, history_path
from crosscut_runtime.jobs.anomaly_scan import AnomalyScanJob
from crosscut_runtime.jobs.loop_kpi import LoopKpiJob
from crosscut_runtime.jobs.tuning_review import TuningReviewJob
from crosscut_runtime.scheduler import JobSlot, Scheduler
from crosscut_runtime.store import RuntimeStore

RUNNABLE_KINDS = ("loop_kpi", "anomaly_scan", "tuning_review", "controller")


def _failing_run(message: str) -> Callable[[], Any]:
    """A run function that raises on every pass, for a job that cannot be built."""

    def run() -> Any:
        raise ValueError(message)

    return run


class RuntimeService:
    """Service that manages job scheduling, execution, and state reporting."""

    def __init__(
        self,
        root: Path,
        connector_factory: Callable[[dict[str, Any]], Any] = connector_from_source,
        clock: Callable[[], float] = time.time,
        gateway_ports: Any = default_gateway_ports,
    ) -> None:
        """Initialize the service with a storage root and injected dependencies."""
        self._store = RuntimeStore(root)
        self._scheduler = Scheduler(clock)
        self._connector_factory = connector_factory
        self._clock = clock
        self._gateway_ports = gateway_ports
        self._controller_jobs: dict[str, tuple[dict[str, Any], ControllerJob]] = {}
        self._job_docs: dict[str, dict[str, Any]] = {}
        self._addresses: dict[str, dict[str, str]] = {}
        self._connectors: dict[str, Any] = {}
        self._kpi_jobs: dict[str, LoopKpiJob] = {}
        self._anomaly_jobs: dict[str, tuple[dict[str, Any], AnomalyScanJob]] = {}
        self._review_jobs: dict[str, TuningReviewJob] = {}
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
        addresses = {t["id"]: t["address"] for t in site.get("tags", []) if t.get("address")}
        active_ids = set()

        for job in jobs:
            job_id = job["id"]
            if not job.get("enabled", False):
                self._remove_job(job_id)
                continue

            active_ids.add(job_id)
            if job["kind"] == "tuning_review":
                self._sync_review(job)
            elif job["kind"] == "loop_kpi":
                self._sync_job(job, sources, addresses, lambda doc: self._loop_run(doc, loop_docs))
            elif job["kind"] == "anomaly_scan":
                self._sync_job(job, sources, addresses, self._anomaly_run)
            elif job["kind"] == "controller":
                self._sync_controller(job, site)

        for job_id in self._scheduler.ids():
            if job_id not in active_ids:
                self._remove_job(job_id)

    def _remove_job(self, job_id: str) -> None:
        """Unschedule a job and drop its cached job objects (the rolling windows go with them)."""
        self._scheduler.remove(job_id)
        self._kpi_jobs.pop(job_id, None)
        self._anomaly_jobs.pop(job_id, None)
        self._review_jobs.pop(job_id, None)
        self._controller_jobs.pop(job_id, None)

    def _sync_controller(self, job: dict[str, Any], site: dict[str, Any]) -> None:
        """Update the JobSlot of a controller job; its host is cached per job doc."""
        run = self._controller_run(job, site)
        existing = self._scheduler.get(job["id"])
        if existing:
            existing.run, existing.period_s = run, job["period_s"]
        else:
            self._scheduler.put(JobSlot(job["id"], job["period_s"], run))

    def _controller_run(self, job: dict[str, Any], site: dict[str, Any]) -> Callable[[], Any]:
        """The run function of a controller job; a job that cannot be built fails each pass."""
        cached = self._controller_jobs.get(job["id"])
        if cached is None or cached[0] != job:
            deps = (self._connector_factory, self._gateway_ports)
            try:
                built = build_controller_job(job, site, self._store.root, deps)
            except (ValueError, ImportError) as error:
                return _failing_run(str(error))
            cached = (job, built)
            self._controller_jobs[job["id"]] = cached
        return cached[1].run

    def _sync_review(self, job: dict[str, Any]) -> None:
        """Update the JobSlot of a tuning_review job; no connector needed."""
        job_id = job["id"]
        cached = self._review_jobs.get(job_id)
        if cached is None or cached.job_doc != job:
            cached = TuningReviewJob(job, self._store.root, self._history, self._clock)
            self._review_jobs[job_id] = cached
        existing = self._scheduler.get(job_id)
        if existing:
            existing.run, existing.period_s = cached.run, job["period_s"]
        else:
            self._scheduler.put(JobSlot(job_id, job["period_s"], cached.run))

    def _sync_job(
        self,
        job: dict[str, Any],
        sources: dict[str, dict[str, Any]],
        addresses: dict[str, str],
        make_run: Callable[[dict[str, Any]], Callable[[], Any]],
    ) -> None:
        """Update the JobSlot of a job; rebuild its connector when the doc or addresses change."""
        job_id = job["id"]
        unchanged = self._job_docs.get(job_id) == job and self._addresses.get(job_id) == addresses

        if not unchanged:
            self._job_docs[job_id] = job
            self._addresses[job_id] = addresses
            connector = self._connector_factory(sources.get(job["source"], {}))
            self._connectors[job_id] = AddressedConnector(connector, addresses)
            self._kpi_jobs.pop(job_id, None)
            self._anomaly_jobs.pop(job_id, None)

        run_fn = make_run(job)
        existing = self._scheduler.get(job_id)
        if existing and unchanged:
            existing.run = run_fn
            existing.period_s = job["period_s"]
        else:
            self._scheduler.put(JobSlot(job_id, job["period_s"], run_fn))

    def _loop_run(
        self, job: dict[str, Any], loop_docs: dict[str, dict[str, Any]]
    ) -> Callable[[], Any]:
        """The run function of a loop_kpi job, bound to its cached LoopKpiJob."""
        return self._kpi_job_for(job, loop_docs).run

    def _anomaly_run(self, job: dict[str, Any]) -> Callable[[], Any]:
        """The run function of an anomaly_scan job; a job that cannot be built fails each pass."""
        try:
            return self._anomaly_job_for(job).run
        except ValueError as error:
            return _failing_run(str(error))

    def _anomaly_job_for(self, job: dict[str, Any]) -> AnomalyScanJob:
        """The cached AnomalyScanJob of a job, so its learned model and clock survive across runs.

        A new instance is made only when the job doc changes; a ValueError propagates.
        """
        job_id = job["id"]
        cached = self._anomaly_jobs.get(job_id)
        if cached is None or cached[0] != job:
            scan_job = AnomalyScanJob(job, self._connectors[job_id], self._history, self._clock)
            cached = (job, scan_job)
            self._anomaly_jobs[job_id] = cached
        return cached[1]

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

    @staticmethod
    def _review_state(st: dict[str, Any], result: dict[str, Any]) -> None:
        """Record a tuning_review pass: error if records were skipped, idle if none open."""
        errors = int(result.get("errors", 0))
        idle = not (result.get("reviewed") or result.get("pending") or errors)
        status = "error" if errors else ("idle" if idle else "ok")
        message = f"{errors} proposal record(s) skipped, see the log" if errors else None
        st.update({"status": status, "error": message, "review": result})

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
            if job["kind"] not in RUNNABLE_KINDS:
                st["status"] = "unsupported"
                continue

            run = results_by_id.get(job_id)
            if run:
                st["last_run_utc"] = now_utc
                if run.ok and job["kind"] == "tuning_review":
                    self._review_state(st, run.result)
                elif run.ok:
                    st.update({"status": "ok", "error": None})
                    st["samples"] = run.result.get("samples")
                    st["kpi"] = run.result.get("kpi")
                    st["scan"] = run.result.get("scan")
                    st["controller"] = run.result.get("controller")
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

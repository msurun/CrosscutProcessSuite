"""
Runtime service orchestrating periodic jobs (Phase 1, #44).

Loads site and jobs, synchronizes the scheduler, executes due jobs, and updates
the state store with results and service status.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_connectors.dependency_index import DependencyView
from crosscut_connectors.registry import connector_from_source
from crosscut_connectors.site import SiteError, load_site
from crosscut_connectors.site_fingerprint import job_tag_ids, reason_text
from crosscut_fuzzy.library import load_document
from crosscut_fuzzy.model import FuzzyModelError

from crosscut_runtime.addressing import AddressedConnector
from crosscut_runtime.controllers.gateway_adapter import make_liveness_sender
from crosscut_runtime.controllers.runtime_beat import RuntimeBeat
from crosscut_runtime.controllers.wiring import (
    FUZZY_FOLDER,
    ControllerJob,
    build_controller_job,
    default_gateway_ports,
)
from crosscut_runtime.history import HistoryError, HistoryStore, history_path
from crosscut_runtime.jobs.anomaly_scan import ANOMALY_DIR, AnomalyScanJob
from crosscut_runtime.jobs.equipment_scan import EquipmentScanJob
from crosscut_runtime.jobs.loop_kpi import LoopKpiJob
from crosscut_runtime.jobs.tuning_review import TuningReviewJob
from crosscut_runtime.kpi_history import record_kpi_run
from crosscut_runtime.scheduler import JobSlot, Scheduler
from crosscut_runtime.store import RuntimeStore, controller_period, controller_period_problem

_UNSET: Any = object()
OVERRUN_PERIODS = 2.0  # a run later than this many periods after the previous one is an overrun
STALE_PREFIX = "stale_dependency"  # error text of a job that refuses to run on a changed tag
RUNNABLE_KINDS = ("loop_kpi", "anomaly_scan", "tuning_review", "controller", "equipment_scan")


def _failing_run(message: str) -> Callable[[], Any]:
    """A run function that raises on every pass, for a job that cannot be built."""

    def run() -> Any:
        raise ValueError(message)

    return run


def _controller_entry(job: dict[str, Any], site: dict[str, Any]) -> dict[str, Any]:
    """The site controller entry a job names; empty when it is absent."""
    # site.get("controllers") and each entry come from untyped JSON, so name the shapes.
    entry: dict[str, Any] = next(
        (c for c in site.get("controllers", []) if c["id"] == job.get("controller")), {}
    )
    return entry


def _controller_tag_ids(controller: dict[str, Any], loops: list[dict[str, Any]]) -> set[str]:
    """Ids of the tags a controller reads or writes: its CV/DV/ICV tags and its MV loop tags."""
    tags = {
        variable["binding"]["tag"] for variable in controller.get("variables", [])
        if variable["role"] != "MV" and "tag" in variable["binding"]
    }
    for loop in loops:
        tags.update(str(loop[key]) for key in ("pv", "sp", "out") if loop.get(key))
    return tags


def _rule_base_content(root: Path, rule_base: str | None) -> Any:
    """The rule base document, or the error text when it cannot be read (it then keys the cache)."""
    try:
        return load_document(str(rule_base), root / FUZZY_FOLDER)
    except (FuzzyModelError, FileNotFoundError, ValueError) as error:
        return f"unreadable: {error}"


def _controller_cache_key(job: dict[str, Any], site: dict[str, Any], root: Path) -> str:
    """Stable hash of everything a controller host is built from.

    Covers the job, the controller entry, its MV loops, the job's source (endpoint), the tag
    addresses it uses and the CONTENT of its rule base, so any change of them rebuilds the host.
    """
    controller = _controller_entry(job, site)
    loop_ids = {
        variable["binding"]["loop"] for variable in controller.get("variables", [])
        if variable["role"] == "MV"
    }
    loops = [loop for loop in site.get("loops", []) if loop["id"] in loop_ids]
    tags = _controller_tag_ids(controller, loops)
    addresses = {
        tag["id"]: tag.get("address") for tag in site.get("tags", []) if tag["id"] in tags
    }
    source = next((s for s in site.get("sources", []) if s["id"] == job.get("source")), {})
    effective = {
        "job": job, "controller": controller, "loops": loops, "source": source,
        "addresses": addresses, "rule_base": _rule_base_content(root, controller.get("rule_base")),
    }
    text = json.dumps(effective, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RuntimeService:
    """Service that manages job scheduling, execution, and state reporting."""

    def __init__(
        self,
        root: Path,
        connector_factory: Callable[[dict[str, Any]], Any] = connector_from_source,
        clock: Callable[[], float] = time.time,
        gateway_ports: Any = default_gateway_ports,
        liveness_factory: Any = _UNSET,
    ) -> None:
        """Initialize the service with a storage root and injected dependencies."""
        self._store = RuntimeStore(root)
        self._scheduler = Scheduler(clock)
        self._connector_factory = connector_factory
        self._clock = clock
        self._gateway_ports = gateway_ports
        self._liveness_factory = (
            (make_liveness_sender if gateway_ports is default_gateway_ports else None)
            if liveness_factory is _UNSET
            else liveness_factory
        )
        self._runtime_beat = RuntimeBeat(root, clock, self._liveness_factory)
        self._controller_jobs: dict[str, tuple[str, ControllerJob]] = {}
        self._job_docs: dict[str, dict[str, Any]] = {}
        self._addresses: dict[str, dict[str, str]] = {}
        self._connectors: dict[str, Any] = {}
        self._kpi_jobs: dict[str, LoopKpiJob] = {}
        self._anomaly_jobs: dict[str, tuple[dict[str, Any], AnomalyScanJob]] = {}
        self._equipment_jobs: dict[str, tuple[str, EquipmentScanJob]] = {}
        self._review_jobs: dict[str, TuningReviewJob] = {}
        self._history = HistoryStore(history_path(root))
        self._dep_memory: dict[str, Any] = {}
        self._deps: DependencyView | None = None
        self._pending_samples: list[tuple[str, float, float, int]] = []
        self._started_utc = datetime.now(UTC).isoformat()

    def run_once(self) -> None:
        """Synchronize configuration, run due jobs, and record the results."""
        jobs_doc = self._store.load_jobs()
        try:
            site = load_site(self._store.root)
        except SiteError as error:
            self._store.append_log("error", f"Failed to load site: {error}")
            return

        self._sync_scheduler(jobs_doc.get("jobs", []), site)
        self._runtime_beat.maybe_send(bool(self._controller_jobs))
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
        self._deps = DependencyView(self._store.root, site, self._dep_memory)
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
                self._sync_review(job, site)
            elif job["kind"] == "loop_kpi":
                make = self._guarded(site, lambda doc: self._loop_run(doc, loop_docs, site))
                self._sync_job(job, sources, addresses, make)
            elif job["kind"] == "anomaly_scan":
                self._sync_job(job, sources, addresses, self._guarded(site, self._anomaly_run))
            elif job["kind"] == "equipment_scan":
                make = self._guarded(site, lambda doc: self._equipment_run(doc, site))
                self._sync_job(job, sources, addresses, make)
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
        self._equipment_jobs.pop(job_id, None)
        self._controller_jobs.pop(job_id, None)

    def _sync_controller(self, job: dict[str, Any], site: dict[str, Any]) -> None:
        """Update a controller slot; cache its host per job and binding documents."""
        run = self._controller_run(job, site)
        period = controller_period(job, _controller_entry(job, site))
        existing = self._scheduler.get(job["id"])
        if existing:
            existing.run, existing.period_s = run, period
        else:
            self._scheduler.put(JobSlot(job["id"], period, run))

    def _controller_run(self, job: dict[str, Any], site: dict[str, Any]) -> Callable[[], Any]:
        """The run function of a controller job; a job that cannot be built fails each pass."""
        reasons = self._stale_reasons(job, site)
        try:
            problem = controller_period_problem(job, _controller_entry(job, site))
            if problem:
                raise ValueError(problem)
            key = _controller_cache_key(job, site, self._store.root)
            cached = self._controller_jobs.get(job["id"])
            if cached is None or cached[0] != key:
                deps = (self._connector_factory, self._gateway_ports, self._liveness_factory)
                built = build_controller_job(job, site, self._store.root, deps)
                cached = (key, built)
                self._controller_jobs[job["id"]] = cached
        except (ValueError, ImportError, TypeError, KeyError) as error:
            return self._controller_unbuildable(job, reasons, error)
        cached[1].set_stale(reasons)
        return cached[1].run

    def _controller_unbuildable(
        self, job: dict[str, Any], reasons: list[str], error: Exception
    ) -> Callable[[], Any]:
        """Run for a controller that cannot be built now.

        A running host whose tags went stale keeps cycling in the shed state, so the existing
        shed path and liveness beat release its targets; otherwise the job fails visibly.
        """
        cached = self._controller_jobs.get(job["id"])
        if reasons and cached is not None:
            cached[1].set_stale(reasons)
            return cached[1].run
        return _failing_run(reasons[0] if reasons else str(error))

    def _stale_reasons(self, job: dict[str, Any], site: dict[str, Any]) -> list[str]:
        """Texts of the dependencies of a job that no longer match the catalogue (empty: fine)."""
        try:
            view = self._deps if self._deps is not None else DependencyView(self._store.root, site)
            dependent = {"kind": "job", "id": job["id"], "tags": sorted(job_tag_ids(job, site))}
            found = view.reasons(f"job:{job['id']}", dependent)
            if job["kind"] == "anomaly_scan":
                found += view.reasons(f"anomaly:{job.get('anomaly_id', job['id'])}")
        except (KeyError, TypeError, AttributeError):
            return []  # a malformed document is reported by the job's own build, not here
        return [reason_text(found)] if found else []

    def _guarded(
        self, site: dict[str, Any], make_run: Callable[[dict[str, Any]], Callable[[], Any]]
    ) -> Callable[[dict[str, Any]], Callable[[], Any]]:
        """Wrap a run factory: a job on a stale tag refuses to run (no silent fallback)."""

        def make(job: dict[str, Any]) -> Callable[[], Any]:
            reasons = self._stale_reasons(job, site)
            return _failing_run(reasons[0]) if reasons else make_run(job)

        return make

    def _sync_review(self, job: dict[str, Any], site: dict[str, Any]) -> None:
        """Update the JobSlot of a tuning_review job; no connector needed."""
        job_id = job["id"]
        cached = self._review_jobs.get(job_id)
        if cached is None or cached.job_doc != job:
            cached = TuningReviewJob(job, self._store.root, self._history, self._clock)
            self._review_jobs[job_id] = cached
        reasons = self._stale_reasons(job, site)
        run = _failing_run(reasons[0]) if reasons else cached.run
        existing = self._scheduler.get(job_id)
        if existing:
            existing.run, existing.period_s = run, job["period_s"]
        else:
            self._scheduler.put(JobSlot(job_id, job["period_s"], run))

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
            self._equipment_jobs.pop(job_id, None)

        run_fn = make_run(job)
        existing = self._scheduler.get(job_id)
        if existing and unchanged:
            existing.run = run_fn
            existing.period_s = job["period_s"]
        else:
            self._scheduler.put(JobSlot(job_id, job["period_s"], run_fn))

    def _loop_run(
        self, job: dict[str, Any], loop_docs: dict[str, dict[str, Any]],
        site: dict[str, Any] | None = None,
    ) -> Callable[[], Any]:
        """The run function of a loop_kpi job, bound to its cached LoopKpiJob."""
        return self._kpi_job_for(job, loop_docs, site).run

    def _equipment_run(self, job: dict[str, Any], site: dict[str, Any]) -> Callable[[], Any]:
        """Keep per-equipment hysteresis until the job or catalogue changes."""
        key = json.dumps({"job": job, "site": site}, sort_keys=True)
        cached = self._equipment_jobs.get(job["id"])
        if cached is None or cached[0] != key:
            scan = EquipmentScanJob(job, site, self._connectors[job["id"]], self._store.root)
            scan.clock = self._clock
            cached = (key, scan)
            self._equipment_jobs[job["id"]] = cached
        return cached[1].run

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
            scan_job = AnomalyScanJob(
                job,
                self._connectors[job_id],
                self._history,
                self._clock,
                self._store.root / ANOMALY_DIR,
            )
            cached = (job, scan_job)
            self._anomaly_jobs[job_id] = cached
        return cached[1]

    def _kpi_job_for(
        self, job: dict[str, Any], loop_docs: dict[str, dict[str, Any]],
        site: dict[str, Any] | None = None,
    ) -> LoopKpiJob:
        """The cached LoopKpiJob of a job, so its rolling window survives across runs.

        A new instance (and an empty window) is made only when the job doc or the loop docs change.
        """
        job_id = job["id"]
        cached = self._kpi_jobs.get(job_id)
        modes = {"modes": (site or {}).get("modes", []),
                 "equipment": (site or {}).get("equipment", [])}
        if (cached is None or cached.job_doc != job or cached.loop_docs != loop_docs
                or cached.site != modes):
            cached = LoopKpiJob(
                job, loop_docs, self._connectors[job_id], on_sample=self._buffer_sample,
                site=modes,
            )
            self._kpi_jobs[job_id] = cached
        return cached

    def _buffer_sample(self, tag: str, ts: float, value: float) -> None:
        """Queue one accepted live sample; it is written to history at the end of the pass.

        Only GOOD samples are accepted by the loop-KPI job, so they are stored with quality 0.
        """
        self._pending_samples.append((tag, ts, value, 0))

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
                _note_run(st, job, now_utc, run.ok)
                if run.ok and job["kind"] == "tuning_review":
                    self._review_state(st, run.result)
                elif run.ok:
                    st.update({"status": "ok", "error": None})
                    st["samples"] = run.result.get("samples")
                    st["kpi"] = run.result.get("kpi")
                    st["scan"] = run.result.get("scan")
                    st["controller"] = run.result.get("controller")
                    st["equipment"] = run.result.get("equipment")
                    if job["kind"] == "loop_kpi":
                        record_kpi_run(self._store, job, st, now_utc)
                else:
                    stale = str(run.error).startswith(STALE_PREFIX)
                    st.update({"status": "stale" if stale else "error", "error": run.error})
                    self._store.append_log("error", run.error, job_id)
            elif not st.get("status"):
                st["status"] = "idle"

        state.update(
            {
                "service": "running",
                "updated_at_utc": now_utc,
                "started_at_utc": self._started_utc,
                "jobs": job_states,
            }
        )
        self._store.save_state(state)


def _late_by_periods(previous_utc: str | None, now_utc: str, period_s: float) -> bool:
    """True when two runs of a job lay more than two periods apart (it overran its slot)."""
    if previous_utc is None or period_s <= 0:
        return False
    try:
        now, previous = datetime.fromisoformat(now_utc), datetime.fromisoformat(previous_utc)
        gap = (now - previous).total_seconds()
    except ValueError:
        return False
    return gap > OVERRUN_PERIODS * period_s


def _note_run(st: dict[str, Any], job: dict[str, Any], now_utc: str, ok: bool) -> None:
    """Record one run in the job state: last run, last success or error time, overrun count."""
    if _late_by_periods(st.get("last_run_utc"), now_utc, float(job.get("period_s") or 0)):
        st["overrun_count"] = int(st.get("overrun_count", 0)) + 1
    st["last_run_utc"] = now_utc
    st["last_success_utc" if ok else "last_error_utc"] = now_utc


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

"""Inputs of a tuning proposal: the loop, its KPI job, the live values and the tuning report.

Everything the create route needs before ``build_proposal`` runs. Each failure is an
HTTPException with a stable code: 404 unknown loop or dataset, 409 no running loop_kpi job /
no live values / no parameter targets, 422 a window or loop the report cannot be made from.
The API reads the DCS only through a connector (read-only); nothing here writes anywhere.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from crosscut_connectors.base import Connector, ConnectorError
from crosscut_connectors.site import SiteError, load_site
from crosscut_loops.overview import LoopTags, analyze_dataset
from crosscut_loops.tuning_payload import MIN_WINDOW_S
from crosscut_loops.tuning_proposal import AMIGO_PID, WindowSpec
from crosscut_loops.tuning_report import TuningReport, build_tuning_report
from crosscut_loops.tuning_view import suggest_windows
from crosscut_runtime.history import HistoryStore, history_path
from crosscut_runtime.jobs.tuning_review import loop_tags, read_window
from crosscut_runtime.store import JobStoreError, RuntimeStore
from fastapi import HTTPException

SERVICE_FRESHNESS_S = 30.0
MIN_SAMPLES = 10
NS_PER_S = 1e9
INTEGRATING = "integrating"
BAD_JOB_STATES = ("error", "unsupported")
PI_PARAMS = ("gain", "ti")
PID_PARAMS = ("gain", "ti", "td", "tf")
LoadWide = Callable[[str], tuple[np.ndarray, dict[str, Any]]]
LoopsOf = Callable[[str], list[LoopTags]]
ConnectorFactory = Callable[[dict[str, Any]], Connector]


@dataclass(frozen=True)
class ReportSpec:
    """What to build the report from: the window choice, robustness and the ABB spans."""

    dataset_id: str | None = None
    history: tuple[datetime, datetime] | None = None
    start_s: float | None = None
    end_s: float | None = None
    robustness: float = 0.5
    pv_span: float | None = None
    out_span: float = 100.0


@dataclass(frozen=True)
class Sources:
    """Where the data comes from: the data root, the dataset loader and its loop finder."""

    root: Path
    load_wide: LoadWide
    loops_of: LoopsOf


def _refuse(status: int, code: str) -> HTTPException:
    """An HTTPException whose detail is a stable machine-readable code."""
    return HTTPException(status_code=status, detail=code)


def site_loop(root: Path, loop_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The site document and the loop entry ``loop_id``; 404 when there is none."""
    try:
        site = load_site(root)
    except SiteError:
        raise _refuse(404, "unknown_loop") from None
    for loop in site.get("loops", []):
        if loop.get("id") == loop_id:
            return site, loop
    raise _refuse(404, "unknown_loop")


def _service_fresh(state: dict[str, Any], now: float) -> bool:
    """True when the runtime state says running and was written within the freshness limit."""
    try:
        updated = datetime.fromisoformat(str(state["updated_at_utc"]))
    except (KeyError, ValueError):
        return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return state.get("service") == "running" and now - updated.timestamp() <= SERVICE_FRESHNESS_S


def running_kpi_job(root: Path, loop_id: str, now: float) -> dict[str, Any]:
    """The enabled loop_kpi job of the loop in a running runtime; 409 no_kpi_job otherwise."""
    store = RuntimeStore(root)
    try:
        jobs = store.load_jobs().get("jobs", [])
        state = store.load_state()
    except JobStoreError:
        raise _refuse(409, "no_kpi_job") from None
    if _service_fresh(state, now):
        for job in jobs:
            status = (state.get("jobs", {}).get(job.get("id")) or {}).get("status")
            if _is_kpi_job_of(job, loop_id) and status not in BAD_JOB_STATES:
                return dict(job)
    raise _refuse(409, "no_kpi_job")


def _is_kpi_job_of(job: dict[str, Any], loop_id: str) -> bool:
    """True for an enabled loop_kpi job that names the loop."""
    return (
        job.get("kind") == "loop_kpi"
        and job.get("enabled", True)
        and loop_id in (job.get("loops") or [])
    )


def wanted_targets(method: str, targets: dict[str, str]) -> dict[str, str]:
    """The policy targets a method writes: gain and ti, plus td and tf for amigo_pid."""
    names = PID_PARAMS if method == AMIGO_PID else PI_PARAMS
    return {name: tags for name, tags in targets.items() if name in names}


def read_current(
    site: dict[str, Any], source_id: str, targets: dict[str, str], factory: ConnectorFactory
) -> dict[str, float]:
    """Read the current parameter values live through the source's connector.

    Raises:
        HTTPException: 409 no_live_values when the source is unknown, the read fails, or a value
            is missing or not of good quality.
    """
    source = next((s for s in site.get("sources", []) if s.get("id") == source_id), None)
    if source is None or not targets:
        raise _refuse(409, "no_live_values")
    try:
        live = factory(source).read_live(list(targets.values()))
    except (ConnectorError, OSError, TimeoutError, ValueError):
        raise _refuse(409, "no_live_values") from None
    return _good_values(live, targets)


def _good_values(live: dict[str, Any], targets: dict[str, str]) -> dict[str, float]:
    """Parameter -> value from good-quality live values; 409 no_live_values when one is bad."""
    current: dict[str, float] = {}
    for param, tag in targets.items():
        sample = live.get(tag)
        if sample is None or sample.value is None or sample.quality != 0:
            raise _refuse(409, "no_live_values")
        current[param] = float(sample.value)
    return current


def pv_span_of(site: dict[str, Any], loop: dict[str, Any]) -> float | None:
    """Engineering span of the loop's PV tag from the site catalogue, or None."""
    for tag in site.get("tags", []):
        limits = tag.get("eng_limits") or {}
        if tag.get("id") == loop.get("pv") and {"min", "max"} <= set(limits):
            return float(limits["max"]) - float(limits["min"])
    return None


def sample_time(t_s: np.ndarray) -> float:
    """Median sample interval of a time axis, in seconds."""
    return float(np.median(np.diff(t_s)))


def make_report(
    arrays: tuple[str, np.ndarray, np.ndarray, float], spec: ReportSpec, stiction: bool
) -> TuningReport:
    """Build the tuning report of one window; arrays = (loop name, OUT, PV, sample time)."""
    name, out, pv, dt_s = arrays
    verdict = "stiction" if stiction else None
    return build_tuning_report(
        name, out, pv, dt_s, robustness=spec.robustness, stiction_verdict=verdict,
        pv_span=spec.pv_span, out_span=spec.out_span,
    )  # fmt: skip


def _find_dataset_loop(loops: list[LoopTags], loop_id: str, loop_doc: dict[str, Any]) -> LoopTags:
    """The dataset loop of a site loop (matched by id, then by the site loop's name)."""
    names = (loop_id, loop_doc.get("name"))
    for loop in loops:
        if loop.name in names:
            return loop
    raise _refuse(404, "loop_not_in_dataset")


def _chosen_window(t_s: np.ndarray, windows: list[tuple[float, float]], spec: ReportSpec) -> Any:
    """The requested window, else the best suggestion, else the whole record."""
    if spec.start_s is not None and spec.end_s is not None:
        return spec.start_s, spec.end_s
    return windows[0] if windows else (float(t_s[0]), float(t_s[-1]))


def _dataset_loop(sources: Sources, loop_doc: dict[str, Any], dataset_id: str) -> LoopTags:
    """The dataset loop of the site loop; 422 when the loop is an integrating (level) loop."""
    loops = sources.loops_of(dataset_id)
    loop = _find_dataset_loop(loops, str(loop_doc["id"]), loop_doc)
    if loop.process_kind == INTEGRATING:
        raise _refuse(422, "integrating_not_supported")
    return loop


def _stiction_suspected(t_s: np.ndarray, values: dict[str, Any], loop: LoopTags) -> bool:
    """True when the loop analysis of the whole record finds stiction."""
    findings = analyze_dataset(t_s, values, [loop])[0]["findings"]
    return any(finding["code"] == "stiction" for finding in findings)


def dataset_report(
    sources: Sources, loop_doc: dict[str, Any], spec: ReportSpec
) -> tuple[TuningReport, WindowSpec]:
    """The tuning report of a dataset window and the WindowSpec that names it."""
    dataset_id = str(spec.dataset_id)
    stamps, values = sources.load_wide(dataset_id)
    t_s = (stamps - stamps[0]) / NS_PER_S
    loop = _dataset_loop(sources, loop_doc, dataset_id)
    found = suggest_windows(t_s, values[loop.mode], values[loop.out], MIN_WINDOW_S)
    start_s, end_s = _chosen_window(t_s, found, spec)
    keep = (t_s >= start_s) & (t_s <= end_s)
    if int(keep.sum()) < MIN_SAMPLES:
        raise _refuse(422, "window_too_short")
    arrays = (loop.name, values[loop.out][keep], values[loop.pv][keep], sample_time(t_s[keep]))
    origin = float(stamps[0]) / NS_PER_S
    bounds = (origin + start_s, origin + end_s)
    start, end = (datetime.fromtimestamp(b, UTC) for b in bounds)
    window = WindowSpec(start, end, dataset_id)
    return make_report(arrays, spec, _stiction_suspected(t_s, values, loop)), window


def history_report(
    root: Path, loop_doc: dict[str, Any], spec: ReportSpec
) -> tuple[TuningReport, WindowSpec]:
    """The tuning report of a window of the runtime history and the WindowSpec that names it."""
    tags = loop_tags(loop_doc)
    if tags is None:
        raise _refuse(422, "loop_tags_missing")
    if spec.history is None or not history_path(root).exists():
        raise _refuse(422, "no_history")
    start, end = spec.history
    data = read_window(HistoryStore(history_path(root)), tags, (start.timestamp(), end.timestamp()))
    if len(data.t_s) < MIN_SAMPLES:
        raise _refuse(422, "window_too_short")
    arrays = (str(loop_doc["id"]), data.out, data.pv, sample_time(data.t_s))
    return make_report(arrays, spec, False), WindowSpec(start, end, None)


def build_report(sources: Sources, loop_doc: dict[str, Any], spec: ReportSpec) -> Any:
    """Report and window from a dataset when ``dataset_id`` is given, else from the history."""
    if spec.dataset_id is not None:
        return dataset_report(sources, loop_doc, spec)
    return history_report(sources.root, loop_doc, spec)


def now_seconds() -> float:
    """Wall clock in epoch seconds (a function so tests can replace it)."""
    return time.time()

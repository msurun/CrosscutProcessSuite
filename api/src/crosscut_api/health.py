"""Aggregated health of the runtime, the gateway and the jobs (issue #170).

``build_report`` is pure: it reads everything through ``HealthSources`` (callables), so tests
inject fake sources. Each item has a status (ok, warning, error), a machine ``code``, an English
``reason`` and small ``details`` for the GUI. The report status is the worst item status.
Nothing here writes anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

Doc = dict[str, Any]
OK, WARNING, ERROR = "ok", "warning", "error"
_RANK = {OK: 0, WARNING: 1, ERROR: 2}
RUNTIME_FRESH_S = 30.0  # same as runtime_routes.SERVICE_FRESHNESS_S
GATEWAY_FRESH_S = 10.0  # same as the gateway_provider default
JOB_WARN_PERIODS = 2.0  # a job not run for more than this many periods is late
JOB_ERROR_PERIODS = 5.0
DISK_WARN_FRACTION, DISK_ERROR_FRACTION = 0.10, 0.05
DISK_WARN_BYTES, DISK_ERROR_BYTES = 5 * 2**30, 1 * 2**30


@dataclass(frozen=True)
class HealthSources:
    """Where the report reads from; every member is a plain callable so tests can fake it."""

    now: Callable[[], datetime]
    runtime_state: Callable[[], Doc]
    jobs: Callable[[], list[Doc]]
    gateway_state: Callable[[], Doc | None]
    auth_audit_last: Callable[[], datetime | None]
    disk: Callable[[], tuple[int, int]]  # (free bytes, total bytes) of the data root
    versions: Callable[[], dict[str, str | None]]


def item(item_id: str, group: str, status: str, code: str, reason: str, **details: Any) -> Doc:
    """One health item."""
    return {"id": item_id, "group": group, "status": status, "code": code,
            "reason": reason, "details": details}


def parse_utc(value: Any) -> datetime | None:
    """An ISO time string as an aware datetime; ``None`` for anything else."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _age_s(value: Any, now: datetime) -> float | None:
    """Seconds between an ISO time and ``now``; ``None`` when the time is unknown."""
    moment = parse_utc(value)
    return None if moment is None else (now - moment).total_seconds()


def runtime_item(state: Doc, now: datetime) -> Doc:
    """The runtime process: not started, stopped, stale or running (with its uptime)."""
    age = _age_s(state.get("updated_at_utc"), now)
    if age is None:
        return item("runtime", "runtime", WARNING, "runtime_never_started",
                    "The runtime has not written a state yet.")
    if state.get("service") == "stopped":
        return item("runtime", "runtime", WARNING, "runtime_stopped",
                    "The runtime was stopped.", updated_age_s=age)
    if age > RUNTIME_FRESH_S:
        return item("runtime", "runtime", ERROR, "runtime_stale",
                    f"The runtime state is {age:.0f} s old.", updated_age_s=age)
    return item("runtime", "runtime", OK, "runtime_running", "The runtime is running.",
                updated_age_s=age, uptime_s=_age_s(state.get("started_at_utc"), now),
                started_at_utc=state.get("started_at_utc"))


def _job_status(job: Doc, st: Doc, runtime_up: bool, now: datetime) -> tuple[str, str, str]:
    """Status, code and reason of one enabled job."""
    if st.get("status") == "error":
        return ERROR, "job_error", f"The last run failed: {st.get('error') or 'unknown error'}."
    period = float(job.get("period_s") or 0)
    lag = _age_s(st.get("last_run_utc"), now)
    if not runtime_up:
        return WARNING, "job_runtime_down", "The runtime is not running, so the job is not run."
    if lag is None:
        return WARNING, "job_never_run", "The job has not run yet."
    if period > 0 and lag > JOB_ERROR_PERIODS * period:
        return ERROR, "job_overdue", f"No run for {lag:.0f} s (period {period:.0f} s)."
    if period > 0 and lag > JOB_WARN_PERIODS * period:
        return WARNING, "job_late", f"The last run was {lag:.0f} s ago (period {period:.0f} s)."
    return OK, "job_ok", "The job runs on time."


def job_items(state: Doc, jobs: list[Doc], now: datetime) -> list[Doc]:
    """One item per enabled job: last run, last success, last error, overruns and lag."""
    runtime_up = runtime_item(state, now)["status"] == OK
    states = state.get("jobs", {})
    items = []
    for job in jobs:
        if not job.get("enabled", False):
            continue
        st = states.get(job.get("id"), {})
        status, code, reason = _job_status(job, st, runtime_up, now)
        period = float(job.get("period_s") or 0)
        lag = _age_s(st.get("last_run_utc"), now)
        items.append(item(
            f"job:{job.get('id')}", "jobs", status, code, reason,
            kind=job.get("kind"), period_s=period or None, last_run_utc=st.get("last_run_utc"),
            last_success_utc=st.get("last_success_utc"), last_error_utc=st.get("last_error_utc"),
            last_error=st.get("error"), overrun_count=int(st.get("overrun_count", 0)),
            lag_s=None if lag is None else max(0.0, lag - period)))
    return items


def gateway_items(state: Doc | None, now: datetime, runtime_running: bool) -> list[Doc]:
    """The gateway process and mode, then the liveness it sees of the runtime and controllers."""
    if state is None:
        return [item("gateway", "gateway", ERROR, "gateway_unreachable",
                     "The gateway state file is missing or unreadable.")]
    age = _age_s(state.get("updated_at_utc"), now)
    mode = state.get("mode")
    if age is None or age > GATEWAY_FRESH_S:
        return [item("gateway", "gateway", ERROR, "gateway_stale",
                     "The gateway has not updated its state recently.",
                     mode=mode, updated_age_s=age)]
    if mode == "off":
        gateway = item("gateway", "gateway", WARNING, "gateway_mode_off",
                       "The gateway mode is off.", mode=mode)
    else:
        gateway = item("gateway", "gateway", OK, "gateway_ok",
                       f"The gateway runs in mode {mode}.", mode=mode)
    return [gateway, *liveness_items(state.get("liveness") or {}, runtime_running)]


def _beat_item(item_id: str, row: Doc | None, required: bool) -> Doc:
    """Liveness of one sender as the gateway sees it."""
    if row is None:
        status = WARNING if required else OK
        return item(item_id, "liveness", status, "liveness_unknown",
                    "The gateway has not received a beat yet.")
    if row.get("lost"):
        return item(item_id, "liveness", ERROR, "liveness_lost",
                    "The gateway lost the beat of this sender.", age_s=row.get("age_s"))
    return item(item_id, "liveness", OK, "liveness_ok", "The gateway sees fresh beats.",
                age_s=row.get("age_s"), state=row.get("state"))


def liveness_items(block: Doc, runtime_running: bool) -> list[Doc]:
    """Runtime and controller beats from the ``liveness`` block of the gateway state."""
    items = [_beat_item("liveness:runtime", block.get("runtime"), runtime_running)]
    for controller_id, row in sorted((block.get("controllers") or {}).items()):
        items.append(_beat_item(f"liveness:controller:{controller_id}", row, False))
    return items


def audit_items(gateway: Doc | None, auth_last: datetime | None, now: datetime) -> list[Doc]:
    """Last audit write (gateway chain tail and sign-in log) and the gateway chain integrity."""
    items = []
    if gateway is not None and gateway.get("chain_ok") is False:
        items.append(item("audit:chain", "audit", ERROR, "audit_chain_broken",
                          "The gateway audit chain does not verify."))
    tail = (gateway or {}).get("audit_tail") or []
    gateway_last = None
    if tail:
        gateway_last = datetime.fromtimestamp(int(tail[-1]["t_ns"]) / 1e9, tz=UTC)
    last = max((t for t in (gateway_last, auth_last) if t is not None), default=None)
    if last is None:
        items.append(item("audit", "audit", OK, "audit_empty",
                          "No audit record has been written yet."))
    else:
        items.append(item("audit", "audit", OK, "audit_ok", "Audit records are written.",
                          last_write_utc=last.isoformat(), age_s=(now - last).total_seconds()))
    return items


def disk_item(free: int, total: int) -> Doc:
    """Free space of the data root: warning below 10 % or 5 GiB, error below 5 % or 1 GiB."""
    fraction = free / total if total else 0.0
    details = {"free_bytes": free, "total_bytes": total, "free_fraction": fraction}
    if fraction < DISK_ERROR_FRACTION or free < DISK_ERROR_BYTES:
        return item("disk", "system", ERROR, "disk_critical",
                    "The data disk is almost full.", **details)
    if fraction < DISK_WARN_FRACTION or free < DISK_WARN_BYTES:
        return item("disk", "system", WARNING, "disk_low",
                    "The data disk is running low.", **details)
    return item("disk", "system", OK, "disk_ok", "Enough free space on the data disk.", **details)


def version_item(versions: dict[str, str | None]) -> Doc:
    """Package versions; a warning when the installed Crosscut packages differ."""
    installed = {v for v in versions.values() if v is not None}
    if len(installed) > 1:
        return item("versions", "system", WARNING, "versions_differ",
                    "The installed Crosscut packages have different versions.", versions=versions)
    return item("versions", "system", OK, "versions_ok", "Package versions are consistent.",
                versions=versions)


def worst(items: list[Doc]) -> str:
    """The most severe status among the items (ok for none)."""
    return max((i["status"] for i in items), key=_RANK.__getitem__, default=OK)


def build_report(sources: HealthSources) -> Doc:
    """Collect every item of the report; its status is the worst item status."""
    now = sources.now()
    runtime = sources.runtime_state()
    gateway = sources.gateway_state()
    runtime_row = runtime_item(runtime, now)
    free, total = sources.disk()
    items = [
        runtime_row,
        *job_items(runtime, sources.jobs(), now),
        *gateway_items(gateway, now, runtime_row["status"] == OK),
        *audit_items(gateway, sources.auth_audit_last(), now),
        disk_item(free, total),
        version_item(sources.versions()),
    ]
    return {"generated_utc": now.isoformat(), "status": worst(items), "items": items}

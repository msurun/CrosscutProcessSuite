"""Persist live loop KPI observations and uninterrupted finding ages.

History is best effort so unavailable storage cannot stop runtime scheduling.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path
from typing import Any

from crosscut_runtime.store import RuntimeStore

HISTORY_LINES = 10_000  # observations retained after a trim
TRIM_THRESHOLD = HISTORY_LINES * 6 // 5  # 20 percent slack between rewrites


def finding_codes(kpi: dict[str, Any]) -> set[str]:
    """Normalize string findings and structured findings into unique codes."""
    codes = (entry.get("code") if isinstance(entry, dict) else entry
             for entry in kpi.get("findings", []))
    return {code for code in codes if isinstance(code, str) and code}


def _mode_field(kpi: dict[str, Any] | None) -> dict[str, str]:
    """The operating mode of the newest sample as an observation field, absent without modes."""
    mode = (kpi or {}).get("mode")
    return {"mode": mode} if mode else {}


def _append_observation(path: Path, observation: dict[str, Any]) -> None:
    """Append one JSON line and trim in batches once the slack is exhausted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(observation) + "\n")
    with path.open(encoding="utf-8") as stream:
        lines = deque(stream, maxlen=TRIM_THRESHOLD + 1)
    if len(lines) > TRIM_THRESHOLD:
        # Retain the newest observations; the slack amortizes the rewrite cost.
        path.write_text("".join(list(lines)[-HISTORY_LINES:]), encoding="utf-8")


def _log_failure(store: RuntimeStore, job_id: str, error: OSError) -> None:
    """Report history failures even when the runtime log directory is unavailable."""
    try:
        store.append_log("error", f"KPI history write failed: {error}", job_id)
    except OSError as log_error:
        logging.getLogger(__name__).warning("KPI history log failed: %s", log_error)


def record_kpi_run(
    store: RuntimeStore, job: dict[str, Any], state: dict[str, Any], utc: str,
) -> None:
    """Record each loop and update finding ages in the mutable job state."""
    values = state.get("kpi") or {}
    findings_since = state.setdefault("findings_since", {})
    for loop_id in job.get("loops", []):
        kpi = values.get(loop_id)
        if kpi is not None:
            previous = findings_since.get(loop_id, {})
            # Missing measurements do not prove recovery; only an observed absence does.
            findings_since[loop_id] = {code: previous.get(code, utc) for code in finding_codes(kpi)}
        path = store.root / "_runtime" / "kpi" / f"{loop_id}.jsonl"
        try:
            _append_observation(path, {"utc": utc, "job": job["id"], "kpi": kpi,
                                      **_mode_field(kpi)})
        except OSError as error:
            _log_failure(store, job["id"], error)

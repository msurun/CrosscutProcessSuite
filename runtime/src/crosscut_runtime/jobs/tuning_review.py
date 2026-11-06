"""KPI before/after review of applied tuning proposals (ADR 014 section 5, Phase 3).

The job scans <root>/_tuning/proposals/*.json for records of the reviewed loops that are
``applied`` (or already ``reviewing`` after an early warning), builds the before and after windows
from the runtime HistoryStore and lets ``crosscut_loops.tuning_review.compare_windows`` decide.
The review is written back into the record (atomic write, schema-validated). The record stays the
single source of truth: the job keeps no state about it, so a restart changes nothing.

Mode convention: the site loop document carries only the mode TAG, no code mapping, so a mode
sample counts as closed loop (AUTO or CAS) when it is nonzero and as open loop (MAN) when it is 0,
which matches the simulator codes MAN=0, AUTO=1, CAS=2.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from crosscut_connectors.site import load_site
from crosscut_loops import tuning_review as tr
from jsonschema import Draft202012Validator

from crosscut_runtime.history import HistoryError, HistoryStore
from crosscut_runtime.store import RuntimeStore, schemas_dir

PROPOSALS_PARTS = ("_tuning", "proposals")
PROPOSAL_SCHEMA_FILE = "tuning-proposal.schema.json"
# A cycle of the loop is at least this long in seconds, so a fast model never gives a 0 s window.
MIN_CYCLE_S = 60.0
OPEN_STATUSES = ("applied", "reviewing")
EXTERNAL_CHANGE_REASON = "param_changed_externally"
# A before-value with an absolute size below this (signal units) counts as zero in a ratio.
ZERO_EPS = 1e-12


class BadRecordError(ValueError):
    """A proposal record that cannot be read, is schema-invalid, or cannot be reviewed."""


@dataclass(frozen=True)
class LoopTags:
    """The four history tag ids of one loop."""

    pv: str
    sp: str
    out: str
    mode: str


@dataclass(frozen=True)
class Evaluation:
    """The outcome of one evaluation: the review block and whether it is final."""

    review: dict[str, Any]
    final: bool


@dataclass(frozen=True)
class Timing:
    """Window geometry of one applied proposal, all epoch seconds UTC."""

    before: tuple[float, float]
    after: tuple[float, float]
    cycle_s: float


@lru_cache(maxsize=4)
def _validator(schema_dir: str) -> Draft202012Validator:
    """The tuning-proposal validator for a schemas directory."""
    text = (Path(schema_dir) / PROPOSAL_SCHEMA_FILE).read_text(encoding="utf-8")
    return Draft202012Validator(json.loads(text))


def utc_to_epoch(text: str) -> float:
    """Epoch seconds of an ISO 8601 UTC timestamp such as 2026-11-05T10:00:00Z."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def epoch_to_utc(epoch_s: float) -> str:
    """ISO 8601 UTC text (whole seconds, trailing Z) of epoch seconds."""
    return datetime.fromtimestamp(epoch_s, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def loop_tags(loop_doc: dict[str, Any] | None) -> LoopTags | None:
    """The pv/sp/out/mode tag ids of a site loop doc, or None when one is not stated."""
    if loop_doc is None:
        return None
    ids = [loop_doc.get(channel) for channel in ("pv", "sp", "out", "mode")]
    if any(tag is None for tag in ids):
        return None
    return LoopTags(*(str(tag) for tag in ids))


def read_window(
    history: HistoryStore, tags: LoopTags, bounds: tuple[float, float], end_open: bool = False
) -> tr.WindowData:
    """Time-aligned WindowData of one window: only instants present for all four tags.

    ``bounds`` is (start, end) in epoch seconds; ``end_open`` excludes a sample stamped exactly
    at the end. The mode column is 1.0 where the raw mode is nonzero (closed loop), else 0.0.
    """
    start, end = bounds
    until = math.nextafter(end, -math.inf) if end_open else end
    series = {
        name: dict(history.query(getattr(tags, name), start, until))
        for name in ("pv", "sp", "out", "mode")
    }
    common = sorted(set.intersection(*(set(rows) for rows in series.values())))

    def column(name: str) -> np.ndarray:
        """One channel at the common instants."""
        return np.array([series[name][ts] for ts in common], dtype=float)

    return tr.WindowData(
        t_s=np.array(common, dtype=float),
        pv=column("pv"),
        sp=column("sp"),
        out=column("out"),
        mode=(column("mode") != 0.0).astype(float),
    )


def _ratio(after: float, before: float) -> float | None:
    """after / before, or None when the before-value is (nearly) zero."""
    return None if abs(before) < ZERO_EPS else float(after / before)


def _review_block(verdict: str, reasons: list[str], now_s: float) -> dict[str, Any]:
    """A review block without metrics, stamped with the evaluation time."""
    return {"verdict": verdict, "t": epoch_to_utc(now_s), "reasons": reasons}


def _compared_review(result: dict[str, Any], now_s: float) -> dict[str, Any]:
    """The review block of a compare_windows result, with before/after and ratio metrics."""
    review = _review_block(str(result["verdict"]), list(result["reasons"]), now_s)
    before, after = result["before"], result["after"]
    review["before"], review["after"], review["note"] = before, after, result["note"]
    review["metrics"] = {
        "error_std_ratio": _ratio(after["error_std"], before["error_std"]),
        "iae_per_h_ratio": _ratio(after["iae_per_h"], before["iae_per_h"]),
        "out_travel_ratio": _ratio(after["out_travel_per_h"], before["out_travel_per_h"]),
    }
    return review


def _timing(record: dict[str, Any]) -> Timing:
    """Window geometry from the applied time and the model of the proposal."""
    applied = record.get("applied")
    if not applied:
        raise BadRecordError("applied record without an applied block")
    model = record["source"]["model"]
    theta, tau = float(model["theta_s"]), float(model["tau_s"])
    before, after = tr.window_bounds(utc_to_epoch(applied["t"]), theta, tau)
    return Timing(before, after, max(theta + tau, MIN_CYCLE_S))


def _write_atomic(path: Path, document: dict[str, Any]) -> None:
    """Replace a JSON file atomically (temp file in the same folder, then os.replace)."""
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temp_name, path)
    except Exception:
        os.unlink(temp_name)
        raise


class TuningReviewJob:
    """Reviews the applied tuning proposals of the job's loops; stateless between runs."""

    def __init__(
        self,
        job_doc: dict[str, Any],
        root: Path,
        history: HistoryStore,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Create the job from its jobs.json doc, data root, history and a clock (epoch s)."""
        self.job_doc = job_doc
        self._root = root
        self._history = history
        self._clock = clock
        self._loops = frozenset(job_doc.get("loops", []))
        self._log = RuntimeStore(root)
        self._logged: set[tuple[str, int, str]] = set()

    @property
    def proposals_dir(self) -> Path:
        """Folder of the proposal records: <root>/_tuning/proposals."""
        return self._root.joinpath(*PROPOSALS_PARTS)

    def run(self) -> dict[str, Any]:
        """Review every open record of the job's loops once.

        Returns ``{"reviewed": [ids made final], "pending": [ids still waiting], "errors": n}``.
        A record file that is unreadable or invalid is skipped, logged and counted in errors.
        """
        site = load_site(self._root)
        loops = {loop["id"]: loop for loop in site.get("loops", [])}
        outcome: dict[str, Any] = {"reviewed": [], "pending": [], "errors": 0}
        for path in sorted(self.proposals_dir.glob("*.json")):
            bucket, proposal_id = self._process_file(path, loops)
            if bucket == "errors":
                outcome["errors"] += 1
            elif bucket:
                outcome[bucket].append(proposal_id)
        return outcome

    def _process_file(self, path: Path, loops: dict[str, Any]) -> tuple[str, str]:
        """Review one file; returns (bucket, id) with bucket reviewed, pending, errors or ''."""
        try:
            record = self._load_open_record(path)
            if record is None:
                return "", ""
            evaluation = self._evaluate(record, loops.get(record["loop_id"]))
            if evaluation is None:
                return "pending", str(record["id"])
            self._store_review(path, record, evaluation)
            return ("reviewed" if evaluation.final else "pending"), str(record["id"])
        except (BadRecordError, HistoryError, OSError, KeyError, ValueError) as error:
            self._log_once(path, f"tuning record {path.name} skipped: {error}")
            return "errors", ""

    def _log_once(self, path: Path, message: str) -> None:
        """Append an error log line, once per file version and message."""
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            stamp = 0
        key = (path.name, stamp, message)
        if key not in self._logged:
            self._logged.add(key)
            self._log.append_log("error", message, self.job_doc.get("id"))

    def _load_open_record(self, path: Path) -> dict[str, Any] | None:
        """The validated record when it is open and belongs to a reviewed loop, else None."""
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BadRecordError(f"unreadable: {error}") from error
        if not isinstance(record, dict):
            raise BadRecordError("not a JSON object")
        if record.get("status") not in OPEN_STATUSES or record.get("loop_id") not in self._loops:
            return None
        problems = [e.message for e in _validator(str(schemas_dir())).iter_errors(record)]
        if problems:
            raise BadRecordError("schema-invalid: " + "; ".join(problems[:3]))
        return record

    def _evaluate(
        self, record: dict[str, Any], loop_doc: dict[str, Any] | None
    ) -> Evaluation | None:
        """Decide what the record gets now; None means keep waiting (nothing to write)."""
        now_s = self._clock()
        applied = record["applied"] or {}
        if applied.get("invalid"):
            review = _review_block("insufficient_data", [EXTERNAL_CHANGE_REASON], now_s)
            return Evaluation(review, True)
        tags = loop_tags(loop_doc)
        if tags is None:
            review = _review_block("insufficient_data", ["loop_tags_missing"], now_s)
            return Evaluation(review, True)
        timing = _timing(record)
        if now_s >= timing.after[1]:
            return self._final(record, tags, timing, now_s)
        return self._early(record, tags, timing, now_s)

    def _final(
        self, record: dict[str, Any], tags: LoopTags, timing: Timing, now_s: float
    ) -> Evaluation:
        """The final verdict from the complete before and after windows."""
        before = read_window(self._history, tags, timing.before, end_open=True)
        after = read_window(self._history, tags, timing.after)
        review = _compared_review(tr.compare_windows(before, after), now_s)
        if (record["review"] or {}).get("early"):
            review["early"] = "worse_early"
        return Evaluation(review, True)

    def _early(
        self, record: dict[str, Any], tags: LoopTags, timing: Timing, now_s: float
    ) -> Evaluation | None:
        """A worse_early warning when the first cycles of the after window oscillate, else None."""
        thresholds = tr.DEFAULT_THRESHOLDS
        if now_s < timing.after[0] + thresholds.early_cycles * timing.cycle_s:
            return None
        if (record["review"] or {}).get("early"):
            return None
        after = read_window(self._history, tags, (timing.after[0], min(now_s, timing.after[1])))
        if tr.early_check(after, timing.cycle_s, thresholds) != "worse_early":
            return None
        review = _review_block("worse_early", ["early_oscillation"], now_s)
        review["early"] = "worse_early"
        return Evaluation(review, False)

    def _store_review(self, path: Path, record: dict[str, Any], evaluation: Evaluation) -> None:
        """Write the review and the new status into the record (validated, atomic)."""
        review = evaluation.review
        updated = dict(record)
        updated["review"] = review
        updated["status"] = f"reviewed:{review['verdict']}" if evaluation.final else "reviewing"
        problems = [e.message for e in _validator(str(schemas_dir())).iter_errors(updated)]
        if problems:
            raise BadRecordError("review does not fit the schema: " + "; ".join(problems[:3]))
        _write_atomic(path, updated)

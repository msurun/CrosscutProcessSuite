"""Append-only, hash-chained advisory log (ADR 010).

Each line is {"record": ..., "sha256": ...}; a record's prev_sha256 is the sha of the previous line.
Operator acknowledgements are appended with `ack`.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DECISIONS = ("accepted", "rejected", "deferred")


class AuditError(ValueError):
    """Raised for an invalid audit operation or an unreadable log."""


@dataclass(frozen=True)
class ChainReport:
    """Result of verifying the chain: ok flag, line count and first broken line index."""

    ok: bool
    records: int
    first_broken_index: int | None
    reason: str


@dataclass(frozen=True)
class AckRequest:
    """Operator acknowledgement of one advice."""

    advice_id: str
    decision: str
    reason_code: str
    who: str
    t_ns: int
    note: str = ""


def canonical_bytes(record: Mapping[str, Any]) -> bytes:
    """Canonical JSON bytes of a record (sorted keys, compact, UTF-8) without any own hash."""
    body = {k: v for k, v in record.items() if k != "sha256"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def record_sha(record: Mapping[str, Any]) -> str:
    """SHA-256 hex digest of the canonical bytes of a record."""
    return hashlib.sha256(canonical_bytes(record)).hexdigest()


def _parse_line(line: str) -> tuple[dict[str, Any], str]:
    """Parse one log line into (record, stored sha); raise AuditError if garbled."""
    try:
        obj = json.loads(line)
        record, sha = obj["record"], obj["sha256"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AuditError(f"garbled line: {exc}") from exc
    if not isinstance(record, dict) or not isinstance(sha, str):
        raise AuditError("garbled line: wrong field types")
    return record, sha


class AuditLog:
    """Hash-chained JSON-lines log file."""

    def __init__(self, path: Path) -> None:
        """Bind the log to a file path (created on first append)."""
        self.path = Path(path)
        self._lock = threading.Lock()

    def _lines(self) -> list[str]:
        """Non-empty raw lines of the file (empty list if missing)."""
        if not self.path.exists():
            return []
        text = self.path.read_text(encoding="utf-8")
        return [ln for ln in text.split("\n") if ln.strip()]

    def _last_sha(self) -> str:
        """Stored sha of the last line, or empty string for an empty log."""
        lines = self._lines()
        return _parse_line(lines[-1])[1] if lines else ""

    def append(self, record: Mapping[str, Any]) -> str:
        """Chain and append a record; return its sha."""
        with self._lock:
            body = dict(record)
            body["prev_sha256"] = self._last_sha()
            sha = record_sha(body)
            line = json.dumps({"record": body, "sha256": sha}, sort_keys=True, ensure_ascii=False)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return sha

    def records(self) -> list[dict[str, Any]]:
        """All records in order; raises AuditError on a garbled line."""
        return [_parse_line(ln)[0] for ln in self._lines()]

    def verify(self) -> ChainReport:
        """Recompute every sha and prev link; report the first broken line."""
        lines = self._lines()
        prev = ""
        for i, line in enumerate(lines):
            try:
                record, sha = _parse_line(line)
            except AuditError as exc:
                return ChainReport(False, len(lines), i, str(exc))
            if record.get("prev_sha256") != prev:
                return ChainReport(False, len(lines), i, "prev_sha256 does not match previous line")
            if record_sha(record) != sha:
                return ChainReport(False, len(lines), i, "sha256 does not match record")
            prev = sha
        return ChainReport(True, len(lines), None, "ok")

    def find_advice(self, advice_id: str) -> dict[str, Any] | None:
        """Return the advice record with this id, or None."""
        for rec in self.records():
            if rec.get("kind") == "advice" and rec.get("advice_id") == advice_id:
                return rec
        return None


def ack(log: AuditLog, req: AckRequest) -> str:
    """Append an acknowledgement of a logged advice; return its sha."""
    if req.decision not in DECISIONS:
        raise AuditError(f"decision must be one of {DECISIONS}")
    if not req.who.strip() or not req.reason_code.strip():
        raise AuditError("who and reason_code must not be empty")
    if log.find_advice(req.advice_id) is None:
        raise AuditError(f"unknown advice_id {req.advice_id}")
    return log.append(
        {
            "kind": "ack",
            "advice_id": req.advice_id,
            "decision": req.decision,
            "reason_code": req.reason_code,
            "note": req.note,
            "who": req.who,
            "t_ns": req.t_ns,
        }
    )

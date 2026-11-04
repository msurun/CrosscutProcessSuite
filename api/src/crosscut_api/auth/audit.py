"""
Implements an append-only, hash-chained audit log for authentication events.
Provides tamper-detection by chaining records cryptographically.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

GENESIS_HASH: str = "0" * 64
RESERVED_KEYS: frozenset[str] = frozenset({"seq", "t_ns", "event", "prev_hash", "hash"})


class AuthAuditError(ValueError):
    """Raised when the audit log chain is broken, tampered, or improperly used."""


def _compute_hash(record: dict[str, str]) -> str:
    """Computes SHA-256 hash of a record's canonical JSON representation."""
    data = {key: value for key, value in record.items() if key != "hash"}
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def verify_chain(records: list[dict[str, str]]) -> bool:
    """
    Verifies the cryptographic chain and sequence continuity of a list of records.
    Returns True if valid, False if any link or hash is broken.
    """
    expected_prev_hash = GENESIS_HASH

    for index, record in enumerate(records):
        if record.get("seq") != str(index):
            return False
        if record.get("prev_hash") != expected_prev_hash:
            return False
        if record.get("hash") != _compute_hash(record):
            return False

        expected_prev_hash = record["hash"]

    return True


def read_records(path: Path) -> list[dict[str, str]]:
    """Reads and parses the audit log from the file system."""
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as file:
        lines = [line.strip() for line in file]
    return [_parse_line(line) for line in lines if line]


def _parse_line(line: str) -> dict[str, str]:
    """Parses one JSON object line of the audit log."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError as err:
        raise AuthAuditError(f"Malformed JSON in audit log: {err}") from err
    if not isinstance(record, dict):
        raise AuthAuditError("Line is not a valid JSON object.")
    return record


class AuthAudit:
    """
    Manages an append-only, hash-chained sequence of authentication audit events.

    Callers must never pass passwords, hashes, tokens or csrf values as fields.
    """

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()

    def records(self) -> list[dict[str, str]]:
        """Returns a copy of all loaded audit records."""
        return read_records(self._path)

    def verify(self) -> bool:
        """Returns True if the full audit chain on disk is intact."""
        return verify_chain(self.records())

    def append(self, event: str, **fields: object) -> dict[str, str]:
        """
        Appends a new event to the audit log.
        Raises AuthAuditError if reserved keys are present or chain verification fails.
        """
        self._check_reserved_keys(fields)

        with self._lock:
            records = read_records(self._path)
            if not verify_chain(records):
                raise AuthAuditError("Chain integrity check failed.")

            new_record = self._build_record(event, fields, records)
            self._write_record(new_record)
            return new_record

    def _check_reserved_keys(self, fields: dict[str, Any]) -> None:
        """Rejects field names that would overwrite chain metadata."""
        if any(key in RESERVED_KEYS for key in fields):
            raise AuthAuditError(f"Fields contain reserved keys: {RESERVED_KEYS}")

    def _build_record(
        self, event: str, fields: dict[str, Any], records: list[dict[str, str]]
    ) -> dict[str, str]:
        """Builds the next chained record, including its hash."""
        prev_hash =records[-1]["hash"] if records else GENESIS_HASH
        record: dict[str, str] = {
            "seq": str(len(records)),
            "t_ns": str(int(self._clock() * 1e9)),
            "event": event,
            "prev_hash": prev_hash,
            **{key: "" if value is None else str(value) for key, value in fields.items()},
        }
        record["hash"] = _compute_hash(record)
        return record

    def _write_record(self, record: dict[str, str]) -> None:
        """Appends one JSON line to the audit file, creating parent directories."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()

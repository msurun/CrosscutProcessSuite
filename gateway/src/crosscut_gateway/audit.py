"""
Append-only hash-chained audit log of the Write Gateway.
Implements ADR 011/012, Phase 2 #46 for secure, verifiable logging.
Each record is cryptographically linked to the previous one to detect tampering.
"""

import hashlib
import json
from pathlib import Path

GENESIS_HASH = "0" * 64
RESERVED_KEYS = {"seq", "t_ns", "event", "prev_hash", "hash"}


class AuditError(ValueError):
    """Raised when the audit log chain is broken, tampered, or improperly used."""
    pass


def _compute_hash(record: dict[str, str]) -> str:
    """
    Computes the SHA-256 hash of a record's canonical JSON representation.
    Expects the record without the 'hash' key.
    """
    canonical_json = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
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

        record_without_hash = {k: v for k, v in record.items() if k != "hash"}
        calculated_hash = _compute_hash(record_without_hash)

        if record.get("hash") != calculated_hash:
            return False

        expected_prev_hash = calculated_hash

    return True


class AuditLog:
    """Manages an append-only, hash-chained sequence of audit events."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._records: list[dict[str, str]] = []
        self._load_and_verify()

    def _load_and_verify(self) -> None:
        """Loads records from the file if it exists and verifies their integrity."""
        if not self._path or not self._path.exists():
            return

        with self._path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                try:
                    self._records.append(json.loads(line))
                except json.JSONDecodeError as err:
                    raise AuditError(f"Malformed JSON in audit log: {err}") from err

        if not verify_chain(self._records):
            raise AuditError("Audit log chain verification failed. File may be tampered.")

    def _write_record(self, record: dict[str, str]) -> None:
        """Appends a single JSON line to the audit log file on disk."""
        if not self._path:
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8", newline="\n") as file:
            json_line = json.dumps(record, ensure_ascii=False)
            file.write(f"{json_line}\n")
            file.flush()

    def append(self, event: str, fields: dict[str, str], t_ns: int) -> dict[str, str]:
        """
        Appends a new event to the audit log, chaining it to the previous record.
        Raises AuditError if 'fields' contains reserved keys.
        """
        if any(key in RESERVED_KEYS for key in fields):
            raise AuditError(f"Fields contain reserved keys: {RESERVED_KEYS}")

        seq = str(len(self._records))
        prev_hash = self._records[-1]["hash"] if self._records else GENESIS_HASH

        record = {
            "seq": seq,
            "t_ns": str(t_ns),
            "event": event,
            **fields,
            "prev_hash": prev_hash,
        }

        record["hash"] = _compute_hash(record)
        self._records.append(record)
        self._write_record(record)

        return record.copy()

    def records(self) -> list[dict[str, str]]:
        """Returns a copy of all loaded audit records."""
        return [record.copy() for record in self._records]

"""
Append-only hash-chained audit log of the Write Gateway.
Implements ADR 011/012, Phase 2 #46 for secure, verifiable logging.
Each record is cryptographically linked to the previous one to detect tampering.

When a key is given, each record hash is an HMAC-SHA256 under that key, so records cannot be
edited, inserted or forged without the key. Records written before keying (plain SHA-256) are
accepted only as a prefix of the chain, before the first keyed record.

Limitation: the chain does not detect truncation of the tail of the log, nor replacement of the
whole file by another chain (for example a plain-hash chain while a legacy prefix is allowed).
Keying protects against editing, inserting and forging records without the key only.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path

GENESIS_HASH = "0" * 64
RESERVED_KEYS = {"seq", "t_ns", "event", "prev_hash", "hash"}
_KEYED = "keyed"
_PLAIN = "plain"


class AuditError(ValueError):
    """Raised when the audit log chain is broken, tampered, or improperly used."""
    pass


class AuditWriteError(AuditError, OSError):
    """The record could not be written to disk; the in-memory chain is left unchanged.

    It is also an OSError, so callers that fail closed on I/O errors keep working.
    """


def _canonical_bytes(record: dict[str, str]) -> bytes:
    """Returns the canonical JSON encoding of a record as UTF-8 bytes."""
    canonical_json = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return canonical_json.encode("utf-8")


def _compute_hash(record: dict[str, str], key: bytes | None = None) -> str:
    """
    Computes the hash of a record's canonical JSON representation.
    Plain SHA-256 when 'key' is None, HMAC-SHA256 under 'key' otherwise.
    Expects the record without the 'hash' key.
    """
    canonical = _canonical_bytes(record)
    if key is None:
        return hashlib.sha256(canonical).hexdigest()
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def _classify(record: dict[str, str], key: bytes | None) -> str | None:
    """Returns which hash scheme the record's stored hash matches, or None if neither."""
    body = {k: v for k, v in record.items() if k != "hash"}
    stored = record.get("hash")
    if key is not None and stored == _compute_hash(body, key):
        return _KEYED
    if stored == _compute_hash(body):
        return _PLAIN
    return None


def _scheme_allowed(
    scheme: str, key: bytes | None, keyed_seen: bool, allow_plain_prefix: bool
) -> bool:
    """Decides whether a record hashed with 'scheme' may appear at this point of the chain."""
    if scheme == _KEYED:
        return True
    return key is None or (allow_plain_prefix and not keyed_seen)


def verify_chain(
    records: list[dict[str, str]],
    key: bytes | None = None,
    *,
    allow_plain_prefix: bool = True,
) -> bool:
    """
    Verifies the cryptographic chain and sequence continuity of a list of records.
    Returns True if valid, False if any link or hash is broken.
    With a key, plain-hash records are valid only before the first keyed record, and only
    while allow_plain_prefix is True.
    """
    expected_prev_hash = GENESIS_HASH
    keyed_seen = False

    for index, record in enumerate(records):
        if record.get("seq") != str(index) or record.get("prev_hash") != expected_prev_hash:
            return False
        scheme = _classify(record, key)
        if scheme is None or not _scheme_allowed(scheme, key, keyed_seen, allow_plain_prefix):
            return False
        keyed_seen = keyed_seen or scheme == _KEYED
        expected_prev_hash = record["hash"]

    return True


def _fsync_quietly(descriptor: int) -> None:
    """Best-effort fsync: a file system that cannot sync is not an error."""
    try:
        os.fsync(descriptor)
    except OSError:
        pass


def _truncate_quietly(path: Path, size: int) -> None:
    """Best effort: cut a partly written line off the end of the file."""
    try:
        if path.exists() and path.stat().st_size > size:
            os.truncate(path, size)
    except OSError:
        pass


class AuditLog:
    """Manages an append-only, hash-chained sequence of audit events."""

    def __init__(self, path: Path | None = None, key: bytes | None = None) -> None:
        self._path = path
        self._key = key
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

        if not verify_chain(self._records, self._key):
            raise AuditError("Audit log chain verification failed. File may be tampered.")

    def _write_record(self, record: dict[str, str]) -> None:
        """Appends a single JSON line to the audit log file on disk (flush and fsync).

        Raises:
            AuditWriteError: If the line could not be written; the file is cut back to its
                previous size (best effort) and nothing is kept in memory.
        """
        if not self._path:
            return
        json_line = json.dumps(record, ensure_ascii=False)
        size = self._path.stat().st_size if self._path.exists() else 0
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(f"{json_line}\n")
                file.flush()
                _fsync_quietly(file.fileno())
        except OSError as err:
            _truncate_quietly(self._path, size)
            raise AuditWriteError(f"Audit record could not be written: {err}") from err

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

        record["hash"] = _compute_hash(record, self._key)
        self._write_record(record)
        self._records.append(record)

        return record.copy()

    def records(self) -> list[dict[str, str]]:
        """Returns a copy of all loaded audit records."""
        return [record.copy() for record in self._records]

"""File store of tuning proposal records and their review files (ADR 014 sections 1 and 3).

<root>/_tuning/proposals/<id>.json is owned by the API (schema tuning-proposal); the runtime job
writes the KPI review to the separate <id>.review.json (schema tuning-review) and never touches
the record. Every change of a record goes through `ProposalStore.exclusive`: a per-record lock
(thread lock plus lock file, so several API processes agree) around read, check and atomic
replace. The status only moves forward (draft -> queued -> applying -> applied, or to a terminal
state) and a terminal state is never overwritten; the content of a record is frozen after creation.
``applying`` means approve was sent but the gateway audit has not confirmed the outcome yet: it can
only become ``applied`` (never expired or rejected, the gateway may have written the values).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from crosscut_runtime.jobs.tuning_review import replace_with_retry
from crosscut_runtime.store import schemas_dir
from jsonschema import Draft202012Validator

PROPOSALS_PARTS = ("_tuning", "proposals")
REVIEW_SUFFIX = ".review.json"
RECORD_SCHEMA_FILE = "tuning-proposal.schema.json"
LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 60.0
LOCK_BREAK_STALE_S = 5.0
LOCK_POLL_S = 0.01
READ_ATTEMPTS = 20
TERMINAL = ("rejected", "expired")
# Fields that change during the life of a record; everything else is frozen at creation.
MUTABLE_FIELDS = frozenset({"status", "gateway_key", "applied", "review"})
ROLLBACK_VERDICTS = ("worse", "worse_early")

Record = dict[str, Any]


class StoreError(Exception):
    """Base of the store failures; the routes map the subclasses to HTTP codes."""


class ProposalNotFound(StoreError):
    """No record with that id (HTTP 404)."""


class TransitionRefused(StoreError):
    """The change would move a status backwards, overwrite a terminal state or edit frozen data."""


class StoreBusy(StoreError):
    """The record lock could not be taken in time (HTTP 503)."""


def is_terminal(status: str) -> bool:
    """True for rejected, expired and refused:<code>: nothing may change them any more."""
    return status in TERMINAL or status.startswith("refused:")


def transition_allowed(old: str, new: str) -> bool:
    """True when a record may go from status ``old`` to ``new`` (same status: not terminal)."""
    if old == new:
        return not is_terminal(old)
    if is_terminal(old):
        return False
    ends = ("rejected", "expired")
    if old == "draft":
        return new in ("queued", *ends) or new.startswith("refused:")
    if old == "queued":
        return new in ("applying", "applied", *ends) or new.startswith("refused:")
    if old == "applying":
        return new in ("applied", "rejected")
    return False


@lru_cache(maxsize=2)
def _validator(schema_dir: str) -> Draft202012Validator:
    """The validator of the proposal record schema."""
    text = (Path(schema_dir) / RECORD_SCHEMA_FILE).read_text(encoding="utf-8")
    return Draft202012Validator(json.loads(text))


def check_change(old: Record, new: Record) -> None:
    """Raise TransitionRefused unless ``new`` is an allowed successor of ``old``."""
    if not transition_allowed(old["status"], new["status"]):
        raise TransitionRefused(f"status {old['status']} -> {new['status']}")
    for name in set(old) | set(new):
        if name not in MUTABLE_FIELDS and old.get(name) != new.get(name):
            raise TransitionRefused(f"field {name} is frozen")
    _check_applied(old.get("applied"), new.get("applied"))


def _check_applied(old: Record | None, new: Record | None) -> None:
    """Once applied, only the ``invalid`` flag may change, and it never goes away."""
    if old is None:
        return
    if new is None:
        raise TransitionRefused("the applied block cannot be removed")
    strip = {key: value for key, value in old.items() if key != "invalid"}
    if strip != {key: value for key, value in new.items() if key != "invalid"}:
        raise TransitionRefused("the applied block is frozen")
    if old.get("invalid") and not new.get("invalid"):
        raise TransitionRefused("the invalid flag is never cleared")


def _write_atomic(path: Path, document: Record) -> None:
    """Replace a JSON file atomically (temp file in the same folder, then os.replace)."""
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        replace_with_retry(temp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise


def _read_json(path: Path) -> Any:
    """Parse a JSON file, retrying while a writer swaps it (PermissionError on Windows)."""
    for _ in range(READ_ATTEMPTS - 1):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, json.JSONDecodeError):
            time.sleep(LOCK_POLL_S)
    return json.loads(path.read_text(encoding="utf-8"))


def _is_stale(path: Path, limit_s: float) -> bool:
    """True when the file exists and was last written more than ``limit_s`` seconds ago."""
    try:
        return time.time() - path.stat().st_mtime > limit_s
    except OSError:
        return False


@contextlib.contextmanager
def _break_mutex(lock: Path) -> Iterator[bool]:
    """Hold the short-lived mutex that serialises breakers of one lock; False when it is taken."""
    mutex = lock.with_suffix(".break")
    try:
        handle = os.open(mutex, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except (FileExistsError, PermissionError):
        if _is_stale(mutex, LOCK_BREAK_STALE_S):  # a breaker died inside its short section
            with contextlib.suppress(OSError):
                mutex.unlink()
        yield False
        return
    try:
        yield True
    finally:
        os.close(handle)
        with contextlib.suppress(OSError):
            mutex.unlink()


def _drop_if_stale(lock: Path) -> None:
    """Remove a lock file older than LOCK_STALE_S (its owner died).

    Breakers go one at a time through a mutex file and look at the lock again inside it: a waiter
    that also saw the old lock finds the new owner's fresh lock and leaves it alone. Nobody can
    create the lock while the stale file exists, so only an owner releasing at that very moment
    could be confused; the release is token-checked for that case.
    """
    if not _is_stale(lock, LOCK_STALE_S):
        return
    with _break_mutex(lock) as held:
        if held and _is_stale(lock, LOCK_STALE_S):
            with contextlib.suppress(OSError):
                lock.unlink()


def _release(lock: Path, token: str) -> None:
    """Remove the lock file only while it still carries our owner token."""
    with contextlib.suppress(OSError):
        if lock.read_text(encoding="utf-8") == token:
            lock.unlink()


def _take_lock(lock: Path, deadline: float) -> str:
    """Create the lock file exclusively (content = owner token); StoreBusy after the deadline."""
    token = uuid.uuid4().hex
    while True:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):  # Windows: PermissionError while it is deleted
            _drop_if_stale(lock)
            if time.monotonic() > deadline:
                raise StoreBusy(f"lock {lock.name} is busy") from None
            time.sleep(LOCK_POLL_S)
            continue
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(token)
        return token


@contextlib.contextmanager
def _file_lock(lock: Path, timeout_s: float | None = None) -> Iterator[None]:
    """Hold an exclusive lock file; StoreBusy when it stays taken for the timeout."""
    wait_s = LOCK_TIMEOUT_S if timeout_s is None else timeout_s
    token = _take_lock(lock, time.monotonic() + wait_s)
    try:
        yield
    finally:
        _release(lock, token)


class LockedRecord:
    """A record held under its lock: the current content and a checked, atomic save."""

    def __init__(self, store: ProposalStore, proposal_id: str) -> None:
        """Load the current record of ``proposal_id`` (ProposalNotFound when absent)."""
        self._store = store
        self.proposal_id = proposal_id
        self.record: Record = store.get(proposal_id)

    def save(self, new: Record) -> Record:
        """Check the change against the current record, validate and replace it atomically."""
        check_change(self.record, new)
        self._store.write(self.proposal_id, new)
        self.record = new
        return new


class ProposalStore:
    """The proposal records of one data root."""

    def __init__(self, root: Path) -> None:
        """Bind the store to ``<root>/_tuning/proposals``."""
        self.dir = root.joinpath(*PROPOSALS_PARTS)
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def path(self, proposal_id: str) -> Path:
        """File of a record; an id that is not a lower-case UUID is ProposalNotFound."""
        try:
            canonical = str(uuid.UUID(proposal_id))
        except ValueError:
            raise ProposalNotFound(proposal_id) from None
        if canonical != proposal_id:
            raise ProposalNotFound(proposal_id)
        return self.dir / f"{proposal_id}.json"

    def review_path(self, proposal_id: str) -> Path:
        """File of the review of a record (written by the runtime job)."""
        return self.dir / f"{self.path(proposal_id).stem}{REVIEW_SUFFIX}"

    def get(self, proposal_id: str) -> Record:
        """The stored record; ProposalNotFound when there is none."""
        try:
            record: Record = _read_json(self.path(proposal_id))
        except FileNotFoundError:
            raise ProposalNotFound(proposal_id) from None
        return record

    def read_review(self, proposal_id: str) -> Record | None:
        """The review file of a record, or None when there is none (or it is unreadable)."""
        try:
            review = _read_json(self.review_path(proposal_id))
        except (OSError, ValueError):
            return None
        return review if isinstance(review, dict) else None

    def write(self, proposal_id: str, record: Record) -> None:
        """Validate a record against the schema and replace its file atomically."""
        problems = [e.message for e in _validator(str(schemas_dir())).iter_errors(record)]
        if problems or record.get("id") != proposal_id:
            raise TransitionRefused("record does not fit the schema: " + "; ".join(problems[:3]))
        self.dir.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.path(proposal_id), record)

    def create(self, record: Record) -> Record:
        """Store a new record; TransitionRefused when its id is taken or it is not a draft."""
        proposal_id = str(record.get("id"))
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.exclusive_lock(proposal_id):
            if self.path(proposal_id).exists() or record.get("status") != "draft":
                raise TransitionRefused("a new record must be a draft with a fresh id")
            self.write(proposal_id, record)
        return record

    @contextlib.contextmanager
    def exclusive_lock(self, proposal_id: str, timeout_s: float | None = None) -> Iterator[None]:
        """Hold the thread lock and the lock file of one record (StoreBusy after ``timeout_s``)."""
        lock_file = self.path(proposal_id).with_suffix(".lock")
        with self._guard:
            thread_lock = self._locks.setdefault(proposal_id, threading.Lock())
        wait_s = LOCK_TIMEOUT_S if timeout_s is None else timeout_s
        if not thread_lock.acquire(timeout=wait_s):
            raise StoreBusy(f"record {proposal_id} is busy")
        try:
            with _file_lock(lock_file, wait_s):
                yield
        finally:
            thread_lock.release()

    @contextlib.contextmanager
    def exclusive(self, proposal_id: str, timeout_s: float | None = None) -> Iterator[LockedRecord]:
        """Lock a record and yield it; ProposalNotFound when it does not exist."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.exclusive_lock(proposal_id, timeout_s):
            yield LockedRecord(self, proposal_id)

    def list_records(self) -> list[Record]:
        """All readable records, newest first (by created_at, then id)."""
        records: list[Record] = []
        for path in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []:
            if path.name.endswith(REVIEW_SUFFIX):
                continue
            with contextlib.suppress(OSError, ValueError):
                loaded = _read_json(path)
                if isinstance(loaded, dict) and "status" in loaded:
                    records.append(loaded)
        return sorted(records, key=lambda r: (r.get("created_at", ""), r["id"]), reverse=True)


def _with_review_invalid(applied: Record, review: Record) -> Record:
    """The applied block, flagged when the review job found an outside change of the DCS value."""
    if applied.get("invalid") or "param_changed_externally" not in (review.get("reasons") or []):
        return applied
    return {**applied, "invalid": "param_changed_externally"}


def merged_view(record: Record, review: Record | None) -> Record:
    """The record as the API shows it: status and review derived from the review file.

    Only an applied record has a review; ``reviewing`` / ``reviewed:<verdict>`` replace its
    status. ``rollback_recommended`` is true for a worse or worse_early verdict.
    """
    view = dict(record)
    if review is not None and record["status"] == "applied":
        view["status"] = review["status"]
        view["review"] = review["review"]
        view["applied"] = _with_review_invalid(record["applied"], review["review"])
    verdict = (view.get("review") or {}).get("verdict")
    view["rollback_recommended"] = verdict in ROLLBACK_VERDICTS
    return view

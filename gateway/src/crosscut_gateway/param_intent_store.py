"""Durable store for PID parameter write-intent records (ADR 014 addendum).

Persists intent records atomically before control-system parameter writes,
survives process crashes, and tracks open intents across gateway restarts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from crosscut_gateway.latch_store import read_json_object, write_json_atomic

INTENT_FILE_NAME = "param-intents.json"
STATE_OPEN = "open"
STATE_CLOSED = "closed"


class IntentStoreError(OSError):
    """Raised when an intent record cannot be written or read from storage."""


@dataclass(frozen=True)
class ParamIntentItem:
    """One parameter target and its intended value transition."""

    target: str
    from_value: float
    to_value: float

    def to_dict(self) -> dict[str, Any]:
        """Serialise the item to a JSON-compatible dictionary."""
        return {
            "target": self.target,
            "from_value": self.from_value,
            "to_value": self.to_value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ParamIntentItem:
        """Parse an item from stored dictionary fields."""
        return cls(
            target=str(data["target"]),
            from_value=float(data["from_value"]),
            to_value=float(data["to_value"]),
        )


@dataclass(frozen=True)
class ParamIntentRecord:
    """Durable record of an intent to apply a PID parameter set to a control system."""

    key: str
    loop_id: str
    items: tuple[ParamIntentItem, ...]
    created_time: str
    state: str = STATE_OPEN
    proposal_id: str = ""
    proposer: str = ""

    @property
    def created_at(self) -> str:
        """Timestamp alias for backward compatibility."""
        return self.created_time

    def to_dict(self) -> dict[str, Any]:
        """Serialise the intent record to a JSON-compatible dictionary."""
        return {
            "key": self.key,
            "loop_id": self.loop_id,
            "items": [item.to_dict() for item in self.items],
            "created_time": self.created_time,
            "created_at": self.created_time,
            "state": self.state,
            "proposal_id": self.proposal_id,
            "proposer": self.proposer,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ParamIntentRecord:
        """Construct a record from stored dictionary data."""
        raw_items = data.get("items", [])
        items = tuple(ParamIntentItem.from_dict(item) for item in raw_items)
        created = str(data.get("created_time") or data.get("created_at") or "")
        return cls(
            key=str(data["key"]),
            loop_id=str(data["loop_id"]),
            items=items,
            created_time=created,
            state=str(data.get("state", STATE_OPEN)),
            proposal_id=str(data.get("proposal_id", "")),
            proposer=str(data.get("proposer", "")),
        )


class ParamIntentStore:
    """Durable file store for parameter write-intent records."""

    def __init__(self, location: Path | None = None) -> None:
        """Initialize the intent store bound to a gateway directory or file path.

        Args:
            location: The directory (e.g. <root>/_gateway) or exact JSON file path.
                When None, operations run in-memory without disk persistence.
        """
        self._path: Path | None = self._resolve_path(location)
        self._in_memory: dict[str, ParamIntentRecord] = {}

    @staticmethod
    def _resolve_path(location: Path | None) -> Path | None:
        """Resolve a directory or file path into the canonical target JSON file."""
        if location is None:
            return None
        if location.is_dir() or not location.suffix:
            return location / INTENT_FILE_NAME
        return location

    def record_intent(self, record: ParamIntentRecord) -> None:
        """Save an intent record atomically before writing to the control system.

        # In plain words:
        # We store the intent to disk so that even if the process or machine crashes
        # mid-write, the next startup knows an unverified write may have happened.
        """
        records = {r.key: r for r in self.load_all()}
        records[record.key] = record
        self._save_records(records)

    def close_intent(self, key: str) -> None:
        """Mark an intent as closed after audit confirmation or full revert.

        # In plain words:
        # A closed intent indicates the gateway knows the plant state again, either
        # because the change succeeded and was audited, or because it reverted cleanly.
        """
        records = {r.key: r for r in self.load_all()}
        record = records.get(key)
        if record is None:
            return
        records[key] = replace(record, state=STATE_CLOSED)
        self._save_records(records)

    def load_all(self) -> list[ParamIntentRecord]:
        """Read all intent records from disk or in-memory cache."""
        if self._path is None:
            return list(self._in_memory.values())
        data = read_json_object(self._path)
        if not data or not isinstance(data.get("intents"), dict):
            return list(self._in_memory.values())
        records: list[ParamIntentRecord] = []
        for raw in data["intents"].values():
            if isinstance(raw, dict):
                records.append(ParamIntentRecord.from_dict(raw))
        self._in_memory = {r.key: r for r in records}
        return records

    def load_open(self) -> list[ParamIntentRecord]:
        """Return all intent records whose state is still open."""
        return [record for record in self.load_all() if record.state == STATE_OPEN]

    def has_open_for_loop(self, loop_id: str) -> bool:
        """Return True when an open intent exists for the given loop."""
        return any(record.loop_id == loop_id for record in self.load_open())

    def get(self, key: str) -> ParamIntentRecord | None:
        """Return the intent record for *key*, or None when missing."""
        records = {r.key: r for r in self.load_all()}
        return records.get(key)

    def _save_records(self, records: Mapping[str, ParamIntentRecord]) -> None:
        """Write all intent records to disk atomically with fsync."""
        self._in_memory = dict(records)
        if self._path is None:
            return
        payload = {
            "intents": {k: r.to_dict() for k, r in records.items()}
        }
        write_json_atomic(self._path, payload)


def load_open_intents(gateway_dir: Path) -> list[ParamIntentRecord]:
    """Load all open write intents from the standard gateway directory."""
    return ParamIntentStore(gateway_dir).load_open()


def has_open_intent(gateway_dir: Path, loop_id: str) -> bool:
    """Return True if an open intent exists for *loop_id* in *gateway_dir*."""
    return ParamIntentStore(gateway_dir).has_open_for_loop(loop_id)

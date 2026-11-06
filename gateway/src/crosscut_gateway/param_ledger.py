"""Bounded, persistent view of the parameter events of the audit log (for state.json).

state.json carries only the last 200 audit rows, so a ``param_write`` or a
``param_changed_externally`` can fall out of that tail. The ledger is rebuilt from the whole audit
log when the service starts and updated with every new row afterwards. It keeps the applied sets
per proposal id (the newest MAX_APPLIED) and the last MAX_EVENTS parameter-related events.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

MAX_APPLIED = 200
MAX_EVENTS = 200
EVENT_WRITE = "param_write"
EVENT_EXTERNAL = "param_changed_externally"
_OTHER_PARAM_EVENTS = frozenset({"partial_revert"})


def _is_param_event(event: object) -> bool:
    """True for the audit events that belong to the parameter write path."""
    return isinstance(event, str) and (event.startswith("param_") or event in _OTHER_PARAM_EVENTS)


def _number(text: object) -> float | None:
    """A finite float from audit text, or None when it does not parse (never invented)."""
    try:
        value = float(str(text))
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def _int(text: object) -> int:
    """An int from audit text, 0 when it does not parse."""
    try:
        return int(str(text))
    except ValueError:
        return 0


class ParamLedger:
    """Applied parameter sets by proposal id and the last parameter events."""

    def __init__(self) -> None:
        """Start empty; the first update replays the audit log."""
        self.applied: dict[str, dict[str, Any]] = {}
        self.events: deque[dict[str, str]] = deque(maxlen=MAX_EVENTS)
        self._seen = 0

    def update(self, records: Sequence[Mapping[str, str]]) -> None:
        """Take the audit rows not seen yet (the log is append-only)."""
        for row in records[self._seen :]:
            if _is_param_event(row.get("event")):
                self._take(row)
        self._seen = max(self._seen, len(records))

    def _take(self, row: Mapping[str, str]) -> None:
        """Remember one parameter event; a param_write also feeds the applied map."""
        event = dict(row)
        if row["event"] == EVENT_EXTERNAL:
            event["target"] = row.get("tag", "")
        self.events.append(event)
        if row["event"] == EVENT_WRITE and row.get("proposal_id"):
            self._add_write(row)

    def _add_write(self, row: Mapping[str, str]) -> None:
        """Add one audited item write to the applied entry of its proposal."""
        pid = row["proposal_id"]
        entry = self.applied.setdefault(pid, self._new_entry(row))
        tag = row.get("tag", "")
        entry["applied_from"][tag] = _number(row.get("applied_from"))
        entry["applied_to"][tag] = _number(row.get("applied_to"))
        entry["t_ns"] = max(entry["t_ns"], _int(row.get("t_ns")))
        while len(self.applied) > MAX_APPLIED:
            del self.applied[next(iter(self.applied))]

    @staticmethod
    def _new_entry(row: Mapping[str, str]) -> dict[str, Any]:
        """The empty applied entry of a proposal."""
        return {
            "key": row.get("key", ""),
            "applied_from": {},
            "applied_to": {},
            "t_ns": 0,
            "approver": row.get("actor", ""),
            "status": "applied",
        }

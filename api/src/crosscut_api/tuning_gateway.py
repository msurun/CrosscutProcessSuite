"""Data mapping between tuning proposal records and the gateway (ADR 014 sections 3 and 4).

Pure functions: build the propose_params arguments of a record, read the idempotency key from the
gateway's pending list, and turn the gateway audit into the applied block of a record or into the
"changed outside the write path" flag. The API cannot import crosscut_gateway, so the shapes
(state.json pending_params, audit records param_write / param_changed_externally) are mirrored
here as plain dicts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

Record = dict[str, Any]
NS_PER_S = 1_000_000_000
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
EVENT_WRITE = "param_write"
EVENT_EXTERNAL = "param_changed_externally"
INVALID_REASON = "param_changed_externally"
DECISION_QUEUED = "queued"
# Accepted decisions that queue nothing (advisory records, dry run): no approval is possible.
NOT_QUEUED_STATUS = {"ok": "refused:advisory_only", "dry_run": "refused:dry_run"}
# Approve refusals that leave the set queued in the gateway: the caller may try again.
KEEPS_QUEUED = frozenset({"self_approval", "not_confirm_mode"})
FORBIDDEN_REFUSALS = frozenset({"self_approval", "author_equals_approver"})


def iso_to_ns(text: str) -> int:
    """UTC nanoseconds of an ISO 8601 timestamp such as 2026-11-05T10:00:00Z."""
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return int(moment.timestamp()) * NS_PER_S


def ns_to_iso(t_ns: int) -> str:
    """ISO 8601 UTC text (whole seconds, trailing Z) of UTC nanoseconds."""
    return datetime.fromtimestamp(t_ns // NS_PER_S, UTC).strftime(TIMESTAMP_FORMAT)


def safe_code(code: str) -> str:
    """A gateway reason code as the ``[a-z_]+`` suffix of a refused:<code> status."""
    cleaned = re.sub(r"[^a-z_]+", "_", code.lower()).strip("_")
    return cleaned or "refused"


def param_targets(policy: Mapping[str, Any] | None, loop_id: str) -> dict[str, str]:
    """Parameter -> policy target tag of the pid_param targets of one loop in the live policy."""
    document = (policy or {}).get("document") or {}
    found: dict[str, str] = {}
    for tag, target in (document.get("targets") or {}).items():
        if target.get("kind") == "pid_param" and target.get("loop") == loop_id:
            found[str(target["param"])] = str(tag)
    return found


def propose_args(record: Mapping[str, Any], proposer: str, now_ns: int, reason: str) -> Record:
    """The arguments of the propose_params command for a stored record (reason is not stored)."""
    form = record["vendor_form"]["key"]
    items = [
        {
            "param": item["param"],
            "target": item["target"],
            "unit": item["unit"],
            "vendor_form": form,
            "from": item["from"],
            "to": item["to"],
        }
        for item in record["items"]
    ]
    return {
        "proposal_id": record["id"],
        "loop_id": record["loop_id"],
        "items": items,
        "proposer": proposer,
        "t_ns": now_ns,
        "expires_ns": iso_to_ns(record["expires_at"]),
        "reason": reason,
        "rollback_of": record["rollback_of"],
    }


def queued_key(pending: Sequence[Mapping[str, Any]], proposal_id: str) -> str | None:
    """The idempotency key of the queued parameter set of ``proposal_id``, or None."""
    for entry in pending:
        if entry.get("proposal_id") == proposal_id:
            return str(entry["key"])
    return None


def decision_status(decision: Mapping[str, Any]) -> str:
    """The record status after propose_params: queued, or refused:<code> with the reason."""
    code = str(decision.get("reason_code", ""))
    if decision.get("accepted") and code == DECISION_QUEUED:
        return "queued"
    if decision.get("accepted"):
        return NOT_QUEUED_STATUS.get(code, f"refused:not_queued_{safe_code(code)}")
    return f"refused:{safe_code(code)}"


def _written(records: Sequence[Mapping[str, Any]], key: str) -> list[Mapping[str, Any]]:
    """The param_write audit records of one idempotency key."""
    return [r for r in records if r.get("event") == EVENT_WRITE and r.get("key") == key]


def applied_block(
    records: Sequence[Mapping[str, Any]], record: Mapping[str, Any], approver: str
) -> Record | None:
    """The applied block {from_read, to_read, t, approver} from the audit, or None if incomplete.

    ``from_read`` / ``to_read`` are the audited ``applied_from`` / ``applied_to`` values per
    target, in item units. None when a target of the record has no param_write record.
    """
    rows = _written(records, str(record["gateway_key"]))
    from_read: dict[str, float] = {}
    to_read: dict[str, float] = {}
    try:
        for row in rows:
            from_read[str(row["tag"])] = float(row["applied_from"])
            to_read[str(row["tag"])] = float(row["applied_to"])
        when = max(int(row["t_ns"]) for row in rows)
    except (KeyError, ValueError):
        return None
    if {item["target"] for item in record["items"]} - set(to_read):
        return None
    return {"from_read": from_read, "to_read": to_read, "t": ns_to_iso(when), "approver": approver}


def _superseded(records: Sequence[Mapping[str, Any]], tag: str, span: tuple[int, int]) -> bool:
    """True when a param_write on ``tag`` falls strictly between the two instants."""
    low, high = span
    return any(
        r.get("event") == EVENT_WRITE and r.get("tag") == tag and low < int(r["t_ns"]) < high
        for r in records
    )


def external_change(records: Sequence[Mapping[str, Any]], record: Mapping[str, Any]) -> bool:
    """True when the audit shows a target of an applied record changed at the DCS afterwards.

    The event must follow the apply and no later write of the same target may lie between them.
    """
    own = str(record["gateway_key"])
    others = [r for r in records if r.get("key") != own]
    applied_ns = iso_to_ns(record["applied"]["t"])
    targets = {item["target"] for item in record["items"]}
    for row in records:
        tag = str(row.get("tag"))
        if row.get("event") != EVENT_EXTERNAL or tag not in targets:
            continue
        when = int(row["t_ns"])
        if when >= applied_ns and not _superseded(others, tag, (applied_ns, when)):
            return True
    return False

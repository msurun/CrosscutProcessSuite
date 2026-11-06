"""Data mapping between tuning proposal records and the gateway (ADR 014 sections 3 and 4).

Pure functions: build the propose_params arguments of a record, read the idempotency key from the
gateway's pending list (only a set with the same content counts), and turn the gateway ledger
(state.json applied_params / param_events, read in one piece as a GatewaySnapshot) into the applied
block of a record or into the "changed outside the write path" flag. The API cannot import
crosscut_gateway, so the shapes are mirrored here as plain dicts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from crosscut_runtime.jobs.tuning_review import external_change as events_show_external_change

from crosscut_api.auth.actor_names import same_actor

Record = dict[str, Any]
NS_PER_S = 1_000_000_000
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
INVALID_REASON = "param_changed_externally"
INVALID_UNVERIFIED = "audit_unverified"
INVALID_CHAIN = "audit_chain_broken"
SOURCE_AUDIT = "audit"
SOURCE_REPLY = "gateway_reply"
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


class ForeignPending(Exception):
    """A pending set carries our proposal id but other content: it is not ours (HTTP 409)."""


@dataclass(frozen=True)
class GatewaySnapshot:
    """One consistent read of state.json: pending sets, applied map, param events, chain flag."""

    pending: list[dict[str, Any]]
    applied: dict[str, dict[str, Any]]
    events: list[dict[str, Any]]
    chain_ok: bool


def snapshot_of(raw: Mapping[str, Any]) -> GatewaySnapshot:
    """The GatewaySnapshot of the dict a gateway client's ``snapshot()`` returns."""
    pending, applied, events = raw["pending_params"], raw["applied_params"], raw["param_events"]
    if not (isinstance(pending, list) and isinstance(applied, dict) and isinstance(events, list)):
        raise TypeError("malformed gateway snapshot")
    return GatewaySnapshot(pending, applied, events, raw["chain_ok"] is True)


def _item_digest(items: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, float, float]]:
    """The comparable form of a list of items: (param, target, from, to), sorted."""
    return sorted(
        (str(i["param"]), str(i["target"]), float(i["from"]), float(i["to"])) for i in items
    )


def _same_set(entry: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
    """True when a pending summary has the loop, proposer and items of the record."""
    try:
        return (
            entry.get("loop_id") == record["loop_id"]
            and same_actor(str(entry.get("proposer", "")), record["created_by"])
            and _item_digest(entry["items"]) == _item_digest(record["items"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def queued_key(pending: Sequence[Mapping[str, Any]], record: Mapping[str, Any]) -> str | None:
    """The idempotency key of the queued parameter set of the record, or None.

    Raises:
        ForeignPending: a pending set has the proposal id of the record but another loop,
            proposer or items.
    """
    for entry in pending:
        if entry.get("proposal_id") != record["id"]:
            continue
        if not _same_set(entry, record):
            raise ForeignPending(str(entry.get("key")))
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


def _complete(values: Mapping[str, Any], targets: set[str]) -> bool:
    """True when every target has a number in ``values``."""
    return all(isinstance(values.get(t), (int, float)) for t in targets)


def applied_from_snapshot(
    snapshot: GatewaySnapshot, record: Mapping[str, Any], approver: str
) -> Record | None:
    """The applied block from the gateway ledger, or None while the audit does not show it.

    The entry is found by proposal id and must carry the record's gateway key. Values are the
    audited ``applied_from`` / ``applied_to`` per target (source "audit"); without a verified
    audit chain no values are taken and the block is invalid ("audit_chain_broken").
    """
    entry = snapshot.applied.get(str(record["id"]))
    targets = {item["target"] for item in record["items"]}
    if entry is None or entry.get("key") != record["gateway_key"]:
        return None
    if not (_complete(entry["applied_to"], targets) and _complete(entry["applied_from"], targets)):
        return None
    block: Record = {
        "from_read": {t: entry["applied_from"][t] for t in targets},
        "to_read": {t: entry["applied_to"][t] for t in targets},
        "t": ns_to_iso(int(entry["t_ns"])),
        "approver": str(entry.get("approver") or approver or "unknown"),
        "source": SOURCE_AUDIT,
        "chain_ok": snapshot.chain_ok,
    }
    if snapshot.chain_ok:
        return block
    nulls = {t: None for t in targets}
    return {**block, "from_read": nulls, "to_read": dict(nulls), "invalid": INVALID_CHAIN}


def unverified_block(record: Mapping[str, Any], approver: str, now_ns: int) -> Record:
    """The applied block of a set the gateway applied but could not audit: no values, invalid."""
    nulls = {item["target"]: None for item in record["items"]}
    return {
        "from_read": nulls,
        "to_read": dict(nulls),
        "t": ns_to_iso(now_ns),
        "approver": approver,
        "source": SOURCE_REPLY,
        "chain_ok": False,
        "invalid": INVALID_UNVERIFIED,
    }


def trusted_applied(record: Mapping[str, Any]) -> bool:
    """True when the applied block may be the base of a rollback: audited, chain ok, valid."""
    applied = record.get("applied") or {}
    values = (applied.get("from_read") or {}, applied.get("to_read") or {})
    targets = {item["target"] for item in record["items"]}
    return (
        applied.get("source") == SOURCE_AUDIT
        and applied.get("chain_ok") is True
        and not applied.get("invalid")
        and all(_complete(v, targets) for v in values)
    )


def external_change(events: Sequence[Mapping[str, Any]], record: Mapping[str, Any]) -> bool:
    """True when the param events show a target of an applied record changed at the DCS afterwards.

    The event must follow the apply and no later write of the same target may lie between them.
    """
    return events_show_external_change([dict(e) for e in events], dict(record))

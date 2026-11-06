"""Pure reconciliation of a tuning proposal record with a gateway snapshot (ADR 014).

``plan`` answers "what should this record become, given what the gateway shows now": the late
key of a draft, a set that was applied although the API never saw the reply (the audit is looked
at BEFORE any move to ``expired``), an outside change of an applied value, a draft or queued
record that died. It changes nothing; the routes apply the answer under the record lock.
"""

from __future__ import annotations

from typing import Any

from crosscut_api.tuning_gateway import (
    INVALID_REASON,
    ForeignPending,
    GatewaySnapshot,
    applied_from_snapshot,
    external_change,
    iso_to_ns,
    queued_key,
)

Record = dict[str, Any]
NS_PER_S = 1_000_000_000
DRAFT_GRACE_S = 600  # a draft with no key and no pending set this old never reached the queue


def _older_than(stamp: str, now_ns: int, seconds: float) -> bool:
    """True when the ISO timestamp lies more than ``seconds`` before ``now_ns``."""
    return now_ns - iso_to_ns(stamp) > seconds * NS_PER_S


def plan(record: Record, snap: GatewaySnapshot, now_ns: int) -> Record | None:
    """The record the gateway snapshot implies, or None when nothing changes."""
    status = record["status"]
    if status == "applied":
        return _flag_external(record, snap)
    if status == "rejected" and "escape" in record:
        return _correct_escape(record, snap)
    if status in ("queued", "applying"):
        block = applied_from_snapshot(snap, record, "")
        if block is not None:
            return {**record, "status": "applied", "applied": block}
    if status in ("draft", "queued"):
        return _plan_open(record, snap, now_ns)
    return None


def _plan_open(record: Record, snap: GatewaySnapshot, now_ns: int) -> Record | None:
    """Late key, foreign set or death of a draft / queued record (no applied evidence)."""
    try:
        key = queued_key(snap.pending, record)
    except ForeignPending:
        return {**record, "status": "refused:foreign_pending"}
    if record["status"] == "draft":
        if key is not None:
            return {**record, "status": "queued", "gateway_key": key}
        stale = _older_than(record["created_at"], now_ns, DRAFT_GRACE_S)
        return {**record, "status": "expired"} if stale else None
    if key is None and _past(record, now_ns):
        return {**record, "status": "expired"}
    return None


def _past(record: Record, now_ns: int) -> bool:
    """True when the record's expiry time has passed."""
    return now_ns >= iso_to_ns(record["expires_at"])


def _flag_external(record: Record, snap: GatewaySnapshot) -> Record | None:
    """Set applied.invalid when the param events show the DCS value changed outside the path."""
    applied = record["applied"]
    if applied.get("invalid") or not external_change(snap.events, record):
        return None
    return {**record, "applied": {**applied, "invalid": INVALID_REASON}}


def _correct_escape(record: Record, snap: GatewaySnapshot) -> Record | None:
    """An escape rejection the gateway audit proves wrong becomes applied, flagged as corrected."""
    block = applied_from_snapshot(snap, record, "")
    if block is None:
        return None
    return {**record, "status": "applied", "applied": block, "corrected_from": "rejected"}

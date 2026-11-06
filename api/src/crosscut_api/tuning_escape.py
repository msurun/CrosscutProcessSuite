"""Operator escape of a stalled ``applying`` tuning record (ADR 014 section 4); pure decisions.

An approve that timed out (504) leaves the record ``applying``. The gateway may still apply the
set, so the record is never rejected on a guess: ``decide_escape`` answers from the gateway
snapshot only (applied ledger, audit events, pending list) and says "unknown" (None) when the
evidence does not allow either outcome.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from crosscut_api.tuning_gateway import (
    KEEPS_QUEUED,
    GatewaySnapshot,
    applied_from_snapshot,
    iso_to_ns,
)

Record = dict[str, Any]
NS_PER_S = 1_000_000_000
EXPIRY_MARGIN_S = 600  # the gateway state may lag: wait this long past expires_at
MIN_REASON = 10
_DROP_EVENTS = {"param_rejected": "gateway_rejected", "param_flushed": "gateway_flushed"}


@dataclass(frozen=True)
class EscapeVerdict:
    """What an escape may do: ``applied`` (with the audited block) or ``rejected``."""

    status: str
    evidence: str
    applied: Record | None = None


def terminal_evidence(events: Sequence[dict[str, Any]], key: str) -> str | None:
    """The evidence text of a terminal gateway decision for ``key``, or None.

    Terminal: the set was rejected or flushed, or a decision refused it (any code that does not
    keep the set queued) such as ``expired`` or ``from_mismatch``.
    """
    for event in events:
        if event.get("key") != key:
            continue
        name = str(event.get("event", ""))
        if name in _DROP_EVENTS:
            return _DROP_EVENTS[name]
        code = str(event.get("reason_code", ""))
        if name == "param_decision" and code not in ("ok", "queued") and code not in KEEPS_QUEUED:
            return f"gateway_refused:{code}"
    return None


def decide_escape(record: Record, snap: GatewaySnapshot, now_ns: int) -> EscapeVerdict | None:
    """The escape outcome the gateway evidence allows, or None (409 gateway_state_unknown)."""
    block = applied_from_snapshot(snap, record, "")
    if block is not None:
        return EscapeVerdict("applied", "ledger_applied", block)
    key = record.get("gateway_key")
    if not key:
        return None
    seen = terminal_evidence(snap.events, str(key))
    if seen is not None:
        return EscapeVerdict("rejected", seen)
    listed = any(entry.get("key") == key for entry in snap.pending)
    late = now_ns - iso_to_ns(record["expires_at"]) > EXPIRY_MARGIN_S * NS_PER_S
    if late and not listed:
        return EscapeVerdict("rejected", "expired_not_listed")
    return None

"""Live variable status for APC controllers (Phase 2.5, step 3).

Pure evaluation of every controller variable against one connector snapshot: communication,
quality, staleness, validity range, anomaly flags and the operator switch. The worst reason wins.
No I/O; the caller supplies the snapshot, the clock and the flags.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from crosscut_connectors.base import LiveValue, Snapshot

GOOD, UNCERTAIN, BAD = "good", "uncertain", "bad"
DEFAULT_CYCLE_S = 30.0
DEFAULT_STALE_CYCLES = 3
INSTRUMENT_KINDS = ("stuck", "quality")
_RANK = {GOOD: 0, UNCERTAIN: 1, BAD: 2}


@dataclass(frozen=True)
class VariableStatus:
    """Status of one controller variable at one cycle."""

    variable_id: str
    tag: str | None
    status: str
    reasons: tuple[str, ...]
    value: float | None
    source_utc: str | None
    sp_value: float | None = None  # MV only: value of the second tag (the setpoint)


@dataclass(frozen=True)
class StatusInputs:
    """Everything outside the controller document that evaluation needs.

    ``tags_of`` maps a variable id to its tags (an MV: PV tag first, then SP tag);
    ``flags`` maps a tag to external reasons; ``disabled`` is the set of switched-off ids,
    or ``None`` to use each variable's ``enabled_default``.
    """

    snapshot: Snapshot
    now_utc: datetime
    tags_of: Mapping[str, list[str]]
    flags: Mapping[str, set[str]] = field(default_factory=dict)
    disabled: frozenset[str] | None = None


@dataclass(frozen=True)
class _Limits:
    """Staleness limit in seconds and the validity range of one variable."""

    stale_s: float
    validity: Mapping[str, float] | None


def flags_from_anomaly(
    events: Iterable[Mapping[str, Any]], kinds: tuple[str, ...] = INSTRUMENT_KINDS
) -> dict[str, set[str]]:
    """Map tag -> {"anomaly"} for instrument events only (process-level PCA events are skipped)."""
    flags: dict[str, set[str]] = {}
    for event in events:
        tag = event.get("stuck_tag") or event.get("tag")
        if event.get("kind") in kinds and tag:
            flags.setdefault(str(tag), set()).add("anomaly")
    return flags


def _parse_utc(text: str) -> datetime | None:
    """Parse an ISO time stamp as UTC; ``None`` when it cannot be read."""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_stale(live: LiveValue, now_utc: datetime, limit_s: float) -> bool:
    """True when the source time stamp is unreadable or older than ``limit_s``."""
    stamp = _parse_utc(live.timestamp_utc)
    return stamp is None or (now_utc - stamp).total_seconds() > limit_s


def _out_of_validity(live: LiveValue, validity: Mapping[str, float] | None) -> bool:
    """True when a numeric value lies outside the validity range."""
    if validity is None or live.value is None:
        return False
    return not validity["lo"] <= live.value <= validity["hi"]


def _tag_reasons(
    live: LiveValue | None, tag: str, limits: _Limits, inputs: StatusInputs
) -> list[str]:
    """Reasons found for one tag (``live`` is ``None`` when the tag was not sampled)."""
    if live is None:
        return ["quality"]
    reasons = []
    if live.quality >= 1:
        reasons.append("quality")
    if _is_stale(live, inputs.now_utc, limits.stale_s):
        reasons.append("stale")
    if _out_of_validity(live, limits.validity):
        reasons.append("out_of_validity")
    if "anomaly" in inputs.flags.get(tag, ()):
        reasons.append("anomaly")
    return reasons


def _tag_status(live: LiveValue | None, reasons: list[str]) -> str:
    """Status of one tag: uncertain quality alone is uncertain, any other reason is bad."""
    if not reasons:
        return GOOD
    if live is not None and live.quality == 1 and reasons == ["quality"]:
        return UNCERTAIN
    return BAD


def _is_off(variable: Mapping[str, Any], disabled: frozenset[str] | None) -> bool:
    """True when the operator switched the variable off."""
    if disabled is None:
        return not variable.get("enabled_default", True)
    return variable["id"] in disabled


def _judge_tags(
    tags: list[str], limits: _Limits, inputs: StatusInputs
) -> tuple[str, list[str]]:
    """Worst status and the union of reasons over the tags of one variable."""
    if not inputs.snapshot.comm_ok:
        return BAD, ["comm_loss"]
    status, reasons = GOOD, []
    for tag in tags:
        live = inputs.snapshot.values.get(tag)
        found = _tag_reasons(live, tag, limits, inputs)
        reasons += [reason for reason in found if reason not in reasons]
        status = max(status, _tag_status(live, found), key=_RANK.__getitem__)
    return status, reasons


def _variable_status(
    variable: Mapping[str, Any], controller: Mapping[str, Any], inputs: StatusInputs
) -> VariableStatus:
    """Evaluate one variable over all of its tags."""
    tags = inputs.tags_of.get(variable["id"], [])
    stale_s = controller.get("stale_cycles", DEFAULT_STALE_CYCLES) * controller.get(
        "cycle_s", DEFAULT_CYCLE_S
    )
    limits = _Limits(stale_s, variable.get("limits", {}).get("validity"))
    status, reasons = _judge_tags(tags, limits, inputs)
    if _is_off(variable, inputs.disabled):
        status, reasons = BAD, [*reasons, "operator_off"]
    first = inputs.snapshot.values.get(tags[0]) if tags else None
    second = inputs.snapshot.values.get(tags[1]) if len(tags) > 1 else None
    return VariableStatus(
        variable["id"],
        tags[0] if tags else None,
        status,
        tuple(reasons),
        first.value if first else None,
        first.timestamp_utc if first else None,
        second.value if second else None,
    )


def evaluate(controller_doc: Mapping[str, Any], inputs: StatusInputs) -> list[VariableStatus]:
    """Status of every variable of one site ``controllers[]`` entry."""
    return [
        _variable_status(variable, controller_doc, inputs)
        for variable in controller_doc.get("variables", [])
    ]

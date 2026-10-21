"""Loop-health gates for the advisory supervisor (ADR 010): module 1 rows in, gate state out.

Fail closed: a missing loop row, a not-assessed gating loop (when 'unknown' blocks) or a bad
input blocks advice. Keys read from module 1 rows: name, status, classification, findings,
service_percent.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from crosscut_supervisor.config import GateRule, SupervisorConfig

MANUAL_SERVICE_PERCENT = 50  # service below this share of time counts as manual
_BLOCKABLE = ("manual", "saturated", "flatline")


@dataclass(frozen=True)
class GateResult:
    """Overall gate state with the sorted, unique reasons behind it."""

    state: Literal["open", "degraded", "blocked"]
    reasons: tuple[str, ...]


def gate_state(rows: Sequence[Mapping[str, Any]], config: SupervisorConfig) -> GateResult:
    """Combine every configured gate rule over the module 1 per-loop ``rows``.

    Blocked if any rule blocks, else degraded if any degrades, else open (also with no rules).
    Choice: a loop whose status is 'not_assessed' blocks only when its rule lists 'unknown' in
    ``block_on``; otherwise it always degrades, because its state cannot be confirmed healthy.
    """
    by_name = {str(row.get("name")): row for row in rows}
    blocked: set[str] = set()
    degraded: set[str] = set()
    for rule in config.gates:
        row = by_name.get(rule.loop)
        if row is None:
            blocked.add(f"loop_missing:{rule.loop}")
            continue
        rule_blocked, rule_degraded = _evaluate_rule(rule, row)
        blocked.update(rule_blocked)
        degraded.update(rule_degraded)
    if blocked:
        return GateResult("blocked", tuple(sorted(blocked | degraded)))
    if degraded:
        return GateResult("degraded", tuple(sorted(degraded)))
    return GateResult("open", ())


def gate_inputs_ok(
    snapshot: Mapping[str, float | None], ranges: Mapping[str, tuple[float, float]]
) -> list[str]:
    """Reasons why ``snapshot`` fails the fail-closed input rule (empty list = inputs fine).

    For every id in ``ranges``: absent or None gives ``input_missing:<id>``, NaN gives
    ``input_nan:<id>``, a value outside the inclusive range gives ``input_out_of_range:<id>``.
    """
    reasons = [_input_reason(name, snapshot, bounds) for name, bounds in ranges.items()]
    return sorted(reason for reason in reasons if reason)


def _input_reason(
    name: str, snapshot: Mapping[str, float | None], bounds: tuple[float, float]
) -> str:
    """The failure reason of one input, or an empty string when it is acceptable."""
    value = snapshot.get(name)
    if value is None:
        return f"input_missing:{name}"
    if math.isnan(value):
        return f"input_nan:{name}"
    if not bounds[0] <= value <= bounds[1]:
        return f"input_out_of_range:{name}"
    return ""


def _evaluate_rule(rule: GateRule, row: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    """Blocking and degrading reasons of one rule applied to its loop row."""
    flags = _flags(row)
    blocked: set[str] = set()
    degraded: set[str] = set()
    for state in _BLOCKABLE:
        if flags[state] and state in rule.block_on:
            blocked.add(f"{state}:{rule.loop}")
    # Oscillating is warn-only per the schema, so block_on is ignored for it.
    if flags["oscillating"] and "oscillating" in rule.warn_on:
        degraded.add(f"oscillating:{rule.loop}")
    if flags["not_assessed"]:
        target = blocked if "unknown" in rule.block_on else degraded
        target.add(f"not_assessed:{rule.loop}")
    return blocked, degraded


def _flags(row: Mapping[str, Any]) -> dict[str, bool]:
    """Boolean loop states derived from the classification, findings, service and status."""
    codes = {str(finding.get("code")) for finding in row.get("findings") or []}
    classification = row.get("classification")
    service = row.get("service_percent")
    return {
        "manual": classification == "manual"
        or (isinstance(service, int | float) and service < MANUAL_SERVICE_PERCENT),
        "saturated": classification == "saturated" or "saturated" in codes,
        "flatline": "flatline" in codes,
        "oscillating": classification == "oscillating" or "oscillating" in codes,
        "not_assessed": row.get("status") == "not_assessed",
    }

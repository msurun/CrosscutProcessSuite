"""Turn an overview's per-loop rows into a prioritised worklist: one next action per loop.

The ordering here is a rule of thumb for advice, not a validated score: saying which fix comes
first would need a blind review by a control engineer on real plant data. Until then, this module
only says what to look at next, and in which order.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from crosscut_loops.health_kpis import QUANTISATION_LIMITING

# --- Action codes shown to the operator -------------------------------------

ASK_WHY_MANUAL = "ask_why_manual"
CHECK_MEASUREMENT = "check_measurement"
CHECK_OUTPUT_LIMIT = "check_output_limit"
VALVE_TEST = "valve_test"
FIND_COMMON_SOURCE = "find_common_source"
TEST_CYCLE_CAUSE = "test_cycle_cause"
CHECK_OUTPUT_RESOLUTION = "check_output_resolution"
BUMP_TEST_AND_RETUNE = "bump_test_and_retune"
REVIEW_VALVE_SIZING = "review_valve_sizing"
CONFIGURE_KNOWLEDGE = "configure_knowledge"
NO_ACTION = "none"

# --- Row values this module reads -------------------------------------------

MANUAL_CLASSIFICATION = "manual"
SATURATED_CLASSIFICATION = "saturated"
OSCILLATING_CLASSIFICATION = "oscillating"
POOR_PERFORMANCE_CLASSIFICATION = "poor_performance"

FLATLINE_CODE = "flatline"
STICTION_CODE = "stiction"
STICTION_TEST_ADVICE = "test_valve"
PERCENT_PARAM = "percent"
LOOPS_PARAM = "loops"
RATIO_PARAM = "ratio"
HINT_PARAM = "hint"
MISSING_PARAM = "missing"

# --- Priorities -------------------------------------------------------------

PROBLEM_URGENCY = 0
WARNING_URGENCY = 1
OTHER_URGENCY = 2
CONFIGURE_URGENCY = 3
NO_ACTION_URGENCY = 4
UNKNOWN_HEALTH = 101  # sorts unknown health after every real score in the same urgency band

STATUS_URGENCY = {"problem": PROBLEM_URGENCY, "warning": WARNING_URGENCY}
ADVICE_URGENCIES = {CONFIGURE_KNOWLEDGE: CONFIGURE_URGENCY, NO_ACTION: NO_ACTION_URGENCY}

Row = dict[str, Any]


def _action(code: str, params: dict[str, Any]) -> dict[str, Any]:
    """A next action as the JSON-ready dict the UI expects."""
    return {"code": code, "params": params}


def _finding_codes(row: Row) -> set[str]:
    """The codes of all findings of one row; an empty set when it has none."""
    findings = row.get("findings") or []
    return {
        str(finding.get("code")) if isinstance(finding, dict) else str(finding)
        for finding in findings
    }


def _is_manual(row: Row) -> bool:
    """True when the loop is classified as run by hand."""
    return row.get("classification") == MANUAL_CLASSIFICATION


def _is_saturated(row: Row) -> bool:
    """True when the controller output sat at a limit."""
    return row.get("classification") == SATURATED_CLASSIFICATION


def _is_oscillating(row: Row) -> bool:
    """True when the loop cycles around its setpoint."""
    return row.get("classification") == OSCILLATING_CLASSIFICATION


def _is_flatlined(row: Row) -> bool:
    """True when the PV was reported frozen."""
    return FLATLINE_CODE in _finding_codes(row)


def _stiction_doubted(row: Row) -> bool:
    """True when the valve is suspected of sticking or was advised a valve test."""
    advised = row.get("stiction_advice") == STICTION_TEST_ADVICE
    return advised or STICTION_CODE in _finding_codes(row)


def _shared_period_loops(row: Row) -> list[str]:
    """The other loops cycling at the same period as this one, sorted by name."""
    peers = row.get("same_period_as") or []
    return sorted([peers] if isinstance(peers, str) else [str(name) for name in peers])


def _manual_params(row: Row) -> dict[str, Any]:
    """The share of time the loop ran outside automatic control, as a whole percent.

    An unknown service factor gives None, not "100 % manual".
    """
    service = _number_or_none(row.get("service_percent"))
    percent = None if service is None else 100 - round(service)
    return {PERCENT_PARAM: percent}


def _number_or_none(value: Any) -> float | None:
    """The value as a float, or None when it is missing, not a number or NaN."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value):
        return None
    return float(value)


def _common_source_params(row: Row) -> dict[str, Any]:
    """The loops cycling together, which point at one disturbance to find before any retuning."""
    return {LOOPS_PARAM: _shared_period_loops(row)}


def _resolution_params(row: Row) -> dict[str, Any]:
    """A coarse output steps in visible jumps, so the cycle may be resolution, not tuning."""
    return {RATIO_PARAM: round(row["out_quantisation_ratio"], 1)}


def _sizing_params(row: Row) -> dict[str, Any]:
    """An oversized or undersized valve limits control whatever the tuning says."""
    return {HINT_PARAM: row["valve_sizing_hint"]}


def _configure_params(row: Row) -> dict[str, Any]:
    """Conclusions withheld for missing per-loop knowledge cannot be checked until it is given."""
    return {MISSING_PARAM: list(row.get("not_assessed") or [])}


def _has_sizing_hint(row: Row) -> bool:
    """True when the valve sizing check produced a hint."""
    return row.get("valve_sizing_hint") is not None


def _has_coarse_output(row: Row) -> bool:
    """True when the output resolution is at or above the limiting ratio."""
    ratio = row.get("out_quantisation_ratio")
    return ratio is not None and ratio >= QUANTISATION_LIMITING


def _needs_knowledge(row: Row) -> bool:
    """True when at least one conclusion was withheld for missing knowledge."""
    return bool(row.get("not_assessed"))


# One rule: (applies?, action code, builder of the action parameters or None for no parameters).
Rule = tuple[Callable[[Row], bool], str, Callable[[Row], dict[str, Any]] | None]

# Rules in the order they are tried; the first match wins. The order is the only place that
# decides which advice outranks which, so each rule's comment says why it sits where it does.
RULES: tuple[Rule, ...] = (
    # A manual loop is not controlled at all: nothing else can be judged until someone says why.
    (_is_manual, ASK_WHY_MANUAL, _manual_params),
    # A frozen reading makes every other finding untrustworthy, so it is checked before them.
    (_is_flatlined, CHECK_MEASUREMENT, None),
    # The output pinned at a limit may be the real cause of a flatline or a cycle elsewhere.
    (_is_saturated, CHECK_OUTPUT_LIMIT, None),
    # A sticking valve must be fixed before any retuning, and before blaming a shared source.
    (lambda row: _is_oscillating(row) and _stiction_doubted(row), VALVE_TEST, None),
    # One disturbance driving several loops is found before retuning any single one of them.
    (
        lambda row: _is_oscillating(row) and bool(_shared_period_loops(row)),
        FIND_COMMON_SOURCE,
        _common_source_params,
    ),
    # A cycle nobody else sees is caused by the loop or by its process: bump the loop and see
    # whether the period changes (inside cause) or not (outside cause).
    (_is_oscillating, TEST_CYCLE_CAUSE, None),
    # Coarse output steps explain a small cycle, so they are checked before calling it poor tuning.
    (_has_coarse_output, CHECK_OUTPUT_RESOLUTION, _resolution_params),
    # Poor performance is the retuning case; every mechanical cause above is already excluded.
    (
        lambda row: row.get("classification") == POOR_PERFORMANCE_CLASSIFICATION,
        BUMP_TEST_AND_RETUNE,
        None,
    ),
    # A valve that is too big or too small limits control whatever the tuning: review it first.
    (_has_sizing_hint, REVIEW_VALVE_SIZING, _sizing_params),
    # Only when nothing is wrong: give the missing knowledge so the checks can run at all.
    (_needs_knowledge, CONFIGURE_KNOWLEDGE, _configure_params),
)


def next_action(row: Row) -> dict[str, Any]:
    """The first advice that applies to one overview row, as a dict with "code" and "params".

    Missing or None row values are tolerated, so rows written by an older overview version still
    get an answer.

    Returns:
        One action dict; the fallback, when no rule applies, is NO_ACTION with no parameters.
    """
    for applies, code, build_params in RULES:
        if applies(row):
            return _action(code, build_params(row) if build_params is not None else {})
    return _action(NO_ACTION, {})


def _urgency(row: Row) -> int:
    """Priority band of one row: 0 is looked at first, 4 last."""
    status = row.get("status")
    if status in STATUS_URGENCY:
        return STATUS_URGENCY[status]
    return ADVICE_URGENCIES.get(row["next_action"]["code"], OTHER_URGENCY)


def _health(row: Row) -> int:
    """Health score used as tie-breaker, or UNKNOWN_HEALTH when it is missing."""
    health = _number_or_none(row.get("health_percent"))
    return UNKNOWN_HEALTH if health is None else int(health)


def priority_key(row: Row) -> tuple[int, int]:
    """Sort key of one row; smaller comes first.

    Expects ``row["next_action"]`` to be set already, which ``add_worklist`` guarantees.

    Returns:
        (urgency, health): the band first, then the worst health within that band.
    """
    return (_urgency(row), _health(row))


def add_worklist(rows: list[Row]) -> None:
    """Set ``next_action`` and ``priority_rank`` (1 = look first) on every row, in place.

    The sort is stable, so rows of equal priority keep their input order and equal rows do not
    swap places between two exports.
    """
    for row in rows:
        row["next_action"] = next_action(row)
    ordered = sorted(rows, key=priority_key)
    for rank, row in enumerate(ordered, start=1):
        row["priority_rank"] = rank
